"""Random scenarios + random directives: every feasible solve must pass Replay."""
import random

from app.directives import build_constraints, raw_to_directive
from app.optimizer import InfeasibleError, solve, to_hourly_plan
from app.replay import replay
from app.schemas import OptimizeRequest

TYPES = ["solar_reduction", "minimum_battery_reserve", "no_charge_window", "no_discharge_window", "max_grid_window"]


def random_case(rng):
    cap = round(rng.uniform(50, 800), 3)
    mn = round(rng.uniform(0, cap * 0.3), 3)
    req = OptimizeRequest(
        scenario_id="F",
        operator_notes=["x"],
        hours=[{"hour": h, "demand_kwh": round(rng.uniform(20, 400), 3),
                "solar_kwh": round(max(0, rng.gauss(150, 80)) if 6 <= h <= 18 else 0, 3),
                "tariff_bdt_per_kwh": round(rng.uniform(3, 18), 2)} for h in range(24)],
        battery={"capacity_kwh": cap, "initial_energy_kwh": round(rng.uniform(mn, cap), 3), "minimum_energy_kwh": mn,
                 "max_charge_kwh_per_hour": round(rng.uniform(10, cap / 2), 3),
                 "max_discharge_kwh_per_hour": round(rng.uniform(10, cap / 2), 3)},
    )
    raws = []
    for _ in range(rng.randint(0, 3)):
        t = rng.choice(TYPES)
        s = rng.randint(0, 23)
        raw = {"directive_type": t, "spans": [{"start_hour": s, "end_hour": rng.randint(1, 24)}]}
        if raw["spans"][0]["end_hour"] == s:
            continue
        if t == "solar_reduction":
            raw.update(solar_value=rng.choice([0, 10, 20, 33.3333, 50, 75, 80]), solar_meaning=rng.choice(["remaining", "reduction"]))
        elif t == "minimum_battery_reserve":
            raw.update(amount_value=rng.choice([10, 25, 50, 60]), amount_unit="percent_of_capacity")
        elif t == "max_grid_window":
            raw.update(amount_value=round(rng.uniform(100, 450), 2), amount_unit="kwh")
        raws.append(raw)
    return req, [raw_to_directive(r, i, req.battery) for i, r in enumerate(raws)]


def test_fuzz_replay_always_passes():
    rng = random.Random(2026)
    solved = 0
    for _ in range(400):
        req, ds = random_case(rng)
        cons = build_constraints(ds, [h.solar_kwh for h in req.hours], req.battery)
        try:
            raw = solve(req.hours, req.battery, cons)
        except InfeasibleError:
            continue
        plan = to_hourly_plan(raw, req.hours, req.battery, cons)
        replay(plan, req.hours, req.battery, cons)  # raises on any violation
        solved += 1
    assert solved > 150
