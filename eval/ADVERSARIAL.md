# Adversarial operator-note suite

> Be adversarial toward the interpreter, not toward the official specification: every test has a clear single correct answer under the published rules.

**180 notes**: 77 category tests, 11 hard no_op distractors, 12 time traps, 12 numeric traps, 10 paraphrase sets (46 notes), 11 minimal pairs (22 notes).

Machine-readable copy: [`adversarial.jsonl`](adversarial.jsonl). It uses the same `note/type/hours/value/capacity` keys as `paraphrases.jsonl`, so the existing runner works with it: `python -m eval.run_eval --file adversarial.jsonl`. `capacity` is the battery capacity the expected reserve kWh assumes. Every expected output passes this repo's own `DirectiveInterpretation` schema and guardrail bounds (checked by `tests/test_adversarial_dataset.py`).

Scores are 1-5: **S** = semantic difficulty, **F** = likelihood of fooling a small LLM, **B** = likelihood of exposing brittle prompt or keyword logic. **Tripwire** is what `app/tripwire.py` does with the note after the tripwire fix: `correct`, `unsure` (returns None, which forces escalation), or `WRONG` (a confident wrong reading).

## Top 20 to put in your local suite

| # | ID | Note | Expected | Why it earns a slot | Tripwire |
|---|----|------|----------|---------------------|----------|
| 1 | B02 | "Solar production will come in 20% below normal from 8 AM to 11 AM due to morning fog." | `solar_reduction` `{"hours": [8, 9, 10], "factor": 0.8}` | Loss written as '20% below'. The tripwire used to get it wrong the same way a weak LLM would, confirming the error. | correct |
| 2 | B03 | "A reduction to 70% of rated PV output applies from 10:00 to 12:00 while one inverter string is serviced." | `solar_reduction` `{"hours": [10, 11], "factor": 0.7}` | The keyword 'reduction' with 'to', which inverts under keyword logic. | correct |
| 3 | NT10 | "Solar output will be reduced from 100% to 35% between 11 AM and 1 PM." | `solar_reduction` `{"hours": [11, 12], "factor": 0.35}` | Two percentages and 'reduced'; the tripwire used to take the first % and output factor 1.0. | correct |
| 4 | MP02 | "Solar will drop to 30% from 10 AM to noon." / "Solar will drop by 30% from 10 AM to noon." | `solar_reduction` `{"hours": [10, 11], "factor": 0.3}` / `solar_reduction` `{"hours": [10, 11], "factor": 0.7}` | Pair: 'to' vs 'by', the smallest possible edit that inverts the factor. | correct / correct |
| 5 | NT01 | "PV will deliver 0.3 of its normal output from 10 AM to noon." | `solar_reduction` `{"hours": [10, 11], "factor": 0.3}` | Decimal 0.3 in a percent field gives 0.003, and the guardrail accepts it. | unsure |
| 6 | NT02 | "State of charge must not dip below 0.4 between 6 PM and 9 PM." | `minimum_battery_reserve` `{"hours": [18, 19, 20], "minimum_energy_kwh": 80}` | Decimal SOC gives 0.8 kWh if unconverted; the tripwire used to classify it as no_charge_window ('state of charge'). | unsure |
| 7 | MP05 | "The battery must not discharge below 80 kWh from 6 to 9 PM." / "The battery must not discharge from 6 to 9 PM." | `minimum_battery_reserve` `{"hours": [18, 19, 20], "minimum_energy_kwh": 80}` / `no_discharge_window` `{"hours": [18, 19, 20]}` | Pair: 'must not discharge below 80 kWh' is a reserve; the tripwire used to say no_discharge_window. | correct / correct |
| 8 | TT05 | "Charger locked out for hour slots 18, 19 and 20." | `no_charge_window` `{"hours": [18, 19, 20]}` | Explicit slot list in an exclusive-end span format; the tripwire used to return [19]. | correct |
| 9 | E02 | "Charging is blocked during hours 14 through 16 inclusive." | `no_charge_window` `{"hours": [14, 15, 16]}` | '14 through 16 inclusive'; the default exclusive rule drops 16 (the tripwire used to as well). | correct |
| 10 | TT10 | "Charging is suspended from 1 PM through the end of the 3 PM hour." | `no_charge_window` `{"hours": [13, 14, 15]}` | 'Through the end of the 3 PM hour' needs an inclusive override. | unsure |
| 11 | I01 | "Phone charging lockers in the library will be unavailable from 2 PM to 4 PM." | `no_op` `null` | Phone charging lockers; the tripwire used to say no_charge_window [14,15] with confidence. | correct |
| 12 | HN09 | "Operators asked whether the 6-9 PM feeder cap of 150 kWh applies today: it does not." | `no_op` `null` | A perfect grid-cap spec negated by the last three words; the tripwire used to apply it. | unsure |
| 13 | HN01 | "The earlier note about reduced solar between 1 and 3 PM was sent in error - please disregard it." | `no_op` `null` | Retraction of an earlier note. | unsure |
| 14 | HN02 | "Today's solar forecast already accounts for the expected cloud cover; do not apply any additional reduction." | `no_op` `null` | 'Do not apply any additional reduction': negated solar. | unsure |
| 15 | H04 | "The charging ban originally set for tomorrow has been moved to today, 1 PM to 3 PM." | `no_charge_window` `{"hours": [13, 14]}` | Rescheduled from tomorrow to today; a 'tomorrow' keyword filter drops it. | unsure |
| 16 | H01 | "From today until Friday, grid import must stay at or below 180 kWh between 6 PM and 9 PM." | `max_grid_window` `{"hours": [18, 19, 20], "max_grid_kwh": 180}` | 'From today until Friday' is a multi-day range that includes today. | correct |
| 17 | F07 | "Discharge protection test: the battery's charging circuit stays live, but its output is disabled from 7 PM to 9 PM." | `no_discharge_window` `{"hours": [19, 20]}` | 'charging' is closest to 'disabled', but the output is what gets disabled. | unsure |
| 18 | F03 | "Discharging is fine, but do not charge the battery between 3 PM and 5 PM." | `no_charge_window` `{"hours": [15, 16]}` | Both verbs present; tests negation scope. | unsure |
| 19 | NT04 | "The feeder is rated 250 kWh per hour, but only 60% of that is available from 6 PM to 9 PM." | `max_grid_window` `{"hours": [18, 19, 20], "max_grid_kwh": 150}` | Cap is 60% of a stated rating, which the raw schema cannot express, so the LLM must do the arithmetic. | unsure |
| 20 | HN11 | "Clear skies should push solar output about 20% above forecast from 11 AM to 1 PM." | `no_op` `null` | Solar increase; tempts a factor of 1.2 (malformed) or an inversion. The tripwire used to say 0.2. | unsure |

Honourable mentions: B06, MP08, TT03, TT08, D03, J07, HN03, A06, G03, D05.

## What these tests reveal

Your pipeline has the LLM report a Raw Reading and code does the arithmetic. That already rules out the classic failures of end-exclusive expansion, percent-to-kWh conversion and reduction-to-factor arithmetic, **as long as the LLM fills the enum fields correctly**. So the remaining attack surface is narrow and specific:

1. **Semantic choices encoded in one enum field**: `directive_type`, `solar_meaning`, `amount_unit`. A wrong choice is still valid output, so the guardrail cannot see it.
2. **Notes that don't fit the Raw Reading vocabulary.** Inclusive slot lists, decimal fractions, MWh, kW and '60% of the rating' all push the LLM to do the arithmetic the design meant to keep in code.
3. **Correlated errors between the tripwire and the cheap model.** The tripwire only protects you when it is unsure or disagrees. When it is confidently wrong in the same direction as the cheap LLM, the wrong reading is accepted with no escalation, and it is cached.

| Failure mode | Looks like | Tests that expose it | Caught by guardrail? | Tripwire behaviour before the fix |
|---|---|---|---|---|
| Wrong directive classification | no_charge <-> no_discharge, reserve <-> no_discharge, reserve <-> grid cap | F03, F07, MP01, MP11, MP05a, MP09, G03, G07, C08, A05 | No (both types are valid) | Confirms MP05a and NT02 (the 'state of charge' + 'not' pattern gives no_charge_window) |
| Wrong no_op | False no_op on indirect wording, or false apply on energy-flavoured distractors | A01, A06, F01, B08, J01 / I01, I02, I05, HN01-HN10, MP06b | No | Confirms I01 and HN09 (applies them); misses A05, C03, J01, J03, J09 (no_op) |
| Wrong hour range | Meridiem errors, 12 AM/PM, noon + bare hour | D03, D05, D07, TT01, TT06, TT07, TT12, MP07 | Only if a span is empty or out of range | D03 wraps noon-2 to 14 hours; J07/J10 read 1700-2000 as 00-20; TT12 starts at 0 |
| Inclusive-end mistake | Dropping or adding the last slot | E02, TT05, TT10, E03, E01 (double exclusion), TT02, TT03 | No | E02 -> [14,15]; TT05 -> [19] |
| Percentage inversion | factor = lost instead of remaining, or the reverse | B01-B09, NT09, NT10, MP02, MP10, J08, PS01b/d | No | **Systematic:** the 'remaining' regex matches the word `to` in any 'X to Y' time range, so almost every loss phrasing outside its short verb list is read as remaining (B01, B02, B04, B05, B06, B09) |
| Reserve conversion | Percent left as kWh, double conversion, decimal SOC | C01-C06, NT02, NT07, NT11, MP04, PS04, PS08 | Only if above capacity | Mostly unsure |
| Decimal-fraction scale | 0.3 reported where a percentage is expected | NT01, NT02, PS01e | **No**: 0.3 is inside 0..100, so factor 0.003 passes | Unsure (escalates) |
| Unit / arithmetic | MWh, kW, '% of rating', 'X below Y', distractor numbers | NT03, NT04, NT05, NT06, G04, PS10c, NT12 | No (any non-negative kWh passes) | J07: 'twenty-five' becomes 'twenty-5', read as 5 kWh |
| Hallucinated unsupported directive | Tariff/demand/battery-parameter notes pushed into a supported type | HN04, HN05, HN06, HN11, I05 | Type is blocked; shoe-horning into a valid type is not | HN11 -> factor 0.2 |
| Wrong note applicability | Future/past/cancelled/retracted notes applied, or today's notes dropped | H01-H08, MP03, MP08, HN01, HN09, PS07 | No | Keyword-based; H04 escalates, HN09 is applied |
| Malformed structured output | factor > 1, empty span, two entries for one note, 24 in the hours list | HN11, D06, TT08, G05, D02, B08 | **Yes**: rejected, then escalated | n/a |

### Cheap fixes these tests point at (the three tripwire items are done)

- **Done. Tripwire solar meaning**: strip time-range text before running the 'remaining' regex (you already strip amounts); add `down|short|less|below|curtail\w*|lose|knock out` to the loss side; take the *last* percentage in 'from X% to Y%'.
- **Done. Tripwire classification**: remove 'state of charge'/'SOC' before the `charg` test; treat 'below N kWh' after 'discharge' as a reserve; require the battery/charger as the subject of a charge ban (phone/EV chargers are not it).
- **Done. Tripwire times**: parse 4-digit `HHMM` before the `\d{1,2}` time pattern; after `noon`, a bare end hour below 12 means PM.
- **Guardrail**: if `solar_value < 1` (or a percent-of-capacity reserve is below 1) and the note has no `%`/'percent', escalate instead of accepting. This closes the silent decimal-fraction hole.
- **Prompt**: add one line each for explicit inclusive slot lists ('hours 14 through 16 inclusive' -> end 17), decimal fractions ('0.3 of normal' -> 30 remaining), 'X% below/less' (loss), retractions/cancellations (no_op), and increases (no_op).

## Tripwire snapshot: 28 confident wrong readings, now 0

Of 180 notes, before the fix: 50 correct, 102 unsure, 28 WRONG. After it: 84 correct, 96 unsure, 0 WRONG. Unsure notes always escalate. A WRONG reading escalates when the cheap model is right. When the cheap model makes the same mistake, the error is accepted and cached, and in Degraded Mode it is shipped. That is why the tripwire now returns None whenever it is not sure. Each note below is a regression case in `tests/test_tripwire.py`, which also checks that no note in this file, `paraphrases.jsonl` or the official samples is misread.

| ID | Note | Expected | Now |
|---|---|---|---|
| A05 | Whatever happens this evening, the storage bank has to still be holding 110 kWh at the end of every hour from 6 PM to 10 PM. | `minimum_battery_reserve` `{"hours": [18, 19, 20, 21], "minimum_energy_kwh": 110}` | unsure |
| B01 | Expect solar to fall 60 percent short of forecast from 11 AM to 2 PM. | `solar_reduction` `{"hours": [11, 12, 13], "factor": 0.4}` | correct |
| B02 | Solar production will come in 20% below normal from 8 AM to 11 AM due to morning fog. | `solar_reduction` `{"hours": [8, 9, 10], "factor": 0.8}` | correct |
| B04 | Rooftop solar will lose three-quarters of its output between noon and 3 PM. | `solar_reduction` `{"hours": [12, 13, 14], "factor": 0.25}` | correct |
| B05 | Dust on the panels will cut PV output by two-thirds from 9 AM to noon. | `solar_reduction` `{"hours": [9, 10, 11], "factor": 0.333333}` | correct |
| B06 | PV curtailment of 70% will be in effect from 1 PM to 3 PM for inverter firmware testing. | `solar_reduction` `{"hours": [13, 14], "factor": 0.3}` | correct |
| B09 | Solar output will be down by 25% from 3 PM to 5 PM. | `solar_reduction` `{"hours": [15, 16], "factor": 0.75}` | correct |
| C03 | From 5 PM until 9 PM, stored energy must stay at or above one-third of full capacity. | `minimum_battery_reserve` `{"hours": [17, 18, 19, 20], "minimum_energy_kwh": 80}` | unsure |
| D03 | Solar drops to 50% from noon till 2. | `solar_reduction` `{"hours": [12, 13], "factor": 0.5}` | correct |
| E02 | Charging is blocked during hours 14 through 16 inclusive. | `no_charge_window` `{"hours": [14, 15, 16]}` | correct |
| E06 | Charging is allowed only until 6 AM; after that, no charging for the rest of the day. | `no_charge_window` `{"hours": [6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23]}` | unsure |
| I01 | Phone charging lockers in the library will be unavailable from 2 PM to 4 PM. | `no_op` `null` | correct |
| J01 | no chrging of the batery 2-4pm pls | `no_charge_window` `{"hours": [14, 15]}` | unsure |
| J03 | keep >=90kWh in batt, 6pm-10pm!! | `minimum_battery_reserve` `{"hours": [18, 19, 20, 21], "minimum_energy_kwh": 90}` | correct |
| J07 | Grid import: max one hundred and twenty-five kWh/hour, 1700-2000. | `max_grid_window` `{"hours": [17, 18, 19], "max_grid_kwh": 125}` | correct |
| J09 | BESS min SOC = 30%, 00:00-06:00 | `minimum_battery_reserve` `{"hours": [0, 1, 2, 3, 4, 5], "minimum_energy_kwh": 90}` | correct |
| J10 | discharge NOT permitted 1200-1400 | `no_discharge_window` `{"hours": [12, 13]}` | correct |
| HN09 | Operators asked whether the 6-9 PM feeder cap of 150 kWh applies today: it does not. | `no_op` `null` | unsure |
| HN11 | Clear skies should push solar output about 20% above forecast from 11 AM to 1 PM. | `no_op` `null` | unsure |
| TT05 | Charger locked out for hour slots 18, 19 and 20. | `no_charge_window` `{"hours": [18, 19, 20]}` | correct |
| TT12 | Keep at least 60 kWh stored until 3 PM, starting at 1. | `minimum_battery_reserve` `{"hours": [13, 14], "minimum_energy_kwh": 60}` | unsure |
| NT02 | State of charge must not dip below 0.4 between 6 PM and 9 PM. | `minimum_battery_reserve` `{"hours": [18, 19, 20], "minimum_energy_kwh": 80}` | unsure |
| NT10 | Solar output will be reduced from 100% to 35% between 11 AM and 1 PM. | `solar_reduction` `{"hours": [11, 12], "factor": 0.35}` | correct |
| PS03d | Do not draw energy out of the storage system from five until eight this evening. | `no_discharge_window` `{"hours": [17, 18, 19]}` | unsure |
| PS04e | Don't let stored energy dip under one hundred twenty-five kilowatt-hours, 6pm-10pm. | `minimum_battery_reserve` `{"hours": [18, 19, 20, 21], "minimum_energy_kwh": 125}` | correct |
| PS05d | Please keep campus imports at or under one hundred sixty kWh from six until nine this evening. | `max_grid_window` `{"hours": [18, 19, 20], "max_grid_kwh": 160}` | unsure |
| MP05a | The battery must not discharge below 80 kWh from 6 to 9 PM. | `minimum_battery_reserve` `{"hours": [18, 19, 20], "minimum_energy_kwh": 80}` | correct |
| MP09b | From 6 to 9 PM: maximum 150 kWh imported. | `max_grid_window` `{"hours": [18, 19, 20], "max_grid_kwh": 150}` | correct |

## Deliberately excluded: the spec does not give a single answer

Avoid scoring these as hard gates. Organiser tests may choose either reading.

- **'1 PM through 3 PM'** with clock times. The spec defines only 'to' (exclusive). 'Through' could mean [13,14] or [13,14,15]. The suite uses 'through' only with an explicit slot or 'end of the hour' wording (E02, TT10).
- **Overnight wrap ('10 PM to 2 AM').** The horizon is hours 0-23 of one day, and the spec does not say whether 0-1 belongs to this schedule. Note: `eval/paraphrases.jsonl` and `tests/test_tripwire.py` both assert `[0,1,22,23]`, which is your assumption, not the spec's.
- **Minute-level times ('until 3:30 PM').** The spec says whole-hour intervals, and partial-hour rounding is undefined. Your prompt rounds outward, but a judge might round differently.
- **Vague periods ('this afternoon', 'the evening peak')** with no clock hours.
- **Window-total grid limits ('no more than 450 kWh over 6-9 PM').** max_grid_window is per hour, so a total is not representable.
- **Battery ceilings ('don't charge above 80%', 'keep 100 kWh of headroom').** No such directive exists.
- **'Reduced by a factor of four'.** Divide by 4 and subtract 4/5 are both common readings.
- **'Battery idle 2-4 PM'.** It implies both no-charge and no-discharge, which is two directives from one note.
- **Relative-to-now ('for the next two hours') and named weekdays ('on Saturday').** The request carries no clock or date.

## Catalogue

### 1. Category tests

#### A. Same meaning, indirect wording (no reduce/charge/discharge/cap)

**A01**: "The battery will not be able to take in any energy from 10 AM to 1 PM while the BMS is recalibrated."

- **Expected:** `no_charge_window` `{"hours": [10, 11, 12]}`
- **Why tricky:** No 'charge' keyword; 'take in energy' is charging. 'not be able' + 'battery' reads like a generic battery lockout.
- **Common wrong interpretation:** no_discharge_window [10,11,12] (generic 'battery unavailable'), or no_op (no trigger word).
- **Checking:** Classification from the direction of energy flow rather than from the word 'charge'.
- **S/F/B:** 3/3/4 · **Tripwire:** unsure · **Modes:** wrong_type, false_no_op

**A02**: "From 5 PM until 8 PM, the campus loads must be served without any help from the battery."

- **Expected:** `no_discharge_window` `{"hours": [17, 18, 19]}`
- **Why tricky:** No 'discharge' keyword; the battery 'helping' the load is discharging. Talks about serving load, which smells like demand or grid.
- **Common wrong interpretation:** no_op, or max_grid_window with no number, or minimum_battery_reserve.
- **Checking:** Recognising 'battery must not supply load' as no_discharge_window without the keyword.
- **S/F/B:** 3/3/4 · **Tripwire:** unsure · **Modes:** wrong_type, false_no_op

**A03**: "Haze from the brick kilns will leave the rooftop arrays producing roughly two-fifths of their forecast between 9 AM and noon."

- **Expected:** `solar_reduction` `{"hours": [9, 10, 11], "factor": 0.4}`
- **Why tricky:** Never says 'solar' or 'reduce'. 'two-fifths' is an unusual fraction; 'leave ... producing' means the remaining share.
- **Common wrong interpretation:** factor 0.6 (treating two-fifths as the loss), or no_op because 'arrays' isn't recognised as solar.
- **Checking:** Solar detection from synonyms, fraction normalisation, and 'remaining' semantics.
- **S/F/B:** 3/3/3 · **Tripwire:** correct · **Modes:** percent_inversion, false_no_op

**A04**: "The transformer serving campus is derated tonight: no more than 170 kWh may come in from the utility in any hour from 7 PM to 10 PM."

- **Expected:** `max_grid_window` `{"hours": [19, 20, 21], "max_grid_kwh": 170}`
- **Why tricky:** No 'grid', 'import' or 'cap'. 'Derated' is solar-inverter jargon too, and 'tonight' may trip a future-day filter.
- **Common wrong interpretation:** solar_reduction (from 'derated'), or no_op (tonight judged as not today).
- **Checking:** Mapping 'come in from the utility' to grid import; 'tonight' is today.
- **S/F/B:** 3/2/3 · **Tripwire:** correct · **Modes:** wrong_type, applicability

**A05**: "Whatever happens this evening, the storage bank has to still be holding 110 kWh at the end of every hour from 6 PM to 10 PM."

- **Expected:** `minimum_battery_reserve` `{"hours": [18, 19, 20, 21], "minimum_energy_kwh": 110}` (capacity 200 kWh)
- **Why tricky:** No 'reserve'/'minimum'/'at least'. 'Still be holding' sounds like 'hold the battery' (idle) and so like no_discharge_window.
- **Common wrong interpretation:** no_discharge_window [18..21] (drops the 110 kWh), or hours [18..22].
- **Checking:** Reserve detection from end-of-hour energy wording, which matches the spec's battery_energy_after semantics.
- **S/F/B:** 4/3/4 · **Tripwire:** unsure · **Modes:** wrong_type

**A06**: "Electricians will have the charger's supply breaker open from 13:00 to 15:00."

- **Expected:** `no_charge_window` `{"hours": [13, 14]}`
- **Why tricky:** Implied restriction: an open breaker on the charger means no charging. No prohibition verb at all; it reads as an FYI.
- **Common wrong interpretation:** no_op (sounds informational), or no_discharge_window (the 'battery is offline').
- **Checking:** Inferring a restriction from an equipment state.
- **S/F/B:** 4/4/4 · **Tripwire:** unsure · **Modes:** false_no_op, wrong_type

**A07**: "Shade cloth is going up over the PV canopy for the 2-4 PM photo shoot; plan on just half of what it would normally give."

- **Expected:** `solar_reduction` `{"hours": [14, 15], "factor": 0.5}`
- **Why tricky:** Solar only as 'PV canopy'; the value is 'half of what it would normally give' with no percent sign; 'photo shoot' looks like a distractor event.
- **Common wrong interpretation:** no_op (sounds like an event notice).
- **Checking:** Not dismissing an event-flavoured note that carries a real solar constraint.
- **S/F/B:** 2/2/3 · **Tripwire:** correct · **Modes:** false_no_op

**A08**: "The UPS bus for the server room must always find at least 60 kWh waiting in the campus battery between midnight and 5 AM."

- **Expected:** `minimum_battery_reserve` `{"hours": [0, 1, 2, 3, 4], "minimum_energy_kwh": 60}` (capacity 200 kWh)
- **Why tricky:** Reserve phrased from the load's point of view ('find ... waiting'); midnight start.
- **Common wrong interpretation:** no_discharge_window, or hours [0..5] (treating 5 AM as inclusive).
- **Checking:** Reserve semantics from indirect phrasing plus a midnight start.
- **S/F/B:** 3/2/3 · **Tripwire:** correct · **Modes:** wrong_type, end_inclusive

#### B. Solar value: reduction vs remaining

**B01**: "Expect solar to fall 60 percent short of forecast from 11 AM to 2 PM."

- **Expected:** `solar_reduction` `{"hours": [11, 12, 13], "factor": 0.4}`
- **Why tricky:** 'Fall ... short' is a shortfall (a loss) but has no 'by'; many readers see 'fall ... 60 percent' as 'fall to 60%'.
- **Common wrong interpretation:** factor 0.6.
- **Checking:** Loss vs remaining semantics without the words 'by' or 'reduction'.
- **S/F/B:** 3/3/4 · **Tripwire:** correct · **Modes:** percent_inversion

**B02**: "Solar production will come in 20% below normal from 8 AM to 11 AM due to morning fog."

- **Expected:** `solar_reduction` `{"hours": [8, 9, 10], "factor": 0.8}`
- **Why tricky:** '20% below normal' means 80% remains. The number sits next to a lowering word, so pattern logic picks 'remaining 20'.
- **Common wrong interpretation:** factor 0.2.
- **Checking:** Percent inversion in the other direction: a small loss must not become a small remainder.
- **S/F/B:** 4/4/5 · **Tripwire:** correct · **Modes:** percent_inversion

**B03**: "A reduction to 70% of rated PV output applies from 10:00 to 12:00 while one inverter string is serviced."

- **Expected:** `solar_reduction` `{"hours": [10, 11], "factor": 0.7}`
- **Why tricky:** Contains the word 'reduction' but it is a reduction TO 70%, so 70% remains.
- **Common wrong interpretation:** factor 0.3 (keyword 'reduction' forces the loss reading).
- **Checking:** 'Reduction to X' vs 'reduction of X'; the preposition decides.
- **S/F/B:** 4/4/5 · **Tripwire:** correct · **Modes:** percent_inversion

**B04**: "Rooftop solar will lose three-quarters of its output between noon and 3 PM."

- **Expected:** `solar_reduction` `{"hours": [12, 13, 14], "factor": 0.25}`
- **Why tricky:** Verbal fraction plus a loss verb; noon start.
- **Common wrong interpretation:** factor 0.75.
- **Checking:** Fraction-as-loss normalisation.
- **S/F/B:** 3/3/3 · **Tripwire:** correct · **Modes:** percent_inversion

**B05**: "Dust on the panels will cut PV output by two-thirds from 9 AM to noon."

- **Expected:** `solar_reduction` `{"hours": [9, 10, 11], "factor": 0.333333}`
- **Why tricky:** Non-terminating fraction lost; the answer is 1/3, not 2/3. Tolerance matters (0.33 vs 0.3333).
- **Common wrong interpretation:** factor 0.666667, or a rounded 0.3.
- **Checking:** Loss fraction to remaining factor, with rounding inside tolerance.
- **S/F/B:** 3/3/3 · **Tripwire:** correct · **Modes:** percent_inversion, arithmetic

**B06**: "PV curtailment of 70% will be in effect from 1 PM to 3 PM for inverter firmware testing."

- **Expected:** `solar_reduction` `{"hours": [13, 14], "factor": 0.3}`
- **Why tricky:** Grid jargon: 70% curtailment means 70% is thrown away. There is no reduce/drop verb.
- **Common wrong interpretation:** factor 0.7 ('curtailment of 70%' read as a 70% level).
- **Checking:** Domain term 'curtailment' mapped to the loss semantics.
- **S/F/B:** 3/3/4 · **Tripwire:** correct · **Modes:** percent_inversion

**B07**: "Only one-tenth of the usual solar yield will be available 2-5 PM because of the dust storm."

- **Expected:** `solar_reduction` `{"hours": [14, 15, 16], "factor": 0.1}`
- **Why tricky:** Uncommon fraction 'one-tenth'; 'yield' instead of output.
- **Common wrong interpretation:** factor 0.9.
- **Checking:** Fraction normalisation with remaining semantics.
- **S/F/B:** 2/2/2 · **Tripwire:** correct · **Modes:** percent_inversion

**B08**: "The solar field will be switched off entirely for inspection from 7 AM to 9 AM."

- **Expected:** `solar_reduction` `{"hours": [7, 8], "factor": 0.0}`
- **Why tricky:** No number at all; the factor is 0. Code that tests `if factor:` treats 0 as missing, and an LLM may say no_op because nothing is 'reduced'.
- **Common wrong interpretation:** no_op, a missing factor, or factor 1.0.
- **Checking:** Full outage expressed as factor 0.0, which is a valid value and not a missing one.
- **S/F/B:** 3/3/4 · **Tripwire:** unsure · **Modes:** false_no_op, malformed_output

**B09**: "Solar output will be down by 25% from 3 PM to 5 PM."

- **Expected:** `solar_reduction` `{"hours": [15, 16], "factor": 0.75}`
- **Why tricky:** 'Down by' vs 'down to' is one short word apart.
- **Common wrong interpretation:** factor 0.25.
- **Checking:** The preposition 'by' marks a loss.
- **S/F/B:** 2/3/3 · **Tripwire:** correct · **Modes:** percent_inversion

#### C. Reserve as percentage / fraction of capacity

**C01**: "Keep the battery at least 40% charged from 6 PM to 9 PM."

- **Expected:** `minimum_battery_reserve` `{"hours": [18, 19, 20], "minimum_energy_kwh": 100}` (capacity 250 kWh)
- **Why tricky:** '40% charged' is a state of charge, so it must become 0.40 x 250 = 100 kWh. The word 'charged' may pull toward the charge-window types.
- **Common wrong interpretation:** 40 kWh (unit dropped), or no_charge_window.
- **Checking:** Percent-of-capacity conversion; 'charged' as an adjective, not an action.
- **S/F/B:** 2/2/3 · **Tripwire:** correct · **Modes:** reserve_conversion, wrong_type

**C02**: "Hold half the pack in reserve between 19:00 and 23:00."

- **Expected:** `minimum_battery_reserve` `{"hours": [19, 20, 21, 22], "minimum_energy_kwh": 150}` (capacity 300 kWh)
- **Why tricky:** 'Half the pack' has no percent sign and 'pack' is slang for the battery.
- **Common wrong interpretation:** 50 kWh (half read as 50), or 0.5 kWh.
- **Checking:** Fraction of capacity: 0.5 x 300 = 150.
- **S/F/B:** 3/2/3 · **Tripwire:** unsure · **Modes:** reserve_conversion

**C03**: "From 5 PM until 9 PM, stored energy must stay at or above one-third of full capacity."

- **Expected:** `minimum_battery_reserve` `{"hours": [17, 18, 19, 20], "minimum_energy_kwh": 80}` (capacity 240 kWh)
- **Why tricky:** Third of 240 = 80; a third as a percentage is 33.33, which tests rounding.
- **Common wrong interpretation:** 33.33 kWh, or 79.99 (rounding beyond tolerance is fine, but 33 is not).
- **Checking:** Fraction-of-capacity conversion with a non-terminating percentage.
- **S/F/B:** 3/3/3 · **Tripwire:** unsure · **Modes:** reserve_conversion, arithmetic

**C04**: "Battery should be no less than three-quarters full from 8 PM until midnight."

- **Expected:** `minimum_battery_reserve` `{"hours": [20, 21, 22, 23], "minimum_energy_kwh": 150}` (capacity 200 kWh)
- **Why tricky:** 'Three-quarters full' = 75% SOC = 150 of 200. 'Until midnight' must end at 24, not 0.
- **Common wrong interpretation:** 75 kWh, or hours [] / [20] because midnight is parsed as hour 0.
- **Checking:** Reserve conversion plus the 'until midnight' end boundary.
- **S/F/B:** 3/3/3 · **Tripwire:** unsure · **Modes:** reserve_conversion, meridiem

**C05**: "Maintain 35 percent state of charge or higher from midnight to 4 AM."

- **Expected:** `minimum_battery_reserve` `{"hours": [0, 1, 2, 3], "minimum_energy_kwh": 140}` (capacity 400 kWh)
- **Why tricky:** Written 'percent' plus the SOC acronym-in-words; the capacity is 400.
- **Common wrong interpretation:** 35 kWh.
- **Checking:** Reserve conversion with a verbal percent.
- **S/F/B:** 2/2/3 · **Tripwire:** correct · **Modes:** reserve_conversion

**C06**: "Keep 45 kWh - a quarter of the pack - in reserve from 6 PM to 8 PM."

- **Expected:** `minimum_battery_reserve` `{"hours": [18, 19], "minimum_energy_kwh": 45}` (capacity 180 kWh)
- **Why tricky:** Redundant, consistent restatement. A converter may apply the fraction on top of the kWh (a quarter of 45) or report 25 with unit kWh.
- **Common wrong interpretation:** 11.25 kWh, 25 kWh, or 45% of capacity (81 kWh).
- **Checking:** Not double-converting when an absolute kWh value is given.
- **S/F/B:** 3/3/4 · **Tripwire:** correct · **Modes:** reserve_conversion

**C07**: "Keep a 30 kWh floor in the battery from 1 PM to 4 PM."

- **Expected:** `minimum_battery_reserve` `{"hours": [13, 14, 15], "minimum_energy_kwh": 30}` (capacity 200 kWh)
- **Why tricky:** When the scenario's base minimum is higher (e.g. 40 kWh), the directive is still 30. Some pipelines 'fix' it to the base minimum or drop it as redundant.
- **Common wrong interpretation:** no_op ('already covered by the base minimum'), or minimum_energy_kwh = 40.
- **Checking:** Reporting the stated value, not the effective floor. The optimizer applies max(base, directive), not the interpreter.
- **S/F/B:** 3/2/3 · **Tripwire:** correct · **Modes:** false_no_op, reserve_conversion

**C08**: "The battery must not drop under 60% from 7 PM to 10 PM."

- **Expected:** `minimum_battery_reserve` `{"hours": [19, 20, 21], "minimum_energy_kwh": 120}` (capacity 200 kWh)
- **Why tricky:** 'Must not drop' contains 'not' and 'battery', which prohibition patterns pick up as a window type.
- **Common wrong interpretation:** no_discharge_window [19,20,21].
- **Checking:** A floor is a reserve, not a ban on discharge.
- **S/F/B:** 2/2/3 · **Tripwire:** correct · **Modes:** wrong_type, reserve_conversion

#### D. 12h / 24h / noon / midnight

**D01**: "No charging from 0600 to 0900 hrs."

- **Expected:** `no_charge_window` `{"hours": [6, 7, 8]}`
- **Why tricky:** Military time without a colon; '0600' may be read as 600.
- **Common wrong interpretation:** hours out of range or rejected; [6,7,8,9].
- **Checking:** Four-digit time normalisation.
- **S/F/B:** 2/2/3 · **Tripwire:** correct · **Modes:** wrong_hours

**D02**: "Grid import must stay under 130 kWh 20:00-24:00."

- **Expected:** `max_grid_window` `{"hours": [20, 21, 22, 23], "max_grid_kwh": 130}`
- **Why tricky:** '24:00' is a legal end time but not a legal hour. Naive parsers produce 24 in the list or reject the span.
- **Common wrong interpretation:** hours [20..24] (invalid), or [20,21,22].
- **Checking:** End-of-day handling: end 24 means up to and including hour 23.
- **S/F/B:** 2/3/4 · **Tripwire:** correct · **Modes:** wrong_hours, malformed_output

**D03**: "Solar drops to 50% from noon till 2."

- **Expected:** `solar_reduction` `{"hours": [12, 13], "factor": 0.5}`
- **Why tricky:** '2' has no meridiem; after noon it is 14. 'till' spelling.
- **Common wrong interpretation:** hours [2..11] or a wrap-around from 12 to 2 AM.
- **Checking:** Meridiem inference from the start time.
- **S/F/B:** 2/3/3 · **Tripwire:** correct · **Modes:** meridiem

**D04**: "Keep 90 kWh in the battery from 9 in the evening until midnight."

- **Expected:** `minimum_battery_reserve` `{"hours": [21, 22, 23], "minimum_energy_kwh": 90}` (capacity 200 kWh)
- **Why tricky:** '9 in the evening' instead of PM; 'until midnight' must end at 24.
- **Common wrong interpretation:** hours [9..23], or [] from midnight = 0.
- **Checking:** Evening meridiem phrase plus the midnight end.
- **S/F/B:** 2/2/3 · **Tripwire:** unsure · **Modes:** meridiem

**D05**: "Battery discharge is blocked from 12 AM to 2 AM."

- **Expected:** `no_discharge_window` `{"hours": [0, 1]}`
- **Why tricky:** '12 AM' is midnight (0), not noon. Naive 12h conversion gives 12.
- **Common wrong interpretation:** hours [12,13] or a wrap [12..23, 0, 1].
- **Checking:** 12 AM = 0.
- **S/F/B:** 3/3/4 · **Tripwire:** correct · **Modes:** meridiem

**D06**: "The charger is down for the hour starting at 3 PM."

- **Expected:** `no_charge_window` `{"hours": [15]}`
- **Why tricky:** Single-hour window with only a start given. An LLM reporting start 15 and end 15 creates an empty span.
- **Common wrong interpretation:** hours [] or [15,16], or a guardrail rejection for an empty span.
- **Checking:** Single-slot window: start 15, end 16.
- **S/F/B:** 3/3/4 · **Tripwire:** unsure · **Modes:** wrong_hours, malformed_output

**D07**: "From 11 AM until 12 PM, solar will be at a quarter of forecast."

- **Expected:** `solar_reduction` `{"hours": [11], "factor": 0.25}`
- **Why tricky:** '12 PM' is noon. Naive conversion makes it 24 or 0 and produces [11..23] or a wrap.
- **Common wrong interpretation:** hours [11..23].
- **Checking:** 12 PM = 12, giving a one-hour window.
- **S/F/B:** 3/3/4 · **Tripwire:** correct · **Modes:** meridiem

#### E. Until / through / between and start-inclusive, end-exclusive traps

**E01**: "Do not discharge the battery from 4 PM up to but not including 7 PM."

- **Expected:** `no_discharge_window` `{"hours": [16, 17, 18]}`
- **Why tricky:** Explicit exclusivity. A model told 'end is exclusive' may exclude twice and drop 18.
- **Common wrong interpretation:** [16,17].
- **Checking:** No double exclusion.
- **S/F/B:** 2/3/4 · **Tripwire:** unsure · **Modes:** end_inclusive

**E02**: "Charging is blocked during hours 14 through 16 inclusive."

- **Expected:** `no_charge_window` `{"hours": [14, 15, 16]}`
- **Why tricky:** Hour slots, not clock times, and explicitly inclusive. In an end-exclusive span format the end must be 17.
- **Common wrong interpretation:** [14,15] (the default exclusive rule applied blindly).
- **Checking:** Slot-inclusive language overrides the default exclusive clock rule.
- **S/F/B:** 3/4/5 · **Tripwire:** correct · **Modes:** end_inclusive

**E03**: "Grid cap of 140 kWh applies from the start of the 6 PM hour to the end of the 8 PM hour."

- **Expected:** `max_grid_window` `{"hours": [18, 19, 20], "max_grid_kwh": 140}`
- **Why tricky:** 'End of the 8 PM hour' = 9 PM. A literal reading of '8 PM' as the end loses hour 20.
- **Common wrong interpretation:** [18,19].
- **Checking:** Hour-slot end phrase converted to the exclusive end 21.
- **S/F/B:** 3/3/4 · **Tripwire:** unsure · **Modes:** end_inclusive

**E04**: "Solar will be at 30% between the hours of 1 and 3 in the afternoon."

- **Expected:** `solar_reduction` `{"hours": [13, 14], "factor": 0.3}`
- **Why tricky:** 'Between the hours of' sounds slot-like, but these are clock times, so the window is exclusive. 'In the afternoon' supplies PM.
- **Common wrong interpretation:** [13,14,15], or [1,2].
- **Checking:** 'Between' plus clock times follows the default exclusive rule.
- **S/F/B:** 2/2/2 · **Tripwire:** unsure · **Modes:** end_inclusive, meridiem

**E05**: "No discharging for three hours from 6 PM."

- **Expected:** `no_discharge_window` `{"hours": [18, 19, 20]}`
- **Why tricky:** Duration instead of an end time.
- **Common wrong interpretation:** [18,19,20,21] or [18].
- **Checking:** Duration arithmetic: 3 hours from 18 gives 18, 19, 20.
- **S/F/B:** 2/2/3 · **Tripwire:** unsure · **Modes:** wrong_hours

**E06**: "Charging is allowed only until 6 AM; after that, no charging for the rest of the day."

- **Expected:** `no_charge_window` `{"hours": [6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23]}`
- **Why tricky:** The restricted window is the complement of the stated 'allowed' window. It opens with a permission.
- **Common wrong interpretation:** [0..5] (the stated range taken as the restriction), or no_op.
- **Checking:** Complement windows and 'rest of the day' ending at 24.
- **S/F/B:** 4/3/4 · **Tripwire:** unsure · **Modes:** wrong_hours, false_no_op

**E07**: "From 10 PM onward the battery must keep at least 70 kWh."

- **Expected:** `minimum_battery_reserve` `{"hours": [22, 23], "minimum_energy_kwh": 70}` (capacity 200 kWh)
- **Why tricky:** Open-ended 'onward' runs to the end of the horizon, not to the next morning.
- **Common wrong interpretation:** [22] only, or wrapping into [0..].
- **Checking:** Open-ended window clipped at 24.
- **S/F/B:** 2/2/3 · **Tripwire:** correct · **Modes:** wrong_hours

#### F. Maintenance implying no-charge vs no-discharge

**F01**: "The rectifier that feeds energy into the battery bank will be swapped between 1 AM and 4 AM."

- **Expected:** `no_charge_window` `{"hours": [1, 2, 3]}`
- **Why tricky:** Pure equipment description; 'feeds energy into the battery' identifies the charging path. No prohibition word.
- **Common wrong interpretation:** no_op (maintenance FYI), or no_discharge_window.
- **Checking:** Maintenance on the charging path implies no_charge_window.
- **S/F/B:** 4/3/4 · **Tripwire:** unsure · **Modes:** false_no_op, wrong_type

**F02**: "The battery may soak up surplus solar, but it must not supply any load from 9 AM to 11 AM."

- **Expected:** `no_discharge_window` `{"hours": [9, 10]}`
- **Why tricky:** Mentions solar (a solar_reduction pull) and a permitted charge ('soak up') before the actual ban.
- **Common wrong interpretation:** solar_reduction, or no_charge_window.
- **Checking:** Picking the prohibited direction when both directions are mentioned.
- **S/F/B:** 3/3/4 · **Tripwire:** unsure · **Modes:** wrong_type

**F03**: "Discharging is fine, but do not charge the battery between 3 PM and 5 PM."

- **Expected:** `no_charge_window` `{"hours": [15, 16]}`
- **Why tricky:** Both keywords appear; 'discharging' comes first and the negation attaches to 'charge'.
- **Common wrong interpretation:** no_discharge_window [15,16].
- **Checking:** Negation scope: which verb 'do not' governs.
- **S/F/B:** 3/3/5 · **Tripwire:** unsure · **Modes:** wrong_type

**F04**: "Relay testing on the battery's output side, 18:00-20:00: the pack can't push power to the campus bus."

- **Expected:** `no_discharge_window` `{"hours": [18, 19]}`
- **Why tricky:** 'Output side', 'pack', 'push power to the bus': discharge described without the word.
- **Common wrong interpretation:** no_op, or no_charge_window.
- **Checking:** Discharge synonyms.
- **S/F/B:** 3/3/3 · **Tripwire:** unsure · **Modes:** wrong_type, false_no_op

**F05**: "Nothing may be drawn from the battery between 5 and 7 PM."

- **Expected:** `no_discharge_window` `{"hours": [17, 18]}`
- **Why tricky:** Short passive form; 'drawn from' means discharge.
- **Common wrong interpretation:** no_charge_window.
- **Checking:** 'Drawn from' direction.
- **S/F/B:** 2/2/3 · **Tripwire:** unsure · **Modes:** wrong_type

**F06**: "The battery must not be topped up between 2 and 4 PM."

- **Expected:** `no_charge_window` `{"hours": [14, 15]}`
- **Why tricky:** 'Topped up' means charged, an idiom with no 'charge' keyword.
- **Common wrong interpretation:** no_discharge_window, or no_op.
- **Checking:** Charging idiom.
- **S/F/B:** 2/2/3 · **Tripwire:** unsure · **Modes:** wrong_type

**F07**: "Discharge protection test: the battery's charging circuit stays live, but its output is disabled from 7 PM to 9 PM."

- **Expected:** `no_discharge_window` `{"hours": [19, 20]}`
- **Why tricky:** 'charging' sits next to the only prohibition-like word ('disabled'), while 'Discharge' appears only as the test's name.
- **Common wrong interpretation:** no_charge_window [19,20].
- **Checking:** Which subsystem the restriction applies to (output), not which keyword is closest.
- **S/F/B:** 4/4/5 · **Tripwire:** unsure · **Modes:** wrong_type

**F08**: "Charge controller firmware flash 2-3 AM; the battery cannot accept energy during the flash."

- **Expected:** `no_charge_window` `{"hours": [2]}`
- **Why tricky:** One-hour window in the early morning; 'accept energy' means charging.
- **Common wrong interpretation:** [2,3], or PM hours [14].
- **Checking:** Single-hour AM window and a charging synonym.
- **S/F/B:** 3/2/3 · **Tripwire:** correct · **Modes:** wrong_hours, meridiem

#### G. Grid-cap wording and reserve/grid confusion

**G01**: "The feeder can only deliver 175 kWh to campus in any hour between 5 PM and 8 PM."

- **Expected:** `max_grid_window` `{"hours": [17, 18, 19], "max_grid_kwh": 175}`
- **Why tricky:** The feeder is the subject; the limit is on supply, not on import, so there is no 'cap' or 'exceed' word.
- **Common wrong interpretation:** minimum_battery_reserve 175, or no_op.
- **Checking:** 'Can only deliver' as an upper bound on grid import.
- **S/F/B:** 2/2/3 · **Tripwire:** unsure · **Modes:** wrong_type

**G02**: "Demand-response event 1-3 PM: the utility will only honour imports up to 95 kWh in each hour."

- **Expected:** `max_grid_window` `{"hours": [13, 14], "max_grid_kwh": 95}`
- **Why tricky:** Business framing ('demand-response event', 'honour') and the word 'demand', which pulls toward a demand change.
- **Common wrong interpretation:** no_op (sounds like a program announcement).
- **Checking:** Grid cap from contractual wording.
- **S/F/B:** 2/2/3 · **Tripwire:** unsure · **Modes:** false_no_op

**G03**: "The utility is holding feeder headroom in reserve for the hospital; campus grid import cannot exceed 140 kWh in any hour from 5 PM to 8 PM."

- **Expected:** `max_grid_window` `{"hours": [17, 18, 19], "max_grid_kwh": 140}`
- **Why tricky:** Contains 'reserve' but it is the utility's feeder reserve, not the battery's.
- **Common wrong interpretation:** minimum_battery_reserve 140 kWh.
- **Checking:** Keyword 'reserve' must not override the subject (grid import).
- **S/F/B:** 3/3/4 · **Tripwire:** unsure · **Modes:** wrong_type

**G04**: "Keep grid draw 40 kWh below the 200 kWh feeder rating between 6 PM and 9 PM."

- **Expected:** `max_grid_window` `{"hours": [18, 19, 20], "max_grid_kwh": 160}`
- **Why tricky:** Two numbers; the cap has to be computed (200 - 40).
- **Common wrong interpretation:** max_grid_kwh 40, or 200.
- **Checking:** Arithmetic the LLM must do itself because the cap is not stated directly.
- **S/F/B:** 3/4/4 · **Tripwire:** unsure · **Modes:** arithmetic

**G05**: "Grid import must stay below 180 kWh from 7 PM to 10 PM; the battery should cover anything above that."

- **Expected:** `max_grid_window` `{"hours": [19, 20, 21], "max_grid_kwh": 180}`
- **Why tricky:** The second clause describes how to meet the cap and sounds like a battery instruction.
- **Common wrong interpretation:** Two readings for one note, or minimum_battery_reserve.
- **Checking:** One note gives one directive; explanatory clauses are not constraints.
- **S/F/B:** 3/3/4 · **Tripwire:** correct · **Modes:** wrong_type, malformed_output

**G06**: "Campus must not rely on the grid for more than 110 kWh in any hour from 11 AM to 2 PM."

- **Expected:** `max_grid_window` `{"hours": [11, 12, 13], "max_grid_kwh": 110}`
- **Why tricky:** 'Rely on ... for more than' is an indirect upper bound.
- **Common wrong interpretation:** no_op.
- **Checking:** Indirect upper-bound wording.
- **S/F/B:** 2/2/3 · **Tripwire:** unsure · **Modes:** false_no_op

**G07**: "To protect the evening backup, battery energy must stay at or above 120 kWh from 6 PM to 9 PM even though grid import will be high."

- **Expected:** `minimum_battery_reserve` `{"hours": [18, 19, 20], "minimum_energy_kwh": 120}` (capacity 200 kWh)
- **Why tricky:** Mentions 'grid import will be high' with a kWh number nearby.
- **Common wrong interpretation:** max_grid_window 120.
- **Checking:** Keyword 'grid import' must not override the subject (battery energy floor).
- **S/F/B:** 3/3/4 · **Tripwire:** unsure · **Modes:** wrong_type

#### H. Note applicability: today vs other days, cancellations

**H01**: "From today until Friday, grid import must stay at or below 180 kWh between 6 PM and 9 PM."

- **Expected:** `max_grid_window` `{"hours": [18, 19, 20], "max_grid_kwh": 180}`
- **Why tricky:** Multi-day range that includes today. A future-day filter that fires on 'until Friday' drops it.
- **Common wrong interpretation:** no_op.
- **Checking:** A range starting today applies today.
- **S/F/B:** 4/4/5 · **Tripwire:** correct · **Modes:** applicability, false_no_op

**H02**: "Last night's no-discharge window is being repeated tonight, 6 PM to 8 PM."

- **Expected:** `no_discharge_window` `{"hours": [18, 19]}`
- **Why tricky:** Past reference ('last night') that is re-applied today.
- **Common wrong interpretation:** no_op (past event).
- **Checking:** Past mention with a present re-application.
- **S/F/B:** 4/4/4 · **Tripwire:** correct · **Modes:** applicability, false_no_op

**H03**: "Tonight from 8 to 11, keep at least 100 kWh in the battery for the hostel backup."

- **Expected:** `minimum_battery_reserve` `{"hours": [20, 21, 22], "minimum_energy_kwh": 100}` (capacity 200 kWh)
- **Why tricky:** 'Tonight' supplies PM and means today. '8 to 11' has no meridiem.
- **Common wrong interpretation:** no_op, or hours [8,9,10].
- **Checking:** 'Tonight' as a today marker and meridiem source.
- **S/F/B:** 2/2/3 · **Tripwire:** unsure · **Modes:** applicability, meridiem

**H04**: "The charging ban originally set for tomorrow has been moved to today, 1 PM to 3 PM."

- **Expected:** `no_charge_window` `{"hours": [13, 14]}`
- **Why tricky:** Contains 'tomorrow', but the ban has been moved to today.
- **Common wrong interpretation:** no_op (keyword 'tomorrow').
- **Checking:** Resolving the final date after a reschedule.
- **S/F/B:** 4/4/5 · **Tripwire:** unsure · **Modes:** applicability, false_no_op

**H05**: "Solar will be down to 20% from 9 AM to 11 AM this morning; tomorrow should be back to normal."

- **Expected:** `solar_reduction` `{"hours": [9, 10], "factor": 0.2}`
- **Why tricky:** The trailing 'tomorrow' clause is about recovery, not the constraint.
- **Common wrong interpretation:** no_op.
- **Checking:** Future clause does not cancel today's constraint.
- **S/F/B:** 3/3/4 · **Tripwire:** correct · **Modes:** applicability, false_no_op

**H06**: "Yesterday the feeder was capped at 150 kWh from 6 to 9 PM; that restriction has ended."

- **Expected:** `no_op` `null`
- **Why tricky:** A complete, well-formed grid-cap spec, but in the past and explicitly ended.
- **Common wrong interpretation:** max_grid_window [18,19,20] 150.
- **Checking:** Past plus ended means no effect today.
- **S/F/B:** 3/3/4 · **Tripwire:** correct · **Modes:** applicability, false_apply

**H07**: "The 2-4 PM charger outage announced this morning has been called off."

- **Expected:** `no_op` `null`
- **Why tricky:** Today, with an exact window and a charger outage, but cancelled. 'This morning' is a today marker.
- **Common wrong interpretation:** no_charge_window [14,15].
- **Checking:** Cancellation semantics.
- **S/F/B:** 4/4/4 · **Tripwire:** unsure · **Modes:** applicability, false_apply

**H08**: "Next Monday, the battery must not discharge between 5 and 7 PM for the fire drill."

- **Expected:** `no_op` `null`
- **Why tricky:** A fully specified no-discharge window on another day.
- **Common wrong interpretation:** no_discharge_window [17,18].
- **Checking:** Future-day filter on a well-formed constraint.
- **S/F/B:** 2/2/2 · **Tripwire:** correct · **Modes:** applicability, false_apply

#### I. Distractors dense with energy vocabulary

**I01**: "Phone charging lockers in the library will be unavailable from 2 PM to 4 PM."

- **Expected:** `no_op` `null`
- **Why tricky:** 'charging' + 'unavailable' + a clean window is exactly the no_charge_window template. The device is a phone locker, not the campus battery.
- **Common wrong interpretation:** no_charge_window [14,15].
- **Checking:** Checks the subject (which device) before matching the keyword.
- **S/F/B:** 3/4/5 · **Tripwire:** correct · **Modes:** false_apply

**I02**: "The Energy Club's talk 'Why batteries should never discharge below 20%' starts at 5 PM."

- **Expected:** `no_op` `null`
- **Why tricky:** Quoted title contains a complete reserve-like rule with a percentage and a time.
- **Common wrong interpretation:** minimum_battery_reserve 20% from 17.
- **Checking:** Quoted or reported text is not an instruction.
- **S/F/B:** 3/3/4 · **Tripwire:** unsure · **Modes:** false_apply

**I03**: "Solar-powered benches in the quad will be removed for repainting from 9 AM to noon."

- **Expected:** `no_op` `null`
- **Why tricky:** 'Solar' + window + 'removed'; campus PV output is unaffected.
- **Common wrong interpretation:** solar_reduction [9,10,11] factor 0.
- **Checking:** Solar keyword attached to an unrelated asset.
- **S/F/B:** 2/3/4 · **Tripwire:** unsure · **Modes:** false_apply

**I04**: "Please log battery temperature readings every hour from 10 AM to 2 PM."

- **Expected:** `no_op` `null`
- **Why tricky:** Polite imperative + battery + window, but it is a monitoring task.
- **Common wrong interpretation:** no_discharge_window or no_charge_window [10..13].
- **Checking:** An imperative is not automatically a constraint.
- **S/F/B:** 2/2/3 · **Tripwire:** unsure · **Modes:** false_apply

**I05**: "The metering team will read the grid import meter at 6 PM and 9 PM today."

- **Expected:** `no_op` `null`
- **Why tricky:** 'grid import' + two times + 'today' form a full max_grid template without a number.
- **Common wrong interpretation:** max_grid_window [18,19,20] with an invented value.
- **Checking:** No number means no cap; do not hallucinate one.
- **S/F/B:** 3/3/4 · **Tripwire:** unsure · **Modes:** false_apply, unsupported_directive

#### J. Surface noise: typos, shorthand, words for numbers, politeness, passive

**J01**: "no chrging of the batery 2-4pm pls"

- **Expected:** `no_charge_window` `{"hours": [14, 15]}`
- **Why tricky:** Misspelled keywords defeat regex or keyword checks; lowercase, no punctuation.
- **Common wrong interpretation:** no_op (no recognised keyword).
- **Checking:** Typo robustness.
- **S/F/B:** 1/2/4 · **Tripwire:** unsure · **Modes:** false_no_op

**J02**: "grid imprt cap -> 150kwh (18h-21h)"

- **Expected:** `max_grid_window` `{"hours": [18, 19, 20], "max_grid_kwh": 150}`
- **Why tricky:** Arrow, glued unit, 'h' suffix hours, typo.
- **Common wrong interpretation:** hours [18..21], or parse failure.
- **Checking:** Shorthand normalisation.
- **S/F/B:** 2/2/4 · **Tripwire:** correct · **Modes:** wrong_hours

**J03**: "keep >=90kWh in batt, 6pm-10pm!!"

- **Expected:** `minimum_battery_reserve` `{"hours": [18, 19, 20, 21], "minimum_energy_kwh": 90}` (capacity 200 kWh)
- **Why tricky:** The symbol '>=' carries the whole meaning; 'batt' abbreviation.
- **Common wrong interpretation:** max_grid_window 90 (the symbol ignored), or no_op.
- **Checking:** Symbolic comparison operators.
- **S/F/B:** 2/2/3 · **Tripwire:** correct · **Modes:** wrong_type

**J04**: "PV: approx. 1/4 of forecast; 10:00-12:00 (panel wash)."

- **Expected:** `solar_reduction` `{"hours": [10, 11], "factor": 0.25}`
- **Why tricky:** Slash fraction '1/4'; the 'approx.' abbreviation contains a period.
- **Common wrong interpretation:** factor 0.75, or 1/4 read as the date 1 April.
- **Checking:** Slash-fraction parsing with remaining semantics.
- **S/F/B:** 2/2/3 · **Tripwire:** unsure · **Modes:** percent_inversion

**J05**: "Kindly ensure that the battery is not discharged at any point between seven and nine this evening."

- **Expected:** `no_discharge_window` `{"hours": [19, 20]}`
- **Why tricky:** Polite passive; times in words; 'this evening' supplies PM.
- **Common wrong interpretation:** hours [7,8].
- **Checking:** Word times plus evening meridiem.
- **S/F/B:** 2/2/3 · **Tripwire:** unsure · **Modes:** meridiem

**J06**: "It has been decided that charging of the battery shall not be carried out between fourteen hundred and sixteen hundred hours."

- **Expected:** `no_charge_window` `{"hours": [14, 15]}`
- **Why tricky:** Bureaucratic passive and spoken military time ('fourteen hundred hours').
- **Common wrong interpretation:** hours [4..6], or a parse failure.
- **Checking:** Spoken 24h time.
- **S/F/B:** 3/3/4 · **Tripwire:** correct · **Modes:** wrong_hours

**J07**: "Grid import: max one hundred and twenty-five kWh/hour, 1700-2000."

- **Expected:** `max_grid_window` `{"hours": [17, 18, 19], "max_grid_kwh": 125}`
- **Why tricky:** Number in words ('one hundred and twenty-five'), where 'and' may split it; the unit is written 'kWh/hour'.
- **Common wrong interpretation:** max 100 or 25.
- **Checking:** Compound number words.
- **S/F/B:** 2/2/3 · **Tripwire:** correct · **Modes:** arithmetic

**J08**: "Solar output to be reduced by eighty percent between eleven a.m. and one p.m."

- **Expected:** `solar_reduction` `{"hours": [11, 12], "factor": 0.2}`
- **Why tricky:** Verbal percent plus dotted meridiems.
- **Common wrong interpretation:** factor 0.8.
- **Checking:** Verbal percent in loss semantics.
- **S/F/B:** 2/2/3 · **Tripwire:** correct · **Modes:** percent_inversion

**J09**: "BESS min SOC = 30%, 00:00-06:00"

- **Expected:** `minimum_battery_reserve` `{"hours": [0, 1, 2, 3, 4, 5], "minimum_energy_kwh": 90}` (capacity 300 kWh)
- **Why tricky:** Pure jargon (BESS = the battery system); no verb.
- **Common wrong interpretation:** no_op, or 30 kWh.
- **Checking:** Acronym understanding plus percent conversion (30% of 300).
- **S/F/B:** 2/2/3 · **Tripwire:** correct · **Modes:** reserve_conversion, false_no_op

**J10**: "discharge NOT permitted 1200-1400"

- **Expected:** `no_discharge_window` `{"hours": [12, 13]}`
- **Why tricky:** Upper-case negation, military times, no subject.
- **Common wrong interpretation:** [12,13,14], or times read as 1200 kWh.
- **Checking:** Terse log-style note.
- **S/F/B:** 1/2/3 · **Tripwire:** correct · **Modes:** wrong_hours

### 2. Very hard no_op distractors

**HN01**: "The earlier note about reduced solar between 1 and 3 PM was sent in error - please disregard it."

- **Expected:** `no_op` `null`
- **Why tricky:** Contains a complete solar-reduction description (without a value); the instruction is to cancel it.
- **Common wrong interpretation:** solar_reduction [13,14] with an invented factor.
- **Checking:** Retraction semantics; no invented numbers.
- **S/F/B:** 4/4/5 · **Tripwire:** unsure · **Modes:** false_apply, applicability

**HN02**: "Today's solar forecast already accounts for the expected cloud cover; do not apply any additional reduction."

- **Expected:** `no_op` `null`
- **Why tricky:** Contains 'solar', 'cloud cover', 'today' and 'reduction' but explicitly says no reduction.
- **Common wrong interpretation:** solar_reduction (all day, invented factor).
- **Checking:** Negated directive means no_op.
- **S/F/B:** 4/4/5 · **Tripwire:** unsure · **Modes:** false_apply

**HN03**: "EV chargers in parking lot C will be out of service from 9 AM to 1 PM."

- **Expected:** `no_op` `null`
- **Why tricky:** EV chargers are campus loads, not the battery's charger. 'out of service' + a window matches the no_charge template.
- **Common wrong interpretation:** no_charge_window [9,10,11,12].
- **Checking:** Subject disambiguation between charging devices.
- **S/F/B:** 3/4/4 · **Tripwire:** correct · **Modes:** false_apply

**HN04**: "The electricity tariff will be 20% higher than usual from 6 PM to 9 PM today."

- **Expected:** `no_op` `null`
- **Why tricky:** It really would change costs today, but tariffs come from the request and no directive can change them (spec: no invention of tariffs).
- **Common wrong interpretation:** Any directive (commonly max_grid_window or a percent shoved into solar_reduction factor 0.8).
- **Checking:** Unsupported change stays no_op; no invented directive.
- **S/F/B:** 4/3/4 · **Tripwire:** correct · **Modes:** unsupported_directive, false_apply

**HN05**: "Campus demand is expected to rise about 30% between 2 PM and 5 PM because of the convocation."

- **Expected:** `no_op` `null`
- **Why tricky:** Demand changes are not a supported directive; demand comes from the request.
- **Common wrong interpretation:** solar_reduction factor 0.7, or max_grid_window.
- **Checking:** No demand modification.
- **S/F/B:** 3/3/4 · **Tripwire:** correct · **Modes:** unsupported_directive, false_apply

**HN06**: "The battery's maximum charge rate has been confirmed at 50 kWh per hour."

- **Expected:** `no_op` `null`
- **Why tricky:** Restates a battery parameter with a kWh number. Battery limits come from the request, and there is no time window.
- **Common wrong interpretation:** no_charge_window (all day), or max_grid_window 50.
- **Checking:** No modification of battery parameters.
- **S/F/B:** 4/4/4 · **Tripwire:** unsure · **Modes:** unsupported_directive, false_apply

**HN07**: "The sustainability society's 'Discharge Your Stress' session runs from 5 to 7 PM in the student centre."

- **Expected:** `no_op` `null`
- **Why tricky:** A pun: 'Discharge' + a clean window.
- **Common wrong interpretation:** no_discharge_window [17,18].
- **Checking:** Keyword inside a proper noun.
- **S/F/B:** 2/3/4 · **Tripwire:** unsure · **Modes:** false_apply

**HN08**: "If the grid goes down tonight, follow the manual's battery reserve procedure."

- **Expected:** `no_op` `null`
- **Why tricky:** Conditional and hypothetical, with no value and no window; mentions grid, tonight and battery reserve.
- **Common wrong interpretation:** minimum_battery_reserve with an invented value.
- **Checking:** Hypothetical text is not a scheduled constraint.
- **S/F/B:** 3/3/3 · **Tripwire:** unsure · **Modes:** false_apply

**HN09**: "Operators asked whether the 6-9 PM feeder cap of 150 kWh applies today: it does not."

- **Expected:** `no_op` `null`
- **Why tricky:** The first 80% of the note is a perfect max_grid spec; the final three words negate it.
- **Common wrong interpretation:** max_grid_window [18,19,20] 150.
- **Checking:** Reads to the end; the final negation wins.
- **S/F/B:** 4/4/5 · **Tripwire:** unsure · **Modes:** false_apply, applicability

**HN10**: "Guest lecture at 2 PM in room 301: 'Capping grid import at 100 kWh with smart batteries'."

- **Expected:** `no_op` `null`
- **Why tricky:** A title contains 'capping grid import at 100 kWh'.
- **Common wrong interpretation:** max_grid_window from 14 with 100 kWh.
- **Checking:** Quoted material is not an instruction.
- **S/F/B:** 3/4/4 · **Tripwire:** unsure · **Modes:** false_apply

**HN11**: "Clear skies should push solar output about 20% above forecast from 11 AM to 1 PM."

- **Expected:** `no_op` `null`
- **Why tricky:** Solar + percentage + window, but it is an INCREASE. solar_reduction needs a factor in [0,1], and solar comes from the request.
- **Common wrong interpretation:** solar_reduction factor 1.2 (malformed), or factor 0.8 (inverted), or 0.2.
- **Checking:** An increase is not a reduction; the model must not emit an out-of-range factor.
- **S/F/B:** 3/3/4 · **Tripwire:** unsure · **Modes:** malformed_output, false_apply, unsupported_directive

### 3. Time-normalisation traps

**TT01**: "Grid import capped at 140 kWh from 12 AM to 3 AM."

- **Expected:** `max_grid_window` `{"hours": [0, 1, 2], "max_grid_kwh": 140}`
- **Why tricky:** 12 AM = 0.
- **Common wrong interpretation:** [12,13,14], or [12..23,0,1,2].
- **Checking:** 12 AM normalisation.
- **S/F/B:** 3/3/4 · **Tripwire:** correct · **Modes:** meridiem

**TT02**: "Charging blocked from 11 PM until midnight."

- **Expected:** `no_charge_window` `{"hours": [23]}`
- **Why tricky:** One-hour window ending at midnight; midnight as the end is 24, not 0.
- **Common wrong interpretation:** [] (23 to 0 read as empty), or [23,0] (a wrap), or all of [0..23].
- **Checking:** Midnight as an end boundary.
- **S/F/B:** 2/3/4 · **Tripwire:** correct · **Modes:** meridiem, wrong_hours

**TT03**: "No discharge 22:00-00:00."

- **Expected:** `no_discharge_window` `{"hours": [22, 23]}`
- **Why tricky:** '00:00' as an end means end of day. Naive parsing gives end 0 < start 22, so a wrap to the full day or an empty window.
- **Common wrong interpretation:** [22,23,0,...] or [].
- **Checking:** 24h end-of-day normalisation.
- **S/F/B:** 3/3/5 · **Tripwire:** correct · **Modes:** wrong_hours

**TT04**: "Solar at half output for three hours starting at 14:00."

- **Expected:** `solar_reduction` `{"hours": [14, 15, 16], "factor": 0.5}`
- **Why tricky:** Duration plus start; no end time given.
- **Common wrong interpretation:** [14,15,16,17] or [14].
- **Checking:** Duration expansion.
- **S/F/B:** 2/2/3 · **Tripwire:** unsure · **Modes:** wrong_hours

**TT05**: "Charger locked out for hour slots 18, 19 and 20."

- **Expected:** `no_charge_window` `{"hours": [18, 19, 20]}`
- **Why tricky:** An explicit list of slots, not a range. Systems that represent windows as start/end with an exclusive end must emit end 21; turning the list into '18 to 20' loses hour 20.
- **Common wrong interpretation:** [18,19].
- **Checking:** Explicit slot lists survive a start/end span representation.
- **S/F/B:** 3/4/5 · **Tripwire:** correct · **Modes:** end_inclusive

**TT06**: "Keep 80 kWh in the battery from 9 until noon."

- **Expected:** `minimum_battery_reserve` `{"hours": [9, 10, 11], "minimum_energy_kwh": 80}` (capacity 200 kWh)
- **Why tricky:** '9' has no meridiem; 'until noon' implies AM.
- **Common wrong interpretation:** [21,22,23,0..11] (9 PM wrap).
- **Checking:** Meridiem inferred from the end.
- **S/F/B:** 2/2/3 · **Tripwire:** unsure · **Modes:** meridiem

**TT07**: "Battery must not discharge from 6 in the evening until 9."

- **Expected:** `no_discharge_window` `{"hours": [18, 19, 20]}`
- **Why tricky:** The meridiem is on the start only; the end '9' inherits evening.
- **Common wrong interpretation:** [18..23,0..8] (9 AM wrap).
- **Checking:** Meridiem propagation from start to end.
- **S/F/B:** 2/2/3 · **Tripwire:** unsure · **Modes:** meridiem

**TT08**: "Two separate charging blackouts today: 7-9 AM and 5-7 PM."

- **Expected:** `no_charge_window` `{"hours": [7, 8, 17, 18]}`
- **Why tricky:** One note, two windows, one directive. Models may emit two entries for one note_index or keep only the first window.
- **Common wrong interpretation:** [7,8] only; or two interpretation entries (a duplicate note_index); or [7..18] merged.
- **Checking:** Multi-span union inside a single directive.
- **S/F/B:** 3/3/5 · **Tripwire:** unsure · **Modes:** multi_span, malformed_output

**TT09**: "From 7 PM onward, grid import may not exceed 120 kWh."

- **Expected:** `max_grid_window` `{"hours": [19, 20, 21, 22, 23], "max_grid_kwh": 120}`
- **Why tricky:** No end time.
- **Common wrong interpretation:** [19] only, or a wrap into the morning.
- **Checking:** Open-ended window to 24.
- **S/F/B:** 2/2/3 · **Tripwire:** correct · **Modes:** wrong_hours

**TT10**: "Charging is suspended from 1 PM through the end of the 3 PM hour."

- **Expected:** `no_charge_window` `{"hours": [13, 14, 15]}`
- **Why tricky:** 'Through the end of the 3 PM hour' explicitly includes slot 15, which overrides the default exclusive end.
- **Common wrong interpretation:** [13,14].
- **Checking:** Inclusive override phrasing.
- **S/F/B:** 4/4/5 · **Tripwire:** unsure · **Modes:** end_inclusive

**TT11**: "Solar will be at 40% from 10 AM, for the next four hours."

- **Expected:** `solar_reduction` `{"hours": [10, 11, 12, 13], "factor": 0.4}`
- **Why tricky:** Duration after a comma; 'next' might be read relative to the current time.
- **Common wrong interpretation:** [10..14] or [10].
- **Checking:** Duration expansion.
- **S/F/B:** 2/2/3 · **Tripwire:** unsure · **Modes:** wrong_hours

**TT12**: "Keep at least 60 kWh stored until 3 PM, starting at 1."

- **Expected:** `minimum_battery_reserve` `{"hours": [13, 14], "minimum_energy_kwh": 60}` (capacity 200 kWh)
- **Why tricky:** End before start in the sentence; the start '1' has no meridiem.
- **Common wrong interpretation:** [1,2,...,14] (from 1 AM), or [0..14].
- **Checking:** Reordered clauses and meridiem inherited from the end.
- **S/F/B:** 3/3/4 · **Tripwire:** unsure · **Modes:** meridiem

### 4. Numeric-normalisation traps

**NT01**: "PV will deliver 0.3 of its normal output from 10 AM to noon."

- **Expected:** `solar_reduction` `{"hours": [10, 11], "factor": 0.3}`
- **Why tricky:** A decimal fraction, not a percentage. If a model reports percentages it must say 30. Reporting 0.3 gives factor 0.003, and a 0..100 range check accepts it silently.
- **Common wrong interpretation:** factor 0.003 (0.3 treated as a percentage), or 0.7.
- **Checking:** Decimal-fraction vs percent scale.
- **S/F/B:** 3/4/5 · **Tripwire:** unsure · **Modes:** decimal_fraction, percent_inversion

**NT02**: "State of charge must not dip below 0.4 between 6 PM and 9 PM."

- **Expected:** `minimum_battery_reserve` `{"hours": [18, 19, 20], "minimum_energy_kwh": 80}` (capacity 200 kWh)
- **Why tricky:** SOC as a decimal (0.4 = 40% of 200 = 80). Reporting 0.4 as a percentage gives 0.8 kWh, which passes every range check.
- **Common wrong interpretation:** 0.8 kWh, 0.4 kWh, or 40 kWh.
- **Checking:** Decimal SOC to kWh.
- **S/F/B:** 3/4/5 · **Tripwire:** unsure · **Modes:** decimal_fraction, reserve_conversion

**NT03**: "Limit utility import to 0.2 MWh per hour from 17:00 to 20:00."

- **Expected:** `max_grid_window` `{"hours": [17, 18, 19], "max_grid_kwh": 200}`
- **Why tricky:** MWh unit; must be converted to 200 kWh.
- **Common wrong interpretation:** 0.2 kWh.
- **Checking:** Unit conversion.
- **S/F/B:** 3/3/4 · **Tripwire:** correct · **Modes:** unit_conversion

**NT04**: "The feeder is rated 250 kWh per hour, but only 60% of that is available from 6 PM to 9 PM."

- **Expected:** `max_grid_window` `{"hours": [18, 19, 20], "max_grid_kwh": 150}`
- **Why tricky:** The cap is a percentage of a stated rating and must be computed (0.6 x 250). There is no 'percent of rating' unit for grid caps.
- **Common wrong interpretation:** max_grid_kwh 250, 60, or 100 (40% lost confused with remaining).
- **Checking:** In-note arithmetic with remaining semantics.
- **S/F/B:** 4/4/5 · **Tripwire:** unsure · **Modes:** arithmetic, percent_inversion

**NT05**: "Four of the five equally sized rooftop arrays will be shaded and produce nothing from 9 AM to 11 AM."

- **Expected:** `solar_reduction` `{"hours": [9, 10], "factor": 0.2}`
- **Why tricky:** Count-based fraction: 1 of 5 arrays still produces, so factor 0.2.
- **Common wrong interpretation:** factor 0.8, or 0.
- **Checking:** Ratio reasoning to remaining factor.
- **S/F/B:** 4/4/4 · **Tripwire:** unsure · **Modes:** arithmetic, percent_inversion

**NT06**: "Grid import limited to 150 kW from 6 PM to 9 PM."

- **Expected:** `max_grid_window` `{"hours": [18, 19, 20], "max_grid_kwh": 150}`
- **Why tricky:** kW (power) rather than kWh. Over one-hour slots, a 150 kW limit caps each hour at 150 kWh.
- **Common wrong interpretation:** Rejected as the wrong unit, or no_op.
- **Checking:** Power-to-hourly-energy equivalence.
- **S/F/B:** 2/3/4 · **Tripwire:** unsure · **Modes:** unit_conversion, false_no_op

**NT07**: "Battery reserve: never less than a quarter of capacity, midnight-6 AM."

- **Expected:** `minimum_battery_reserve` `{"hours": [0, 1, 2, 3, 4, 5], "minimum_energy_kwh": 80}` (capacity 320 kWh)
- **Why tricky:** Fraction of capacity (0.25 x 320).
- **Common wrong interpretation:** 25 kWh.
- **Checking:** Fraction conversion.
- **S/F/B:** 2/2/3 · **Tripwire:** unsure · **Modes:** reserve_conversion

**NT08**: "Keep ninety-five kilowatt-hours in the battery from 7 to 10 PM."

- **Expected:** `minimum_battery_reserve` `{"hours": [19, 20, 21], "minimum_energy_kwh": 95}` (capacity 200 kWh)
- **Why tricky:** Number and unit both spelled out.
- **Common wrong interpretation:** 90 or 5.
- **Checking:** Compound number words.
- **S/F/B:** 2/2/3 · **Tripwire:** unsure · **Modes:** arithmetic

**NT09**: "Solar will produce 20% less than forecast between 1 PM and 4 PM."

- **Expected:** `solar_reduction` `{"hours": [13, 14, 15], "factor": 0.8}`
- **Why tricky:** '20% less' is a loss of 20.
- **Common wrong interpretation:** factor 0.2.
- **Checking:** Comparative-loss semantics.
- **S/F/B:** 3/4/5 · **Tripwire:** correct · **Modes:** percent_inversion

**NT10**: "Solar output will be reduced from 100% to 35% between 11 AM and 1 PM."

- **Expected:** `solar_reduction` `{"hours": [11, 12], "factor": 0.35}`
- **Why tricky:** Two percentages and the keyword 'reduced'. The end state (35%) is what remains.
- **Common wrong interpretation:** factor 0.65 (35 treated as the reduction), or 1.0.
- **Checking:** Choosing the end state from a from-to range.
- **S/F/B:** 3/4/5 · **Tripwire:** correct · **Modes:** percent_inversion

**NT11**: "Keep at least 50 kWh (20% of capacity) in the battery from 5 to 8 PM."

- **Expected:** `minimum_battery_reserve` `{"hours": [17, 18, 19], "minimum_energy_kwh": 50}` (capacity 250 kWh)
- **Why tricky:** Redundant but consistent (20% of 250 = 50). There are two candidate numbers.
- **Common wrong interpretation:** 10 kWh (20% of 50), or 20.
- **Checking:** No double conversion.
- **S/F/B:** 3/3/4 · **Tripwire:** unsure · **Modes:** reserve_conversion

**NT12**: "Keep grid import under 200 kWh per hour from 6 PM to 9 PM, which is 50 kWh less than usual."

- **Expected:** `max_grid_window` `{"hours": [18, 19, 20], "max_grid_kwh": 200}`
- **Why tricky:** A distractor number (50) and a 'less than' phrase.
- **Common wrong interpretation:** max_grid_kwh 150 or 50.
- **Checking:** Ignoring explanatory numbers.
- **S/F/B:** 3/3/4 · **Tripwire:** unsure · **Modes:** arithmetic

### 5. Paraphrase-equivalence sets

#### PS01: Solar 40% remaining, 10:00-13:00

All variants: `solar_reduction` `{"hours": [10, 11, 12], "factor": 0.4}`

**Checking:** Output must be identical across the set: same type, same hours, same factor.

| ID | Note | Trap | Common wrong | S/F/B | Tripwire |
|---|---|---|---|---|---|
| PS01a | Rooftop PV will run at 40% of forecast from 10 AM to 1 PM. | baseline wording | factor 0.6 | 1/1/2 | correct |
| PS01b | Haze will knock out 60 percent of solar production between 10:00 and 13:00. | loss phrasing ('knock out 60 percent') | factor 0.6 | 3/3/4 | correct |
| PS01c | From ten until one, only two-fifths of the expected solar will actually be usable. | word times without meridiem; two-fifths | hours [22,23,0] or [10..12] with factor 0.6 | 3/3/4 | unsure |
| PS01d | Expect solar to be cut by three-fifths during the late-morning window, 10 AM-1 PM. | loss as a fraction | factor 0.6 | 3/3/3 | correct |
| PS01e | PV derated to 0.4 of normal, 1000-1300 hrs. | decimal fraction + military time | factor 0.004 | 3/4/5 | unsure |

#### PS02: No charge 02:00-06:00

All variants: `no_charge_window` `{"hours": [2, 3, 4, 5]}`

**Checking:** Identical no_charge_window [2,3,4,5] across the set.

| ID | Note | Trap | Common wrong | S/F/B | Tripwire |
|---|---|---|---|---|---|
| PS02a | Battery charger offline 2 AM to 6 AM. | baseline | no_discharge_window | 1/1/2 | correct |
| PS02b | No energy may be put into the battery between 02:00 and 06:00. | direction phrase, no 'charge' | no_discharge_window | 2/2/3 | unsure |
| PS02c | The storage bank can't take a charge from two until six this morning. | word times + 'this morning' | hours [14..17] | 2/2/3 | unsure |
| PS02d | Please make sure the battery is not topped up during the 2-6 AM firmware flash. | idiom + polite form | no_op | 2/2/3 | unsure |
| PS02e | Charging is locked out for four hours starting at 2 AM. | duration | [2..6] | 2/2/3 | unsure |

#### PS03: No discharge 17:00-20:00

All variants: `no_discharge_window` `{"hours": [17, 18, 19]}`

**Checking:** Identical no_discharge_window [17,18,19] across the set.

| ID | Note | Trap | Common wrong | S/F/B | Tripwire |
|---|---|---|---|---|---|
| PS03a | Battery must not discharge from 5 PM to 8 PM. | baseline | no_charge_window | 1/1/2 | correct |
| PS03b | Between 17:00 and 20:00 the battery may not supply any load. | 'supply load' | no_op | 2/2/3 | unsure |
| PS03c | Relay testing 5-8 PM: battery output held at zero. | 'output held at zero' | minimum_battery_reserve 0 | 3/3/4 | unsure |
| PS03d | Do not draw energy out of the storage system from five until eight this evening. | word times + direction | no_charge_window | 2/2/3 | unsure |
| PS03e | The battery can still absorb solar, but it cannot be used to serve the load from 5 PM until 8 PM. | permitted charge mentioned first | no_charge_window or solar_reduction | 3/3/4 | unsure |

#### PS04: Reserve 125 kWh (50% of 250), 18:00-22:00

All variants: `minimum_battery_reserve` `{"hours": [18, 19, 20, 21], "minimum_energy_kwh": 125}` (capacity 250 kWh)

**Checking:** Identical minimum_energy_kwh = 125 whatever the unit in the text.

| ID | Note | Trap | Common wrong | S/F/B | Tripwire |
|---|---|---|---|---|---|
| PS04a | Keep at least 125 kWh in the battery from 6 PM to 10 PM. | baseline kWh | hours [18..22] | 1/1/2 | correct |
| PS04b | Maintain a minimum 50% state of charge between 18:00 and 22:00. | percent SOC | 50 kWh | 2/2/3 | correct |
| PS04c | From six until ten tonight the battery should never be less than half full. | 'half full' + word times | 50 kWh or hours [6..9] | 3/3/4 | unsure |
| PS04d | Emergency lighting needs half the pack held in reserve for the 6-10 PM window. | 'half the pack' | 50 kWh | 2/2/3 | unsure |
| PS04e | Don't let stored energy dip under one hundred twenty-five kilowatt-hours, 6pm-10pm. | number words | 100 or 25 | 2/2/3 | correct |

#### PS05: Grid cap 160 kWh, 18:00-21:00

All variants: `max_grid_window` `{"hours": [18, 19, 20], "max_grid_kwh": 160}`

**Checking:** Identical max_grid_window [18,19,20] 160.

| ID | Note | Trap | Common wrong | S/F/B | Tripwire |
|---|---|---|---|---|---|
| PS05a | Grid import cannot exceed 160 kWh per hour from 6 PM to 9 PM. | baseline | hours [18..21] | 1/1/2 | correct |
| PS05b | The feeder can only supply 160 kWh an hour between 18:00 and 21:00. | feeder as subject | minimum_battery_reserve | 2/2/3 | unsure |
| PS05c | Limit utility draw to 160 kWh in each hour of the 6-9 PM peak. | 'utility draw' | no_op | 2/2/3 | correct |
| PS05d | Please keep campus imports at or under one hundred sixty kWh from six until nine this evening. | number words + word times | 106 or 60; hours [6..8] | 2/2/3 | unsure |
| PS05e | Between 6 and 9 PM, no single hour's grid purchase may go over 160 kWh. | 'grid purchase' | no_op | 2/2/3 | unsure |

#### PS06: Solar zero, 07:00-10:00

All variants: `solar_reduction` `{"hours": [7, 8, 9], "factor": 0.0}`

**Checking:** Identical solar_reduction [7,8,9] factor 0.0.

| ID | Note | Trap | Common wrong | S/F/B | Tripwire |
|---|---|---|---|---|---|
| PS06a | Solar array completely offline 7-10 AM for inverter replacement. | no number | no_op | 2/2/3 | unsure |
| PS06b | No PV generation will be available from 07:00 until 10:00. | negated availability | no_op | 2/2/3 | unsure |
| PS06c | Expect a 100% loss of rooftop solar between seven and ten this morning. | 100% loss | factor 1.0 | 2/3/4 | unsure |
| PS06d | Panels disconnected for three hours starting at 7 AM - treat solar as zero. | duration + 'zero' | [7..10] | 2/2/3 | unsure |

#### PS07: Not today (no_op)

All variants: `no_op` `null`

**Checking:** All five are no_op, with applies=false and structured_adjustment=null.

| ID | Note | Trap | Common wrong | S/F/B | Tripwire |
|---|---|---|---|---|---|
| PS07a | Tomorrow the feeder will be limited to 150 kWh per hour from 6 to 9 PM. | future grid cap | max_grid_window | 2/2/3 | correct |
| PS07b | Next week's panel washing will cut solar in half between noon and 2 PM. | future solar | solar_reduction | 2/2/3 | correct |
| PS07c | A battery charger inspection is pencilled in for next Monday, 2-4 PM. | future charger | no_charge_window | 2/2/3 | correct |
| PS07d | Starting tomorrow, keep at least 100 kWh in reserve overnight. | future reserve | minimum_battery_reserve | 2/2/3 | correct |
| PS07e | Yesterday's no-discharge window from 6 to 8 PM went smoothly. | past discharge | no_discharge_window | 2/3/3 | correct |

#### PS08: Reserve 80 kWh (25% of 320), 00:00-06:00

All variants: `minimum_battery_reserve` `{"hours": [0, 1, 2, 3, 4, 5], "minimum_energy_kwh": 80}` (capacity 320 kWh)

**Checking:** Identical reserve [0..5] = 80 kWh.

| ID | Note | Trap | Common wrong | S/F/B | Tripwire |
|---|---|---|---|---|---|
| PS08a | Hold at least 80 kWh in storage from midnight until 6 AM. | baseline | hours [0..6] | 1/1/2 | correct |
| PS08b | Keep a quarter of the battery's capacity in reserve from 00:00 to 06:00. | fraction | 25 kWh | 2/2/3 | unsure |
| PS08c | From 12 AM to 6 AM the battery must not drop below 25% SOC. | 12 AM | hours [12..17] | 3/3/4 | correct |
| PS08d | Server-room backup requires 80 kWh on hand for the first six hours of the day. | window as 'first six hours' | no_op, or hours missing | 3/3/4 | unsure |

#### PS09: No charge 14:00-16:00 with discharge mentioned

All variants: `no_charge_window` `{"hours": [14, 15]}`

**Checking:** Identical no_charge_window [14,15].

| ID | Note | Trap | Common wrong | S/F/B | Tripwire |
|---|---|---|---|---|---|
| PS09a | From 14:00 to 16:00 the battery may discharge but must not charge. | both verbs | no_discharge_window | 3/3/4 | unsure |
| PS09b | Charger isolation, 2-4 PM: discharging is fine, charging is not. | elliptical negation | no_discharge_window | 3/3/5 | unsure |
| PS09c | The battery can't be topped up between two and four this afternoon. | idiom + word times | hours [2,3] | 2/2/3 | unsure |
| PS09d | Between 2 and 4 PM, no energy may flow into the battery. | direction only | no_discharge_window | 2/2/3 | unsure |

#### PS10: Grid cap 120 kWh, 11:00-13:00

All variants: `max_grid_window` `{"hours": [11, 12], "max_grid_kwh": 120}`

**Checking:** Identical max_grid_window [11,12] 120.

| ID | Note | Trap | Common wrong | S/F/B | Tripwire |
|---|---|---|---|---|---|
| PS10a | From 11 in the morning to 1 in the afternoon the campus can pull at most 120 kWh an hour off the grid. | word meridiems | hours [11..12] with an inclusive end | 2/2/3 | unsure |
| PS10b | Import ceiling of 120 kWh/h between 11:00 and 13:00. | 'ceiling' + kWh/h | no_op | 1/2/3 | correct |
| PS10c | Keep grid purchases from going over 0.12 MWh in any hour, 11 AM-1 PM. | MWh | 0.12 kWh | 3/3/4 | unsure |
| PS10d | Midday substation constraint: utility supply to campus is limited to one hundred twenty kWh per hour, 11 AM until 1 PM. | number words | 100 or 20 | 2/2/3 | correct |

### 6. Minimal pairs

#### MP01: 'receive' -> 'deliver'

**Why tricky:** Direction verb only; no charge/discharge keyword in either note. Flip: 'receive' -> 'deliver'.  
**Checking:** Type flips on one verb; hours identical.

| ID | Note | Expected | Common wrong | S/F/B | Tripwire |
|---|---|---|---|---|---|
| MP01a | The battery cannot receive energy from 2 to 5 PM. | `no_charge_window` `{"hours": [14, 15, 16]}` | no_discharge_window | 2/3/4 | unsure |
| MP01b | The battery cannot deliver energy from 2 to 5 PM. | `no_discharge_window` `{"hours": [14, 15, 16]}` | no_charge_window | 2/3/4 | unsure |

#### MP02: 'to' -> 'by'

**Why tricky:** One preposition inverts the factor. Flip: 'to' -> 'by'.  
**Checking:** Factor flips 0.3 <-> 0.7; type and hours unchanged.

| ID | Note | Expected | Common wrong | S/F/B | Tripwire |
|---|---|---|---|---|---|
| MP02a | Solar will drop to 30% from 10 AM to noon. | `solar_reduction` `{"hours": [10, 11], "factor": 0.3}` | factor 0.7 | 2/3/4 | correct |
| MP02b | Solar will drop by 30% from 10 AM to noon. | `solar_reduction` `{"hours": [10, 11], "factor": 0.7}` | factor 0.3 | 3/4/5 | correct |

#### MP03: 'today' -> 'tomorrow'

**Why tricky:** Applicability flips on one word. Flip: 'today' -> 'tomorrow'.  
**Checking:** applies flips; no_op must carry a null adjustment.

| ID | Note | Expected | Common wrong | S/F/B | Tripwire |
|---|---|---|---|---|---|
| MP03a | Panel cleaning today from 1 to 3 PM will halve solar output. | `solar_reduction` `{"hours": [13, 14], "factor": 0.5}` | no_op | 2/2/3 | correct |
| MP03b | Panel cleaning tomorrow from 1 to 3 PM will halve solar output. | `no_op` `null` | solar_reduction [13,14] 0.5 | 2/3/4 | correct |

#### MP04: '%' -> 'kWh'

**Why tricky:** Unit token decides whether capacity conversion happens. Flip: '%' -> 'kWh'.  
**Checking:** Value flips 100 <-> 40.

| ID | Note | Expected | Common wrong | S/F/B | Tripwire |
|---|---|---|---|---|---|
| MP04a | Keep at least 40% in the battery from 6 PM to 9 PM. | `minimum_battery_reserve` `{"hours": [18, 19, 20], "minimum_energy_kwh": 100}` (cap 250) | 40 kWh | 2/2/3 | correct |
| MP04b | Keep at least 40 kWh in the battery from 6 PM to 9 PM. | `minimum_battery_reserve` `{"hours": [18, 19, 20], "minimum_energy_kwh": 40}` (cap 250) | 100 kWh (40 converted as a percentage) | 2/2/3 | correct |

#### MP05: delete 'below 80 kWh'

**Why tricky:** 'must not discharge' + keyword matching gives no_discharge; the qualifier 'below 80 kWh' turns it into a floor. Flip: delete 'below 80 kWh'.  
**Checking:** Type flips reserve <-> no_discharge when the qualifier is removed.

| ID | Note | Expected | Common wrong | S/F/B | Tripwire |
|---|---|---|---|---|---|
| MP05a | The battery must not discharge below 80 kWh from 6 to 9 PM. | `minimum_battery_reserve` `{"hours": [18, 19, 20], "minimum_energy_kwh": 80}` (cap 200) | no_discharge_window [18,19,20] | 4/4/5 | correct |
| MP05b | The battery must not discharge from 6 to 9 PM. | `no_discharge_window` `{"hours": [18, 19, 20]}` | minimum_battery_reserve | 1/1/2 | correct |

#### MP06: 'prohibited' -> 'recommended'

**Why tricky:** A recommendation to charge is not a supported directive (no 'must charge' type exists). Flip: 'prohibited' -> 'recommended'.  
**Checking:** Type flips no_charge <-> no_op on modality.

| ID | Note | Expected | Common wrong | S/F/B | Tripwire |
|---|---|---|---|---|---|
| MP06a | Charging the battery is prohibited from 2 to 4 PM. | `no_charge_window` `{"hours": [14, 15]}` | no_op | 1/1/2 | correct |
| MP06b | Charging the battery is recommended from 2 to 4 PM. | `no_op` `null` | no_charge_window [14,15] | 3/4/4 | unsure |

#### MP07: 'PM' -> 'AM'

**Why tricky:** The trailing meridiem applies to both times. Flip: 'PM' -> 'AM'.  
**Checking:** Hours flip [13,14] <-> [1,2].

| ID | Note | Expected | Common wrong | S/F/B | Tripwire |
|---|---|---|---|---|---|
| MP07a | Grid import is capped at 150 kWh from 1 until 3 PM. | `max_grid_window` `{"hours": [13, 14], "max_grid_kwh": 150}` | [1,2] | 1/2/3 | correct |
| MP07b | Grid import is capped at 150 kWh from 1 until 3 AM. | `max_grid_window` `{"hours": [1, 2], "max_grid_kwh": 150}` | [13,14] (afternoon bias) | 2/3/3 | correct |

#### MP08: 'confirmed' -> 'cancelled'

**Why tricky:** Status word decides everything. Flip: 'confirmed' -> 'cancelled'.  
**Checking:** applies flips on the status word.

| ID | Note | Expected | Common wrong | S/F/B | Tripwire |
|---|---|---|---|---|---|
| MP08a | The 2-4 PM charging ban is confirmed for today. | `no_charge_window` `{"hours": [14, 15]}` | no_op | 2/2/3 | unsure |
| MP08b | The 2-4 PM charging ban is cancelled for today. | `no_op` `null` | no_charge_window [14,15] | 3/4/5 | unsure |

#### MP09: 'minimum ... stored' -> 'maximum ... imported'

**Why tricky:** Telegraphic notes; the direction word and the object together decide reserve vs grid (two-token edit). Flip: 'minimum ... stored' -> 'maximum ... imported'.  
**Checking:** Type flips reserve <-> max_grid; value and hours unchanged.

| ID | Note | Expected | Common wrong | S/F/B | Tripwire |
|---|---|---|---|---|---|
| MP09a | From 6 to 9 PM: minimum 150 kWh stored. | `minimum_battery_reserve` `{"hours": [18, 19, 20], "minimum_energy_kwh": 150}` (cap 250) | max_grid_window | 3/3/4 | correct |
| MP09b | From 6 to 9 PM: maximum 150 kWh imported. | `max_grid_window` `{"hours": [18, 19, 20], "max_grid_kwh": 150}` | minimum_battery_reserve | 3/3/4 | correct |

#### MP10: 'by a quarter' -> 'to a quarter'

**Why tricky:** Fraction version of MP02. Flip: 'by a quarter' -> 'to a quarter'.  
**Checking:** Factor flips 0.75 <-> 0.25.

| ID | Note | Expected | Common wrong | S/F/B | Tripwire |
|---|---|---|---|---|---|
| MP10a | Solar inspection 1-3 PM will cut output by a quarter. | `solar_reduction` `{"hours": [13, 14], "factor": 0.75}` | factor 0.25 | 3/4/5 | correct |
| MP10b | Solar inspection 1-3 PM will cut output to a quarter. | `solar_reduction` `{"hours": [13, 14], "factor": 0.25}` | factor 0.75 | 2/3/4 | correct |

#### MP11: 'into' -> 'out of'

**Why tricky:** Direction preposition only. Flip: 'into' -> 'out of'.  
**Checking:** Type flips on the preposition.

| ID | Note | Expected | Common wrong | S/F/B | Tripwire |
|---|---|---|---|---|---|
| MP11a | Energy may not flow into the battery from 7 to 9 PM. | `no_charge_window` `{"hours": [19, 20]}` | no_discharge_window | 2/3/4 | unsure |
| MP11b | Energy may not flow out of the battery from 7 to 9 PM. | `no_discharge_window` `{"hours": [19, 20]}` | no_charge_window | 2/3/4 | unsure |

## Full ranking

Sorted by S+F+B, with ties broken by B (brittleness), then F.

- **Top 12 by semantic difficulty:** B02 (4), B03 (4), F07 (4), H01 (4), H04 (4), HN01 (4), HN02 (4), HN09 (4), MP05a (4), NT04 (4), TT10 (4), A06 (4)
- **Top 12 by fool likelihood:** B02 (4), B03 (4), F07 (4), H01 (4), H04 (4), HN01 (4), HN02 (4), HN09 (4), MP05a (4), NT04 (4), TT10 (4), A06 (4)
- **Top 12 by brittleness exposure:** B02 (5), B03 (5), F07 (5), H01 (5), H04 (5), HN01 (5), HN02 (5), HN09 (5), MP05a (5), NT04 (5), TT10 (5), E02 (5)

| Rank | ID | Type | S | F | B | Total | Tripwire |
|---|---|---|---|---|---|---|---|
| 1 | B02 | solar_reduction | 4 | 4 | 5 | 13 | correct |
| 2 | B03 | solar_reduction | 4 | 4 | 5 | 13 | correct |
| 3 | F07 | no_discharge_window | 4 | 4 | 5 | 13 | unsure |
| 4 | H01 | max_grid_window | 4 | 4 | 5 | 13 | correct |
| 5 | H04 | no_charge_window | 4 | 4 | 5 | 13 | unsure |
| 6 | HN01 | no_op | 4 | 4 | 5 | 13 | unsure |
| 7 | HN02 | no_op | 4 | 4 | 5 | 13 | unsure |
| 8 | HN09 | no_op | 4 | 4 | 5 | 13 | unsure |
| 9 | MP05a | minimum_battery_reserve | 4 | 4 | 5 | 13 | correct |
| 10 | NT04 | max_grid_window | 4 | 4 | 5 | 13 | unsure |
| 11 | TT10 | no_charge_window | 4 | 4 | 5 | 13 | unsure |
| 12 | E02 | no_charge_window | 3 | 4 | 5 | 12 | correct |
| 13 | I01 | no_op | 3 | 4 | 5 | 12 | correct |
| 14 | MP02b | solar_reduction | 3 | 4 | 5 | 12 | correct |
| 15 | MP08b | no_op | 3 | 4 | 5 | 12 | unsure |
| 16 | MP10a | solar_reduction | 3 | 4 | 5 | 12 | correct |
| 17 | NT01 | solar_reduction | 3 | 4 | 5 | 12 | unsure |
| 18 | NT02 | minimum_battery_reserve | 3 | 4 | 5 | 12 | unsure |
| 19 | NT09 | solar_reduction | 3 | 4 | 5 | 12 | correct |
| 20 | NT10 | solar_reduction | 3 | 4 | 5 | 12 | correct |
| 21 | PS01e | solar_reduction | 3 | 4 | 5 | 12 | unsure |
| 22 | TT05 | no_charge_window | 3 | 4 | 5 | 12 | correct |
| 23 | A06 | no_charge_window | 4 | 4 | 4 | 12 | unsure |
| 24 | H02 | no_discharge_window | 4 | 4 | 4 | 12 | correct |
| 25 | H07 | no_op | 4 | 4 | 4 | 12 | unsure |
| 26 | HN06 | no_op | 4 | 4 | 4 | 12 | unsure |
| 27 | NT05 | solar_reduction | 4 | 4 | 4 | 12 | unsure |
| 28 | F03 | no_charge_window | 3 | 3 | 5 | 11 | unsure |
| 29 | PS09b | no_charge_window | 3 | 3 | 5 | 11 | unsure |
| 30 | TT03 | no_discharge_window | 3 | 3 | 5 | 11 | correct |
| 31 | TT08 | no_charge_window | 3 | 3 | 5 | 11 | unsure |
| 32 | G04 | max_grid_window | 3 | 4 | 4 | 11 | unsure |
| 33 | HN03 | no_op | 3 | 4 | 4 | 11 | correct |
| 34 | HN10 | no_op | 3 | 4 | 4 | 11 | unsure |
| 35 | MP06b | no_op | 3 | 4 | 4 | 11 | unsure |
| 36 | A05 | minimum_battery_reserve | 4 | 3 | 4 | 11 | unsure |
| 37 | E06 | no_charge_window | 4 | 3 | 4 | 11 | unsure |
| 38 | F01 | no_charge_window | 4 | 3 | 4 | 11 | unsure |
| 39 | HN04 | no_op | 4 | 3 | 4 | 11 | correct |
| 40 | A01 | no_charge_window | 3 | 3 | 4 | 10 | unsure |
| 41 | A02 | no_discharge_window | 3 | 3 | 4 | 10 | unsure |
| 42 | B01 | solar_reduction | 3 | 3 | 4 | 10 | correct |
| 43 | B06 | solar_reduction | 3 | 3 | 4 | 10 | correct |
| 44 | B08 | solar_reduction | 3 | 3 | 4 | 10 | unsure |
| 45 | C06 | minimum_battery_reserve | 3 | 3 | 4 | 10 | correct |
| 46 | D05 | no_discharge_window | 3 | 3 | 4 | 10 | correct |
| 47 | D06 | no_charge_window | 3 | 3 | 4 | 10 | unsure |
| 48 | D07 | solar_reduction | 3 | 3 | 4 | 10 | correct |
| 49 | E03 | max_grid_window | 3 | 3 | 4 | 10 | unsure |
| 50 | F02 | no_discharge_window | 3 | 3 | 4 | 10 | unsure |
| 51 | G03 | max_grid_window | 3 | 3 | 4 | 10 | unsure |
| 52 | G05 | max_grid_window | 3 | 3 | 4 | 10 | correct |
| 53 | G07 | minimum_battery_reserve | 3 | 3 | 4 | 10 | unsure |
| 54 | H05 | solar_reduction | 3 | 3 | 4 | 10 | correct |
| 55 | H06 | no_op | 3 | 3 | 4 | 10 | correct |
| 56 | HN05 | no_op | 3 | 3 | 4 | 10 | correct |
| 57 | HN11 | no_op | 3 | 3 | 4 | 10 | unsure |
| 58 | I02 | no_op | 3 | 3 | 4 | 10 | unsure |
| 59 | I05 | no_op | 3 | 3 | 4 | 10 | unsure |
| 60 | J06 | no_charge_window | 3 | 3 | 4 | 10 | correct |
| 61 | MP09a | minimum_battery_reserve | 3 | 3 | 4 | 10 | correct |
| 62 | MP09b | max_grid_window | 3 | 3 | 4 | 10 | correct |
| 63 | NT03 | max_grid_window | 3 | 3 | 4 | 10 | correct |
| 64 | NT11 | minimum_battery_reserve | 3 | 3 | 4 | 10 | unsure |
| 65 | NT12 | max_grid_window | 3 | 3 | 4 | 10 | unsure |
| 66 | PS01b | solar_reduction | 3 | 3 | 4 | 10 | correct |
| 67 | PS01c | solar_reduction | 3 | 3 | 4 | 10 | unsure |
| 68 | PS03c | no_discharge_window | 3 | 3 | 4 | 10 | unsure |
| 69 | PS03e | no_discharge_window | 3 | 3 | 4 | 10 | unsure |
| 70 | PS04c | minimum_battery_reserve | 3 | 3 | 4 | 10 | unsure |
| 71 | PS08c | minimum_battery_reserve | 3 | 3 | 4 | 10 | correct |
| 72 | PS08d | minimum_battery_reserve | 3 | 3 | 4 | 10 | unsure |
| 73 | PS09a | no_charge_window | 3 | 3 | 4 | 10 | unsure |
| 74 | PS10c | max_grid_window | 3 | 3 | 4 | 10 | unsure |
| 75 | TT01 | max_grid_window | 3 | 3 | 4 | 10 | correct |
| 76 | TT12 | minimum_battery_reserve | 3 | 3 | 4 | 10 | unsure |
| 77 | D02 | max_grid_window | 2 | 3 | 4 | 9 | correct |
| 78 | E01 | no_discharge_window | 2 | 3 | 4 | 9 | unsure |
| 79 | HN07 | no_op | 2 | 3 | 4 | 9 | unsure |
| 80 | I03 | no_op | 2 | 3 | 4 | 9 | unsure |
| 81 | MP01a | no_charge_window | 2 | 3 | 4 | 9 | unsure |
| 82 | MP01b | no_discharge_window | 2 | 3 | 4 | 9 | unsure |
| 83 | MP02a | solar_reduction | 2 | 3 | 4 | 9 | correct |
| 84 | MP03b | no_op | 2 | 3 | 4 | 9 | correct |
| 85 | MP10b | solar_reduction | 2 | 3 | 4 | 9 | correct |
| 86 | MP11a | no_charge_window | 2 | 3 | 4 | 9 | unsure |
| 87 | MP11b | no_discharge_window | 2 | 3 | 4 | 9 | unsure |
| 88 | NT06 | max_grid_window | 2 | 3 | 4 | 9 | unsure |
| 89 | PS06c | solar_reduction | 2 | 3 | 4 | 9 | unsure |
| 90 | TT02 | no_charge_window | 2 | 3 | 4 | 9 | correct |
| 91 | A03 | solar_reduction | 3 | 3 | 3 | 9 | correct |
| 92 | B04 | solar_reduction | 3 | 3 | 3 | 9 | correct |
| 93 | B05 | solar_reduction | 3 | 3 | 3 | 9 | correct |
| 94 | C03 | minimum_battery_reserve | 3 | 3 | 3 | 9 | unsure |
| 95 | C04 | minimum_battery_reserve | 3 | 3 | 3 | 9 | unsure |
| 96 | F04 | no_discharge_window | 3 | 3 | 3 | 9 | unsure |
| 97 | HN08 | no_op | 3 | 3 | 3 | 9 | unsure |
| 98 | PS01d | solar_reduction | 3 | 3 | 3 | 9 | correct |
| 99 | J02 | max_grid_window | 2 | 2 | 4 | 8 | correct |
| 100 | B09 | solar_reduction | 2 | 3 | 3 | 8 | correct |
| 101 | D03 | solar_reduction | 2 | 3 | 3 | 8 | correct |
| 102 | MP07b | max_grid_window | 2 | 3 | 3 | 8 | correct |
| 103 | PS07e | no_op | 2 | 3 | 3 | 8 | correct |
| 104 | A04 | max_grid_window | 3 | 2 | 3 | 8 | correct |
| 105 | A08 | minimum_battery_reserve | 3 | 2 | 3 | 8 | correct |
| 106 | C02 | minimum_battery_reserve | 3 | 2 | 3 | 8 | unsure |
| 107 | C07 | minimum_battery_reserve | 3 | 2 | 3 | 8 | correct |
| 108 | F08 | no_charge_window | 3 | 2 | 3 | 8 | correct |
| 109 | J01 | no_charge_window | 1 | 2 | 4 | 7 | unsure |
| 110 | A07 | solar_reduction | 2 | 2 | 3 | 7 | correct |
| 111 | C01 | minimum_battery_reserve | 2 | 2 | 3 | 7 | correct |
| 112 | C05 | minimum_battery_reserve | 2 | 2 | 3 | 7 | correct |
| 113 | C08 | minimum_battery_reserve | 2 | 2 | 3 | 7 | correct |
| 114 | D01 | no_charge_window | 2 | 2 | 3 | 7 | correct |
| 115 | D04 | minimum_battery_reserve | 2 | 2 | 3 | 7 | unsure |
| 116 | E05 | no_discharge_window | 2 | 2 | 3 | 7 | unsure |
| 117 | E07 | minimum_battery_reserve | 2 | 2 | 3 | 7 | correct |
| 118 | F05 | no_discharge_window | 2 | 2 | 3 | 7 | unsure |
| 119 | F06 | no_charge_window | 2 | 2 | 3 | 7 | unsure |
| 120 | G01 | max_grid_window | 2 | 2 | 3 | 7 | unsure |
| 121 | G02 | max_grid_window | 2 | 2 | 3 | 7 | unsure |
| 122 | G06 | max_grid_window | 2 | 2 | 3 | 7 | unsure |
| 123 | H03 | minimum_battery_reserve | 2 | 2 | 3 | 7 | unsure |
| 124 | I04 | no_op | 2 | 2 | 3 | 7 | unsure |
| 125 | J03 | minimum_battery_reserve | 2 | 2 | 3 | 7 | correct |
| 126 | J04 | solar_reduction | 2 | 2 | 3 | 7 | unsure |
| 127 | J05 | no_discharge_window | 2 | 2 | 3 | 7 | unsure |
| 128 | J07 | max_grid_window | 2 | 2 | 3 | 7 | correct |
| 129 | J08 | solar_reduction | 2 | 2 | 3 | 7 | correct |
| 130 | J09 | minimum_battery_reserve | 2 | 2 | 3 | 7 | correct |
| 131 | MP03a | solar_reduction | 2 | 2 | 3 | 7 | correct |
| 132 | MP04a | minimum_battery_reserve | 2 | 2 | 3 | 7 | correct |
| 133 | MP04b | minimum_battery_reserve | 2 | 2 | 3 | 7 | correct |
| 134 | MP08a | no_charge_window | 2 | 2 | 3 | 7 | unsure |
| 135 | NT07 | minimum_battery_reserve | 2 | 2 | 3 | 7 | unsure |
| 136 | NT08 | minimum_battery_reserve | 2 | 2 | 3 | 7 | unsure |
| 137 | PS02b | no_charge_window | 2 | 2 | 3 | 7 | unsure |
| 138 | PS02c | no_charge_window | 2 | 2 | 3 | 7 | unsure |
| 139 | PS02d | no_charge_window | 2 | 2 | 3 | 7 | unsure |
| 140 | PS02e | no_charge_window | 2 | 2 | 3 | 7 | unsure |
| 141 | PS03b | no_discharge_window | 2 | 2 | 3 | 7 | unsure |
| 142 | PS03d | no_discharge_window | 2 | 2 | 3 | 7 | unsure |
| 143 | PS04b | minimum_battery_reserve | 2 | 2 | 3 | 7 | correct |
| 144 | PS04d | minimum_battery_reserve | 2 | 2 | 3 | 7 | unsure |
| 145 | PS04e | minimum_battery_reserve | 2 | 2 | 3 | 7 | correct |
| 146 | PS05b | max_grid_window | 2 | 2 | 3 | 7 | unsure |
| 147 | PS05c | max_grid_window | 2 | 2 | 3 | 7 | correct |
| 148 | PS05d | max_grid_window | 2 | 2 | 3 | 7 | unsure |
| 149 | PS05e | max_grid_window | 2 | 2 | 3 | 7 | unsure |
| 150 | PS06a | solar_reduction | 2 | 2 | 3 | 7 | unsure |
| 151 | PS06b | solar_reduction | 2 | 2 | 3 | 7 | unsure |
| 152 | PS06d | solar_reduction | 2 | 2 | 3 | 7 | unsure |
| 153 | PS07a | no_op | 2 | 2 | 3 | 7 | correct |
| 154 | PS07b | no_op | 2 | 2 | 3 | 7 | correct |
| 155 | PS07c | no_op | 2 | 2 | 3 | 7 | correct |
| 156 | PS07d | no_op | 2 | 2 | 3 | 7 | correct |
| 157 | PS08b | minimum_battery_reserve | 2 | 2 | 3 | 7 | unsure |
| 158 | PS09c | no_charge_window | 2 | 2 | 3 | 7 | unsure |
| 159 | PS09d | no_charge_window | 2 | 2 | 3 | 7 | unsure |
| 160 | PS10a | max_grid_window | 2 | 2 | 3 | 7 | unsure |
| 161 | PS10d | max_grid_window | 2 | 2 | 3 | 7 | correct |
| 162 | TT04 | solar_reduction | 2 | 2 | 3 | 7 | unsure |
| 163 | TT06 | minimum_battery_reserve | 2 | 2 | 3 | 7 | unsure |
| 164 | TT07 | no_discharge_window | 2 | 2 | 3 | 7 | unsure |
| 165 | TT09 | max_grid_window | 2 | 2 | 3 | 7 | correct |
| 166 | TT11 | solar_reduction | 2 | 2 | 3 | 7 | unsure |
| 167 | J10 | no_discharge_window | 1 | 2 | 3 | 6 | correct |
| 168 | MP07a | max_grid_window | 1 | 2 | 3 | 6 | correct |
| 169 | PS10b | max_grid_window | 1 | 2 | 3 | 6 | correct |
| 170 | B07 | solar_reduction | 2 | 2 | 2 | 6 | correct |
| 171 | E04 | solar_reduction | 2 | 2 | 2 | 6 | unsure |
| 172 | H08 | no_op | 2 | 2 | 2 | 6 | correct |
| 173 | MP05b | no_discharge_window | 1 | 1 | 2 | 4 | correct |
| 174 | MP06a | no_charge_window | 1 | 1 | 2 | 4 | correct |
| 175 | PS01a | solar_reduction | 1 | 1 | 2 | 4 | correct |
| 176 | PS02a | no_charge_window | 1 | 1 | 2 | 4 | correct |
| 177 | PS03a | no_discharge_window | 1 | 1 | 2 | 4 | correct |
| 178 | PS04a | minimum_battery_reserve | 1 | 1 | 2 | 4 | correct |
| 179 | PS05a | max_grid_window | 1 | 1 | 2 | 4 | correct |
| 180 | PS08a | minimum_battery_reserve | 1 | 1 | 2 | 4 | correct |
