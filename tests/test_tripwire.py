import pytest

from app.directives import raw_to_directive
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
