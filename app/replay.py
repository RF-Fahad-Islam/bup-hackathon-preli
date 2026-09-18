"""Replay: re-check a finished Hourly Plan hour by hour, like the judge does.

Independent of the optimizer: it only sees the published plan, the request
and the merged constraints, and it recomputes the totals from the plan.
"""
from dataclasses import dataclass

from .directives import HourlyConstraints
from .schemas import BatterySpec, HourSlot

TOL = 1e-3  # judge tolerance is 0.01; we hold ourselves to 10x tighter


class ReplayError(Exception):
    def __init__(self, violations: list[str]):
        super().__init__("; ".join(violations[:5]))
        self.violations = violations


@dataclass
class Totals:
    total_grid_kwh: float
    total_cost_bdt: float
    peak_grid_kwh: float


def replay(plan: list[dict], hours: list[HourSlot], battery: BatterySpec, cons: HourlyConstraints) -> Totals:
    v: list[str] = []
    if [p["hour"] for p in plan] != list(range(24)):
        raise ReplayError(["plan must list hours 0..23 in order"])

    energy = float(battery.initial_energy_kwh)
    for p, slot in zip(plan, hours):
        h = p["hour"]
        g, s, a, b, after = (p["grid_kwh"], p["solar_used_kwh"], p["battery_action"],
                             p["battery_kwh"], p["battery_energy_after_kwh"])
        for name, val in (("grid", g), ("solar_used", s), ("battery_kwh", b)):
            if val < -TOL:
                v.append(f"h{h}: negative {name}")
        charge = b if a == "charge" else 0.0
        discharge = b if a == "discharge" else 0.0
        if a not in ("charge", "discharge", "idle"):
            v.append(f"h{h}: bad action {a!r}")
        if a == "idle" and abs(b) > TOL:
            v.append(f"h{h}: idle with non-zero battery_kwh")
        if a != "idle" and b <= 0:
            v.append(f"h{h}: {a} with zero battery_kwh")
        expected = energy + charge - discharge
        if abs(after - expected) > TOL:
            v.append(f"h{h}: transition {energy}->{after}, expected {expected}")
        if after > battery.capacity_kwh + TOL:
            v.append(f"h{h}: above capacity")
        if after < cons.reserve_floor[h] - TOL:
            v.append(f"h{h}: below reserve floor {cons.reserve_floor[h]}")
        if charge > battery.max_charge_kwh_per_hour + TOL:
            v.append(f"h{h}: charge rate")
        if discharge > battery.max_discharge_kwh_per_hour + TOL:
            v.append(f"h{h}: discharge rate")
        if s > cons.effective_solar[h] + TOL:
            v.append(f"h{h}: solar above effective solar {cons.effective_solar[h]}")
        if cons.no_charge[h] and charge > TOL:
            v.append(f"h{h}: charging in no-charge window")
        if cons.no_discharge[h] and discharge > TOL:
            v.append(f"h{h}: discharging in no-discharge window")
        if g > cons.grid_cap[h] + TOL:
            v.append(f"h{h}: grid above cap {cons.grid_cap[h]}")
        if abs(g + s + discharge - slot.demand_kwh - charge) > TOL:
            v.append(f"h{h}: energy balance")
        energy = after
    if abs(energy - battery.initial_energy_kwh) > TOL:
        v.append(f"final energy {energy} != initial {battery.initial_energy_kwh}")
    if v:
        raise ReplayError(v)

    return Totals(
        total_grid_kwh=round(sum(p["grid_kwh"] for p in plan), 4),
        total_cost_bdt=round(sum(p["grid_kwh"] * s.tariff_bdt_per_kwh for p, s in zip(plan, hours)), 4),
        peak_grid_kwh=round(max(p["grid_kwh"] for p in plan), 4),
    )
