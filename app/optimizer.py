"""Deterministic directive compilation and 24-hour energy optimization.

Natural-language interpretation deliberately does not belong in this module. The
optimizer accepts only validated request and directive models, compiles them into
hourly bounds, solves one linear program, and returns numeric scheduling results.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import cast

import numpy as np
from scipy.optimize import linprog

from app.models import (
    BatteryAction,
    DirectiveInterpretation,
    DirectiveType,
    HourlyPlanItem,
    MaxGridWindowAdjustment,
    MinimumBatteryReserveAdjustment,
    NoChargeWindowAdjustment,
    NoDischargeWindowAdjustment,
    OptimizeEnergyRequest,
    SolarReductionAdjustment,
)


HOUR_COUNT = 24
VARIABLE_COUNT = HOUR_COUNT * 4
NORMALIZATION_EPSILON = 1e-7


class DirectiveCompilationError(ValueError):
    """A validated directive cannot safely be applied to this request."""


class OptimizationError(RuntimeError):
    """The mathematical optimizer failed to produce a valid solution vector."""


@dataclass(frozen=True)
class CompiledConstraints:
    """All directive effects expressed as canonical per-hour LP bounds.

    Multiple reserves merge using their maximum; grid caps merge using their
    minimum; charge/discharge prohibitions merge using logical AND. Overlapping
    solar reductions are rejected because the public specification does not
    define whether their factors replace, multiply, or otherwise combine.
    """

    effective_solar: tuple[float, ...]
    minimum_energy: tuple[float, ...]
    max_grid: tuple[float | None, ...]
    charge_allowed: tuple[bool, ...]
    discharge_allowed: tuple[bool, ...]


@dataclass(frozen=True)
class OptimizationResult:
    hourly_plan: list[HourlyPlanItem]
    total_grid_kwh: float
    total_cost_bdt: float
    peak_grid_kwh: float


def grid_index(hour: int) -> int:
    return hour


def solar_index(hour: int) -> int:
    return HOUR_COUNT + hour


def battery_flow_index(hour: int) -> int:
    return (2 * HOUR_COUNT) + hour


def energy_index(hour: int) -> int:
    return (3 * HOUR_COUNT) + hour


def _validate_directive_mapping(
    request: OptimizeEnergyRequest,
    directives: list[DirectiveInterpretation],
) -> None:
    note_count = len(request.operator_notes)
    if len(directives) != note_count:
        raise DirectiveCompilationError(
            "directive count must match the request operator note count"
        )

    indexes = [directive.note_index for directive in directives]
    if indexes != list(range(note_count)):
        raise DirectiveCompilationError(
            "directive note indexes must be exactly 0 through N-1 in order"
        )


def compile_directives(
    request: OptimizeEnergyRequest,
    directives: list[DirectiveInterpretation],
) -> CompiledConstraints:
    """Compile validated directives into deterministic hourly restrictions."""

    _validate_directive_mapping(request, directives)
    hour_data = {item.hour: item for item in request.hours}
    battery = request.battery

    effective_solar = [hour_data[hour].solar_kwh for hour in range(HOUR_COUNT)]
    minimum_energy = [battery.minimum_energy_kwh] * HOUR_COUNT
    max_grid: list[float | None] = [None] * HOUR_COUNT
    charge_allowed = [True] * HOUR_COUNT
    discharge_allowed = [True] * HOUR_COUNT
    solar_directive_seen = [False] * HOUR_COUNT

    for directive in directives:
        if directive.directive_type is DirectiveType.NO_OP:
            continue

        if directive.directive_type is DirectiveType.SOLAR_REDUCTION:
            adjustment = cast(
                SolarReductionAdjustment, directive.structured_adjustment
            )
            for hour in adjustment.hours:
                if solar_directive_seen[hour]:
                    raise DirectiveCompilationError(
                        "overlapping solar_reduction directives are ambiguous "
                        f"for hour {hour}"
                    )
                solar_directive_seen[hour] = True
                effective_solar[hour] = hour_data[hour].solar_kwh * adjustment.factor

        elif directive.directive_type is DirectiveType.MINIMUM_BATTERY_RESERVE:
            adjustment = cast(
                MinimumBatteryReserveAdjustment, directive.structured_adjustment
            )
            if adjustment.minimum_energy_kwh > battery.capacity_kwh:
                raise DirectiveCompilationError(
                    "minimum battery reserve must not exceed battery capacity"
                )
            for hour in adjustment.hours:
                minimum_energy[hour] = max(
                    minimum_energy[hour], adjustment.minimum_energy_kwh
                )

        elif directive.directive_type is DirectiveType.NO_CHARGE_WINDOW:
            adjustment = cast(NoChargeWindowAdjustment, directive.structured_adjustment)
            for hour in adjustment.hours:
                charge_allowed[hour] = False

        elif directive.directive_type is DirectiveType.NO_DISCHARGE_WINDOW:
            adjustment = cast(
                NoDischargeWindowAdjustment, directive.structured_adjustment
            )
            for hour in adjustment.hours:
                discharge_allowed[hour] = False

        elif directive.directive_type is DirectiveType.MAX_GRID_WINDOW:
            adjustment = cast(MaxGridWindowAdjustment, directive.structured_adjustment)
            for hour in adjustment.hours:
                current_cap = max_grid[hour]
                max_grid[hour] = (
                    adjustment.max_grid_kwh
                    if current_cap is None
                    else min(current_cap, adjustment.max_grid_kwh)
                )

    return CompiledConstraints(
        effective_solar=tuple(effective_solar),
        minimum_energy=tuple(minimum_energy),
        max_grid=tuple(max_grid),
        charge_allowed=tuple(charge_allowed),
        discharge_allowed=tuple(discharge_allowed),
    )


def _build_objective(request: OptimizeEnergyRequest) -> np.ndarray:
    hour_data = {item.hour: item for item in request.hours}
    objective = np.zeros(VARIABLE_COUNT, dtype=float)
    for hour in range(HOUR_COUNT):
        objective[grid_index(hour)] = hour_data[hour].tariff_bdt_per_kwh
    return objective


def _build_equalities(
    request: OptimizeEnergyRequest,
) -> tuple[np.ndarray, np.ndarray]:
    """Build energy balance, battery transition, and final-neutrality equations."""

    hour_data = {item.hour: item for item in request.hours}
    row_count = HOUR_COUNT + HOUR_COUNT + 1
    matrix = np.zeros((row_count, VARIABLE_COUNT), dtype=float)
    rhs = np.zeros(row_count, dtype=float)
    row = 0

    # g[h] + s[h] - b[h] = demand[h]
    for hour in range(HOUR_COUNT):
        matrix[row, grid_index(hour)] = 1.0
        matrix[row, solar_index(hour)] = 1.0
        matrix[row, battery_flow_index(hour)] = -1.0
        rhs[row] = hour_data[hour].demand_kwh
        row += 1

    # e[0] - b[0] = initial; e[h] - e[h-1] - b[h] = 0 thereafter.
    for hour in range(HOUR_COUNT):
        matrix[row, energy_index(hour)] = 1.0
        matrix[row, battery_flow_index(hour)] = -1.0
        if hour == 0:
            rhs[row] = request.battery.initial_energy_kwh
        else:
            matrix[row, energy_index(hour - 1)] = -1.0
        row += 1

    # End-of-day neutrality: e[23] = initial energy.
    matrix[row, energy_index(HOUR_COUNT - 1)] = 1.0
    rhs[row] = request.battery.initial_energy_kwh
    return matrix, rhs


def _build_bounds(
    request: OptimizeEnergyRequest,
    compiled: CompiledConstraints,
) -> list[tuple[float | None, float | None]]:
    bounds: list[tuple[float | None, float | None]] = []

    # Grid bounds: non-negative, optionally capped by a directive.
    bounds.extend((0.0, compiled.max_grid[hour]) for hour in range(HOUR_COUNT))

    # Solar bounds: non-negative and capped by effective available solar.
    bounds.extend(
        (0.0, compiled.effective_solar[hour]) for hour in range(HOUR_COUNT)
    )

    # Signed battery flow: negative discharges, positive charges.
    for hour in range(HOUR_COUNT):
        lower = (
            -request.battery.max_discharge_kwh_per_hour
            if compiled.discharge_allowed[hour]
            else 0.0
        )
        upper = (
            request.battery.max_charge_kwh_per_hour
            if compiled.charge_allowed[hour]
            else 0.0
        )
        bounds.append((lower, upper))

    # Battery energy after each hour.
    bounds.extend(
        (compiled.minimum_energy[hour], request.battery.capacity_kwh)
        for hour in range(HOUR_COUNT)
    )
    return bounds


def _normalize(value: float) -> float:
    value = float(value)
    return 0.0 if abs(value) < NORMALIZATION_EPSILON else value


def _classify_battery_flow(battery_flow: float) -> tuple[BatteryAction, float]:
    """Convert signed battery flow into the public action and magnitude fields."""

    if battery_flow > NORMALIZATION_EPSILON:
        return BatteryAction.CHARGE, battery_flow
    if battery_flow < -NORMALIZATION_EPSILON:
        return BatteryAction.DISCHARGE, abs(battery_flow)
    return BatteryAction.IDLE, 0.0


def optimize_energy(
    request: OptimizeEnergyRequest,
    directives: list[DirectiveInterpretation],
) -> OptimizationResult:
    """Return the minimum-cost schedule for a request and structured directives."""

    compiled = compile_directives(request, directives)
    objective = _build_objective(request)
    equality_matrix, equality_rhs = _build_equalities(request)
    bounds = _build_bounds(request, compiled)

    solver_result = linprog(
        objective,
        A_eq=equality_matrix,
        b_eq=equality_rhs,
        bounds=bounds,
        method="highs",
    )
    if not solver_result.success or solver_result.x is None:
        diagnostic = solver_result.message or "unknown solver failure"
        raise OptimizationError(
            f"HiGHS could not produce an optimal schedule: {diagnostic}"
        )

    solution = solver_result.x
    hourly_plan: list[HourlyPlanItem] = []
    for hour in range(HOUR_COUNT):
        grid = _normalize(solution[grid_index(hour)])
        solar = _normalize(solution[solar_index(hour)])
        battery_flow = _normalize(solution[battery_flow_index(hour)])
        energy = _normalize(solution[energy_index(hour)])

        action, battery_kwh = _classify_battery_flow(battery_flow)

        hourly_plan.append(
            HourlyPlanItem(
                hour=hour,
                grid_kwh=grid,
                solar_used_kwh=solar,
                battery_action=action,
                battery_kwh=battery_kwh,
                battery_energy_after_kwh=energy,
            )
        )

    hour_data = {item.hour: item for item in request.hours}
    total_grid = sum(item.grid_kwh for item in hourly_plan)
    total_cost = sum(
        item.grid_kwh * hour_data[item.hour].tariff_bdt_per_kwh
        for item in hourly_plan
    )
    peak_grid = max(item.grid_kwh for item in hourly_plan)

    return OptimizationResult(
        hourly_plan=hourly_plan,
        total_grid_kwh=_normalize(total_grid),
        total_cost_bdt=_normalize(total_cost),
        peak_grid_kwh=_normalize(peak_grid),
    )
