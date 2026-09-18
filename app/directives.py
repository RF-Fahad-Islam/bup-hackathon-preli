"""Raw Reading -> Directive (the Guardrail) and Directives -> per-hour constraints.

The LLM only reports what a note literally says (a Raw Reading). Everything
arithmetic -- expanding end-exclusive windows, wrapping past midnight,
turning "% of capacity" into kWh and "80% reduction" into factor 0.2 -- is
done here, deterministically. See docs/adr/0001.
"""
import math
from dataclasses import dataclass, field
from typing import Optional

from .schemas import BatterySpec

CONSTRAINT_TYPES = {
    "solar_reduction",
    "minimum_battery_reserve",
    "no_charge_window",
    "no_discharge_window",
    "max_grid_window",
}
ALL_TYPES = CONSTRAINT_TYPES | {"no_op"}
VALUE_TOL = 1e-6


class GuardrailError(ValueError):
    """A Raw Reading that must not become a constraint."""


@dataclass(frozen=True)
class Directive:
    note_index: int
    directive_type: str
    hours: tuple[int, ...] = ()
    value: Optional[float] = None  # factor | minimum_energy_kwh | max_grid_kwh
    reason: str = ""
    source: str = "llm"  # llm | tripwire (degraded mode only)

    @property
    def applies(self) -> bool:
        return self.directive_type != "no_op"

    def structured_adjustment(self) -> Optional[dict]:
        t = self.directive_type
        if t == "no_op":
            return None
        adj: dict = {"hours": list(self.hours)}
        if t == "solar_reduction":
            adj["factor"] = self.value
        elif t == "minimum_battery_reserve":
            adj["minimum_energy_kwh"] = self.value
        elif t == "max_grid_window":
            adj["max_grid_kwh"] = self.value
        return adj

    def same_meaning(self, other: "Directive") -> bool:
        if self.directive_type != other.directive_type or self.hours != other.hours:
            return False
        if self.value is None or other.value is None:
            return self.value is other.value
        return abs(self.value - other.value) <= VALUE_TOL


def _finite(x) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x)


def expand_spans(spans) -> tuple[int, ...]:
    """Start-inclusive, end-exclusive; a span whose end is before its start wraps past midnight."""
    if not isinstance(spans, list) or not spans:
        raise GuardrailError("a constraint directive needs at least one time span")
    hours: set[int] = set()
    for span in spans:
        if not isinstance(span, dict):
            raise GuardrailError("span must be an object")
        s, e = span.get("start_hour"), span.get("end_hour")
        if not (isinstance(s, int) and isinstance(e, int)) or isinstance(s, bool) or isinstance(e, bool):
            raise GuardrailError("span hours must be integers")
        if not (0 <= s <= 23 and 0 <= e <= 24):
            raise GuardrailError("span hours out of range")
        if e == 0:
            e = 24  # "until midnight"
        if s == e:
            raise GuardrailError("empty span")
        hours.update(range(s, e) if s < e else [*range(s, 24), *range(0, e)])
    return tuple(sorted(hours))


def raw_to_directive(raw: dict, note_index: int, battery: BatterySpec, source: str = "llm") -> Directive:
    """The Guardrail: validate one untrusted Raw Reading and normalise it into a Directive."""
    if not isinstance(raw, dict):
        raise GuardrailError("reading must be an object")
    t = raw.get("directive_type")
    if t not in ALL_TYPES:
        raise GuardrailError(f"unsupported directive_type {t!r}")
    reason = str(raw.get("reason") or "")[:300]
    if t == "no_op":
        return Directive(note_index, "no_op", reason=reason, source=source)

    hours = expand_spans(raw.get("spans"))
    value: Optional[float] = None

    if t == "solar_reduction":
        v, meaning = raw.get("solar_value"), raw.get("solar_meaning")
        if not _finite(v) or not 0 <= v <= 100:
            raise GuardrailError("solar_value must be a percentage 0..100")
        if meaning == "remaining":
            value = v / 100
        elif meaning == "reduction":
            value = 1 - v / 100
        else:
            raise GuardrailError("solar_meaning must be 'remaining' or 'reduction'")
        value = round(value, 6)

    elif t == "minimum_battery_reserve":
        v, unit = raw.get("amount_value"), raw.get("amount_unit")
        if not _finite(v) or v < 0:
            raise GuardrailError("reserve amount must be a non-negative number")
        if unit == "percent_of_capacity":
            if v > 100:
                raise GuardrailError("reserve percentage above 100")
            value = battery.capacity_kwh * v / 100
        elif unit == "kwh":
            value = v
        else:
            raise GuardrailError("reserve unit must be 'kwh' or 'percent_of_capacity'")
        value = round(float(value), 6)
        if value > battery.capacity_kwh + VALUE_TOL:
            raise GuardrailError("reserve exceeds battery capacity")

    elif t == "max_grid_window":
        v, unit = raw.get("amount_value"), raw.get("amount_unit")
        if not _finite(v) or v < 0:
            raise GuardrailError("grid cap must be a non-negative number")
        if unit != "kwh":
            raise GuardrailError("grid cap unit must be 'kwh'")
        value = round(float(v), 6)

    return Directive(note_index, t, hours, value, reason, source)


def interpretation_to_directives(readings, notes: list[str], battery: BatterySpec, source: str = "llm") -> list[Directive]:
    """Validate a whole interpretation: exactly one guardrail-valid Directive per note, in order."""
    if not isinstance(readings, list):
        raise GuardrailError("interpretation must be a list")
    by_index: dict[int, dict] = {}
    for r in readings:
        idx = r.get("note_index") if isinstance(r, dict) else None
        if not isinstance(idx, int) or isinstance(idx, bool) or not 0 <= idx < len(notes):
            raise GuardrailError("note_index does not reference a real note")
        if idx in by_index:
            raise GuardrailError(f"duplicate note_index {idx}")
        by_index[idx] = r
    if len(by_index) != len(notes):
        raise GuardrailError("every note must be interpreted exactly once")
    return [raw_to_directive(by_index[i], i, battery, source) for i in range(len(notes))]


@dataclass
class HourlyConstraints:
    """All Directives merged per hour; the most restrictive wins."""
    effective_solar: list[float]
    reserve_floor: list[float]
    grid_cap: list[float]
    no_charge: list[bool] = field(default_factory=lambda: [False] * 24)
    no_discharge: list[bool] = field(default_factory=lambda: [False] * 24)


def build_constraints(directives: list[Directive], solar: list[float], battery: BatterySpec) -> HourlyConstraints:
    factor = [1.0] * 24
    c = HourlyConstraints(
        effective_solar=[],
        reserve_floor=[float(battery.minimum_energy_kwh)] * 24,
        grid_cap=[math.inf] * 24,
    )
    for d in directives:
        for h in d.hours:
            if d.directive_type == "solar_reduction":
                factor[h] = min(factor[h], d.value)
            elif d.directive_type == "minimum_battery_reserve":
                c.reserve_floor[h] = max(c.reserve_floor[h], d.value)
            elif d.directive_type == "max_grid_window":
                c.grid_cap[h] = min(c.grid_cap[h], d.value)
            elif d.directive_type == "no_charge_window":
                c.no_charge[h] = True
            elif d.directive_type == "no_discharge_window":
                c.no_discharge[h] = True
    c.effective_solar = [solar[h] * factor[h] for h in range(24)]
    return c
