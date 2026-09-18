import pytest

from app.directives import GuardrailError, build_constraints, expand_spans, interpretation_to_directives, raw_to_directive
from app.schemas import BatterySpec

BAT = BatterySpec(capacity_kwh=200, initial_energy_kwh=100, minimum_energy_kwh=20,
                  max_charge_kwh_per_hour=50, max_discharge_kwh_per_hour=50)


@pytest.mark.parametrize("spans,hours", [
    ([{"start_hour": 13, "end_hour": 15}], (13, 14)),
    ([{"start_hour": 18, "end_hour": 21}], (18, 19, 20)),
    ([{"start_hour": 22, "end_hour": 2}], (0, 1, 22, 23)),
    ([{"start_hour": 20, "end_hour": 24}], (20, 21, 22, 23)),
    ([{"start_hour": 20, "end_hour": 0}], (20, 21, 22, 23)),
    ([{"start_hour": 2, "end_hour": 4}, {"start_hour": 22, "end_hour": 23}], (2, 3, 22)),
    ([{"start_hour": 13, "end_hour": 15}, {"start_hour": 14, "end_hour": 16}], (13, 14, 15)),
])
def test_windows_are_end_exclusive_sorted_unique(spans, hours):
    assert expand_spans(spans) == hours


@pytest.mark.parametrize("value,meaning,factor", [(20, "remaining", 0.2), (80, "reduction", 0.2),
                                                   (0, "remaining", 0.0), (50, "reduction", 0.5)])
def test_solar_factor_is_fraction_remaining(value, meaning, factor):
    d = raw_to_directive({"directive_type": "solar_reduction", "spans": [{"start_hour": 13, "end_hour": 15}],
                          "solar_value": value, "solar_meaning": meaning}, 0, BAT)
    assert d.structured_adjustment() == {"hours": [13, 14], "factor": factor}


def test_reserve_percent_of_capacity_becomes_kwh():
    d = raw_to_directive({"directive_type": "minimum_battery_reserve", "spans": [{"start_hour": 18, "end_hour": 21}],
                          "amount_value": 50, "amount_unit": "percent_of_capacity"}, 0, BAT)
    assert d.structured_adjustment() == {"hours": [18, 19, 20], "minimum_energy_kwh": 100}


def test_no_op_shape():
    d = raw_to_directive({"directive_type": "no_op", "spans": []}, 0, BAT)
    assert (d.applies, d.structured_adjustment()) == (False, None)


@pytest.mark.parametrize("raw", [
    {"directive_type": "demand_shift", "spans": [{"start_hour": 1, "end_hour": 2}]},
    {"directive_type": "no_charge_window", "spans": []},
    {"directive_type": "no_charge_window", "spans": [{"start_hour": 25, "end_hour": 26}]},
    {"directive_type": "no_charge_window", "spans": [{"start_hour": 5, "end_hour": 5}]},
    {"directive_type": "solar_reduction", "spans": [{"start_hour": 1, "end_hour": 2}], "solar_value": 120, "solar_meaning": "remaining"},
    {"directive_type": "solar_reduction", "spans": [{"start_hour": 1, "end_hour": 2}], "solar_value": 20, "solar_meaning": None},
    {"directive_type": "minimum_battery_reserve", "spans": [{"start_hour": 1, "end_hour": 2}], "amount_value": 500, "amount_unit": "kwh"},
    {"directive_type": "max_grid_window", "spans": [{"start_hour": 1, "end_hour": 2}], "amount_value": -5, "amount_unit": "kwh"},
    {"directive_type": "max_grid_window", "spans": [{"start_hour": 1, "end_hour": 2}], "amount_value": float("nan"), "amount_unit": "kwh"},
])
def test_guardrail_rejects(raw):
    with pytest.raises(GuardrailError):
        raw_to_directive(raw, 0, BAT)


def test_every_note_exactly_once():
    noop = {"directive_type": "no_op", "spans": []}
    with pytest.raises(GuardrailError):
        interpretation_to_directives([{**noop, "note_index": 0}], ["a", "b"], BAT)
    with pytest.raises(GuardrailError):
        interpretation_to_directives([{**noop, "note_index": 0}, {**noop, "note_index": 0}], ["a", "b"], BAT)
    ds = interpretation_to_directives([{**noop, "note_index": 1}, {**noop, "note_index": 0}], ["a", "b"], BAT)
    assert [d.note_index for d in ds] == [0, 1]


def test_overlaps_most_restrictive_wins():
    mk = lambda raw: raw_to_directive(raw, 0, BAT)  # noqa: E731
    ds = [
        mk({"directive_type": "solar_reduction", "spans": [{"start_hour": 12, "end_hour": 15}], "solar_value": 50, "solar_meaning": "remaining"}),
        mk({"directive_type": "solar_reduction", "spans": [{"start_hour": 13, "end_hour": 14}], "solar_value": 20, "solar_meaning": "remaining"}),
        mk({"directive_type": "minimum_battery_reserve", "spans": [{"start_hour": 13, "end_hour": 14}], "amount_value": 10, "amount_unit": "kwh"}),
        mk({"directive_type": "max_grid_window", "spans": [{"start_hour": 13, "end_hour": 14}], "amount_value": 90, "amount_unit": "kwh"}),
        mk({"directive_type": "max_grid_window", "spans": [{"start_hour": 13, "end_hour": 14}], "amount_value": 70, "amount_unit": "kwh"}),
    ]
    c = build_constraints(ds, [100.0] * 24, BAT)
    assert c.effective_solar[12] == 50 and c.effective_solar[13] == 20
    assert c.reserve_floor[13] == 20  # base minimum beats the weaker directive
    assert c.grid_cap[13] == 70
