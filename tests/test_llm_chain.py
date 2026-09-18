"""Provider chain: fallback order, cool-down on dead accounts, parsing of chain specs."""
import asyncio
import json

import httpx
import pytest

from app import llm

READING = {"readings": [{"note_index": 0, "directive_type": "no_op", "spans": [], "solar_value": None,
                         "solar_meaning": None, "amount_value": None, "amount_unit": None, "reason": "r"}]}


@pytest.fixture(autouse=True)
def keys(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "k1")
    monkeypatch.setenv("GROQ_API_KEY", "k2")
    llm._cooldown_until.clear()


def mock_client(handler):
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def ok_response(request):
    return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps(READING)}}]})


CHAIN = llm.parse_chain("openrouter:a/x|a/y,groq:g/1|g/2")


def test_parse_chain():
    assert CHAIN == (("openrouter", ("a/x", "a/y")), ("groq", ("g/1", "g/2")))
    assert llm.parse_chain("openrouter:deepseek/v4:free") == (("openrouter", ("deepseek/v4:free",)),)
    with pytest.raises(ValueError):
        llm.parse_chain("nosuch:model")


def test_falls_back_to_groq_and_cools_down_dead_provider():
    seen = []

    def handler(request):
        seen.append(request.url.host)
        body = json.loads(request.content)
        if request.url.host == "openrouter.ai":
            assert body["models"] == ["a/x", "a/y"]
            return httpx.Response(402)
        assert "models" not in body
        return ok_response(request)

    async def run():
        async with mock_client(handler) as c:
            first = await llm.read_notes(c, ["n"], CHAIN, 5)
            second = await llm.read_notes(c, ["n"], CHAIN, 5)
        return first, second

    (r1, m1), (_, m2) = asyncio.run(run())
    assert m1 == m2 == "groq:g/1"
    assert seen == ["openrouter.ai", "api.groq.com", "api.groq.com"]  # openrouter skipped while cooling down


def test_tries_next_model_on_same_provider_after_bad_output():
    calls = []

    def handler(request):
        model = json.loads(request.content)["model"]
        calls.append(model)
        if request.url.host == "openrouter.ai":
            return httpx.Response(500)
        if model == "g/1":
            return httpx.Response(200, json={"choices": [{"message": {"content": "not json"}}]})
        return ok_response(request)

    async def run():
        async with mock_client(handler) as c:
            return await llm.read_notes(c, ["n"], CHAIN, 5)

    _, model = asyncio.run(run())
    assert model == "groq:g/2" and calls == ["a/x", "g/1", "g/2"]


def test_all_fail_raises_llm_error():
    async def run():
        async with mock_client(lambda r: httpx.Response(503)) as c:
            await llm.read_notes(c, ["n"], CHAIN, 5)

    with pytest.raises(llm.LLMError):
        asyncio.run(run())


def test_rate_limit_skips_only_that_model_briefly():
    calls = []

    def handler(request):
        model = json.loads(request.content)["model"]
        calls.append(model)
        if request.url.host == "openrouter.ai" or model == "g/1":
            return httpx.Response(429, headers={"retry-after": "3"})
        return ok_response(request)

    async def run():
        async with mock_client(handler) as c:
            await llm.read_notes(c, ["n"], CHAIN, 5)
            await llm.read_notes(c, ["n"], CHAIN, 5)

    asyncio.run(run())
    assert calls == ["a/x", "g/1", "g/2", "g/2"]
    assert "openrouter" not in llm._cooldown_until  # a rate limit never benches the whole provider
