"""Interpretation pipeline: cheap LLM -> Tripwire check -> Escalation -> (Degraded Mode).

The LLM is always the interpreter. The Tripwire only decides whether the cheap
model's reading is trusted or escalated to the strong model; the strong model's
guardrail-valid answer is final. See docs/adr/0001.
"""
import logging
import os
import re
import time
from collections import OrderedDict
from dataclasses import dataclass

import httpx

from . import llm, tripwire
from .directives import Directive, GuardrailError, interpretation_to_directives, raw_to_directive
from .schemas import BatterySpec

log = logging.getLogger("gridwise.interpreter")

CHEAP_TIMEOUT = float(os.getenv("LLM_CHEAP_TIMEOUT_S", "6"))
STRONG_TIMEOUT = float(os.getenv("LLM_STRONG_TIMEOUT_S", "10"))
DEADLINE = float(os.getenv("INTERPRET_DEADLINE_S", "20"))
CACHE_SIZE = int(os.getenv("INTERPRET_CACHE_SIZE", "1000"))


class InterpretationUnavailable(Exception):
    """Every LLM path failed and the Tripwire could not read every note confidently."""


@dataclass
class Interpretation:
    directives: list[Directive]
    path: str  # cache | cheap | strong | degraded | mixed


class ReadingCache:
    """LRU of guardrail-valid, non-degraded Raw Readings keyed by normalised note text.

    Raw Readings are capacity-independent (percentages are converted in code),
    so the note text alone is a sound key.
    """

    def __init__(self, size: int):
        self.size = size
        self._d: OrderedDict[str, dict] = OrderedDict()

    @staticmethod
    def key(note: str) -> str:
        return re.sub(r"\s+", " ", note.strip().lower())

    def get(self, note: str):
        k = self.key(note)
        if k in self._d:
            self._d.move_to_end(k)
            return self._d[k]
        return None

    def put(self, note: str, reading: dict):
        k = self.key(note)
        self._d[k] = {key: v for key, v in reading.items() if key != "note_index"}
        self._d.move_to_end(k)
        while len(self._d) > self.size:
            self._d.popitem(last=False)

    def evict(self, notes: list[str]):
        for n in notes:
            self._d.pop(self.key(n), None)


cache = ReadingCache(CACHE_SIZE)


def _tripwire_directives(notes: list[str], battery: BatterySpec) -> list[Directive | None]:
    out = []
    for i, n in enumerate(notes):
        raw = tripwire.read_note(n)
        try:
            out.append(raw_to_directive(raw, i, battery, source="tripwire") if raw else None)
        except GuardrailError:
            out.append(None)
    return out


async def interpret(client: httpx.AsyncClient, notes: list[str], battery: BatterySpec,
                    force_strong: bool = False, feedback: str | None = None) -> Interpretation:
    started = time.monotonic()
    remaining = lambda: DEADLINE - (time.monotonic() - started)  # noqa: E731

    results: dict[int, Directive] = {}
    if not force_strong:
        for i, n in enumerate(notes):
            raw = cache.get(n)
            if raw is not None:
                try:
                    results[i] = raw_to_directive(raw, i, battery)
                except GuardrailError:
                    cache.evict([n])
    pending = [i for i in range(len(notes)) if i not in results]
    if not pending:
        return Interpretation([results[i] for i in range(len(notes))], "cache")

    sub = [notes[i] for i in pending]
    accepted: list[Directive] | None = None
    accepted_raw: list | None = None
    path = "strong"

    if not force_strong:
        try:
            raw, model = await llm.read_notes(client, sub, llm.CHEAP_MODELS, min(CHEAP_TIMEOUT, remaining()))
            cheap = interpretation_to_directives(raw, sub, battery)
            trip = _tripwire_directives(sub, battery)
            disagreements = [j for j, (c, t) in enumerate(zip(cheap, trip)) if t is None or not c.same_meaning(t)]
            if not disagreements:
                accepted, accepted_raw, path = cheap, raw, "cheap"
            else:
                log.info("escalating: tripwire disagrees on notes %s (cheap model %s)", disagreements, model)
        except (llm.LLMError, GuardrailError) as e:
            log.warning("cheap interpretation rejected: %s", e)

    if accepted is None:
        try:
            if remaining() < 1:
                raise llm.LLMError("interpretation deadline reached")
            raw, model = await llm.read_notes(client, sub, llm.STRONG_MODELS, min(STRONG_TIMEOUT, remaining()),
                                              feedback=feedback)
            accepted, accepted_raw, path = interpretation_to_directives(raw, sub, battery), raw, "strong"
        except (llm.LLMError, GuardrailError) as e:
            log.error("strong interpretation failed: %s", e)

    if accepted is None:
        trip = _tripwire_directives(sub, battery)
        if any(t is None for t in trip):
            raise InterpretationUnavailable("language model unavailable and notes could not be read safely")
        log.error("DEGRADED MODE: using tripwire readings for notes %s", pending)
        accepted, path = trip, "degraded"
    else:
        by_idx = {r["note_index"]: r for r in accepted_raw}
        for j, orig in enumerate(pending):
            cache.put(notes[orig], by_idx[j])

    for j, orig in enumerate(pending):
        d = accepted[j]
        results[orig] = Directive(orig, d.directive_type, d.hours, d.value, d.reason, d.source)
    if len(pending) < len(notes):
        path = f"mixed:{path}"
    return Interpretation([results[i] for i in range(len(notes))], path)
