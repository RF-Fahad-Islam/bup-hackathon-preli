import json

import pytest
from fastapi.testclient import TestClient

from app import interpreter, llm
from app.main import app
from tests.conftest import make_request

NOTES = [
    "Expect an 80% reduction in rooftop solar during the 1-3 PM maintenance window.",
    "The cafeteria menu changes tomorrow.",
]
GOOD = [
    {"note_index": 0, "directive_type": "solar_reduction", "spans": [{"start_hour": 13, "end_hour": 15}],
     "solar_value": 80, "solar_meaning": "reduction", "amount_value": None, "amount_unit": None, "reason": "r"},
    {"note_index": 1, "directive_type": "no_op", "spans": [], "solar_value": None, "solar_meaning": None,
     "amount_value": None, "amount_unit": None, "reason": "r"},
]


@pytest.fixture(autouse=True)
def fresh_cache():
    interpreter.cache._d.clear()


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


def fake_llm(monkeypatch, cheap, strong=None):
    calls = []

    async def read_notes(client, notes, models, timeout, feedback=None):
        tier = "cheap" if models == llm.CHEAP_CHAIN else "strong"
        calls.append(tier)
        out = cheap if tier == "cheap" else strong
        if isinstance(out, Exception):
            raise out
        return out, tier

    monkeypatch.setattr(llm, "read_notes", read_notes)
    return calls


def test_health(client):
    r = client.get("/health")
    assert r.status_code == 200 and r.json() == {"status": "ok"}


def test_full_response_contract(client, monkeypatch):
    calls = fake_llm(monkeypatch, GOOD)
    r = client.post("/optimize-energy", json=make_request(NOTES))
    assert r.status_code == 200, r.text
    body = r.json()
    assert calls == ["cheap"]  # tripwire agreed, no escalation
    assert body["scenario_id"] == "TEST-1"
    assert set(body) == {"scenario_id", "directive_interpretation", "hourly_plan", "total_grid_kwh",
                         "total_cost_bdt", "peak_grid_kwh", "plan_summary"}
    di = body["directive_interpretation"]
    assert di[0]["structured_adjustment"] == {"hours": [13, 14], "factor": 0.2} and di[0]["applies"] is True
    assert di[1] == {**di[1], "applies": False, "directive_type": "no_op", "structured_adjustment": None}
    assert [p["hour"] for p in body["hourly_plan"]] == list(range(24))
    assert body["total_grid_kwh"] == pytest.approx(sum(p["grid_kwh"] for p in body["hourly_plan"]), abs=1e-3)

    fake_llm(monkeypatch, RuntimeError("must not be called"))
    assert client.post("/optimize-energy", json=make_request(NOTES)).status_code == 200  # served from cache


def test_escalates_when_tripwire_disagrees(client, monkeypatch):
    wrong = [dict(GOOD[0], solar_meaning="remaining"), GOOD[1]]  # cheap model misreads 80% reduction
    calls = fake_llm(monkeypatch, wrong, GOOD)
    body = client.post("/optimize-energy", json=make_request(NOTES)).json()
    assert calls == ["cheap", "strong"]
    assert body["directive_interpretation"][0]["structured_adjustment"]["factor"] == 0.2


def test_strong_model_wins_over_tripwire(client, monkeypatch):
    strong = [dict(GOOD[0], solar_value=30), GOOD[1]]
    fake_llm(monkeypatch, llm.LLMError("down"), strong)
    body = client.post("/optimize-energy", json=make_request(NOTES)).json()
    assert body["directive_interpretation"][0]["structured_adjustment"]["factor"] == 0.7


def test_degraded_mode_when_all_llms_fail(client, monkeypatch):
    fake_llm(monkeypatch, llm.LLMError("down"), llm.LLMError("down"))
    r = client.post("/optimize-energy", json=make_request(NOTES))
    assert r.status_code == 200
    assert r.json()["directive_interpretation"][0]["structured_adjustment"] == {"hours": [13, 14], "factor": 0.2}


def test_unconfirmed_cheap_reading_used_when_strong_unavailable(client, monkeypatch):
    note = ["Panel washing from one until three will leave roughly one-fifth of normal solar output."]
    cheap = [dict(GOOD[0], solar_value=20, solar_meaning="remaining")]
    calls = fake_llm(monkeypatch, cheap, llm.LLMError("HTTP 402"))
    r = client.post("/optimize-energy", json=make_request(note))
    assert r.status_code == 200
    assert r.json()["directive_interpretation"][0]["structured_adjustment"] == {"hours": [13, 14], "factor": 0.2}
    assert calls == ["cheap", "strong"]
    client.post("/optimize-energy", json=make_request(note))
    assert calls == ["cheap", "strong", "cheap", "strong"]  # unconfirmed readings are not cached


def test_all_notes_explained_for_every_directive_type(client, monkeypatch):
    readings = [
        dict(GOOD[1], note_index=0, directive_type="no_charge_window", spans=[{"start_hour": 2, "end_hour": 5}]),
        dict(GOOD[1], note_index=1, directive_type="no_discharge_window", spans=[{"start_hour": 18, "end_hour": 20}]),
        dict(GOOD[1], note_index=2, directive_type="minimum_battery_reserve", spans=[{"start_hour": 18, "end_hour": 21}],
             amount_value=50, amount_unit="percent_of_capacity"),
    ]
    fake_llm(monkeypatch, readings, readings)
    r = client.post("/optimize-energy", json=make_request(["a", "b", "c"]))
    assert r.status_code == 200, r.text
    assert all(d["explanation"] for d in r.json()["directive_interpretation"])


def test_502_when_llms_fail_and_tripwire_unsure(client, monkeypatch):
    fake_llm(monkeypatch, llm.LLMError("down"), llm.LLMError("down"))
    r = client.post("/optimize-energy", json=make_request(["Panel washing from one until three will leave roughly one-fifth of normal solar output."]))
    assert r.status_code == 502
    assert "Traceback" not in r.text


def test_guardrail_rejects_invented_directive_then_strong(client, monkeypatch):
    bad = [dict(GOOD[0], directive_type="demand_response"), GOOD[1]]
    calls = fake_llm(monkeypatch, bad, GOOD)
    assert client.post("/optimize-energy", json=make_request(NOTES)).status_code == 200
    assert calls == ["cheap", "strong"]


@pytest.mark.parametrize("mutate", [
    lambda r: r.update(hours=r["hours"][:23]),
    lambda r: r["hours"][5].update(hour=4),
    lambda r: r.update(operator_notes=[]),
    lambda r: r.update(operator_notes=["a", "b", "c", "d"]),
    lambda r: r.update(operator_notes=["  "]),
    lambda r: r["battery"].pop("capacity_kwh"),
    lambda r: r["hours"][0].update(demand_kwh="lots"),
    lambda r: r.pop("scenario_id"),
])
def test_structural_errors_are_400(client, mutate):
    req = make_request(NOTES)
    mutate(req)
    r = client.post("/optimize-energy", json=req)
    assert r.status_code == 400, r.text


def test_malformed_json_is_400(client):
    r = client.post("/optimize-energy", content="{not json", headers={"content-type": "application/json"})
    assert r.status_code == 400


def test_physically_impossible_is_422(client):
    r = client.post("/optimize-energy", json=make_request(NOTES, initial_energy_kwh=10))
    assert r.status_code == 422


def test_unordered_hours_accepted(client, monkeypatch):
    fake_llm(monkeypatch, GOOD)
    req = make_request(NOTES)
    req["hours"].reverse()
    r = client.post("/optimize-energy", json=req)
    assert r.status_code == 200 and [p["hour"] for p in r.json()["hourly_plan"]] == list(range(24))
