"""Provider-agnostic LLM client (OpenAI-compatible chat APIs).

The LLM returns Raw Readings only; app.directives does the arithmetic.
Each tier is an ordered chain of (provider, models). Providers are tried in
order until one returns a parseable reading; a provider that answers
401/402/403 (dead account) is skipped for a long cool-down; a model that
answers 429 (rate limit) is skipped only until its Retry-After (capped).
"""
import json
import logging
import os
import re
import time
from dataclasses import dataclass

import httpx

log = logging.getLogger("gridwise.llm")


@dataclass(frozen=True)
class Provider:
    name: str
    base_url: str
    key_env: str
    model_list_routing: bool = False  # OpenRouter: send all models in one request via "models"


PROVIDERS = {
    "openrouter": Provider("openrouter", os.getenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1"),
                           "OPENROUTER_API_KEY", model_list_routing=True),
    "groq": Provider("groq", os.getenv("GROQ_BASE_URL", "https://api.groq.com/openai/v1"), "GROQ_API_KEY"),
    "openai": Provider("openai", os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1"), "OPENAI_API_KEY"),
}


def parse_chain(spec: str) -> tuple[tuple[str, tuple[str, ...]], ...]:
    """'openrouter:a/b|c/d,groq:e/f' -> (('openrouter', ('a/b', 'c/d')), ('groq', ('e/f',)))"""
    chain = []
    for entry in spec.split(","):
        entry = entry.strip()
        if not entry:
            continue
        provider, _, models = entry.partition(":")
        if provider not in PROVIDERS or not models:
            raise ValueError(f"bad LLM chain entry {entry!r}")
        chain.append((provider, tuple(m.strip() for m in models.split("|") if m.strip())))
    return tuple(chain)


CHEAP_CHAIN = parse_chain(os.getenv(
    "LLM_CHEAP_CHAIN",
    "openrouter:openai/gpt-4.1-mini|google/gemini-2.5-flash,groq:openai/gpt-oss-20b|qwen/qwen3.8-27b"))
STRONG_CHAIN = parse_chain(os.getenv(
    "LLM_STRONG_CHAIN",
    "openrouter:anthropic/claude-sonnet-5|anthropic/claude-sonnet-4.6,groq:openai/gpt-oss-120b|openai/gpt-oss-20b"))
COOLDOWN_S = float(os.getenv("LLM_PROVIDER_COOLDOWN_S", "300"))
RATE_LIMIT_MAX_WAIT_S = 30.0
_cooldown_until: dict[str, float] = {}  # "provider" or "provider:model" -> monotonic time


def _cooling(key: str) -> bool:
    return _cooldown_until.get(key, 0) > time.monotonic()


def _retry_after(r: httpx.Response) -> float:
    try:
        return min(max(float(r.headers.get("retry-after", "10")), 1.0), RATE_LIMIT_MAX_WAIT_S)
    except ValueError:
        return 10.0


class LLMError(Exception):
    pass


SYSTEM_PROMPT = """You interpret campus energy operator notes for a 24-hour battery/solar/grid schedule (hours 0-23 of TODAY).

For EACH note, report what it literally says as a "raw reading". You do NOT compute hour lists or factors; code does that.

Choose exactly one directive_type per note:
- solar_reduction: available solar/PV/panel output is reduced during some hours (washing, maintenance, clouds, shading, inverter trouble).
- minimum_battery_reserve: battery stored energy must stay at or above some level during some hours.
- no_charge_window: the battery must not / cannot CHARGE during some hours (charger offline, maintenance...).
- no_discharge_window: the battery must not / cannot DISCHARGE (be drawn from / supply load) during some hours.
- max_grid_window: grid import/draw must not exceed some kWh per hour during some hours.
- no_op: anything else - irrelevant to today's energy schedule (menus, meetings, events, staff notices, things that happen tomorrow or another day, general info with no constraint, or statements that solar/battery/grid will be normal).

Time spans ("spans"): list of {start_hour, end_hour} using the 24-hour clock.
- start_hour is the first affected hour (0-23). end_hour is the hour the restriction ENDS (exclusive, 1-24). "1 PM to 3 PM" -> {13,15}. "6 PM until 9 PM" -> {18,21}. "18:00-21:00" -> {18,21}.
- "until midnight"/"end of day"/"onwards"/"rest of the day" -> end_hour 24. No start given ("until 6 AM", "before 6 AM") -> start_hour 0. "All day" -> {0,24}.
- Overnight spans may wrap: "10 PM to 2 AM" -> {22,2}.
- If a time has minutes, start = the hour it falls in, end = the next whole hour after it ("until 3:30 PM" -> end_hour 16).
- Resolve AM/PM from context: "1-3 PM" -> {13,15}; "noon" = 12; "midnight" = 0 as a start, 24 as an end. Solar work in "one until three" means the afternoon {13,15}. Evening peak phrases like "the 6-9 evening peak" -> {18,21}.
- Several separate periods in one note -> several spans.
- For no_op, spans = [].

Values:
- solar_reduction: solar_value is a PERCENTAGE (0-100). solar_meaning = "remaining" if the number is how much solar is still available ("drops to 20%", "only 20% of normal", "one-fifth of normal output" -> 20 remaining, "half output" -> 50 remaining), or "reduction" if it is how much is LOST ("80% reduction", "reduced by 80%", "cut by 80%", "loses 80%" -> 80 reduction). Fractions: one-fifth = 20, quarter = 25, third = 33.3333, half = 50. "Solar unavailable/zero/completely offline" -> 0 remaining.
- minimum_battery_reserve: amount_value + amount_unit = "kwh" for absolute energy ("keep 120 kWh") or "percent_of_capacity" for a share of the battery ("keep 50% of battery capacity", "half the battery" -> 50).
- max_grid_window: amount_value in kWh, amount_unit = "kwh" (a per-hour cap on grid import).
- Otherwise set unused value fields to null.

Only use numbers stated in the note. Never invent constraints; when a note does not clearly restrict today's schedule, use no_op.
"reason": one short sentence explaining the reading.

Return JSON {"readings": [...]} with exactly one reading per note, same note_index, in order."""

READING_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["readings"],
    "properties": {
        "readings": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["note_index", "directive_type", "spans", "solar_value", "solar_meaning",
                             "amount_value", "amount_unit", "reason"],
                "properties": {
                    "note_index": {"type": "integer"},
                    "directive_type": {"type": "string", "enum": [
                        "solar_reduction", "minimum_battery_reserve", "no_charge_window",
                        "no_discharge_window", "max_grid_window", "no_op"]},
                    "spans": {"type": "array", "items": {
                        "type": "object", "additionalProperties": False,
                        "required": ["start_hour", "end_hour"],
                        "properties": {"start_hour": {"type": "integer"}, "end_hour": {"type": "integer"}}}},
                    "solar_value": {"type": ["number", "null"]},
                    "solar_meaning": {"type": ["string", "null"], "enum": ["remaining", "reduction", None]},
                    "amount_value": {"type": ["number", "null"]},
                    "amount_unit": {"type": ["string", "null"], "enum": ["kwh", "percent_of_capacity", None]},
                    "reason": {"type": "string"},
                },
            },
        }
    },
}


def _user_message(notes: list[str], feedback: str | None) -> str:
    body = "\n".join(f"[{i}] {n}" for i, n in enumerate(notes))
    msg = f"Operator notes:\n{body}"
    if feedback:
        msg += f"\n\nA previous reading was rejected: {feedback}. Re-read the notes carefully."
    return msg


def _extract_json(text: str):
    text = text.strip()
    fence = re.search(r"```(?:json)?\s*(.*?)```", text, re.S)
    if fence:
        text = fence.group(1)
    start = text.find("{")
    end = text.rfind("}")
    if start < 0 or end < 0:
        raise LLMError("no JSON object in model output")
    return json.loads(text[start:end + 1])


def _payload(provider: Provider, model: str, models: tuple[str, ...], notes: list[str], feedback: str | None) -> dict:
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": _user_message(notes, feedback)},
        ],
        "temperature": 0,
        "response_format": {"type": "json_schema",
                            "json_schema": {"name": "raw_readings", "strict": True, "schema": READING_SCHEMA}},
    }
    if provider.model_list_routing:
        payload["models"] = list(models)  # OpenRouter falls through this list on provider errors
        payload["max_tokens"] = 1500
    else:
        payload["max_completion_tokens"] = 3000
    if "gpt-oss" in model:
        payload["reasoning_effort"] = "low"
    return payload


async def _call(client: httpx.AsyncClient, provider: Provider, model: str, models: tuple[str, ...],
                notes: list[str], timeout: float, feedback: str | None) -> list:
    key = os.getenv(provider.key_env)
    r = await client.post(f"{provider.base_url}/chat/completions", timeout=timeout,
                          json=_payload(provider, model, models, notes, feedback),
                          headers={"Authorization": f"Bearer {key}", "X-Title": "GridWise"})
    if r.status_code in (401, 402, 403):
        _cooldown_until[provider.name] = time.monotonic() + COOLDOWN_S
    elif r.status_code == 429:
        _cooldown_until[f"{provider.name}:{model}"] = time.monotonic() + _retry_after(r)
    if r.status_code != 200:
        raise LLMError(f"{provider.name} returned HTTP {r.status_code}")
    try:
        content = r.json()["choices"][0]["message"]["content"]
        parsed = _extract_json(content if isinstance(content, str) else json.dumps(content))
        return parsed["readings"] if isinstance(parsed, dict) else parsed
    except (KeyError, IndexError, TypeError, ValueError) as e:
        raise LLMError(f"{provider.name} gave unparseable output: {type(e).__name__}") from None


async def read_notes(client: httpx.AsyncClient, notes: list[str], chain, timeout: float,
                     feedback: str | None = None) -> tuple[list, str]:
    """One batched call for all notes, walking the provider chain within `timeout` seconds.

    Returns (readings, "provider:model").
    """
    deadline = time.monotonic() + timeout
    errors = []
    for provider_name, models in chain:
        provider = PROVIDERS[provider_name]
        if not os.getenv(provider.key_env):
            continue
        if _cooling(provider_name):
            errors.append(f"{provider_name} cooling down")
            continue
        targets = models[:1] if provider.model_list_routing else models
        for model in targets:
            if _cooling(f"{provider_name}:{model}"):
                errors.append(f"{provider_name}:{model} rate-limited")
                continue
            remaining = deadline - time.monotonic()
            if remaining < 0.5:
                raise LLMError("; ".join(errors + ["tier timeout"]))
            try:
                return await _call(client, provider, model, models, notes, remaining, feedback), f"{provider_name}:{model}"
            except httpx.HTTPError as e:
                errors.append(f"{provider_name} request failed: {type(e).__name__}")
            except LLMError as e:
                errors.append(str(e))
            log.warning("LLM attempt failed: %s", errors[-1])
            if _cooling(provider_name):
                break
    raise LLMError("; ".join(errors) or "no LLM provider configured")
