"""Strict Pydantic contracts for GridWise requests and responses.

This module intentionally contains schema-local validation only. Constraints that
need both a scenario and a generated plan belong in a later domain validator.
"""

from __future__ import annotations

from enum import Enum
from typing import Annotated, Any, Literal

from pydantic import (
    AfterValidator,
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    StrictBool,
    StrictStr,
    field_validator,
    model_validator,
)


def _require_json_number(value: Any) -> Any:
    """Accept JSON-style integers/floats, but reject booleans and coercion."""

    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("must be a JSON number")
    return value


def _validate_directive_hours(hours: list[int]) -> list[int]:
    """Require directive hours to be unique and already ascending."""

    if len(hours) != len(set(hours)):
        raise ValueError("directive hours must be unique")
    if hours != sorted(hours):
        raise ValueError("directive hours must be in ascending order")
    return hours


FiniteNonNegativeFloat = Annotated[
    float,
    BeforeValidator(_require_json_number),
    Field(ge=0, allow_inf_nan=False),
]
FiniteUnitFloat = Annotated[
    float,
    BeforeValidator(_require_json_number),
    Field(ge=0, le=1, allow_inf_nan=False),
]
HourIndex = Annotated[int, Field(strict=True, ge=0, le=23)]
NonNegativeIndex = Annotated[int, Field(strict=True, ge=0)]
DirectiveHours = Annotated[
    list[HourIndex],
    AfterValidator(_validate_directive_hours),
]


class StrictModel(BaseModel):
    """Base model that rejects undocumented fields."""

    model_config = ConfigDict(extra="forbid")


class HourInput(StrictModel):
    hour: HourIndex
    demand_kwh: FiniteNonNegativeFloat
    solar_kwh: FiniteNonNegativeFloat
    tariff_bdt_per_kwh: FiniteNonNegativeFloat


class BatteryInput(StrictModel):
    capacity_kwh: FiniteNonNegativeFloat
    initial_energy_kwh: FiniteNonNegativeFloat
    minimum_energy_kwh: FiniteNonNegativeFloat
    max_charge_kwh_per_hour: FiniteNonNegativeFloat
    max_discharge_kwh_per_hour: FiniteNonNegativeFloat

    @model_validator(mode="after")
    def validate_energy_bounds(self) -> BatteryInput:
        if self.initial_energy_kwh > self.capacity_kwh:
            raise ValueError("initial_energy_kwh must not exceed capacity_kwh")
        if self.minimum_energy_kwh > self.capacity_kwh:
            raise ValueError("minimum_energy_kwh must not exceed capacity_kwh")
        if self.initial_energy_kwh < self.minimum_energy_kwh:
            raise ValueError(
                "initial_energy_kwh must be greater than or equal to "
                "minimum_energy_kwh"
            )
        return self


class OptimizeEnergyRequest(StrictModel):
    scenario_id: StrictStr
    operator_notes: Annotated[list[StrictStr], Field(min_length=1, max_length=3)]
    hours: Annotated[list[HourInput], Field(min_length=24, max_length=24)]
    battery: BatteryInput

    @field_validator("scenario_id")
    @classmethod
    def validate_scenario_id(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("scenario_id must not be empty or whitespace-only")
        return value

    @field_validator("operator_notes")
    @classmethod
    def validate_operator_notes(cls, notes: list[str]) -> list[str]:
        if any(not note.strip() for note in notes):
            raise ValueError("operator notes must not be empty or whitespace-only")
        return notes

    @field_validator("hours")
    @classmethod
    def validate_complete_hours(cls, hours: list[HourInput]) -> list[HourInput]:
        hour_values = [entry.hour for entry in hours]
        if len(hour_values) != len(set(hour_values)):
            raise ValueError("hour values must be unique")
        if set(hour_values) != set(range(24)):
            raise ValueError("hours must contain every hour from 0 through 23")
        return hours


class DirectiveType(str, Enum):
    SOLAR_REDUCTION = "solar_reduction"
    MINIMUM_BATTERY_RESERVE = "minimum_battery_reserve"
    NO_CHARGE_WINDOW = "no_charge_window"
    NO_DISCHARGE_WINDOW = "no_discharge_window"
    MAX_GRID_WINDOW = "max_grid_window"
    NO_OP = "no_op"


class SolarReductionAdjustment(StrictModel):
    hours: DirectiveHours
    factor: FiniteUnitFloat


class MinimumBatteryReserveAdjustment(StrictModel):
    hours: DirectiveHours
    minimum_energy_kwh: FiniteNonNegativeFloat


class NoChargeWindowAdjustment(StrictModel):
    hours: DirectiveHours


class NoDischargeWindowAdjustment(StrictModel):
    hours: DirectiveHours


class MaxGridWindowAdjustment(StrictModel):
    hours: DirectiveHours
    max_grid_kwh: FiniteNonNegativeFloat


StructuredAdjustment = (
    SolarReductionAdjustment
    | MinimumBatteryReserveAdjustment
    | NoChargeWindowAdjustment
    | NoDischargeWindowAdjustment
    | MaxGridWindowAdjustment
)


_ADJUSTMENT_MODEL_BY_DIRECTIVE: dict[DirectiveType, type[StrictModel]] = {
    DirectiveType.SOLAR_REDUCTION: SolarReductionAdjustment,
    DirectiveType.MINIMUM_BATTERY_RESERVE: MinimumBatteryReserveAdjustment,
    DirectiveType.NO_CHARGE_WINDOW: NoChargeWindowAdjustment,
    DirectiveType.NO_DISCHARGE_WINDOW: NoDischargeWindowAdjustment,
    DirectiveType.MAX_GRID_WINDOW: MaxGridWindowAdjustment,
}


class DirectiveInterpretation(StrictModel):
    note_index: NonNegativeIndex
    applies: StrictBool
    directive_type: DirectiveType
    structured_adjustment: StructuredAdjustment | None
    explanation: StrictStr

    @model_validator(mode="before")
    @classmethod
    def parse_typed_adjustment(cls, data: Any) -> Any:
        """Parse the adjustment using the model selected by directive_type.

        The two window-only adjustment objects have identical JSON shapes, so a
        normal untagged union cannot reliably distinguish them. Selecting the
        model from directive_type also produces clearer mismatch errors.
        """

        if not isinstance(data, dict):
            return data

        raw_type = data.get("directive_type")
        try:
            directive_type = DirectiveType(raw_type)
        except (TypeError, ValueError):
            return data

        adjustment_model = _ADJUSTMENT_MODEL_BY_DIRECTIVE.get(directive_type)
        raw_adjustment = data.get("structured_adjustment")
        if adjustment_model is None or raw_adjustment is None:
            return data

        parsed_data = dict(data)
        parsed_data["structured_adjustment"] = adjustment_model.model_validate(
            raw_adjustment
        )
        return parsed_data

    @field_validator("explanation")
    @classmethod
    def validate_explanation(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("explanation must not be empty or whitespace-only")
        return value

    @model_validator(mode="after")
    def validate_directive_semantics(self) -> DirectiveInterpretation:
        if self.directive_type is DirectiveType.NO_OP:
            if self.applies:
                raise ValueError("no_op must use applies=false")
            if self.structured_adjustment is not None:
                raise ValueError("no_op must use structured_adjustment=null")
            return self

        if not self.applies:
            raise ValueError("non-no_op directives must use applies=true")
        if self.structured_adjustment is None:
            raise ValueError(
                "non-no_op directives require a structured_adjustment"
            )

        expected_model = _ADJUSTMENT_MODEL_BY_DIRECTIVE[self.directive_type]
        if not isinstance(self.structured_adjustment, expected_model):
            raise ValueError(
                "structured_adjustment does not match directive_type "
                f"{self.directive_type.value}"
            )
        return self


class BatteryAction(str, Enum):
    CHARGE = "charge"
    DISCHARGE = "discharge"
    IDLE = "idle"


class HourlyPlanItem(StrictModel):
    hour: HourIndex
    grid_kwh: FiniteNonNegativeFloat
    solar_used_kwh: FiniteNonNegativeFloat
    battery_action: BatteryAction
    battery_kwh: FiniteNonNegativeFloat
    battery_energy_after_kwh: FiniteNonNegativeFloat

    @model_validator(mode="after")
    def validate_idle_amount(self) -> HourlyPlanItem:
        if self.battery_action is BatteryAction.IDLE and self.battery_kwh != 0:
            raise ValueError("idle battery_action requires battery_kwh=0")
        return self


class OptimizeEnergyResponse(StrictModel):
    scenario_id: StrictStr
    directive_interpretation: Annotated[
        list[DirectiveInterpretation], Field(min_length=1, max_length=3)
    ]
    hourly_plan: Annotated[list[HourlyPlanItem], Field(min_length=24, max_length=24)]
    total_grid_kwh: FiniteNonNegativeFloat
    total_cost_bdt: FiniteNonNegativeFloat
    peak_grid_kwh: FiniteNonNegativeFloat
    plan_summary: StrictStr

    @field_validator("scenario_id")
    @classmethod
    def validate_scenario_id(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("scenario_id must not be empty or whitespace-only")
        return value

    @field_validator("directive_interpretation")
    @classmethod
    def validate_interpretation_indexes(
        cls, interpretations: list[DirectiveInterpretation]
    ) -> list[DirectiveInterpretation]:
        indexes = [item.note_index for item in interpretations]
        if indexes != list(range(len(interpretations))):
            raise ValueError(
                "directive interpretations must be ordered with note_index "
                "values 0 through N-1"
            )
        return interpretations

    @field_validator("hourly_plan")
    @classmethod
    def validate_complete_plan(
        cls, hourly_plan: list[HourlyPlanItem]
    ) -> list[HourlyPlanItem]:
        hour_values = [entry.hour for entry in hourly_plan]
        if len(hour_values) != len(set(hour_values)):
            raise ValueError("hourly plan hour values must be unique")
        if set(hour_values) != set(range(24)):
            raise ValueError("hourly plan must contain every hour from 0 through 23")
        return hourly_plan


class HealthResponse(StrictModel):
    status: Literal["ok"] = "ok"
