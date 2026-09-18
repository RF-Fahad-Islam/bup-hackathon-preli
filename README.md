# GridWise — LLM-guided 24-hour campus energy optimizer

BUP CSE Fest 2026 · GridWise preliminary.

`POST /optimize-energy` works in four steps:
1. **An LLM interprets** the natural-language operator notes.
2. **Deterministic guardrails** turn what the LLM read into strict directives.
3. **A linear program (HiGHS)** builds the cost-optimal grid, solar and battery schedule that satisfies every directive.
4. **An independent replay validator** re-checks every hour and recomputes the totals before responding.

| | |
|---|---|
| Live endpoint | `https://<fly-app>.fly.dev` *(fill in after deploy)* |
| Docker fallback | `docker.io/<dockerhub-user>/gridwise:v1.0.0` *(fill in after push)* |
| Port | `8080` (override with `PORT`) |
| LLM | OpenRouter. Cheap chain `openai/gpt-4.1-mini → google/gemini-2.5-flash`, escalating to `anthropic/claude-sonnet-5 → anthropic/claude-sonnet-4.6` |
| Solver | SciPy `linprog(method="highs")` |

---

## Architecture

```
POST /optimize-energy
   │
   ├─ 1. Request validation (Pydantic)            400 structural · 422 physically impossible
   │
   ├─ 2. Interpretation  (app/interpreter.py, app/llm.py)
   │      one batched LLM call for all notes → a "raw reading" per note:
   │        spans [{start_hour,end_hour}], solar % + "remaining"|"reduction",
   │        amount + "kwh"|"percent_of_capacity"
   │      cheap model ──► tripwire check ──agree──► accept
   │                         │disagree / unsure / invalid
   │                         ▼
   │                   strong model (final answer)
   │      all LLMs down ──► degraded mode (tripwire only if it read every note confidently) else 502
   │
   ├─ 3. Guardrail (app/directives.py)   untrusted LLM output → Directive
   │      whitelist of 6 types · note_index 1:1 and in order · hours 0–23, unique, sorted
   │      end-exclusive expansion (+ midnight wrap) · factor ∈ [0,1] · reserve ∈ [0,capacity]
   │      grid cap ≥ 0, finite · no_op ⇒ applies=false & adjustment=null
   │
   ├─ 4. Merge directives per hour: most restrictive wins
   │      effective_solar = solar × min(factor) · reserve floor = max(base, directives)
   │      grid cap = min(caps) · no-charge / no-discharge flags
   │
   ├─ 5. Optimizer (app/optimizer.py) — two-stage LP, 120 variables
   │      stage 1: min Σ grid·tariff
   │      stage 2: cost ≤ optimum + 1e-6, min Σ(charge+discharge)  (cleanest tied-optimal plan)
   │      infeasible → re-ask strong LLM once → still infeasible → 422
   │
   ├─ 6. Plan building: charge/discharge netted into one action per hour, rounded to 4 d.p.
   │
   └─ 7. Replay (app/replay.py) — independent judge-style re-check of the published plan
          energy balance · transitions · capacity · reserve floor · rate limits · effective solar
          no-charge/no-discharge · grid caps · action consistency · final energy == initial
          totals recomputed from the plan (never taken from the solver)
```

### Why the LLM returns "raw readings" and not final numbers
The LLM reports only what a note literally says: *"1 PM to 3 PM"* becomes `{start_hour:13, end_hour:15}`, and *"80% reduction"* becomes `{solar_value:80, solar_meaning:"reduction"}`. Deterministic code then expands the end-exclusive window to `[13,14]` and computes `factor = 0.2`. This removes the two most common LLM mistakes, off-by-one windows and "80% vs 0.2", and those mistakes are otherwise structurally valid, so a guardrail can't catch them. See [docs/adr/0001](docs/adr/0001-llm-reads-code-computes-with-tripwire-escalation.md).

### Role of the tripwire
`app/tripwire.py` is a pattern-based reader that only **checks** the cheap model's answer. If it disagrees, or can't read a note confidently, the notes escalate to the strong model, whose guardrail-valid answer is final. The tripwire never overrides an LLM. Its reading is used only in **degraded mode**, when every LLM call has failed, and only if it read every note confidently. Otherwise the service returns a controlled `502`. On the labelled paraphrase set it gets 30/42 right and abstains on the other 12, with **0 confident wrong answers**.

### Semantics implemented
- Windows include the start hour and exclude the end hour. `"10 PM to 2 AM"` wraps to `[0,1,22,23]`, `"from 8 PM onwards"` gives `[20..23]`, `"until 6 AM"` gives `[0..5]`, and one note may name several periods.
- `factor` is the fraction of solar **remaining**: "drops to 20%", "one-fifth of normal" and "80% reduction" all give `0.2`.
- Reserves given as a percentage of capacity are converted to kWh (50% of 200 kWh = `100`).
- A reserve applies to `battery_energy_after_kwh` for each covered hour, as `max(base minimum, directive)`.
- Notes about other days ("tomorrow", "next week") or unrelated matters are `no_op`.

---

## Quickstart (local, from a clean machine)

Requires Python 3.11+.

```bash
git clone <repo-url> gridwise && cd gridwise
python -m venv .venv
# Windows: .venv\Scripts\activate    macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
export OPENROUTER_API_KEY=sk-or-...        # Windows PowerShell: $env:OPENROUTER_API_KEY="sk-or-..."
uvicorn app.main:app --host 0.0.0.0 --port 8080
```

```bash
curl http://localhost:8080/health
# {"status":"ok"}

curl -X POST http://localhost:8080/optimize-energy \
  -H "Content-Type: application/json" \
  -d @samples/synthetic/request-only.json
```

## Configuration

| Variable | Required | Default | Purpose |
|---|---|---|---|
| `OPENROUTER_API_KEY` | **yes** | – | OpenRouter API key (never commit it) |
| `LLM_CHEAP_MODELS` | no | `openai/gpt-4.1-mini,google/gemini-2.5-flash` | First-pass models, sent as an OpenRouter `models` fallback list |
| `LLM_STRONG_MODELS` | no | `anthropic/claude-sonnet-5,anthropic/claude-sonnet-4.6` | Escalation models |
| `LLM_CHEAP_TIMEOUT_S` | no | `6` | Cheap-call timeout |
| `LLM_STRONG_TIMEOUT_S` | no | `10` | Strong-call timeout |
| `INTERPRET_DEADLINE_S` | no | `20` | Hard deadline for the whole interpretation step (the judge timeout is 30 s) |
| `INTERPRET_CACHE_SIZE` | no | `1000` | In-memory LRU of validated readings, keyed by normalised note text |
| `PORT` | no | `8080` | Listen port (the container binds `0.0.0.0`) |
| `WEB_CONCURRENCY` | no | `2` | Uvicorn workers in the container |
| `LOG_LEVEL` | no | `INFO` | Logs show the interpretation path (`cheap`/`strong`/`cache`/`degraded`) per request |

The cache stores only guardrail-valid LLM readings, never degraded ones. The first request for any note always goes to the LLM.

## Docker fallback

```bash
docker pull docker.io/<dockerhub-user>/gridwise:v1.0.0
docker run --rm -p 8080:8080 -e OPENROUTER_API_KEY=sk-or-... docker.io/<dockerhub-user>/gridwise:v1.0.0
curl http://localhost:8080/health
```

The image contains no secrets. The key is passed only at runtime with `-e`. The image binds `0.0.0.0:8080` and has a Docker `HEALTHCHECK` on `/health`.

Build it yourself:

```bash
docker build -t <dockerhub-user>/gridwise:v1.0.0 .
docker push <dockerhub-user>/gridwise:v1.0.0
```

## Deploy (Fly.io)

```bash
fly apps create <app-name>            # then set `app` in fly.toml
fly secrets set OPENROUTER_API_KEY=sk-or-...
fly deploy                            # builds remotely; min 1 machine, auto-stop off (always warm)
```

## Testing

```bash
pip install -r requirements-dev.txt
pytest -q                              # unit + API + fuzz tests (no network; the LLM is faked)
```

- `tests/test_guardrail.py`: window expansion, factor/percentage arithmetic, rejection of invented or out-of-range directives, one entry per note, and overlap merging.
- `tests/test_optimizer.py`: every directive is enforced, and the **LP cost equals an independent exhaustive dynamic-programming optimum**.
- `tests/test_fuzz.py`: 400 random scenarios with random directives. Every feasible plan must pass Replay.
- `tests/test_api.py`: response contract, escalation, strong-model-wins, degraded mode, 502 without leaking a stack trace, 400/422 handling, cache.
- `tests/test_tripwire.py`: tripwire readings of common phrasings, and that it abstains when a note is ambiguous.

### Public sample pack
Put the official samples in `samples/` (one JSON per sample: the request at top level or under `request`, and the expected output under `expected`), then start the service and run:

```bash
python scripts/run_samples.py http://localhost:8080 samples
```

For each sample it checks three things:
- the interpretation equals the expected `directive_type`, hours and values;
- the returned plan passes an independent Replay;
- the cost is ≤ the expected optimum + 0.01 BDT.

Equivalent optimal schedules are accepted, as the official rules allow. Expected output: `N/N samples passed`.

### Paraphrase robustness eval (real LLM)
```bash
OPENROUTER_API_KEY=... python -m eval.run_eval            # full cheap→tripwire→strong pipeline
OPENROUTER_API_KEY=... python -m eval.run_eval --strong-only
```
It runs 42 hand-labelled paraphrases covering all six directive types: fractions ("one-fifth"), "reduction" vs "remaining", 24-hour clock, noon/midnight, overnight wrap, "onwards", % of capacity, and "tomorrow" distractors. It prints every miss and the overall score.

## HTTP behaviour

| Status | When |
|---|---|
| 200 | Success (`/health`, `/optimize-energy`) |
| 400 | Malformed JSON, missing or wrong-typed fields, not exactly 24 unique hours 0–23, 0 or >3 notes, blank note |
| 422 | Well-formed but physically impossible (e.g. initial energy outside [minimum, capacity], negative demand), or no feasible schedule even after re-interpretation |
| 502 | Language model unavailable and notes could not be read safely |
| 500 | Controlled internal error |

Error bodies are `{"error": "<code>", "message": "<safe text>"}`. They never contain stack traces, keys or configuration. Hours sent out of order are sorted, and unknown extra fields are ignored.

## Dependencies
FastAPI, Uvicorn, Pydantic v2, SciPy (HiGHS), NumPy, httpx. Pytest for development. Versions are pinned in `requirements*.txt`.

## Secret handling
- The only secret is `OPENROUTER_API_KEY`. It's read from the environment at request time, never logged, and never returned in a response.
- `.env` files are git-ignored and docker-ignored. `.env.example` lists variable names only.
- The Docker image and repository contain no credentials. Fly stores the key with `fly secrets`.

## Known limitations
- The interpretation cache is per process and in memory. It resets on restart and isn't shared between workers.
- A note that could reasonably mean two different directives is resolved by the strong model's reading. The tripwire only ever triggers escalation.
- Times with minutes round outward to whole hours ("until 3:30 PM" covers hour 15). Overnight windows wrap within the same 24-hour day.
- When two solar reductions overlap, the lower factor applies. They are not multiplied.
- Degraded mode, used only when every LLM call fails, relies on pattern matching and returns `502` rather than guess when a note is ambiguous.

## Repository map
```
app/main.py          HTTP layer, status codes, orchestration
app/schemas.py       exact request/response contract
app/llm.py           OpenRouter client, prompt, JSON schema for raw readings
app/interpreter.py   cheap → tripwire → strong escalation, degraded mode, cache
app/tripwire.py      pattern-based reading used as a check
app/directives.py    guardrail: raw reading → Directive; per-hour constraint merge
app/optimizer.py     two-stage HiGHS LP and plan rounding
app/replay.py        independent final validator and totals
app/summary.py       deterministic explanation / plan_summary text
CONTEXT.md           domain glossary · docs/adr/ design decisions
```
