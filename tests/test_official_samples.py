"""Official public samples, offline: expected directives -> LP -> Replay -> reference cost.

Also checks the Tripwire never contradicts the reference interpretation.
"""
import json
from pathlib import Path

import pytest

from app.directives import Directive, build_constraints
from app.optimizer import solve, to_hourly_plan
from app.replay import replay
from app.schemas import OptimizeRequest
from app.summary import explain, plan_summary
from app.tripwire import read_note
from app.directives import raw_to_directive

PACK = Path(__file__).resolve().parent.parent / "samples" / "official" / "public_sample_cases.json"
CASES = json.loads(PACK.read_text(encoding="utf-8"))["cases"] if PACK.exists() else []

VALUE_KEY = {"solar_reduction": "factor", "minimum_battery_reserve": "minimum_energy_kwh", "max_grid_window": "max_grid_kwh"}


def expected_directives(case):
    out = []
    for di in case["expected_output"]["directive_interpretation"]:
        t, adj = di["directive_type"], di["structured_adjustment"]
        if t == "no_op":
            out.append(Directive(di["note_index"], t))
        else:
            out.append(Directive(di["note_index"], t, tuple(adj["hours"]), adj.get(VALUE_KEY.get(t, ""), None)))
    return out


@pytest.mark.skipif(not CASES, reason="official sample pack not present")
@pytest.mark.parametrize("case", CASES, ids=[c["id"] for c in CASES])
def test_reference_cost_reached(case):
    req = OptimizeRequest(**case["input"])
    ds = expected_directives(case)
    cons = build_constraints(ds, [h.solar_kwh for h in req.hours], req.battery)
    plan = to_hourly_plan(solve(req.hours, req.battery, cons), req.hours, req.battery, cons)
    totals = replay(plan, req.hours, req.battery, cons)
    assert totals.total_cost_bdt == pytest.approx(case["expected_output"]["total_cost_bdt"], abs=0.01)
    for d in ds:
        assert explain(d)
    assert plan_summary(plan, totals, ds)


@pytest.mark.skipif(not CASES, reason="official sample pack not present")
@pytest.mark.parametrize("case", CASES, ids=[c["id"] for c in CASES])
def test_tripwire_never_contradicts_reference(case):
    req = OptimizeRequest(**case["input"])
    for note, want in zip(case["input"]["operator_notes"], expected_directives(case)):
        raw = read_note(note)
        if raw is None:
            continue  # abstaining is allowed: it just escalates
        got = raw_to_directive(raw, want.note_index, req.battery)
        assert got.same_meaning(want), note
