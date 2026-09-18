"""Two-stage LP over 24 hours, solved with HiGHS.

Stage 1 minimises grid cost. Stage 2 keeps cost at the optimum and minimises
battery throughput, which gives the cleanest of the tied-optimal plans.
Charge and discharge are separate LP variables; they are netted into one
Battery Action per hour afterwards, which leaves grid, energy and every
constraint unchanged.
"""
import math
from dataclasses import dataclass

import numpy as np
from scipy.optimize import linprog
from scipy.sparse import lil_matrix

from .directives import HourlyConstraints
from .schemas import BatterySpec, HourSlot

H = 24
G, S, C, D, E = range(5)  # variable blocks
N = 5 * H
DECIMALS = 4
EPS = 10 ** -DECIMALS


class InfeasibleError(Exception):
    pass


def _ix(block: int, h: int) -> int:
    return block * H + h


@dataclass
class RawPlan:
    grid: list[float]
    solar_used: list[float]
    net_battery: list[float]  # +charge / -discharge
    energy_after: list[float]


def _build(hours: list[HourSlot], battery: BatterySpec, cons: HourlyConstraints):
    e0 = float(battery.initial_energy_kwh)
    a_eq = lil_matrix((2 * H + 1, N))
    b_eq = np.zeros(2 * H + 1)
    for h in range(H):
        # energy balance: grid + solar + discharge - charge = demand
        a_eq[h, _ix(G, h)] = 1
        a_eq[h, _ix(S, h)] = 1
        a_eq[h, _ix(D, h)] = 1
        a_eq[h, _ix(C, h)] = -1
        b_eq[h] = hours[h].demand_kwh
        # battery transition: e[h] - e[h-1] - charge + discharge = 0
        r = H + h
        a_eq[r, _ix(E, h)] = 1
        a_eq[r, _ix(C, h)] = -1
        a_eq[r, _ix(D, h)] = 1
        if h == 0:
            b_eq[r] = e0
        else:
            a_eq[r, _ix(E, h - 1)] = -1
    # Battery Neutrality
    a_eq[2 * H, _ix(E, H - 1)] = 1
    b_eq[2 * H] = e0

    bounds = []
    for h in range(H):
        cap = cons.grid_cap[h]
        bounds.append((0, None if math.isinf(cap) else cap))
    for h in range(H):
        bounds.append((0, max(0.0, cons.effective_solar[h])))
    for h in range(H):
        bounds.append((0, 0 if cons.no_charge[h] else battery.max_charge_kwh_per_hour))
    for h in range(H):
        bounds.append((0, 0 if cons.no_discharge[h] else battery.max_discharge_kwh_per_hour))
    for h in range(H):
        bounds.append((cons.reserve_floor[h], battery.capacity_kwh))
    return a_eq.tocsr(), b_eq, bounds


def solve(hours: list[HourSlot], battery: BatterySpec, cons: HourlyConstraints) -> RawPlan:
    a_eq, b_eq, bounds = _build(hours, battery, cons)
    for lo, hi in bounds:
        if hi is not None and lo > hi + 1e-9:
            raise InfeasibleError("contradictory bounds")

    cost = np.zeros(N)
    for h in range(H):
        cost[_ix(G, h)] = hours[h].tariff_bdt_per_kwh
    s1 = linprog(cost, A_eq=a_eq, b_eq=b_eq, bounds=bounds, method="highs")
    if s1.status != 0:
        raise InfeasibleError(s1.message)

    throughput = np.zeros(N)
    throughput[C * H:(C + 1) * H] = 1
    throughput[D * H:(D + 1) * H] = 1
    tol = 1e-7 * max(1.0, abs(s1.fun)) + 1e-6
    s2 = linprog(throughput, A_ub=cost.reshape(1, -1), b_ub=[s1.fun + tol],
                 A_eq=a_eq, b_eq=b_eq, bounds=bounds, method="highs")
    x = s2.x if s2.status == 0 else s1.x

    return RawPlan(
        grid=[float(x[_ix(G, h)]) for h in range(H)],
        solar_used=[float(x[_ix(S, h)]) for h in range(H)],
        net_battery=[float(x[_ix(C, h)] - x[_ix(D, h)]) for h in range(H)],
        energy_after=[float(x[_ix(E, h)]) for h in range(H)],
    )


def to_hourly_plan(raw: RawPlan, hours: list[HourSlot], battery: BatterySpec, cons: HourlyConstraints) -> list[dict]:
    """Round to DECIMALS so the published numbers replay exactly.

    Energies are rounded first (the last one pinned to the initial energy),
    battery amounts are the differences, and grid is re-derived from the
    energy balance.
    """
    e0 = float(battery.initial_energy_kwh)
    energy = [round(min(max(e, cons.reserve_floor[h]), battery.capacity_kwh), DECIMALS)
              for h, e in enumerate(raw.energy_after)]
    energy[-1] = e0
    plan, prev = [], e0
    for h in range(H):
        delta = round(energy[h] - prev, DECIMALS)
        if abs(delta) < EPS / 2:
            delta = 0.0
        solar = round(min(max(raw.solar_used[h], 0.0), cons.effective_solar[h]), DECIMALS)
        solar = min(solar, cons.effective_solar[h])
        grid = hours[h].demand_kwh + delta - solar
        if grid < 0:  # rounding residue: take it from solar rather than go negative
            solar = max(0.0, solar + grid)
            grid = 0.0
        grid = round(grid, DECIMALS)
        plan.append({
            "hour": h,
            "grid_kwh": grid + 0.0,
            "solar_used_kwh": round(solar, DECIMALS) + 0.0,
            "battery_action": "charge" if delta > 0 else "discharge" if delta < 0 else "idle",
            "battery_kwh": abs(delta),
            "battery_energy_after_kwh": energy[h],
        })
        prev = energy[h]
    return plan
