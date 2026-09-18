"""Run the public sample pack against a running service and judge each response.

Usage:  python scripts/run_samples.py [BASE_URL] [SAMPLES_PATH]
        (defaults: http://localhost:8080  samples/official)

SAMPLES_PATH is a JSON file or a folder of JSON files. A file is either the
official pack ({"cases": [{"id", "input", "expected_output"}, ...]}) or a single
sample: the request at the top level or under "request"/"input", plus an
optional expected output under "expected"/"expected_output"/"output".
For each sample it checks: interpretation matches expected (type, hours, values),
the plan replays cleanly, and cost is within 0.01 BDT of the expected optimum.
"""
import json
import math
import sys
import time
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app.directives import build_constraints, raw_to_directive  # noqa: E402
from app.replay import ReplayError, replay  # noqa: E402
from app.schemas import OptimizeRequest  # noqa: E402

KEYS_REQ = ("request", "input")
KEYS_EXP = ("expected", "expected_output", "expected_response", "output", "response")


def split(data: dict):
    req = next((data[k] for k in KEYS_REQ if k in data), data)
    exp = next((data[k] for k in KEYS_EXP if k in data), None)
    return req, exp


def load_all(target: Path):
    """Yield (name, request, expected) for every sample under target."""
    files = sorted(target.glob("*.json")) if target.is_dir() else [target]
    for path in files:
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, dict) and isinstance(data.get("cases"), list):
            for case in data["cases"]:
                yield (case.get("id") or case["input"]["scenario_id"], *split(case))
        else:
            yield (path.name, *split(data))


def adjustment_to_raw(di):
    """Turn a published directive back into constraint inputs so Replay can check the plan."""
    t, adj = di["directive_type"], di["structured_adjustment"] or {}
    spans = [{"start_hour": h, "end_hour": h + 1} for h in adj.get("hours", [])]
    raw = {"directive_type": t, "spans": spans}
    if t == "solar_reduction":
        raw.update(solar_value=adj["factor"] * 100, solar_meaning="remaining")
    elif t == "minimum_battery_reserve":
        raw.update(amount_value=adj["minimum_energy_kwh"], amount_unit="kwh")
    elif t == "max_grid_window":
        raw.update(amount_value=adj["max_grid_kwh"], amount_unit="kwh")
    return raw


def same_adjustment(a, b):
    if a is None or b is None:
        return a is b
    if set(a) != set(b):
        return False
    for k in a:
        if isinstance(a[k], list):
            if sorted(a[k]) != sorted(b[k]):
                return False
        elif not math.isclose(float(a[k]), float(b[k]), abs_tol=1e-6):
            return False
    return True


def main():
    base = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8080"
    target = Path(sys.argv[2] if len(sys.argv) > 2 else "samples/official")
    samples = list(load_all(target))
    if not samples:
        sys.exit(f"no samples found in {target}")
    passed, latencies = 0, []
    for name, req, exp in samples:
        t0 = time.monotonic()
        r = httpx.post(f"{base}/optimize-energy", json=req, timeout=35)
        dt = time.monotonic() - t0
        latencies.append(dt)
        problems = []
        if r.status_code != 200:
            problems.append(f"HTTP {r.status_code}: {r.text[:200]}")
        else:
            body = r.json()
            parsed = OptimizeRequest(**req)
            try:
                ds = [raw_to_directive(adjustment_to_raw(d), i, parsed.battery)
                      for i, d in enumerate(body["directive_interpretation"]) if d["applies"]]
                cons = build_constraints(ds, [h.solar_kwh for h in parsed.hours], parsed.battery)
                totals = replay(body["hourly_plan"], parsed.hours, parsed.battery, cons)
                if abs(totals.total_cost_bdt - body["total_cost_bdt"]) > 0.01:
                    problems.append("reported cost != recomputed cost")
            except ReplayError as e:
                problems.append(f"replay: {e}")
            if exp:
                for got, want in zip(body["directive_interpretation"], exp.get("directive_interpretation", [])):
                    if (got["directive_type"], got["applies"]) != (want["directive_type"], want["applies"]) \
                            or not same_adjustment(got["structured_adjustment"], want["structured_adjustment"]):
                        problems.append(f"note {got['note_index']}: got {got['directive_type']} "
                                        f"{got['structured_adjustment']}, want {want['directive_type']} {want['structured_adjustment']}")
                if "total_cost_bdt" in exp and abs(body["total_cost_bdt"] - exp["total_cost_bdt"]) > 0.01:
                    problems.append(f"cost {body['total_cost_bdt']} != reference optimum {exp['total_cost_bdt']}")
        status = "PASS" if not problems else "FAIL"
        passed += not problems
        print(f"{status} {name} ({dt:.2f}s)")
        for p in problems:
            print(f"     - {p}")
    print(f"\n{passed}/{len(samples)} samples passed; max latency {max(latencies):.2f}s")
    sys.exit(0 if passed == len(samples) else 1)


if __name__ == "__main__":
    main()
