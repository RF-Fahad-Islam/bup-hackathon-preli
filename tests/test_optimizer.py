import itertools

import pytest

from app.directives import build_constraints, raw_to_directive
from app.optimizer import InfeasibleError, solve, to_hourly_plan
from app.replay import replay
from app.schemas import OptimizeRequest
from tests.conftest import make_request


def run(notes_raw, **bat):
    req = OptimizeRequest(**make_request(["x"], **bat))
    ds = [raw_to_directive(r, i, req.battery) for i, r in enumerate(notes_raw)]
    cons = build_constraints(ds, [h.solar_kwh for h in req.hours], req.battery)
    plan = to_hourly_plan(solve(req.hours, req.battery, cons), req.hours, req.battery, cons)
    return plan, replay(plan, req.hours, req.battery, cons), req


def span(s, e):
    return [{"start_hour": s, "end_hour": e}]


def test_baseline_plan_is_valid_and_arbitrages():
    plan, totals, req = run([])
    assert plan[-1]["battery_energy_after_kwh"] == req.battery.initial_energy_kwh
    assert any(p["battery_action"] == "discharge" for p in plan if 17 <= p["hour"] <= 21)
    no_battery_cost = sum(max(0, h.demand_kwh - h.solar_kwh) * h.tariff_bdt_per_kwh for h in req.hours)
    assert totals.total_cost_bdt < no_battery_cost


def test_no_discharge_window_respected_even_in_peak():
    plan, _, _ = run([{"directive_type": "no_discharge_window", "spans": span(17, 20)}])
    assert all(p["battery_action"] != "discharge" for p in plan if p["hour"] in (17, 18, 19))


def test_no_charge_window_respected():
    plan, _, _ = run([{"directive_type": "no_charge_window", "spans": span(0, 6)}])
    assert all(p["battery_action"] != "charge" for p in plan if p["hour"] < 6)


def test_grid_cap_and_reserve_together():
    plan, _, _ = run([
        {"directive_type": "max_grid_window", "spans": span(17, 22), "amount_value": 230, "amount_unit": "kwh"},
        {"directive_type": "minimum_battery_reserve", "spans": span(20, 22), "amount_value": 50, "amount_unit": "percent_of_capacity"},
    ])
    assert all(p["grid_kwh"] <= 230 + 1e-6 for p in plan if 17 <= p["hour"] < 22)
    assert all(p["battery_energy_after_kwh"] >= 200 - 1e-6 for p in plan if p["hour"] in (20, 21))


def test_solar_reduction_limits_solar_used():
    plan, _, req = run([{"directive_type": "solar_reduction", "spans": span(11, 14),
                         "solar_value": 80, "solar_meaning": "reduction"}])
    for p in plan:
        if 11 <= p["hour"] < 14:
            assert p["solar_used_kwh"] <= req.hours[p["hour"]].solar_kwh * 0.2 + 1e-6


def test_infeasible_raises():
    with pytest.raises(InfeasibleError):
        run([{"directive_type": "max_grid_window", "spans": span(0, 24), "amount_value": 10, "amount_unit": "kwh"}])


def brute_force_cost(req, step=10):
    """Exhaustive DP over battery energy on a coarse grid -- an independent optimum check."""
    b = req.battery
    levels = [b.minimum_energy_kwh + i * step for i in range(int((b.capacity_kwh - b.minimum_energy_kwh) / step) + 1)]
    best = {b.initial_energy_kwh: 0.0}
    for h in req.hours:
        nxt = {}
        for e, c in best.items():
            for e2 in levels:
                delta = e2 - e
                if delta > b.max_charge_kwh_per_hour or -delta > b.max_discharge_kwh_per_hour:
                    continue
                grid = max(0.0, h.demand_kwh + delta - h.solar_kwh)
                cost = c + grid * h.tariff_bdt_per_kwh
                if cost < nxt.get(e2, float("inf")):
                    nxt[e2] = cost
        best = nxt
    return best[b.initial_energy_kwh]


def test_lp_matches_exhaustive_optimum():
    _, totals, req = run([])
    assert totals.total_cost_bdt == pytest.approx(brute_force_cost(req), abs=0.01)
