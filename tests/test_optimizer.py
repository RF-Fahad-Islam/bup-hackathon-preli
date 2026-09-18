from __future__ import annotations

import json
import math
import random
from pathlib import Path
from typing import Any

import pytest

from app.models import (
    BatteryAction,
    DirectiveInterpretation,
    OptimizeEnergyRequest,
)
from app.optimizer import (
    DirectiveCompilationError,
    OptimizationError,
    OptimizationResult,
    _classify_battery_flow,
    _normalize,
    compile_directives,
    optimize_energy,
)


TOLERANCE = 0.01
PUBLIC_CASE_PATH = (
    Path(__file__).parents[1]
    / "BUP_CSE_FEST_2026_Preli_Public_Sample_Cases.json"
)


def make_request(
    *,
    notes: list[str] | None = None,
    demand: list[float] | None = None,
    solar: list[float] | None = None,
    tariffs: list[float] | None = None,
    capacity: float = 100,
    initial: float = 50,
    minimum: float = 0,
    max_charge: float = 20,
    max_discharge: float = 20,
) -> OptimizeEnergyRequest:
    notes = notes or ["This note does not affect today's energy schedule."]
    demand = demand or [100] * 24
    solar = solar or [0] * 24
    tariffs = tariffs or [5] * 24
    return OptimizeEnergyRequest.model_validate(
        {
            "scenario_id": "TEST-SCENARIO",
            "operator_notes": notes,
            "hours": [
                {
                    "hour": hour,
                    "demand_kwh": demand[hour],
                    "solar_kwh": solar[hour],
                    "tariff_bdt_per_kwh": tariffs[hour],
                }
                for hour in range(24)
            ],
            "battery": {
                "capacity_kwh": capacity,
                "initial_energy_kwh": initial,
                "minimum_energy_kwh": minimum,
                "max_charge_kwh_per_hour": max_charge,
                "max_discharge_kwh_per_hour": max_discharge,
            },
        }
    )


def make_directive(
    note_index: int,
    directive_type: str,
    adjustment: dict[str, Any] | None,
) -> DirectiveInterpretation:
    is_no_op = directive_type == "no_op"
    return DirectiveInterpretation.model_validate(
        {
            "note_index": note_index,
            "applies": not is_no_op,
            "directive_type": directive_type,
            "structured_adjustment": adjustment,
            "explanation": "Structured directive for an optimizer test.",
        }
    )


def make_no_op(note_index: int = 0) -> DirectiveInterpretation:
    return make_directive(note_index, "no_op", None)


def signed_flow(action: BatteryAction, amount: float) -> float:
    if action is BatteryAction.CHARGE:
        return amount
    if action is BatteryAction.DISCHARGE:
        return -amount
    return 0.0


def assert_result_is_mathematically_valid(
    request: OptimizeEnergyRequest,
    directives: list[DirectiveInterpretation],
    result: OptimizationResult,
) -> None:
    compiled = compile_directives(request, directives)
    hour_data = {item.hour: item for item in request.hours}
    previous_energy = request.battery.initial_energy_kwh

    assert [item.hour for item in result.hourly_plan] == list(range(24))
    for item in result.hourly_plan:
        hour = item.hour
        flow = signed_flow(item.battery_action, item.battery_kwh)

        assert item.grid_kwh >= -TOLERANCE
        assert item.solar_used_kwh >= -TOLERANCE
        assert item.solar_used_kwh <= compiled.effective_solar[hour] + TOLERANCE
        assert math.isclose(
            item.grid_kwh + item.solar_used_kwh,
            hour_data[hour].demand_kwh + flow,
            abs_tol=TOLERANCE,
        )
        assert math.isclose(
            item.battery_energy_after_kwh,
            previous_energy + flow,
            abs_tol=TOLERANCE,
        )
        assert (
            compiled.minimum_energy[hour] - TOLERANCE
            <= item.battery_energy_after_kwh
            <= request.battery.capacity_kwh + TOLERANCE
        )
        assert flow <= request.battery.max_charge_kwh_per_hour + TOLERANCE
        assert flow >= -request.battery.max_discharge_kwh_per_hour - TOLERANCE
        if not compiled.charge_allowed[hour]:
            assert flow <= TOLERANCE
        if not compiled.discharge_allowed[hour]:
            assert flow >= -TOLERANCE
        if compiled.max_grid[hour] is not None:
            assert item.grid_kwh <= compiled.max_grid[hour] + TOLERANCE

        previous_energy = item.battery_energy_after_kwh

    assert math.isclose(
        previous_energy, request.battery.initial_energy_kwh, abs_tol=TOLERANCE
    )
    assert math.isclose(
        result.total_grid_kwh,
        sum(item.grid_kwh for item in result.hourly_plan),
        abs_tol=TOLERANCE,
    )
    assert math.isclose(
        result.total_cost_bdt,
        sum(
            item.grid_kwh * hour_data[item.hour].tariff_bdt_per_kwh
            for item in result.hourly_plan
        ),
        abs_tol=TOLERANCE,
    )
    assert math.isclose(
        result.peak_grid_kwh,
        max(item.grid_kwh for item in result.hourly_plan),
        abs_tol=TOLERANCE,
    )


@pytest.mark.parametrize("value", [-1e-10, -1e-8, 1e-8])
def test_normalize_cleans_near_zero_solver_noise(value: float) -> None:
    assert _normalize(value) == 0.0


@pytest.mark.parametrize("value", [1e-6, -1e-6])
def test_normalize_preserves_meaningful_small_values(value: float) -> None:
    assert _normalize(value) == value
    assert _normalize(value) != 0.0


def test_normalize_preserves_normal_nonzero_value() -> None:
    assert _normalize(49.9999998) == 49.9999998


@pytest.mark.parametrize("flow", [-1e-7, -1e-8, 0.0, 1e-8, 1e-7])
def test_battery_flow_within_epsilon_is_idle(flow: float) -> None:
    action, amount = _classify_battery_flow(flow)
    assert action is BatteryAction.IDLE
    assert amount == 0.0


@pytest.mark.parametrize(
    ("flow", "expected_action", "expected_amount"),
    [
        (1e-6, BatteryAction.CHARGE, 1e-6),
        (-1e-6, BatteryAction.DISCHARGE, 1e-6),
    ],
)
def test_battery_flow_above_epsilon_keeps_meaningful_action(
    flow: float,
    expected_action: BatteryAction,
    expected_amount: float,
) -> None:
    action, amount = _classify_battery_flow(flow)
    assert action is expected_action
    assert amount == expected_amount


def test_only_no_op_makes_no_constraint_change() -> None:
    request = make_request()
    directives = [make_no_op()]
    compiled = compile_directives(request, directives)
    result = optimize_energy(request, directives)

    assert compiled.effective_solar == tuple([0.0] * 24)
    assert compiled.minimum_energy == tuple([0.0] * 24)
    assert all(cap is None for cap in compiled.max_grid)
    assert all(compiled.charge_allowed)
    assert all(compiled.discharge_allowed)
    assert_result_is_mathematically_valid(request, directives, result)


def test_empty_directive_list_is_rejected_when_request_has_a_note() -> None:
    with pytest.raises(DirectiveCompilationError, match="directive count"):
        compile_directives(make_request(), [])


def test_solar_reduction_tightens_solar_bound() -> None:
    solar = [0] * 24
    solar[12] = 100
    request = make_request(
        solar=solar,
        capacity=0,
        initial=0,
        max_charge=0,
        max_discharge=0,
    )
    directives = [
        make_directive(0, "solar_reduction", {"hours": [12], "factor": 0.2})
    ]
    compiled = compile_directives(request, directives)
    result = optimize_energy(request, directives)

    assert compiled.effective_solar[12] == pytest.approx(20)
    assert result.hourly_plan[12].solar_used_kwh == pytest.approx(20)
    assert result.hourly_plan[12].grid_kwh == pytest.approx(80)
    assert_result_is_mathematically_valid(request, directives, result)


def test_minimum_reserve_raises_energy_lower_bound() -> None:
    request = make_request(initial=80, minimum=20)
    directives = [
        make_directive(
            0,
            "minimum_battery_reserve",
            {"hours": [5, 6], "minimum_energy_kwh": 70},
        )
    ]
    compiled = compile_directives(request, directives)
    result = optimize_energy(request, directives)

    assert compiled.minimum_energy[5:7] == (70.0, 70.0)
    assert result.hourly_plan[5].battery_energy_after_kwh >= 70 - TOLERANCE
    assert_result_is_mathematically_valid(request, directives, result)


def test_no_charge_window_prohibits_positive_flow() -> None:
    tariffs = [5] * 24
    tariffs[0] = 1
    tariffs[1] = 10
    request = make_request(tariffs=tariffs, initial=0, capacity=20)
    directives = [
        make_directive(0, "no_charge_window", {"hours": [0]})
    ]
    result = optimize_energy(request, directives)
    assert result.hourly_plan[0].battery_action is not BatteryAction.CHARGE
    assert_result_is_mathematically_valid(request, directives, result)


def test_no_discharge_window_prohibits_negative_flow() -> None:
    tariffs = [5] * 24
    tariffs[0] = 1
    tariffs[1] = 10
    request = make_request(tariffs=tariffs, initial=20, capacity=20)
    directives = [
        make_directive(0, "no_discharge_window", {"hours": [1]})
    ]
    result = optimize_energy(request, directives)
    assert result.hourly_plan[1].battery_action is not BatteryAction.DISCHARGE
    assert_result_is_mathematically_valid(request, directives, result)


def test_max_grid_window_caps_grid_import() -> None:
    tariffs = [5] * 24
    tariffs[1] = 10
    request = make_request(tariffs=tariffs, initial=20, capacity=20)
    directives = [
        make_directive(
            0, "max_grid_window", {"hours": [1], "max_grid_kwh": 80}
        )
    ]
    result = optimize_energy(request, directives)
    assert result.hourly_plan[1].grid_kwh <= 80 + TOLERANCE
    assert_result_is_mathematically_valid(request, directives, result)


def test_no_charge_and_no_discharge_force_idle() -> None:
    request = make_request(notes=["No charge.", "No discharge."])
    directives = [
        make_directive(0, "no_charge_window", {"hours": [7]}),
        make_directive(1, "no_discharge_window", {"hours": [7]}),
    ]
    compiled = compile_directives(request, directives)
    result = optimize_energy(request, directives)

    assert not compiled.charge_allowed[7]
    assert not compiled.discharge_allowed[7]
    assert result.hourly_plan[7].battery_action is BatteryAction.IDLE
    assert result.hourly_plan[7].battery_kwh == 0


def test_overlapping_different_directives_are_all_applied() -> None:
    request = make_request(
        notes=["Reserve.", "Grid cap."], initial=20, capacity=20, minimum=0
    )
    directives = [
        make_directive(
            0,
            "minimum_battery_reserve",
            {"hours": [1], "minimum_energy_kwh": 10},
        ),
        make_directive(
            1, "max_grid_window", {"hours": [1], "max_grid_kwh": 90}
        ),
    ]
    result = optimize_energy(request, directives)
    assert result.hourly_plan[1].grid_kwh <= 90 + TOLERANCE
    assert result.hourly_plan[1].battery_energy_after_kwh >= 10 - TOLERANCE
    assert_result_is_mathematically_valid(request, directives, result)


def test_higher_directive_reserve_overrides_base_minimum() -> None:
    request = make_request(initial=80, minimum=30)
    directives = [
        make_directive(
            0,
            "minimum_battery_reserve",
            {"hours": [4], "minimum_energy_kwh": 60},
        )
    ]
    assert compile_directives(request, directives).minimum_energy[4] == 60


def test_two_reserves_use_stricter_maximum() -> None:
    request = make_request(notes=["Reserve one.", "Reserve two."], initial=90)
    directives = [
        make_directive(
            0,
            "minimum_battery_reserve",
            {"hours": [8], "minimum_energy_kwh": 60},
        ),
        make_directive(
            1,
            "minimum_battery_reserve",
            {"hours": [8], "minimum_energy_kwh": 75},
        ),
    ]
    assert compile_directives(request, directives).minimum_energy[8] == 75


def test_two_grid_caps_use_stricter_minimum() -> None:
    request = make_request(notes=["Cap one.", "Cap two."])
    directives = [
        make_directive(
            0, "max_grid_window", {"hours": [8], "max_grid_kwh": 120}
        ),
        make_directive(
            1, "max_grid_window", {"hours": [8], "max_grid_kwh": 90}
        ),
    ]
    assert compile_directives(request, directives).max_grid[8] == 90


def test_reserve_above_capacity_raises_controlled_error() -> None:
    request = make_request(capacity=100, initial=50)
    directives = [
        make_directive(
            0,
            "minimum_battery_reserve",
            {"hours": [8], "minimum_energy_kwh": 101},
        )
    ]
    with pytest.raises(DirectiveCompilationError, match="battery capacity"):
        compile_directives(request, directives)


def test_bad_note_index_mapping_is_rejected() -> None:
    request = make_request()
    directives = [make_no_op(note_index=1)]
    with pytest.raises(DirectiveCompilationError, match="note indexes"):
        compile_directives(request, directives)


def test_shuffled_request_hours_are_solved_in_canonical_order() -> None:
    request_payload = make_request().model_dump(mode="json")
    random.Random(42).shuffle(request_payload["hours"])
    request = OptimizeEnergyRequest.model_validate(request_payload)
    result = optimize_energy(request, [make_no_op()])
    assert [item.hour for item in result.hourly_plan] == list(range(24))
    assert_result_is_mathematically_valid(request, [make_no_op()], result)


def test_objective_charges_cheap_and_discharges_expensive() -> None:
    tariffs = [5] * 24
    tariffs[0] = 1
    tariffs[1] = 10
    request = make_request(
        tariffs=tariffs,
        capacity=20,
        initial=0,
        minimum=0,
        max_charge=20,
        max_discharge=20,
    )
    directives = [make_no_op()]
    result = optimize_energy(request, directives)

    assert result.hourly_plan[0].battery_action is BatteryAction.CHARGE
    assert result.hourly_plan[0].battery_kwh == pytest.approx(20)
    assert result.hourly_plan[1].battery_action is BatteryAction.DISCHARGE
    assert result.hourly_plan[1].battery_kwh == pytest.approx(20)
    assert_result_is_mathematically_valid(request, directives, result)


def test_ambiguous_overlapping_solar_reductions_are_rejected() -> None:
    request = make_request(notes=["Solar one.", "Solar two."])
    directives = [
        make_directive(
            0, "solar_reduction", {"hours": [10, 11], "factor": 0.5}
        ),
        make_directive(
            1, "solar_reduction", {"hours": [11, 12], "factor": 0.8}
        ),
    ]
    with pytest.raises(DirectiveCompilationError, match="ambiguous"):
        compile_directives(request, directives)


def test_infeasible_problem_raises_optimization_error() -> None:
    request = make_request(capacity=0, initial=0, max_charge=0, max_discharge=0)
    directives = [
        make_directive(
            0, "max_grid_window", {"hours": [5], "max_grid_kwh": 0}
        )
    ]
    with pytest.raises(OptimizationError, match="could not produce"):
        optimize_energy(request, directives)


with PUBLIC_CASE_PATH.open(encoding="utf-8") as public_case_file:
    PUBLIC_CASES = json.load(public_case_file)["cases"]


@pytest.mark.parametrize(
    "case", PUBLIC_CASES, ids=[case["id"] for case in PUBLIC_CASES]
)
def test_public_sample_case_matches_reference_optimum(case: dict[str, Any]) -> None:
    request = OptimizeEnergyRequest.model_validate(case["input"])
    directives = [
        DirectiveInterpretation.model_validate(item)
        for item in case["expected_output"]["directive_interpretation"]
    ]
    result = optimize_energy(request, directives)

    assert result.total_cost_bdt == pytest.approx(
        case["expected_output"]["total_cost_bdt"], abs=TOLERANCE
    )
    assert_result_is_mathematically_valid(request, directives, result)
