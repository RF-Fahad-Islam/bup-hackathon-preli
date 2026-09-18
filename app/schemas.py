"""Public API contract. Field names here are fixed by the challenge and must not change."""
from typing import Literal, Optional, Union

from pydantic import BaseModel, ConfigDict, Field, StrictFloat, StrictInt, field_validator

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
    tariff_bdt_per_kwh: Number


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


class DirectiveInterpretation(BaseModel):
    note_index: int
    applies: bool
    directive_type: DirectiveType
    structured_adjustment: Optional[dict]
    explanation: str


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
