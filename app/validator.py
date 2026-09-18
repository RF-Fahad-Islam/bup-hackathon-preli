"""Independent replay validation for completed GridWise schedules.

This module does not invoke the solver or inspect its matrices. It validates a
serialized hourly plan directly against the request, compiled directives, and
the public GridWise accounting rules.
"""

from __future__ import annotations

import math
from typing import Any

from app.models import BatteryAction, DirectiveInterpretation, OptimizeEnergyRequest
from app.optimizer import (
    DirectiveCompilationError,
    OptimizationResult,
    compile_directives,
)


DEFAULT_VALIDATION_TOLERANCE = 0.01
HOUR_COUNT = 24


class PlanValidationError(ValueError):
    """The proposed plan or its reported totals violate GridWise rules."""


def _finite_number(value: Any, label: str) -> float:
    if isinstance(value, bool):
        raise PlanValidationError(f"{label} must be a finite number")
    try:
        numeric = float(value)
    except (TypeError, ValueError) as exc:
        raise PlanValidationError(f"{label} must be a finite number") from exc
    if not math.isfinite(numeric):
        raise PlanValidationError(f"{label} must be finite")
    return numeric


def _close(left: float, right: float, tolerance: float) -> bool:
    return math.isclose(left, right, rel_tol=0.0, abs_tol=tolerance)


def _validate_directive_mapping(
    request: OptimizeEnergyRequest,
    directives: list[DirectiveInterpretation],
) -> None:
    if len(directives) != len(request.operator_notes):
        raise PlanValidationError(
            "directive count does not match the request operator note count"
        )
    indexes = [directive.note_index for directive in directives]
    if indexes != list(range(len(request.operator_notes))):
        raise PlanValidationError(
            "directive note indexes must be exactly 0 through N-1 in order"
        )


def validate_plan(
    request: OptimizeEnergyRequest,
    directives: list[DirectiveInterpretation],
    result: OptimizationResult,
    *,
    tolerance: float = DEFAULT_VALIDATION_TOLERANCE,
) -> None:
    """Independently replay and validate a completed optimization result.

    Returns ``None`` when the plan is valid. The first detected violation raises
    ``PlanValidationError`` with a concise diagnostic suitable for service logs.
    """

    tolerance = _finite_number(tolerance, "tolerance")
    if tolerance < 0:
        raise PlanValidationError("tolerance must be non-negative")

    _validate_directive_mapping(request, directives)
    try:
        compiled = compile_directives(request, directives)
    except DirectiveCompilationError as exc:
        raise PlanValidationError(f"directive compilation failed: {exc}") from exc

    plan = result.hourly_plan
    if len(plan) != HOUR_COUNT:
        raise PlanValidationError("hourly plan must contain exactly 24 items")

    plan_by_hour = {}
    for item in plan:
        hour = item.hour
        if isinstance(hour, bool) or not isinstance(hour, int) or not 0 <= hour < 24:
            raise PlanValidationError("hourly plan contains an invalid hour")
        if hour in plan_by_hour:
            raise PlanValidationError(f"hourly plan contains duplicate hour {hour}")
        plan_by_hour[hour] = item

    missing_hours = set(range(HOUR_COUNT)) - set(plan_by_hour)
    if missing_hours:
        raise PlanValidationError(
            f"hourly plan is missing hour {min(missing_hours)}"
        )

    hour_data = {item.hour: item for item in request.hours}
    expected_before = request.battery.initial_energy_kwh
    recalculated_total_grid = 0.0
    recalculated_total_cost = 0.0
    recalculated_peak_grid = 0.0

    for hour in range(HOUR_COUNT):
        item = plan_by_hour[hour]
        grid = _finite_number(item.grid_kwh, f"hour {hour}: grid_kwh")
        solar = _finite_number(item.solar_used_kwh, f"hour {hour}: solar_used_kwh")
        battery_amount = _finite_number(
            item.battery_kwh, f"hour {hour}: battery_kwh"
        )
        reported_after = _finite_number(
            item.battery_energy_after_kwh,
            f"hour {hour}: battery_energy_after_kwh",
        )

        if grid < -tolerance:
            raise PlanValidationError(f"hour {hour}: grid_kwh must be non-negative")
        if solar < -tolerance:
            raise PlanValidationError(
                f"hour {hour}: solar_used_kwh must be non-negative"
            )
        if battery_amount < 0:
            raise PlanValidationError(
                f"hour {hour}: battery_kwh must be non-negative"
            )
        if reported_after < -tolerance:
            raise PlanValidationError(
                f"hour {hour}: battery_energy_after_kwh must be non-negative"
            )

        effective_battery_amount = (
            0.0 if abs(battery_amount) <= tolerance else battery_amount
        )

        action = item.battery_action
        if not isinstance(action, BatteryAction):
            raise PlanValidationError(f"hour {hour}: invalid battery_action")
        if action is BatteryAction.CHARGE:
            signed_flow = effective_battery_amount
            if (
                effective_battery_amount
                > request.battery.max_charge_kwh_per_hour + tolerance
            ):
                raise PlanValidationError(f"hour {hour}: charge rate limit exceeded")
            if not compiled.charge_allowed[hour] and effective_battery_amount > 0:
                raise PlanValidationError(
                    f"hour {hour}: charging prohibited by directive"
                )
        elif action is BatteryAction.DISCHARGE:
            signed_flow = -effective_battery_amount
            if (
                effective_battery_amount
                > request.battery.max_discharge_kwh_per_hour + tolerance
            ):
                raise PlanValidationError(f"hour {hour}: discharge rate limit exceeded")
            if not compiled.discharge_allowed[hour] and effective_battery_amount > 0:
                raise PlanValidationError(
                    f"hour {hour}: discharging prohibited by directive"
                )
        else:
            signed_flow = 0.0
            if abs(battery_amount) > tolerance:
                raise PlanValidationError(
                    f"hour {hour}: idle action requires zero battery_kwh"
                )

        if solar > compiled.effective_solar[hour] + tolerance:
            raise PlanValidationError(
                f"hour {hour}: solar_used_kwh exceeds effective solar"
            )
        grid_cap = compiled.max_grid[hour]
        if grid_cap is not None and grid > grid_cap + tolerance:
            raise PlanValidationError(f"hour {hour}: grid import cap violated")

        minimum_energy = compiled.minimum_energy[hour]
        if reported_after < minimum_energy - tolerance:
            raise PlanValidationError(f"hour {hour}: battery reserve violated")
        if reported_after > request.battery.capacity_kwh + tolerance:
            raise PlanValidationError(f"hour {hour}: battery capacity exceeded")

        expected_after = expected_before + signed_flow
        if not _close(reported_after, expected_after, tolerance):
            raise PlanValidationError(f"hour {hour}: battery transition violated")

        supplied_energy = grid + solar
        required_energy = hour_data[hour].demand_kwh + signed_flow
        if not _close(supplied_energy, required_energy, tolerance):
            raise PlanValidationError(f"hour {hour}: energy balance violated")

        expected_before = reported_after
        recalculated_total_grid += grid
        recalculated_total_cost += grid * hour_data[hour].tariff_bdt_per_kwh
        recalculated_peak_grid = max(recalculated_peak_grid, grid)

    if not _close(
        expected_before, request.battery.initial_energy_kwh, tolerance
    ):
        raise PlanValidationError(
            "hour 23: end-of-day battery neutrality violated"
        )

    reported_total_grid = _finite_number(
        result.total_grid_kwh, "reported total_grid_kwh"
    )
    reported_total_cost = _finite_number(
        result.total_cost_bdt, "reported total_cost_bdt"
    )
    reported_peak_grid = _finite_number(
        result.peak_grid_kwh, "reported peak_grid_kwh"
    )

    if not _close(reported_total_grid, recalculated_total_grid, tolerance):
        raise PlanValidationError(
            "reported total_grid_kwh does not match recalculated total"
        )
    if not _close(reported_total_cost, recalculated_total_cost, tolerance):
        raise PlanValidationError(
            "reported total_cost_bdt does not match recalculated cost"
        )
    if not _close(reported_peak_grid, recalculated_peak_grid, tolerance):
        raise PlanValidationError(
            "reported peak_grid_kwh does not match recalculated peak"
        )
