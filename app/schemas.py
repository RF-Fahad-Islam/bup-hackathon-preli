"""Public API contract. Field names here are fixed by the challenge and must not change."""
from typing import Literal, Optional, Union

from pydantic import BaseModel, ConfigDict, Field, StrictFloat, StrictInt, field_validator, model_validator

Number = Union[StrictInt, StrictFloat]

DirectiveType = Literal[
    "solar_reduction",
    "minimum_battery_reserve",
    "no_charge_window",
    "no_discharge_window",
    "max_grid_window",
    "no_op",
]


class HourSlot(BaseModel):
    model_config = ConfigDict(extra="ignore")
    hour: StrictInt
    demand_kwh: Number
    solar_kwh: Number
    tariff_bdt_per_kwh: Number = Field(ge=0)


class BatterySpec(BaseModel):
    model_config = ConfigDict(extra="ignore")
    capacity_kwh: Number
    initial_energy_kwh: Number
    minimum_energy_kwh: Number
    max_charge_kwh_per_hour: Number
    max_discharge_kwh_per_hour: Number


class OptimizeRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")
    scenario_id: str
    operator_notes: list[str] = Field(min_length=1, max_length=3)
    hours: list[HourSlot] = Field(min_length=24, max_length=24)
    battery: BatterySpec

    @field_validator("scenario_id")
    @classmethod
    def scenario_id_non_blank(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("scenario_id must not be blank")
        return v

    @field_validator("operator_notes")
    @classmethod
    def notes_non_empty(cls, v: list[str]) -> list[str]:
        if any(not n.strip() for n in v):
            raise ValueError("operator_notes must be non-empty strings")
        return v

    @field_validator("hours")
    @classmethod
    def hours_cover_day(cls, v: list[HourSlot]) -> list[HourSlot]:
        if sorted(h.hour for h in v) != list(range(24)):
            raise ValueError("hours must contain each hour 0..23 exactly once")
        return sorted(v, key=lambda h: h.hour)


class SolarReductionAdjustment(BaseModel):
    model_config = ConfigDict(extra="forbid")
    hours: list[StrictInt]
    factor: Number


class MinimumBatteryReserveAdjustment(BaseModel):
    model_config = ConfigDict(extra="forbid")
    hours: list[StrictInt]
    minimum_energy_kwh: Number


class NoChargeWindowAdjustment(BaseModel):
    model_config = ConfigDict(extra="forbid")
    hours: list[StrictInt]


class NoDischargeWindowAdjustment(BaseModel):
    model_config = ConfigDict(extra="forbid")
    hours: list[StrictInt]


class MaxGridWindowAdjustment(BaseModel):
    model_config = ConfigDict(extra="forbid")
    hours: list[StrictInt]
    max_grid_kwh: Number


_ADJUSTMENT_MODEL_BY_TYPE: dict[str, type[BaseModel]] = {
    "solar_reduction": SolarReductionAdjustment,
    "minimum_battery_reserve": MinimumBatteryReserveAdjustment,
    "no_charge_window": NoChargeWindowAdjustment,
    "no_discharge_window": NoDischargeWindowAdjustment,
    "max_grid_window": MaxGridWindowAdjustment,
}


class DirectiveInterpretation(BaseModel):
    note_index: int
    applies: bool
    directive_type: DirectiveType
    structured_adjustment: Optional[dict]
    explanation: str

    @model_validator(mode="before")
    @classmethod
    def _typecheck_adjustment(cls, data):
        """Validate structured_adjustment against the shape its directive_type requires."""
        if not isinstance(data, dict):
            return data
        model = _ADJUSTMENT_MODEL_BY_TYPE.get(data.get("directive_type"))
        adjustment = data.get("structured_adjustment")
        if model is not None and adjustment is not None:
            data = {**data, "structured_adjustment": model.model_validate(adjustment).model_dump()}
        return data

    @model_validator(mode="after")
    def _validate_semantics(self):
        if self.directive_type == "no_op":
            if self.applies or self.structured_adjustment is not None:
                raise ValueError("no_op must have applies=false and structured_adjustment=null")
        elif not self.applies:
            raise ValueError(f"{self.directive_type} must have applies=true")
        elif self.structured_adjustment is None:
            raise ValueError(f"{self.directive_type} requires a structured_adjustment")
        return self


class HourPlan(BaseModel):
    hour: int
    grid_kwh: float
    solar_used_kwh: float
    battery_action: Literal["charge", "discharge", "idle"]
    battery_kwh: float
    battery_energy_after_kwh: float


class OptimizeResponse(BaseModel):
    scenario_id: str
    directive_interpretation: list[DirectiveInterpretation]
    hourly_plan: list[HourPlan]
    total_grid_kwh: float
    total_cost_bdt: float
    peak_grid_kwh: float
    plan_summary: str
