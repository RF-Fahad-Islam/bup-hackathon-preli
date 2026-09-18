"""The adversarial note suite (eval/adversarial.jsonl) must itself be spec-valid: no LLM needed."""
import json
from pathlib import Path

import pytest

from app.schemas import DirectiveInterpretation

CASES = [json.loads(line) for line in
         (Path(__file__).parent.parent / "eval" / "adversarial.jsonl").read_text(encoding="utf-8").splitlines()
         if line.strip()]


def test_ids_unique():
    ids = [c["id"] for c in CASES]
    assert len(ids) == len(set(ids))


@pytest.mark.parametrize("case", CASES, ids=[c["id"] for c in CASES])
def test_expected_output_is_spec_valid(case):
    adj = case["expected_structured_adjustment"]
    DirectiveInterpretation(note_index=0, applies=case["type"] != "no_op", directive_type=case["type"],
                            structured_adjustment=adj, explanation="x")
    assert case["hours"] == sorted(set(case["hours"])) and all(0 <= h <= 23 for h in case["hours"])
    if adj is not None:
        assert adj["hours"] == case["hours"]
    if case["type"] == "solar_reduction":
        assert 0 <= adj["factor"] <= 1
    if case["type"] == "minimum_battery_reserve":
        assert 0 <= adj["minimum_energy_kwh"] <= case["capacity"]


def test_paraphrase_sets_agree_and_minimal_pairs_flip():
    groups: dict[str, set] = {}
    for c in CASES:
        if c["group"]:
            groups.setdefault(c["group"], set()).add((c["type"], tuple(c["hours"]), c["value"]))
    for g, outcomes in groups.items():
        assert len(outcomes) == (1 if g.startswith("PS") else 2), g
