"""Tripwire: a pattern-based Raw Reading used only to check the LLM.

It never overrides an LLM answer. When it disagrees with the cheap model (or
cannot read a note confidently) the notes are escalated to the strong model.
Only in Degraded Mode -- every LLM call failed -- is its reading used, and
only if it read every note confidently. See docs/adr/0001.

`read_note` returns a Raw Reading dict, or None when it is not confident.
A confident wrong reading is the worst outcome: it confirms the same mistake
from the cheap model (no escalation), so every doubtful pattern returns None.
"""
import re
from typing import Optional

NUM_WORDS = {
    "zero": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8,
    "nine": 9, "ten": 10, "eleven": 11, "twelve": 12, "thirteen": 13, "fourteen": 14, "fifteen": 15,
    "sixteen": 16, "seventeen": 17, "eighteen": 18, "nineteen": 19, "twenty": 20, "thirty": 30,
    "forty": 40, "fifty": 50, "sixty": 60, "seventy": 70, "eighty": 80, "ninety": 90,
}
_W = "|".join(sorted(NUM_WORDS, key=len, reverse=True))
_NOT_FRACTION = r"(?![- ](?:fifths?|quarters?|fourths?|thirds?|tenths?|halves|half)\b)"  # "one-fifth" stays a fraction
NUM_RUN = re.compile(rf"\b(?:{_W})\b{_NOT_FRACTION}(?:(?:[\s-]+and[\s-]+|[\s-]+)(?:(?:{_W})\b{_NOT_FRACTION}|hundred\b|thousand\b))*")
FRACTIONS = [  # longest first: "two-thirds" must not be read as "third"
    (r"three[- ]quarters?", 75), (r"(?:one[- ]|a[- ])?quarter", 25), (r"(?:one[- ]|a[- ])?fourth", 25),
    (r"two[- ]fifths?", 40), (r"three[- ]fifths?", 60), (r"four[- ]fifths?", 80), (r"(?:one[- ]|a[- ])?fifth", 20),
    (r"two[- ]thirds?", 200 / 3), (r"(?:one[- ]|a[- ])?third", 100 / 3), (r"(?:one[- ]|a[- ])?tenth", 10),
    (r"(?:one[- ]|a[- ])?half", 50),
]
FUTURE_ONLY = re.compile(r"\b(tomorrow|next (week|month|day|monday|tuesday|wednesday|thursday|friday|saturday|sunday)|yesterday|last (week|month))\b")
# Retractions, cancellations, conditionals, advice: the note may well be a no_op, but a pattern can't be sure.
RETRACTED = re.compile(r"\b(whether|if|unless|disregard|ignore|in error|by mistake|cancel\w*|called off|lifted|withdrawn|rescind\w*|revoked|scrapped|postponed|no longer|ended|is over|not be repeated|(?:does|do|did|will) not apply|(?:doesn't|don't|won't) apply|it does not|it doesn't|no further|no additional|as normal|as usual|unaffected|no change|not affected|recommend\w*|suggest\w*|optional|encourag\w*|ideally)\b")
COMPLEMENT = re.compile(r"\b(only (?:until|till|before|after|from|between|during)|after that|except|outside|other than|apart from|besides|otherwise)\b")
FOREIGN_CHARGING = re.compile(r"\b(phones?|mobiles?|laptops?|tablets?|ev|evs|electric vehicles?|vehicles?|cars?|scooters?|e-?bikes?|bikes?|lockers?|kiosks?|devices?|usb|stations?|carts?|buggies|drones?)\b")
ENERGY = re.compile(r"\b(solar|pv|photovoltaic|panels?|rooftop|irradiance|sunlight|arrays?|bat+e?r\w*|batt\w*|charg\w*|chrg\w*|chrging|dischrg\w*|grid|import\w*|feeder|utility|substation|mains|transformer|reserve|stor(?:ed|age)|soc|bess|kwh|mwh|kw|inverter|rectifier|bms)\b")

MER = r"(a\.?m\.?|p\.?m\.?)"
# 4-digit 24h times ("1700") and hh:mm; never a digit run inside a longer number or a decimal.
TIME = rf"(noon|midnight|(?<![\d.:/])(?:\d{{4}}|\d{{1,2}}(?::\d{{2}})?)(?!\d)(?!\.\d)\s*{MER}?)"
RANGE = re.compile(rf"{TIME}\s*(?:to|until|till|til|through|thru|and|-|–|—)\s*{TIME}")
FROM_ON = re.compile(rf"(?:from|after|starting(?: at)?|beginning(?: at)?|since)\s+{TIME}(?!\s*(?:to|until|till|through|and|-|–|—)\s*\d)")
UNTIL = re.compile(rf"(?:until|till|before|up to)\s+{TIME}")
SLOT_RANGE = re.compile(r"\b(?:hour slots?|slots?|hours?)\s+(\d{1,2})\s*(?:through|thru|to|until|till|-|–|—)\s*(\d{1,2})\s*,?\s*\(?inclusive\b")
SLOT_LIST = re.compile(r"\b(?:hour slots?|slots?|hours?)\s+(\d{1,2}(?:\s*(?:,\s*and|,|and|&)\s*\d{1,2})+)\b(?!\s*(?:a\.?m|p\.?m|:|%|kwh))")
BOUNDARY_WORDS = re.compile(r"\b(inclusive|end of the|not including|excluding|through|thru)\b")

# Solar meaning. Amounts are replaced by placeholders (amta, amtb, ...) and time text is removed first,
# so "to" in "3 PM to 5 PM" can never pass for "drops to 20%".
Q = r"(?:(?:about|around|roughly|approximately|approx\.?|nearly|almost|some|only|just|an?)\s+|~\s*)*"
LOSS_VERB = r"(?:reduc\w*|cut\w*|drop\w*|decreas\w*|lower\w*|los\w*|fall\w*|fell|down|curtail\w*|knock\w*\s+out|shav\w*|slash\w*|derat\w*)"
SOLAR_FROM_TO = re.compile(rf"\bfrom\s+{Q}amt([a-z])\s+(?:down\s+)?to\s+{Q}amt([a-z])")
SOLAR_LOSS = [
    re.compile(rf"\b{LOSS_VERB}\s+(?:[a-z]+\s+){{0,3}}?by\s+{Q}amt([a-z])"),  # "cut PV output by 60%"
    re.compile(rf"\b{LOSS_VERB}\s+of\s+{Q}amt([a-z])"),                       # "curtailment of 70%"
    re.compile(rf"\b{LOSS_VERB}\s+{Q}amt([a-z])"),                            # "lose 75%", "knock out 60%"
    re.compile(r"amt([a-z])\s+(?:reduction|cut|drop|decrease|loss|lost|lower|less|below|short\w*|curtailment|down|fewer)\b"),
]
SOLAR_REMAINING = [
    re.compile(rf"\b(?:to|at|as|leav\w*|remain\w*|only|just)\s+{Q}amt([a-z])"),  # "drop to 20%", "leave half"
    re.compile(r"amt([a-z])\s+(?:of\s+(?:the\s+|its\s+|their\s+)?(?:normal|usual|typical|rated|expected|forecast\w*|nominal)|remain\w*|left|usable|available)\b"),
]
SOLAR_INCREASE = re.compile(r"\b(above|more than|higher|increas\w*|boost\w*|ris(?:e|es|ing)|up by|extra|exceed\w*|surplus of)\b")


def _run_to_numbers(run: str) -> str:
    """'one hundred and twenty-five' -> '125'; 'fourteen hundred and sixteen hundred' -> '1400 and 1600'."""
    toks = [x for x in re.split(r"[\s-]+", run) if x]
    parts, total, cur, last = [], 0, 0, None
    for i, tok in enumerate(toks):
        if tok == "and":
            nxt, after = toks[i + 1:i + 2], toks[i + 2:i + 3]
            joins = (last in ("hundred", "thousand") and nxt and NUM_WORDS.get(nxt[0], 100) < 100
                     and not (after and after[0] in ("hundred", "thousand")))
            if not joins:
                parts += [str(total + cur), "and"]
                total, cur, last = 0, 0, None
        elif tok == "hundred":
            cur, last = (cur or 1) * 100, "hundred"
        elif tok == "thousand":
            total, cur, last = total + (cur or 1) * 1000, 0, "thousand"
        else:
            v = NUM_WORDS[tok]
            if last is None or last in ("hundred", "thousand") or (last == "tens" and v < 10):
                cur += v
            else:
                parts.append(str(total + cur))
                total, cur = 0, v
            last = "tens" if v >= 20 else "unit"
    parts.append(str(total + cur))
    return " ".join(parts)


def _parse_time(tok: str) -> Optional[tuple[int, int, Optional[str]]]:
    """(hour, minutes, meridiem) where meridiem is am | pm | pm_fixed (noon) | midnight | h24 | None."""
    tok = tok.strip()
    if tok == "noon":
        return 12, 0, "pm_fixed"
    if tok == "midnight":
        return 0, 0, "midnight"
    m = re.fullmatch(r"(\d{2})(\d{2})", tok)
    if m:
        h, mins, mer = int(m.group(1)), int(m.group(2)), "h24"
    else:
        m = re.fullmatch(rf"(\d{{1,2}})(?::(\d{{2}}))?\s*{MER}?", tok)
        if not m:
            return None
        h, mins, mer = int(m.group(1)), int(m.group(2) or 0), m.group(3)
        if mer is not None:
            mer = "pm" if mer.startswith("p") else "am"
        elif m.group(2) is not None and len(m.group(1)) == 2:
            mer = "h24"  # "07:00", "13:00": zero-padded clock time is 24-hour
    if h > 24 or mins > 59 or (h == 24 and mins):
        return None
    return h, mins, mer


def _to24(h: int, mer: Optional[str]) -> int:
    if mer == "pm":
        return h % 12 + 12
    if mer == "am":
        return h % 12
    return h


def _span(start_tok: str, end_tok: str) -> Optional[dict]:
    s, e = _parse_time(start_tok), _parse_time(end_tok)
    if not s or not e:
        return None
    (sh, sm, smer), (eh, em, emer) = s, e
    if emer == "midnight":
        end = 24
    elif emer == "pm_fixed":
        end = 12
    elif emer in ("am", "pm", "h24"):
        end = _to24(eh, emer)
    elif eh > 12:
        end = eh
    elif smer in ("am", "pm", "pm_fixed"):
        # bare end after a start with a meridiem: the first matching clock hour after the start
        # ("from noon till 2" -> 14); if both readings are before the start it would wrap, so abstain
        st = 12 if smer == "pm_fixed" else _to24(sh, smer)
        later = [c for c in (eh % 12, eh % 12 + 12) if c > st]
        if not later:
            return None
        end = min(later)
    else:
        return None  # "from 1 until 3": no meridiem at all, let the LLM judge
    if smer == "midnight":
        start = 0
    elif smer == "pm_fixed":
        start = 12
    elif smer in ("am", "pm", "h24"):
        start = _to24(sh, smer)
    elif emer in ("am", "pm") and sh <= 12:
        # "1-3 PM" -> 13; "11 to 2 PM" -> 11
        pm = sh % 12 + 12
        start = pm if emer == "pm" and pm < (end if end else 24) else sh % 12
    elif emer == "midnight" and sh <= 12:
        return None  # "from 9 until midnight": 9 AM or 9 PM?
    else:
        start = sh
    if em > 0:
        end += 1  # a partially covered hour is covered
    if end > 24 or start > 23:
        return None
    return {"start_hour": start, "end_hour": end % 25}


def _open_span(text: str) -> Optional[dict]:
    m = FROM_ON.search(text)
    if m and re.search(r"\b(onwards?|rest of the (day|evening|night)|end of (the )?day|until close)\b", text):
        t = _parse_time(m.group(1))
        if t and t[2] in ("am", "pm", "pm_fixed", "h24"):
            return {"start_hour": _to24(t[0], t[2]) if t[2] != "pm_fixed" else 12, "end_hour": 24}
    m = UNTIL.search(text)
    if m and not RANGE.search(text) and not FROM_ON.search(text):  # "until 3 PM, starting at 1": start is not 0
        t = _parse_time(m.group(1))
        if t and t[2] in ("am", "pm", "pm_fixed", "h24"):
            return {"start_hour": 0, "end_hour": _to24(t[0], t[2]) if t[2] != "pm_fixed" else 12}
    return None


def _spans(text: str) -> Optional[list[dict]]:
    m = SLOT_RANGE.search(text)  # "hours 14 through 16 inclusive": slot labels, end included
    if m:
        s, e = int(m.group(1)), int(m.group(2))
        return [{"start_hour": s, "end_hour": e + 1}] if s <= e <= 23 else None
    m = SLOT_LIST.search(text)  # "hour slots 18, 19 and 20": a list, not a range
    if m:
        hours = sorted({int(h) for h in re.findall(r"\d{1,2}", m.group(1))})
        return [{"start_hour": h, "end_hour": h + 1} for h in hours] if hours[-1] <= 23 else None
    if BOUNDARY_WORDS.search(text):
        return None  # inclusive/exclusive wording the default rule can't settle
    if re.search(r"\b(all day|whole day|entire day|24 hours|all 24 hours)\b", text):
        return [{"start_hour": 0, "end_hour": 24}]
    spans = []
    for m in RANGE.finditer(text):
        sp = _span(m.group(1), m.group(3))
        if sp is None:
            return None
        spans.append(sp)
    if not spans:
        sp = _open_span(text)
        return [sp] if sp else None
    return spans


def _normalise(note: str) -> str:
    t = note.lower().replace("’", "'")
    t = t.replace("state of charge", "soc")  # not a charging instruction
    t = re.sub(r"\bkilo-?watt[- ]?hours?\b", "kwh", t)
    t = re.sub(r"\bmega-?watt[- ]?hours?\b", "mwh", t)
    t = NUM_RUN.sub(lambda m: _run_to_numbers(m.group(0)), t)
    t = re.sub(r"(\d)\s*(?:hrs|hours|h)\b", r"\1", t)
    return re.sub(r"\s*\b(?:percent|per cent)\b", "%", t)


def _strip_amounts(t: str) -> str:
    return re.sub(r"\d+(?:\.\d+)?\s*(?:kwh|mwh|kw|%)", " ", t)


def _strip_times(t: str) -> str:
    t = RANGE.sub(" ", t)
    return re.sub(TIME, " ", t)


def _kwh(t: str) -> Optional[float]:
    vals = [float(v) for v in re.findall(r"(\d+(?:\.\d+)?)\s*kwh", t)]
    vals += [float(v) * 1000 for v in re.findall(r"(\d+(?:\.\d+)?)\s*mwh", t)]
    return vals[0] if len(vals) == 1 else None


def _solar_value(t: str) -> Optional[tuple[float, str]]:
    """(percentage, 'remaining' | 'reduction') from a solar note, or None when the meaning is not clear-cut."""
    s = re.sub(r"\b(?:cut|reduced?|split)\s+in\s+half\b", "cut by 50%", t)
    s = re.sub(r"\bhalv(?:e|ed|es|ing)\b", "cut by 50%", s)
    for pat, val in FRACTIONS:
        s = re.sub(rf"\b{pat}\b", f" {val}%", s)
    amounts: list[float] = []

    def placeholder(m):
        amounts.append(float(m.group(1)))
        return f" amt{chr(96 + len(amounts))} "

    s = re.sub(r"(\d+(?:\.\d+)?)\s*%", placeholder, s)
    if not amounts or len(amounts) > 26:
        return None
    s = _strip_times(s)
    if SOLAR_INCREASE.search(s):
        return None  # an increase is not a reduction
    amount = lambda letter: amounts[ord(letter) - 97]  # noqa: E731
    m = SOLAR_FROM_TO.search(s)
    if m:
        return amount(m.group(2)), "remaining"  # "reduced from 100% to 35%": the end state remains
    if len(set(amounts)) != 1:
        return None
    loss = any(p.search(s) for p in SOLAR_LOSS)
    remaining_explicit = SOLAR_REMAINING[0].search(s)
    remaining = remaining_explicit or SOLAR_REMAINING[1].search(s)
    if loss and not remaining_explicit:
        return amounts[0], "reduction"
    if remaining and not loss:
        return amounts[0], "remaining"
    return None


def read_note(note: str) -> Optional[dict]:
    t = _normalise(note)
    solar = re.search(r"\b(solar|pv|photovoltaic|panels?|rooftop|irradiance|sunlight)\b", t)
    charge = re.search(r"\bcharg(?:e|er|ers|ing|ed)\b", t)
    discharge = re.search(r"\bdischarg\w*|\bdraw\w* (?:energy |power )?(?:from|out of) the (?:battery|storage|pack)\b", t)
    grid = re.search(r"\b(grid|import\w*|feeder|utility|substation|mains)\b", t)
    reserve = re.search(r"\b(reserve|keep at least|maintain at least|at least|minimum|min|backup|floor|no less than|not less than|never less than|at or above|or higher|or more|stay above)\b|>=|≥|\bnot (?:drop|fall|go|dip|sink) (?:below|under)|\bdischarg\w* (?:below|under)|\b(?:don't|do not|never) let\b.{0,40}\b(?:dip|drop|fall|go|run|sink)\w* (?:below|under)", t)
    prohibit = re.search(r"\b(no|not|never|avoid|unavailable|offline|disabled|prohibited|forbidden|blocked|suspend\w*|pause\w*|must not|do not|don't|cannot|can't|locked|out of service|down|isolated|disconnected|switched off|shut down|out of action)\b", t)
    cap = re.search(r"\b(exceed|cap(ped)?|limit(ed)?|max(imum)?|no more than|at most|not go above|below|under|restrict\w*|ceiling)\b", t)

    if not (ENERGY.search(t) or solar or charge or discharge or grid or reserve):
        return {"directive_type": "no_op", "spans": [], "reason": "tripwire: no energy terms"}
    if FUTURE_ONLY.search(t) and not re.search(r"\b(today|tonight|this (morning|afternoon|evening))\b", t):
        return {"directive_type": "no_op", "spans": [], "reason": "tripwire: not today"}
    if RETRACTED.search(t) or COMPLEMENT.search(t):
        return None

    if solar and not (charge or discharge):
        if re.search(r"\bsolar[- ]powered\b", t):
            return None  # a solar gadget, not the campus array
        sv = _solar_value(t)
        spans = _spans(_strip_amounts(t))
        if sv is None or spans is None:
            return None
        return {"directive_type": "solar_reduction", "spans": spans, "solar_value": sv[0],
                "solar_meaning": sv[1], "reason": "tripwire"}

    spans = _spans(_strip_amounts(t))
    if spans is None:
        return None

    floor = re.search(r"\bdischarg\w*\s+(?:below|under|beyond|past|lower than)\b", t)  # "not discharge below 80 kWh"
    if discharge and prohibit and not charge and not floor:
        return {"directive_type": "no_discharge_window", "spans": spans, "reason": "tripwire"}
    if charge and prohibit and not discharge:
        if FOREIGN_CHARGING.search(t):  # phone lockers, EV chargers: not the campus battery
            if re.search(r"\b(bat+e?r\w*|batt\w*|stor(?:ed|age)|bess|soc|grid|import\w*|solar|pv)\b", t):
                return None
            return {"directive_type": "no_op", "spans": [], "reason": "tripwire: another device's charging"}
        return {"directive_type": "no_charge_window", "spans": spans, "reason": "tripwire"}
    if grid and cap and not reserve:
        kwh = _kwh(t)
        if kwh is None:
            return None
        return {"directive_type": "max_grid_window", "spans": spans, "amount_value": kwh,
                "amount_unit": "kwh", "reason": "tripwire"}
    if reserve and re.search(r"\b(battery|batteries|batt|reserve|stored|storage|soc|bess|pack)\b", t) and not grid:
        pcts = re.findall(r"(\d+(?:\.\d+)?)\s*%", t)
        kwh = _kwh(t)
        if len(pcts) == 1 and kwh is None and float(pcts[0]) >= 1:
            return {"directive_type": "minimum_battery_reserve", "spans": spans,
                    "amount_value": float(pcts[0]), "amount_unit": "percent_of_capacity", "reason": "tripwire"}
        if kwh is not None and not pcts:
            return {"directive_type": "minimum_battery_reserve", "spans": spans,
                    "amount_value": kwh, "amount_unit": "kwh", "reason": "tripwire"}
    return None
