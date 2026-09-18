# GridWise Energy Scheduling

A service that turns a campus operator's plain-English notes into formal rules. It then plans one day of grid imports, solar use and battery use at the lowest electricity cost.

## Language

### Inputs

**Scenario**:
One optimization request: a scenario ID, 1–3 Operator Notes, a 24-hour Profile and a Battery Spec.
_Avoid_: case, job, request (when talking about the domain)

**Operator Note**:
One free-text instruction written by a campus operator. It is identified by its position (`note_index`) in the Scenario.
_Avoid_: instruction, command, message

**Hour Slot**:
One of the 24 hourly records (hours 0–23) holding demand, available solar and tariff.
_Avoid_: interval, period, row

**Battery Spec**:
The battery's fixed physical limits (capacity, base minimum energy, charge and discharge rate limits) and its starting energy.
_Avoid_: battery config, storage settings

### Interpretation

**Directive**:
The single structured meaning of one Operator Note. It is one of five constraint types or No-op.
_Avoid_: rule, instruction, interpretation (when meaning the structured object)

**No-op**:
A Directive meaning the note does not change today's energy schedule. Its `applies` is false and it has no adjustment.
_Avoid_: irrelevant directive, ignored note

**Distractor**:
An Operator Note that is deliberately irrelevant and should be interpreted as a No-op.

**Window**:
The set of hours a Directive covers. It includes the start hour and excludes the end hour, and is stored as unique, ascending hours from 0 to 23.
_Avoid_: range, period, timeframe

**Solar Factor**:
The fraction of original solar that is still usable during a solar-reduction Window. It is always the fraction left over, never the fraction lost.
_Avoid_: reduction percentage, curtailment ratio

**Raw Reading**:
What the LLM reports a note literally says: time spans as start/end clock hours, amounts with their unit (kWh or % of capacity), and whether a solar number is the part remaining or the part lost. Code turns a Raw Reading into a Directive.
_Avoid_: LLM output, extraction

**Tripwire**:
A pattern-based reading of a note used only to check the LLM's Raw Reading. If they disagree, the note is escalated. It never overrides an LLM answer.
_Avoid_: regex parser, fallback parser (except in Degraded Mode)

**Escalation**:
Re-interpreting notes with the strong model after the cheap model's Raw Reading fails the Guardrail or disagrees with the Tripwire. The strong model's answer is final.

**Degraded Mode**:
The last-resort path used when every LLM call has failed. The Tripwire's reading is used only if it parsed every note confidently. Otherwise the request fails with a controlled error.

**Guardrail**:
The deterministic check that accepts or rejects a proposed Directive before it becomes a constraint.
_Avoid_: sanitizer, filter

### Planning

**Effective Solar**:
The solar available in an hour after every solar-reduction Directive is applied.

**Reserve Floor**:
The lowest allowed battery energy at the end of an hour. It is the higher of the base minimum and any reserve Directive covering that hour.
_Avoid_: minimum SOC, reserve

**Grid Cap**:
The highest allowed grid import in an hour, set by a max-grid Directive.

**Hourly Plan**:
The 24-hour schedule. Each hour has grid import, solar used, one Battery Action with its size, and the battery energy after that hour.
_Avoid_: schedule, dispatch

**Battery Action**:
The single thing the battery does in an hour: `charge`, `discharge` or `idle`. Its size (`battery_kwh`) is never negative.

**Energy Balance**:
The per-hour rule: grid + solar used + discharge = demand + charge.

**Battery Neutrality**:
The rule that battery energy after hour 23 equals the starting energy.
_Avoid_: cyclic constraint, end-of-day SOC

**Replay**:
The independent hour-by-hour re-check of a finished Hourly Plan. It confirms every constraint holds and recalculates the totals.
_Avoid_: post-validation, audit
