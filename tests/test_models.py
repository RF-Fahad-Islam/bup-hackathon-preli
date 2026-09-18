from __future__ import annotations

import math
from copy import deepcopy
from typing import Any

import pytest
from pydantic import ValidationError

from app.models import (
    BatteryAction,
    DirectiveInterpretation,
    DirectiveType,
    HealthResponse,
    HourlyPlanItem,
    OptimizeEnergyRequest,
    OptimizeEnergyResponse,
)


def make_valid_request() -> dict[str, Any]:
    return {
        "scenario_id": "SCENARIO-001",
        "operator_notes": ["Do not charge from 2 PM until 4 PM."],
        "hours": [
            {
                "hour": hour,
                "demand_kwh": 100 + hour,
                "solar_kwh": max(0, 12 - abs(12 - hour)) * 5,
                "tariff_bdt_per_kwh": 0 if hour == 0 else 8,
            }
            for hour in range(24)
        ],
        "battery": {
            "capacity_kwh": 200,
            "initial_energy_kwh": 100,
            "minimum_energy_kwh": 40,
            "max_charge_kwh_per_hour": 50,
            "max_discharge_kwh_per_hour": 50,
        },
    }


def make_valid_plan() -> list[dict[str, Any]]:
    return [
        {
            "hour": hour,
            "grid_kwh": 100,
            "solar_used_kwh": 0,
            "battery_action": "idle",
            "battery_kwh": 0,
            "battery_energy_after_kwh": 100,
        }
        for hour in range(24)
    ]


def make_no_op(note_index: int = 0) -> dict[str, Any]:
    return {
        "note_index": note_index,
        "applies": False,
        "directive_type": "no_op",
        "structured_adjustment": None,
        "explanation": "The note does not affect this schedule.",
    }


def make_valid_response() -> dict[str, Any]:
    return {
        "scenario_id": "SCENARIO-001",
        "directive_interpretation": [make_no_op()],
        "hourly_plan": make_valid_plan(),
        "total_grid_kwh": 2400,
        "total_cost_bdt": 19200,
        "peak_grid_kwh": 100,
        "plan_summary": "Uses the grid while leaving the battery idle.",
    }


def assert_request_invalid(payload: dict[str, Any], message: str | None = None) -> None:
    with pytest.raises(ValidationError) as exc_info:
        OptimizeEnergyRequest.model_validate(payload)
    if message is not None:
        assert message in str(exc_info.value)


def assert_directive_invalid(
    payload: dict[str, Any], message: str | None = None
) -> None:
    with pytest.raises(ValidationError) as exc_info:
        DirectiveInterpretation.model_validate(payload)
    if message is not None:
        assert message in str(exc_info.value)


@pytest.mark.parametrize("note_count", [1, 3])
def test_valid_request_note_counts(note_count: int) -> None:
    payload = make_valid_request()
    payload["operator_notes"] = [f"Operator note {index}" for index in range(note_count)]
    request = OptimizeEnergyRequest.model_validate(payload)
    assert len(request.operator_notes) == note_count
    assert len(request.hours) == 24


def test_valid_request_allows_unsorted_complete_hours() -> None:
    payload = make_valid_request()
    payload["hours"] = list(reversed(payload["hours"]))
    request = OptimizeEnergyRequest.model_validate(payload)
    assert request.hours[0].hour == 23


@pytest.mark.parametrize(
    ("field", "value"),
    [("solar_kwh", 0), ("tariff_bdt_per_kwh", 0)],
)
def test_valid_request_allows_zero_hour_values(field: str, value: int) -> None:
    payload = make_valid_request()
    for hour in payload["hours"]:
        hour[field] = value
    OptimizeEnergyRequest.model_validate(payload)


def test_valid_request_allows_initial_equal_to_minimum() -> None:
    payload = make_valid_request()
    payload["battery"]["initial_energy_kwh"] = 40
    request = OptimizeEnergyRequest.model_validate(payload)
    assert request.battery.initial_energy_kwh == request.battery.minimum_energy_kwh


@pytest.mark.parametrize("length", [23, 25])
def test_request_rejects_wrong_hour_count(length: int) -> None:
    payload = make_valid_request()
    if length == 23:
        payload["hours"] = payload["hours"][:23]
    else:
        payload["hours"].append(deepcopy(payload["hours"][-1]))
    assert_request_invalid(payload)


def test_request_rejects_duplicate_hour() -> None:
    payload = make_valid_request()
    payload["hours"][-1]["hour"] = 22
    assert_request_invalid(payload, "hour values must be unique")


def test_request_rejects_missing_hour_23() -> None:
    payload = make_valid_request()
    payload["hours"] = payload["hours"][:23]
    assert_request_invalid(payload)


@pytest.mark.parametrize("invalid_hour", [-1, 24])
def test_request_rejects_out_of_range_hour(invalid_hour: int) -> None:
    payload = make_valid_request()
    payload["hours"][0]["hour"] = invalid_hour
    assert_request_invalid(payload)


@pytest.mark.parametrize(
    "field", ["demand_kwh", "solar_kwh", "tariff_bdt_per_kwh"]
)
def test_request_rejects_negative_hour_numbers(field: str) -> None:
    payload = make_valid_request()
    payload["hours"][0][field] = -0.1
    assert_request_invalid(payload)


@pytest.mark.parametrize("invalid_number", [math.nan, math.inf, -math.inf])
def test_request_rejects_non_finite_numbers(invalid_number: float) -> None:
    payload = make_valid_request()
    payload["hours"][0]["demand_kwh"] = invalid_number
    assert_request_invalid(payload)


@pytest.mark.parametrize("scenario_id", ["", "   "])
def test_request_rejects_blank_scenario_id(scenario_id: str) -> None:
    payload = make_valid_request()
    payload["scenario_id"] = scenario_id
    assert_request_invalid(payload, "scenario_id must not be empty")


@pytest.mark.parametrize("notes", [[], ["1", "2", "3", "4"]])
def test_request_rejects_invalid_note_count(notes: list[str]) -> None:
    payload = make_valid_request()
    payload["operator_notes"] = notes
    assert_request_invalid(payload)


def test_request_rejects_blank_note() -> None:
    payload = make_valid_request()
    payload["operator_notes"] = ["   "]
    assert_request_invalid(payload, "operator notes must not be empty")


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("initial_energy_kwh", 201, "must not exceed capacity_kwh"),
        ("minimum_energy_kwh", 201, "must not exceed capacity_kwh"),
        (
            "initial_energy_kwh",
            39,
            "must be greater than or equal to minimum_energy_kwh",
        ),
    ],
)
def test_request_rejects_invalid_battery_relationships(
    field: str, value: int, message: str
) -> None:
    payload = make_valid_request()
    payload["battery"][field] = value
    assert_request_invalid(payload, message)


@pytest.mark.parametrize(
    "payload",
    [
        {
            "note_index": 0,
            "applies": True,
            "directive_type": "solar_reduction",
            "structured_adjustment": {"hours": [12, 13], "factor": 0.25},
            "explanation": "Solar is reduced during cleaning.",
        },
        {
            "note_index": 0,
            "applies": True,
            "directive_type": "minimum_battery_reserve",
            "structured_adjustment": {
                "hours": [18, 19, 20],
                "minimum_energy_kwh": 100,
            },
            "explanation": "An emergency reserve is required.",
        },
        {
            "note_index": 0,
            "applies": True,
            "directive_type": "no_charge_window",
            "structured_adjustment": {"hours": [14, 15]},
            "explanation": "Charging is unavailable.",
        },
        {
            "note_index": 0,
            "applies": True,
            "directive_type": "no_discharge_window",
            "structured_adjustment": {"hours": [18, 19]},
            "explanation": "Discharging is unavailable.",
        },
        {
            "note_index": 0,
            "applies": True,
            "directive_type": "max_grid_window",
            "structured_adjustment": {"hours": [18, 19], "max_grid_kwh": 155},
            "explanation": "The feeder has an import cap.",
        },
        make_no_op(),
    ],
)
def test_all_six_directive_types_are_valid(payload: dict[str, Any]) -> None:
    interpretation = DirectiveInterpretation.model_validate(payload)
    assert interpretation.directive_type in DirectiveType


def test_directive_rejects_unknown_type() -> None:
    payload = make_no_op()
    payload["directive_type"] = "unknown"
    assert_directive_invalid(payload)


def test_no_op_rejects_applies_true() -> None:
    payload = make_no_op()
    payload["applies"] = True
    assert_directive_invalid(payload, "no_op must use applies=false")


def test_directive_rejects_coerced_boolean() -> None:
    payload = make_no_op()
    payload["applies"] = "false"
    assert_directive_invalid(payload)


def test_no_op_rejects_adjustment() -> None:
    payload = make_no_op()
    payload["structured_adjustment"] = {"hours": [12]}
    assert_directive_invalid(payload, "no_op must use structured_adjustment=null")


def make_no_charge() -> dict[str, Any]:
    return {
        "note_index": 0,
        "applies": True,
        "directive_type": "no_charge_window",
        "structured_adjustment": {"hours": [14, 15]},
        "explanation": "Charging is unavailable.",
    }


def test_non_no_op_rejects_applies_false() -> None:
    payload = make_no_charge()
    payload["applies"] = False
    assert_directive_invalid(payload, "non-no_op directives must use applies=true")


def test_non_no_op_rejects_null_adjustment() -> None:
    payload = make_no_charge()
    payload["structured_adjustment"] = None
    assert_directive_invalid(payload, "require a structured_adjustment")


def test_solar_reduction_rejects_max_grid_adjustment() -> None:
    payload = {
        "note_index": 0,
        "applies": True,
        "directive_type": "solar_reduction",
        "structured_adjustment": {"hours": [12, 13], "max_grid_kwh": 50},
        "explanation": "Solar is reduced.",
    }
    assert_directive_invalid(payload)


@pytest.mark.parametrize("factor", [-0.01, 1.01])
def test_solar_reduction_rejects_factor_outside_unit_interval(factor: float) -> None:
    payload = {
        "note_index": 0,
        "applies": True,
        "directive_type": "solar_reduction",
        "structured_adjustment": {"hours": [12, 13], "factor": factor},
        "explanation": "Solar is reduced.",
    }
    assert_directive_invalid(payload)


@pytest.mark.parametrize("hours", [[14, 14], [15, 14], [24], [-1]])
def test_directive_rejects_invalid_hours(hours: list[int]) -> None:
    payload = make_no_charge()
    payload["structured_adjustment"]["hours"] = hours
    assert_directive_invalid(payload)


@pytest.mark.parametrize(
    ("directive_type", "adjustment"),
    [
        ("max_grid_window", {"hours": [18], "max_grid_kwh": -1}),
        (
            "minimum_battery_reserve",
            {"hours": [18], "minimum_energy_kwh": -1},
        ),
    ],
)
def test_directive_rejects_negative_adjustment_values(
    directive_type: str, adjustment: dict[str, Any]
) -> None:
    payload = {
        "note_index": 0,
        "applies": True,
        "directive_type": directive_type,
        "structured_adjustment": adjustment,
        "explanation": "Applicable constraint.",
    }
    assert_directive_invalid(payload)


def test_hourly_plan_item_accepts_valid_actions() -> None:
    for action, amount in [
        (BatteryAction.CHARGE, 10),
        (BatteryAction.DISCHARGE, 10),
        (BatteryAction.IDLE, 0),
    ]:
        item = HourlyPlanItem.model_validate(
            {
                "hour": 0,
                "grid_kwh": 100,
                "solar_used_kwh": 10,
                "battery_action": action,
                "battery_kwh": amount,
                "battery_energy_after_kwh": 100,
            }
        )
        assert item.battery_action is action


def test_hourly_plan_item_rejects_idle_with_nonzero_amount() -> None:
    payload = make_valid_plan()[0]
    payload["battery_kwh"] = 1
    with pytest.raises(ValidationError, match="idle battery_action requires"):
        HourlyPlanItem.model_validate(payload)


@pytest.mark.parametrize("value", [-1, math.nan, math.inf, -math.inf])
def test_hourly_plan_item_rejects_invalid_grid(value: float) -> None:
    payload = make_valid_plan()[0]
    payload["grid_kwh"] = value
    with pytest.raises(ValidationError):
        HourlyPlanItem.model_validate(payload)


def test_valid_complete_response() -> None:
    response = OptimizeEnergyResponse.model_validate(make_valid_response())
    assert len(response.hourly_plan) == 24
    assert response.directive_interpretation[0].note_index == 0


def test_response_rejects_duplicate_plan_hour() -> None:
    payload = make_valid_response()
    payload["hourly_plan"][-1]["hour"] = 22
    with pytest.raises(ValidationError, match="hourly plan hour values must be unique"):
        OptimizeEnergyResponse.model_validate(payload)


def test_response_rejects_missing_plan_hour() -> None:
    payload = make_valid_response()
    payload["hourly_plan"] = payload["hourly_plan"][:-1]
    with pytest.raises(ValidationError):
        OptimizeEnergyResponse.model_validate(payload)


def test_response_rejects_non_contiguous_interpretation_indexes() -> None:
    payload = make_valid_response()
    payload["directive_interpretation"] = [make_no_op(0), make_no_op(2)]
    with pytest.raises(ValidationError, match="note_index values 0 through N-1"):
        OptimizeEnergyResponse.model_validate(payload)


def test_models_forbid_extra_fields() -> None:
    payload = make_valid_request()
    payload["unexpected"] = True
    assert_request_invalid(payload)


def test_numeric_strings_are_not_silently_coerced() -> None:
    payload = make_valid_request()
    payload["hours"][0]["demand_kwh"] = "100"
    assert_request_invalid(payload, "must be a JSON number")


def test_health_response_contract() -> None:
    assert HealthResponse().model_dump() == {"status": "ok"}
    with pytest.raises(ValidationError):
        HealthResponse.model_validate({"status": "starting"})
