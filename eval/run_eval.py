"""Paraphrase robustness eval: runs the real interpretation pipeline on labelled notes.

Usage:  OPENROUTER_API_KEY=... GROQ_API_KEY=... python -m eval.run_eval [--strong-only] [--pace SECONDS] [--file NAME]
(--pace waits between batches, e.g. to stay inside a free tier's tokens-per-minute limit;
 --file picks a case file in eval/, default paraphrases.jsonl, e.g. adversarial.jsonl)
Notes are sent in batches of 3 (the maximum per scenario), with the cache disabled.
"""
import asyncio
import json
import sys
from pathlib import Path

import httpx

from app import interpreter
from app.schemas import BatterySpec

HERE = Path(__file__).parent


async def main(force_strong: bool, pace: float, case_file: str):
    cases = [json.loads(line) for line in (HERE / case_file).read_text(encoding="utf-8").splitlines() if line.strip()]
    ok, paths = 0, {}
    async with httpx.AsyncClient() as client:
        i = 0
        while i < len(cases):
            cap = cases[i].get("capacity", 200)
            batch = [cases[i]]
            while len(batch) < 3 and i + len(batch) < len(cases) and cases[i + len(batch)].get("capacity", 200) == cap:
                batch.append(cases[i + len(batch)])
            if i and pace:
                await asyncio.sleep(pace)
            i += len(batch)
            battery = BatterySpec(capacity_kwh=cap, initial_energy_kwh=cap / 2, minimum_energy_kwh=0,
                                  max_charge_kwh_per_hour=cap / 4, max_discharge_kwh_per_hour=cap / 4)
            interpreter.cache._d.clear()
            try:
                res = await interpreter.interpret(client, [c["note"] for c in batch], battery, force_strong=force_strong)
            except interpreter.InterpretationUnavailable as e:
                print(f"UNAVAILABLE: {e}")
                continue
            paths[res.path] = paths.get(res.path, 0) + 1
            for c, d in zip(batch, res.directives):
                good = (d.directive_type == c["type"] and list(d.hours) == c["hours"]
                        and (c["value"] is None or (d.value is not None and abs(d.value - c["value"]) < 1e-3)))
                ok += good
                if not good:
                    print(f"MISS [{res.path}] {c.get('id', '')} {c['note']}\n   want {c['type']} {c['hours']} {c['value']}"
                          f"\n   got  {d.directive_type} {list(d.hours)} {d.value}")
    print(f"\n{ok}/{len(cases)} correct; batch paths: {paths}")


if __name__ == "__main__":
    pace = float(sys.argv[sys.argv.index("--pace") + 1]) if "--pace" in sys.argv else 0.0
    case_file = sys.argv[sys.argv.index("--file") + 1] if "--file" in sys.argv else "paraphrases.jsonl"
    asyncio.run(main("--strong-only" in sys.argv, pace, case_file))
