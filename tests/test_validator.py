from __future__ import annotations

import json
import math
import random
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from app.models import (
    BatteryAction,
    DirectiveInterpretation,
    OptimizeEnergyRequest,
)
from app.optimizer import OptimizationResult, compile_directives, optimize_energy
from app.validator import PlanValidationError, validate_plan


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
    notes = notes or ["This note does not affect today's schedule."]
    demand = demand or [100] * 24
    solar = solar or [0] * 24
    tariffs = tariffs or [5] * 24
    return OptimizeEnergyRequest.model_validate(
        {
            "scenario_id": "VALIDATOR-TEST",
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
    return DirectiveInterpretation.model_validate(
        {
            "note_index": note_index,
            "applies": directive_type != "no_op",
            "directive_type": directive_type,
            "structured_adjustment": adjustment,
            "explanation": "Structured directive for validator testing.",
        }
    )


def no_op(note_index: int = 0) -> DirectiveInterpretation:
    return make_directive(note_index, "no_op", None)


def optimize_default() -> tuple[
    OptimizeEnergyRequest, list[DirectiveInterpretation], OptimizationResult
]:
    request = make_request()
    directives = [no_op()]
    return request, directives, optimize_energy(request, directives)


def update_plan_item(
    result: OptimizationResult, hour: int, **updates: Any
) -> OptimizationResult:
    plan = list(result.hourly_plan)
    position = next(index for index, item in enumerate(plan) if item.hour == hour)
    plan[position] = plan[position].model_copy(update=updates)
    return replace(result, hourly_plan=plan)


def flow_from_item(item: Any) -> float:
    if item.battery_action is BatteryAction.CHARGE:
        return item.battery_kwh
    if item.battery_action is BatteryAction.DISCHARGE:
        return -item.battery_kwh
    return 0.0


def action_and_amount(flow: float) -> tuple[BatteryAction, float]:
    if flow > 0:
        return BatteryAction.CHARGE, flow
    if flow < 0:
        return BatteryAction.DISCHARGE, abs(flow)
    return BatteryAction.IDLE, 0.0


def test_valid_optimizer_plan_passes() -> None:
    request, directives, result = optimize_default()
    assert validate_plan(request, directives, result) is None


def test_missing_hour_is_rejected() -> None:
    request, directives, result = optimize_default()
    invalid = replace(result, hourly_plan=result.hourly_plan[:-1])
    with pytest.raises(PlanValidationError, match="exactly 24"):
        validate_plan(request, directives, invalid)


def test_duplicate_hour_is_rejected() -> None:
    request, directives, result = optimize_default()
    plan = list(result.hourly_plan)
    plan[-1] = plan[0]
    invalid = replace(result, hourly_plan=plan)
    with pytest.raises(PlanValidationError, match="duplicate hour 0"):
        validate_plan(request, directives, invalid)


def test_negative_grid_is_rejected() -> None:
    request, directives, result = optimize_default()
    invalid = update_plan_item(result, 0, grid_kwh=-1.0)
    with pytest.raises(PlanValidationError, match="grid_kwh must be non-negative"):
        validate_plan(request, directives, invalid)


def test_solar_above_effective_availability_is_rejected() -> None:
    solar = [0] * 24
    solar[12] = 100
    request = make_request(solar=solar)
    directives = [
        make_directive(0, "solar_reduction", {"hours": [12], "factor": 0.2})
    ]
    result = optimize_energy(request, directives)
    invalid = update_plan_item(result, 12, solar_used_kwh=21.0)
    with pytest.raises(PlanValidationError, match="exceeds effective solar"):
        validate_plan(request, directives, invalid)


def test_wrong_battery_transition_is_rejected() -> None:
    request, directives, result = optimize_default()
    original = result.hourly_plan[0].battery_energy_after_kwh
    invalid = update_plan_item(result, 0, battery_energy_after_kwh=original + 1)
    with pytest.raises(PlanValidationError, match="battery transition violated"):
        validate_plan(request, directives, invalid)


def test_energy_below_base_reserve_is_rejected() -> None:
    request = make_request(initial=50, minimum=40)
    directives = [no_op()]
    result = optimize_energy(request, directives)
    invalid = update_plan_item(result, 0, battery_energy_after_kwh=39)
    with pytest.raises(PlanValidationError, match="battery reserve violated"):
        validate_plan(request, directives, invalid)


def test_energy_below_directive_reserve_is_rejected() -> None:
    request = make_request(initial=80)
    directives = [
        make_directive(
            0,
            "minimum_battery_reserve",
            {"hours": [5], "minimum_energy_kwh": 60},
        )
    ]
    result = optimize_energy(request, directives)
    invalid = update_plan_item(result, 5, battery_energy_after_kwh=59)
    with pytest.raises(PlanValidationError, match="battery reserve violated"):
        validate_plan(request, directives, invalid)


def test_energy_above_capacity_is_rejected() -> None:
    request, directives, result = optimize_default()
    invalid = update_plan_item(result, 0, battery_energy_after_kwh=101)
    with pytest.raises(PlanValidationError, match="battery capacity exceeded"):
        validate_plan(request, directives, invalid)


def test_charge_rate_violation_is_rejected() -> None:
    request, directives, result = optimize_default()
    invalid = update_plan_item(
        result,
        0,
        battery_action=BatteryAction.CHARGE,
        battery_kwh=request.battery.max_charge_kwh_per_hour + 1,
    )
    with pytest.raises(PlanValidationError, match="charge rate limit exceeded"):
        validate_plan(request, directives, invalid)


def test_discharge_rate_violation_is_rejected() -> None:
    request, directives, result = optimize_default()
    invalid = update_plan_item(
        result,
        0,
        battery_action=BatteryAction.DISCHARGE,
        battery_kwh=request.battery.max_discharge_kwh_per_hour + 1,
    )
    with pytest.raises(PlanValidationError, match="discharge rate limit exceeded"):
        validate_plan(request, directives, invalid)


def test_charge_during_no_charge_window_is_rejected() -> None:
    request = make_request(notes=["Charging is unavailable."])
    directives = [make_directive(0, "no_charge_window", {"hours": [7]})]
    result = optimize_energy(request, directives)
    invalid = update_plan_item(
        result, 7, battery_action=BatteryAction.CHARGE, battery_kwh=1
    )
    with pytest.raises(PlanValidationError, match="charging prohibited"):
        validate_plan(request, directives, invalid)


def test_discharge_during_no_discharge_window_is_rejected() -> None:
    request = make_request(notes=["Discharging is unavailable."])
    directives = [make_directive(0, "no_discharge_window", {"hours": [7]})]
    result = optimize_energy(request, directives)
    invalid = update_plan_item(
        result, 7, battery_action=BatteryAction.DISCHARGE, battery_kwh=1
    )
    with pytest.raises(PlanValidationError, match="discharging prohibited"):
        validate_plan(request, directives, invalid)


def make_fully_prohibited_battery_result() -> tuple[
    OptimizeEnergyRequest, list[DirectiveInterpretation], OptimizationResult
]:
    request = make_request(notes=["No charging.", "No discharging."])
    directives = [
        make_directive(0, "no_charge_window", {"hours": [7]}),
        make_directive(1, "no_discharge_window", {"hours": [7]}),
    ]
    return request, directives, optimize_energy(request, directives)


@pytest.mark.parametrize(
    "action", [BatteryAction.CHARGE, BatteryAction.DISCHARGE]
)
def test_prohibited_sub_tolerance_action_is_zero_flow(
    action: BatteryAction,
) -> None:
    request, directives, result = make_fully_prohibited_battery_result()
    invalid_looking_but_effectively_idle = update_plan_item(
        result, 7, battery_action=action, battery_kwh=0.009
    )

    assert (
        validate_plan(request, directives, invalid_looking_but_effectively_idle)
        is None
    )


@pytest.mark.parametrize(
    ("action", "message"),
    [
        (BatteryAction.CHARGE, "charging prohibited"),
        (BatteryAction.DISCHARGE, "discharging prohibited"),
    ],
)
def test_prohibited_above_tolerance_action_is_rejected(
    action: BatteryAction, message: str
) -> None:
    request, directives, result = make_fully_prohibited_battery_result()
    invalid = update_plan_item(result, 7, battery_action=action, battery_kwh=0.011)

    with pytest.raises(PlanValidationError, match=message):
        validate_plan(request, directives, invalid)


@pytest.mark.parametrize(
    "action", [BatteryAction.CHARGE, BatteryAction.DISCHARGE]
)
def test_negative_battery_amount_never_reverses_action(
    action: BatteryAction,
) -> None:
    request, directives, result = optimize_default()
    corrupted = update_plan_item(
        result, 7, battery_action=action, battery_kwh=-0.005
    )

    with pytest.raises(PlanValidationError, match="battery_kwh must be non-negative"):
        validate_plan(request, directives, corrupted)


def test_grid_above_max_grid_directive_is_rejected() -> None:
    request = make_request(notes=["Grid is capped."], initial=20)
    directives = [
        make_directive(
            0, "max_grid_window", {"hours": [7], "max_grid_kwh": 90}
        )
    ]
    result = optimize_energy(request, directives)
    invalid = update_plan_item(result, 7, grid_kwh=91)
    with pytest.raises(PlanValidationError, match="grid import cap violated"):
        validate_plan(request, directives, invalid)


def test_hourly_energy_balance_violation_is_rejected() -> None:
    request, directives, result = optimize_default()
    invalid = update_plan_item(
        result, 4, grid_kwh=result.hourly_plan[4].grid_kwh + 1
    )
    with pytest.raises(PlanValidationError, match="hour 4: energy balance violated"):
        validate_plan(request, directives, invalid)


def test_end_of_day_neutrality_violation_is_rejected() -> None:
    request, directives, result = optimize_default()
    final_item = result.hourly_plan[23]
    old_flow = flow_from_item(final_item)
    delta = -1.0 if old_flow > 0 else 1.0
    new_flow = old_flow + delta
    action, amount = action_and_amount(new_flow)
    invalid = update_plan_item(
        result,
        23,
        grid_kwh=final_item.grid_kwh + delta,
        battery_action=action,
        battery_kwh=amount,
        battery_energy_after_kwh=final_item.battery_energy_after_kwh + delta,
    )
    with pytest.raises(PlanValidationError, match="end-of-day battery neutrality"):
        validate_plan(request, directives, invalid)


@pytest.mark.parametrize(
    ("field", "message"),
    [
        ("total_grid_kwh", "reported total_grid_kwh"),
        ("total_cost_bdt", "reported total_cost_bdt"),
        ("peak_grid_kwh", "reported peak_grid_kwh"),
    ],
)
def test_wrong_reported_totals_are_rejected(field: str, message: str) -> None:
    request, directives, result = optimize_default()
    invalid = replace(result, **{field: getattr(result, field) + 1})
    with pytest.raises(PlanValidationError, match=message):
        validate_plan(request, directives, invalid)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("grid_kwh", math.nan),
        ("solar_used_kwh", math.inf),
        ("battery_kwh", -math.inf),
        ("battery_energy_after_kwh", math.nan),
    ],
)
def test_non_finite_plan_values_are_rejected(field: str, value: float) -> None:
    request, directives, result = optimize_default()
    invalid = update_plan_item(result, 0, **{field: value})
    with pytest.raises(PlanValidationError, match="must be finite"):
        validate_plan(request, directives, invalid)


def test_non_finite_reported_total_is_rejected() -> None:
    request, directives, result = optimize_default()
    invalid = replace(result, total_cost_bdt=math.nan)
    with pytest.raises(PlanValidationError, match="reported total_cost_bdt must be finite"):
        validate_plan(request, directives, invalid)


def test_shuffled_plan_is_canonicalized_safely() -> None:
    request, directives, result = optimize_default()
    shuffled = list(result.hourly_plan)
    random.Random(42).shuffle(shuffled)
    assert validate_plan(
        request, directives, replace(result, hourly_plan=shuffled)
    ) is None


def test_difference_inside_official_tolerance_is_accepted() -> None:
    request, directives, result = optimize_default()
    within_tolerance = replace(
        result, total_grid_kwh=result.total_grid_kwh + 0.009
    )
    assert validate_plan(request, directives, within_tolerance) is None


def test_difference_outside_official_tolerance_is_rejected() -> None:
    request, directives, result = optimize_default()
    outside_tolerance = replace(
        result, total_grid_kwh=result.total_grid_kwh + 0.011
    )
    with pytest.raises(PlanValidationError, match="reported total_grid_kwh"):
        validate_plan(request, directives, outside_tolerance)


def test_directive_count_mismatch_is_rejected() -> None:
    request, _, result = optimize_default()
    with pytest.raises(PlanValidationError, match="directive count"):
        validate_plan(request, [], result)


def test_directive_index_mismatch_is_rejected() -> None:
    request, _, result = optimize_default()
    with pytest.raises(PlanValidationError, match="directive note indexes"):
        validate_plan(request, [no_op(note_index=1)], result)


def test_invalid_battery_action_is_rejected_defensively() -> None:
    request, directives, result = optimize_default()
    invalid = update_plan_item(result, 0, battery_action="charge")
    with pytest.raises(PlanValidationError, match="invalid battery_action"):
        validate_plan(request, directives, invalid)


with PUBLIC_CASE_PATH.open(encoding="utf-8") as public_case_file:
    PUBLIC_CASES = json.load(public_case_file)["cases"]


@pytest.mark.parametrize(
    "case", PUBLIC_CASES, ids=[case["id"] for case in PUBLIC_CASES]
)
def test_all_public_optimizer_results_pass_independent_replay(
    case: dict[str, Any],
) -> None:
    request = OptimizeEnergyRequest.model_validate(case["input"])
    directives = [
        DirectiveInterpretation.model_validate(item)
        for item in case["expected_output"]["directive_interpretation"]
    ]
    result = optimize_energy(request, directives)

    assert validate_plan(request, directives, result) is None
    compiled = compile_directives(request, directives)
    assert len(compiled.effective_solar) == 24
