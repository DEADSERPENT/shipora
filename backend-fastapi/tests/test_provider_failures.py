"""Provider failure and small-model behaviour: Gemini quota/timeouts fall back to the built-in rules, and a model that answers
with a promise ("let me check") instead of data never reaches the user as an answer."""
import time
from types import SimpleNamespace

import pytest
from google.api_core import exceptions as gexc

import config
from agents import base, general_agent
from services import gemini_client
from tests.conftest import register

pytestmark = pytest.mark.anyio


def fake_gemini(monkeypatch, exc):
    import google.generativeai as genai
    calls = {"n": 0}

    class Model:
        def __init__(self, *a, **k): ...
        def generate_content(self, *a, **k):
            calls["n"] += 1
            raise exc
    monkeypatch.setattr(config, "GEMINI_API_KEY", "test-key-not-real")
    monkeypatch.setattr(genai, "configure", lambda **k: None)
    monkeypatch.setattr(genai, "GenerativeModel", Model)
    gemini_client.reset()
    return calls


@pytest.mark.parametrize("exc", [
    gexc.ResourceExhausted("429 You exceeded your current quota (free_tier_requests, limit: 15)"),
    gexc.TooManyRequests("429 rate limited"),
    gexc.DeadlineExceeded("504 deadline exceeded"),
    TimeoutError("timed out"),
], ids=["quota-429", "too-many-requests", "deadline", "timeout"])
async def test_gemini_limits_and_timeouts_fall_back_fast_and_open_the_cooldown(client, monkeypatch, exc):
    calls = fake_gemini(monkeypatch, exc)
    t = time.perf_counter()
    r = await client.post("/api/chat", json={"message": "Where is shipment SHP1A2B3C4D5E?", "sessionId": "pf-1"})
    assert r.status_code == 200 and r.json()["source"] == "builtin" and r.json()["reply"]
    assert calls["n"] == 1 and gemini_client.is_unavailable() and time.perf_counter() - t < 5
    again = await client.post("/api/chat", json={"message": "How do I create a shipment?", "sessionId": "pf-1"})
    assert again.status_code == 200 and calls["n"] == 1                       # in cooldown: Gemini is not touched again
    gemini_client.reset()


async def test_a_bad_request_does_not_trip_the_cooldown(client, monkeypatch):
    calls = fake_gemini(monkeypatch, gexc.InvalidArgument("400 bad tool argument"))
    await client.post("/api/chat", json={"message": "Where is shipment SHP1A2B3C4D5E?", "sessionId": "pf-2"})
    assert not gemini_client.is_unavailable()
    gemini_client.reset()


async def test_a_role_switch_during_an_outage_still_answers_from_the_rules(client, monkeypatch):
    fake_gemini(monkeypatch, gexc.ResourceExhausted("429 quota"))
    for kind in ("user", "driver", "admin"):
        _, h = await register(client, kind, f"pf-{kind}@t.test")
        r = await client.post("/api/chat", json={"message": "hello", "sessionId": f"pf-{kind}"}, headers=h)
        assert r.status_code == 200 and r.json()["reply"]
    gemini_client.reset()


# ── small models that promise instead of answering ──────────────────────────
PROMISES = [
    "Sure, I can help with that. To get the summary, I need to call the get_operations_summary tool. Let me do that for you.",
    "I can check the live vehicle activity for you. Let me fetch that information.",
    "Sure, I'll check the operations summary for you. Just a moment.",
    "Let me pull up the latest numbers from the system.",
]


def model_that_says(monkeypatch, text, calls_tool=False):
    import google.generativeai as genai

    class Model:
        def __init__(self, *a, **k): ...
        def generate_content(self, contents, tools=None, **kw):
            part = SimpleNamespace(function_call=SimpleNamespace(name="", args={}))
            return SimpleNamespace(candidates=[SimpleNamespace(content=SimpleNamespace(parts=[part]))], text=text)
    monkeypatch.setattr(config, "GEMINI_API_KEY", "test-key-not-real")
    monkeypatch.setattr(genai, "configure", lambda **k: None)
    monkeypatch.setattr(genai, "GenerativeModel", Model)
    gemini_client.reset()


@pytest.mark.parametrize("promise", PROMISES)
async def test_a_promise_without_a_tool_call_is_never_returned_as_the_answer(monkeypatch, promise):
    model_that_says(monkeypatch, promise)
    tools = [{"name": "get_operations_summary", "description": "x", "input_schema": {"type": "object", "properties": {}}}]
    reply = await base.run_tool_agent("system", tools, {"get_operations_summary": None}, "summarize", [], "neutral")
    assert reply is not None and reply != promise and "let me" not in reply.lower() and "just a moment" not in reply.lower()
    assert "wasn't able" in reply.lower() or "couldn't" in reply.lower()


async def test_a_real_answer_that_merely_uses_similar_words_is_left_alone(monkeypatch):
    text = "Delivery is same-day within Bengaluru. Let me know if you want the fare for a specific route."
    model_that_says(monkeypatch, text)
    tools = [{"name": "search_knowledge_base", "description": "x", "input_schema": {"type": "object", "properties": {}}}]
    assert await base.run_tool_agent("system", tools, {"search_knowledge_base": None}, "how long", [], "neutral") == text


async def test_admin_summary_is_written_from_the_data_when_the_model_only_promises(client, monkeypatch):
    _, _ = await register(client, "admin", "pf-ops@t.test")

    async def promise(*a, **k):
        return PROMISES[2]
    monkeypatch.setattr(general_agent, "run_tool_agent", promise)
    out = await general_agent.handle("Summarize today's operations", [], "neutral", current_user={"id": "2" * 24, "role": "admin"})
    reply = out["reply"]
    assert "just a moment" not in reply.lower() and "shipments" in reply.lower() and "last 7 days" in reply.lower()


async def test_rider_asking_for_vehicles_is_not_given_their_parcels_as_vehicles():
    from agents import roles
    msg = roles.intent_denial({"role": "driver"}, "Which vehicles are live right now?")
    assert msg and "Operations" in msg
