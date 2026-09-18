"""Tripwire: a pattern-based Raw Reading used only to check the LLM.

It never overrides an LLM answer. When it disagrees with the cheap model (or
cannot read a note confidently) the notes are escalated to the strong model.
Only in Degraded Mode -- every LLM call failed -- is its reading used, and
only if it read every note confidently. See docs/adr/0001.

`read_note` returns a Raw Reading dict, or None when it is not confident.
"""
import re
from typing import Optional

WORD_NUM = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7,
    "eight": 8, "nine": 9, "ten": 10, "eleven": 11, "twelve": 12,
}
FRACTIONS = [
    (r"\bthree[- ]quarters?\b", 75), (r"\b(?:one[- ]|a[- ])?quarter\b", 25),
    (r"\b(?:one[- ]|a[- ])?fourth\b", 25), (r"\b(?:one[- ]|a[- ])?fifth\b", 20),
    (r"\b(?:one[- ]|a[- ])?third\b", 100 / 3), (r"\btwo[- ]thirds\b", 200 / 3),
    (r"\b(?:one[- ]|a[- ])?tenth\b", 10), (r"\bhalf\b", 50),
]
FUTURE_ONLY = re.compile(r"\b(tomorrow|next (week|month|day|monday|tuesday|wednesday|thursday|friday|saturday|sunday)|yesterday|last (week|month))\b")
MER = r"(a\.?m\.?|p\.?m\.?)"
TIME = rf"(noon|midnight|\d{{1,2}}(?::\d{{2}})?\s*{MER}?)"
RANGE = re.compile(rf"{TIME}\s*(?:to|until|till|til|through|thru|and|-|–|—)\s*{TIME}")
FROM_ON = re.compile(rf"(?:from|after|starting(?: at)?|beginning(?: at)?|since)\s+{TIME}(?!\s*(?:to|until|till|through|and|-|–|—)\s*\d)")
UNTIL = re.compile(rf"(?:until|till|before|up to)\s+{TIME}")


def _parse_time(tok: str) -> Optional[tuple[int, int, Optional[str]]]:
    tok = tok.strip()
    if tok == "noon":
        return 12, 0, "pm_fixed"
    if tok == "midnight":
        return 0, 0, "midnight"
    m = re.fullmatch(rf"(\d{{1,2}})(?::(\d{{2}}))?\s*{MER}?", tok)
    if not m:
        return None
    h, mins, mer = int(m.group(1)), int(m.group(2) or 0), m.group(3)
    mer = None if mer is None else ("pm" if mer.startswith("p") else "am")
    if h > 24 or mins > 59:
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
    else:
        if emer is None and eh <= 12 and smer not in ("am", "pm", "pm_fixed"):
            return None  # "from 1 until 3": no meridiem at all, let the LLM judge
        end = _to24(eh, emer) if emer else eh
    if smer == "midnight":
        start = 0
    elif smer == "pm_fixed":
        start = 12
    elif smer in ("am", "pm"):
        start = _to24(sh, smer)
    elif emer in ("am", "pm") and sh <= 12:
        # "1-3 PM" -> 13; "11 to 2 PM" -> 11
        pm = sh % 12 + 12
        start = pm if emer == "pm" and pm < (end if end else 24) else sh % 12
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
        if t and t[2] in ("am", "pm", "pm_fixed"):
            return {"start_hour": _to24(t[0], t[2]) if t[2] != "pm_fixed" else 12, "end_hour": 24}
    m = UNTIL.search(text)
    if m and not RANGE.search(text):
        t = _parse_time(m.group(1))
        if t and t[2] in ("am", "pm", "pm_fixed"):
            return {"start_hour": 0, "end_hour": _to24(t[0], t[2]) if t[2] != "pm_fixed" else 12}
    return None


def _spans(text: str) -> Optional[list[dict]]:
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
    t = re.sub(r"(\d)\s*(?:hrs|hours|h)\b", r"\1", t)
    for w, n in WORD_NUM.items():
        t = re.sub(rf"\b{w}\b(?![- ](?:fifth|quarter|fourth|third|tenth|half))", str(n), t)
    return t


def _strip_amounts(t: str) -> str:
    return re.sub(r"\d+(?:\.\d+)?\s*(?:kwh|kw|%|percent|per cent)", " ", t)


def _percent(t: str) -> Optional[float]:
    m = re.search(r"(\d+(?:\.\d+)?)\s*(?:%|percent|per cent)", t)
    if m:
        return float(m.group(1))
    for pat, val in FRACTIONS:
        if re.search(pat, t):
            return val
    return None


def _kwh(t: str) -> Optional[float]:
    m = re.findall(r"(\d+(?:\.\d+)?)\s*kwh", t)
    return float(m[0]) if len(m) == 1 else None


def read_note(note: str) -> Optional[dict]:
    t = _normalise(note)
    solar = re.search(r"\b(solar|pv|photovoltaic|panels?|rooftop|irradiance|sunlight)\b", t)
    charge = re.search(r"\bcharg(e|er|ing)\b", t)
    discharge = re.search(r"\bdischarg(e|er|ing)\b|\bdraw(ing)? (energy |power )?from the battery\b", t)
    grid = re.search(r"\b(grid|import|feeder|utility|substation|mains)\b", t)
    reserve = re.search(r"\b(reserve|keep at least|maintain at least|at least|minimum|not (?:drop|fall|go) below|stay above|backup)\b", t)
    prohibit = re.search(r"\b(no|not|never|avoid|unavailable|offline|disabled|prohibited|forbidden|blocked|suspend\w*|pause\w*|must not|do not|don't|cannot|can't|locked|out of service|down|isolated|disconnected|switched off|shut down|out of action)\b", t)
    cap = re.search(r"\b(exceed|cap(ped)?|limit(ed)?|max(imum)?|no more than|at most|not go above|below|under|restrict\w*|ceiling)\b", t)

    energy_words = solar or charge or discharge or grid or reserve or re.search(r"\bbattery\b", t)
    if not energy_words:
        return {"directive_type": "no_op", "spans": [], "reason": "tripwire: no energy terms"}
    if FUTURE_ONLY.search(t) and not re.search(r"\b(today|tonight|this (morning|afternoon|evening))\b", t):
        return {"directive_type": "no_op", "spans": [], "reason": "tripwire: not today"}

    if solar and not (charge or discharge):
        pct = _percent(t)
        spans = _spans(_strip_amounts(t))
        if pct is None or spans is None:
            return None
        if re.search(r"\b(reduc\w*|cut|drop|decreas\w*|lower\w*|los[se]\w*|fall|fell)\s+(?:of\s+|by\s+)(?:about\s+|around\s+|roughly\s+|approximately\s+|nearly\s+|~)?\d", t) \
                or re.search(r"\d\s*(?:%|percent|per cent)\s+(reduction|cut|drop|decrease|loss|lower|less)", t):
            meaning = "reduction"
        elif re.search(r"\b(to|at|as|leav\w*|of (the )?(normal|usual|typical|its|rated|expected|forecast\w*)|remain\w*|only|just|left)\b", t):
            meaning = "remaining"
        else:
            return None
        return {"directive_type": "solar_reduction", "spans": spans, "solar_value": pct,
                "solar_meaning": meaning, "reason": "tripwire"}

    spans = _spans(_strip_amounts(t))
    if spans is None:
        return None

    if discharge and prohibit and not charge:
        return {"directive_type": "no_discharge_window", "spans": spans, "reason": "tripwire"}
    if charge and prohibit and not discharge:
        return {"directive_type": "no_charge_window", "spans": spans, "reason": "tripwire"}
    if grid and cap and not reserve:
        kwh = _kwh(t)
        if kwh is None:
            return None
        return {"directive_type": "max_grid_window", "spans": spans, "amount_value": kwh,
                "amount_unit": "kwh", "reason": "tripwire"}
    if reserve and re.search(r"\bbattery|reserve|stored|state of charge|soc\b", t) and not grid:
        m = re.search(r"(\d+(?:\.\d+)?)\s*(?:%|percent|per cent)", t)
        kwh = _kwh(t)
        if m and kwh is None:
            return {"directive_type": "minimum_battery_reserve", "spans": spans,
                    "amount_value": float(m.group(1)), "amount_unit": "percent_of_capacity", "reason": "tripwire"}
        if kwh is not None and not m:
            return {"directive_type": "minimum_battery_reserve", "spans": spans,
                    "amount_value": kwh, "amount_unit": "kwh", "reason": "tripwire"}
    return None
