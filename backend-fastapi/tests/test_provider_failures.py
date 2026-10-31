"""Provider failure and small-model behaviour: an Ollama outage or timeout falls back to the built-in rules (and opens a cooldown),
and a model that answers with a promise ("let me check") instead of data never reaches the user as an answer."""
import time

import httpx
import pytest

from agents import base, general_agent
from services import ollama_client
from tests import fake_ollama
from tests.conftest import register

pytestmark = pytest.mark.anyio


@pytest.mark.parametrize("fail", [
    lambda mp: fake_ollama.failing(mp, httpx.ConnectError("connection refused")),
    lambda mp: fake_ollama.failing(mp, httpx.ReadTimeout("timed out")),
    lambda mp: fake_ollama.status(mp, 503),
], ids=["down", "timeout", "5xx"])
async def test_an_ollama_outage_falls_back_fast_and_opens_the_cooldown(client, monkeypatch, fail):
    calls = fail(monkeypatch)
    t = time.perf_counter()
    r = await client.post("/api/chat", json={"message": "Where is shipment SHP1A2B3C4D5E?", "sessionId": "pf-1"})
    assert r.status_code == 200 and r.json()["source"] == "builtin" and r.json()["reply"]
    assert calls["n"] == 1 and ollama_client.is_unavailable() and time.perf_counter() - t < 5
    again = await client.post("/api/chat", json={"message": "How do I create a shipment?", "sessionId": "pf-1"})
    assert again.status_code == 200 and calls["n"] == 1                       # in cooldown: Ollama is not touched again


async def test_a_bad_request_does_not_trip_the_cooldown(client, monkeypatch):
    fake_ollama.status(monkeypatch, 404)                                      # e.g. the model name is not installed
    await client.post("/api/chat", json={"message": "Where is shipment SHP1A2B3C4D5E?", "sessionId": "pf-2"})
    assert not ollama_client.is_unavailable()


async def test_a_role_switch_during_an_outage_still_answers_from_the_rules(client, monkeypatch):
    fake_ollama.failing(monkeypatch, httpx.ConnectError("connection refused"))
    for kind in ("user", "driver", "admin"):
        _, h = await register(client, kind, f"pf-{kind}@t.test")
        r = await client.post("/api/chat", json={"message": "hello", "sessionId": f"pf-{kind}"}, headers=h)
        assert r.status_code == 200 and r.json()["reply"]


# ── small models that promise instead of answering ──────────────────────────
PROMISES = [
    "Sure, I can help with that. To get the summary, I need to call the get_operations_summary tool. Let me do that for you.",
    "I can check the live vehicle activity for you. Let me fetch that information.",
    "Sure, I'll check the operations summary for you. Just a moment.",
    "Let me pull up the latest numbers from the system.",
]


@pytest.mark.parametrize("promise", PROMISES)
async def test_a_promise_without_a_tool_call_is_never_returned_as_the_answer(monkeypatch, promise):
    fake_ollama.says(monkeypatch, promise)
    tools = [{"name": "get_operations_summary", "description": "x", "input_schema": {"type": "object", "properties": {}}}]
    reply = await base.run_tool_agent("system", tools, {"get_operations_summary": None}, "summarize", [], "neutral")
    assert reply is not None and reply != promise and "let me" not in reply.lower() and "just a moment" not in reply.lower()
    assert "wasn't able" in reply.lower() or "couldn't" in reply.lower()


async def test_a_real_answer_that_merely_uses_similar_words_is_left_alone(monkeypatch):
    text = "Delivery is same-day within Bengaluru. Let me know if you want the fare for a specific route."
    fake_ollama.says(monkeypatch, text)
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


@pytest.mark.parametrize("promise", [
    "Could you please wait while I look up the status of your parcel with tracking number SHP82290370.",
    "Please wait a moment while I check.",
])
def test_please_wait_is_a_promise_not_an_answer(promise):
    assert base.is_empty_promise(promise)


async def test_yes_after_did_you_mean_looks_up_the_suggested_parcel(client, monkeypatch):
    from agents import orchestrator
    assert orchestrator.resolve_did_you_mean("yes", [{"role": "assistant", "content": "I couldn't find SHPA2290370. Did you mean SHP82290370? Say yes and I'll check it."}]) == "Where is SHP82290370?"
    assert orchestrator.resolve_did_you_mean("yes", [{"role": "assistant", "content": "Anything else?"}]) == "yes"
    assert orchestrator.resolve_did_you_mean("no thanks", [{"role": "assistant", "content": "Did you mean SHP82290370?"}]) == "no thanks"
    assert orchestrator.resolve_did_you_mean("yes", []) == "yes"
