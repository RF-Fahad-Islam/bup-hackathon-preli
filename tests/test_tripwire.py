import json
from pathlib import Path

import pytest

from app.directives import GuardrailError, raw_to_directive
from app.schemas import BatterySpec
from app.tripwire import read_note

BAT = BatterySpec(capacity_kwh=200, initial_energy_kwh=100, minimum_energy_kwh=20,
                  max_charge_kwh_per_hour=50, max_discharge_kwh_per_hour=50)

CASES = [
    ("PV production will drop to about 20% between 13:00 and 15:00.", "solar_reduction", [13, 14], 0.2),
    ("Expect an 80% reduction in rooftop solar during the 1-3 PM maintenance window.", "solar_reduction", [13, 14], 0.2),
    ("Solar output reduced by 50% from 11 AM to 2 PM.", "solar_reduction", [11, 12, 13], 0.5),
    ("Battery charger unavailable from 2 AM until 5 AM.", "no_charge_window", [2, 3, 4], None),
    ("Do not discharge the battery from 6 PM until 8 PM.", "no_discharge_window", [18, 19], None),
    ("Keep at least 120 kWh in reserve from 6 PM until 9 PM.", "minimum_battery_reserve", [18, 19, 20], 120),
    ("Keep at least 50% of battery capacity in reserve between 7 PM and 10 PM.", "minimum_battery_reserve", [19, 20, 21], 100),
    ("Grid import must not exceed 155 kWh from 6 PM until 9 PM.", "max_grid_window", [18, 19, 20], 155),
    ("No battery charging from 10 PM to 2 AM.", "no_charge_window", [0, 1, 22, 23], None),
    ("The cafeteria menu changes tomorrow.", "no_op", [], None),
    ("Battery maintenance is scheduled for next week.", "no_op", [], None),
]


@pytest.mark.parametrize("note,dtype,hours,value", CASES)
def test_tripwire_reads_common_phrasings(note, dtype, hours, value):
    raw = read_note(note)
    assert raw is not None, note
    d = raw_to_directive(raw, 0, BAT)
    assert d.directive_type == dtype
    assert list(d.hours) == hours
    if value is not None:
        assert d.value == pytest.approx(value)


@pytest.mark.parametrize("note", [
    "Panel washing from one until three will leave roughly one-fifth of normal solar output.",
])
def test_tripwire_abstains_when_ambiguous(note):
    assert read_note(note) is None


# Notes the tripwire used to misread with confidence (eval/adversarial.jsonl ids). A wrong tripwire reading that
# matches the cheap model's mistake is accepted and cached without escalation, so each note must now be read
# correctly or abstained on (None) -- never read wrongly.
MISREAD = [  # id, note, type, hours, value, battery capacity
    ("A05", "Whatever happens this evening, the storage bank has to still be holding 110 kWh at the end of every hour from 6 PM to 10 PM.", "minimum_battery_reserve", [18, 19, 20, 21], 110, 200),
    ("B01", "Expect solar to fall 60 percent short of forecast from 11 AM to 2 PM.", "solar_reduction", [11, 12, 13], 0.4, 200),
    ("B02", "Solar production will come in 20% below normal from 8 AM to 11 AM due to morning fog.", "solar_reduction", [8, 9, 10], 0.8, 200),
    ("B04", "Rooftop solar will lose three-quarters of its output between noon and 3 PM.", "solar_reduction", [12, 13, 14], 0.25, 200),
    ("B05", "Dust on the panels will cut PV output by two-thirds from 9 AM to noon.", "solar_reduction", [9, 10, 11], 1 / 3, 200),
    ("B06", "PV curtailment of 70% will be in effect from 1 PM to 3 PM for inverter firmware testing.", "solar_reduction", [13, 14], 0.3, 200),
    ("B09", "Solar output will be down by 25% from 3 PM to 5 PM.", "solar_reduction", [15, 16], 0.75, 200),
    ("C03", "From 5 PM until 9 PM, stored energy must stay at or above one-third of full capacity.", "minimum_battery_reserve", [17, 18, 19, 20], 80, 240),
    ("D03", "Solar drops to 50% from noon till 2.", "solar_reduction", [12, 13], 0.5, 200),
    ("E02", "Charging is blocked during hours 14 through 16 inclusive.", "no_charge_window", [14, 15, 16], None, 200),
    ("E06", "Charging is allowed only until 6 AM; after that, no charging for the rest of the day.", "no_charge_window", list(range(6, 24)), None, 200),
    ("I01", "Phone charging lockers in the library will be unavailable from 2 PM to 4 PM.", "no_op", [], None, 200),
    ("J01", "no chrging of the batery 2-4pm pls", "no_charge_window", [14, 15], None, 200),
    ("J03", "keep >=90kWh in batt, 6pm-10pm!!", "minimum_battery_reserve", [18, 19, 20, 21], 90, 200),
    ("J07", "Grid import: max one hundred and twenty-five kWh/hour, 1700-2000.", "max_grid_window", [17, 18, 19], 125, 200),
    ("J09", "BESS min SOC = 30%, 00:00-06:00", "minimum_battery_reserve", [0, 1, 2, 3, 4, 5], 90, 300),
    ("J10", "discharge NOT permitted 1200-1400", "no_discharge_window", [12, 13], None, 200),
    ("HN09", "Operators asked whether the 6-9 PM feeder cap of 150 kWh applies today: it does not.", "no_op", [], None, 200),
    ("HN11", "Clear skies should push solar output about 20% above forecast from 11 AM to 1 PM.", "no_op", [], None, 200),
    ("TT05", "Charger locked out for hour slots 18, 19 and 20.", "no_charge_window", [18, 19, 20], None, 200),
    ("TT12", "Keep at least 60 kWh stored until 3 PM, starting at 1.", "minimum_battery_reserve", [13, 14], 60, 200),
    ("NT02", "State of charge must not dip below 0.4 between 6 PM and 9 PM.", "minimum_battery_reserve", [18, 19, 20], 80, 200),
    ("NT10", "Solar output will be reduced from 100% to 35% between 11 AM and 1 PM.", "solar_reduction", [11, 12], 0.35, 200),
    ("PS03d", "Do not draw energy out of the storage system from five until eight this evening.", "no_discharge_window", [17, 18, 19], None, 200),
    ("PS04e", "Don't let stored energy dip under one hundred twenty-five kilowatt-hours, 6pm-10pm.", "minimum_battery_reserve", [18, 19, 20, 21], 125, 250),
    ("PS05d", "Please keep campus imports at or under one hundred sixty kWh from six until nine this evening.", "max_grid_window", [18, 19, 20], 160, 200),
    ("MP05a", "The battery must not discharge below 80 kWh from 6 to 9 PM.", "minimum_battery_reserve", [18, 19, 20], 80, 200),
    ("MP09b", "From 6 to 9 PM: maximum 150 kWh imported.", "max_grid_window", [18, 19, 20], 150, 250),
]


def _battery(capacity):
    return BatterySpec(capacity_kwh=capacity, initial_energy_kwh=capacity / 2, minimum_energy_kwh=0,
                       max_charge_kwh_per_hour=capacity / 4, max_discharge_kwh_per_hour=capacity / 4)


def _wrong_reading(note, dtype, hours, value, capacity):
    """None when the tripwire is right or abstains; otherwise a description of its wrong reading."""
    raw = read_note(note)
    if raw is None:
        return None
    try:
        d = raw_to_directive(raw, 0, _battery(capacity), source="tripwire")
    except GuardrailError:
        return None  # the Guardrail rejects it, which escalates just like abstaining
    if d.directive_type == dtype and list(d.hours) == hours and (
            (value is None and d.value is None) or (value is not None and d.value == pytest.approx(value, abs=1e-3))):
        return None
    return f"{d.directive_type} {list(d.hours)} {d.value}"


@pytest.mark.parametrize("cid,note,dtype,hours,value,capacity", MISREAD, ids=[m[0] for m in MISREAD])
def test_tripwire_never_misreads_known_traps(cid, note, dtype, hours, value, capacity):
    assert _wrong_reading(note, dtype, hours, value, capacity) is None, note


def _labelled_notes():
    root = Path(__file__).parent.parent
    for name in ("adversarial.jsonl", "paraphrases.jsonl"):
        for i, line in enumerate((root / "eval" / name).read_text(encoding="utf-8").splitlines()):
            if line.strip():
                c = json.loads(line)
                yield f"{name}:{c.get('id', i)}", c["note"], c["type"], c["hours"], c["value"], c.get("capacity", 200)
    keys = {"solar_reduction": "factor", "minimum_battery_reserve": "minimum_energy_kwh", "max_grid_window": "max_grid_kwh"}
    sample = json.loads((root / "samples" / "official" / "public_sample_cases.json").read_text(encoding="utf-8"))
    for case in sample["cases"]:
        for di in case["expected_output"]["directive_interpretation"]:
            adj = di["structured_adjustment"] or {}
            yield (f"{case['id']}#{di['note_index']}", case["input"]["operator_notes"][di["note_index"]],
                   di["directive_type"], adj.get("hours", []), adj.get(keys.get(di["directive_type"], "")),
                   case["input"]["battery"]["capacity_kwh"])


def test_tripwire_never_misreads_any_labelled_note():
    wrong = [f"{cid}: {note} -> {got}" for cid, note, dtype, hours, value, cap in _labelled_notes()
             if (got := _wrong_reading(note, dtype, hours, value, cap))]
    assert not wrong, "\n".join(wrong)


@pytest.mark.parametrize("note,hours", [
    ("No charging from 0600 to 0900 hrs.", [6, 7, 8]),                  # 4-digit 24h times
    ("discharge NOT permitted 1200-1400", [12, 13]),
    ("No discharge 22:00-00:00.", [22, 23]),                             # 00:00 as an end is midnight
    ("Charger locked out for hour slots 18, 19 and 20.", [18, 19, 20]),  # a list of slots, not a range
])
def test_tripwire_time_formats(note, hours):
    raw = read_note(note)
    assert raw is not None, note
    assert list(raw_to_directive(raw, 0, BAT).hours) == hours


def test_tripwire_solar_meaning_ignores_time_ranges():
    # the "to" in "3 PM to 5 PM" is time text, not "drops to 25%"
    for note in ("Solar output will be down by 25% from 3 PM to 5 PM.",
                 "Solar output will be down by 25% between 3 PM and 5 PM."):
        raw = read_note(note)
        assert raw is not None and (raw["solar_value"], raw["solar_meaning"]) == (25, "reduction"), note
