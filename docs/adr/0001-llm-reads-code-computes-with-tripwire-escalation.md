# LLM reads, code computes, and a tripwire escalates to a stronger model

The LLM returns only a Raw Reading: time spans, amounts with units, and whether a solar number is the part remaining or the part lost. Deterministic code then builds the end-exclusive Windows (wrapping past midnight), converts % of capacity to kWh and computes Solar Factors. This removes the off-by-one and "80% reduction vs 0.2" errors that are structurally valid and would slip past the Guardrail. Every note goes first to a cheap model chain (Groq first, then OpenRouter). A pattern-based Tripwire checks the result. If they disagree, or the Guardrail fails, the notes escalate to a strong model, whose answer is final. The Tripwire never overrides an LLM, so the LLM stays the interpreter as the rules require. If the strong model is unavailable, the cheap model's guardrail-valid reading is used unconfirmed and is not cached. Only in Degraded Mode, when every LLM call has failed, may the Tripwire's reading be used, and only if it parsed every note confidently.

## Considered Options

- **Strong model on every request**: simplest and most accurate, but costs more per call. It was rejected in favour of cheap-first with escalation.
- **Escalate only when the Guardrail fails**: rejected because semantic mistakes are structurally valid and would never escalate.
- **Majority vote (cheap / tripwire / strong)**: rejected because it would let pattern matching outvote the LLM.
