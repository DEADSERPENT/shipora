"""Per-turn instrumentation: stage timings, provider call counts and provider errors are recorded with each chat turn."""
import pytest
from google.api_core import exceptions as gexc

from models.chat_analytics import ChatAnalytics
from services import gemini_client, metrics
from tests.test_provider_failures import fake_gemini

pytestmark = pytest.mark.anyio


def test_metrics_accumulate_counts_timings_and_errors_per_turn():
    m = metrics.start()
    metrics.count("tool_calls")
    metrics.count("tool_calls")
    with metrics.timed("tool_ms"):
        pass
    metrics.error("gemini", gexc.ResourceExhausted("429 quota"))
    snap = m.snapshot()
    assert snap["counts"]["tool_calls"] == 2 and "tool_ms" in snap["ms"]
    assert len(snap["errors"]) == 1 and snap["errors"][0]["provider"] == "gemini" and snap["errors"][0]["type"] == "ResourceExhausted"
    assert "quota" in snap["errors"][0]["message"]


def test_recording_outside_a_turn_is_a_harmless_no_op():
    metrics._current.set(None)
    metrics.count("x")
    metrics.add_ms("y", 1)
    metrics.error("z", ValueError("v"))


async def test_a_text_turn_stores_its_stage_timings(client):
    r = await client.post("/api/chat", json={"message": "How do I create a shipment?", "sessionId": "im-1"})
    assert r.status_code == 200
    row = await ChatAnalytics.find_one(ChatAnalytics.sessionId == "im-1")
    assert {"classify_ms", "db_history_ms"} <= set(row.metrics["ms"])
    assert row.metrics["errors"] == []


async def test_a_gemini_quota_error_is_counted_and_recorded(client, monkeypatch):
    fake_gemini(monkeypatch, gexc.ResourceExhausted("429 You exceeded your current quota"))
    r = await client.post("/api/chat", json={"message": "Where is shipment SHP1A2B3C4D5E?", "sessionId": "im-2"})
    assert r.status_code == 200 and r.json()["source"] == "builtin"
    row = await ChatAnalytics.find_one(ChatAnalytics.sessionId == "im-2")
    assert row.metrics["counts"]["gemini_calls"] == 1 and row.metrics["counts"]["gemini_rate_limited"] == 1
    assert row.metrics["errors"][0]["provider"] == "gemini" and row.metrics["errors"][0]["type"] == "ResourceExhausted"
    gemini_client.reset()


async def test_tool_time_and_call_counts_are_recorded(client, monkeypatch):
    import google.generativeai as genai
    from types import SimpleNamespace
    import config
    from tests.test_tracking_agent_my_shipments import make_shipment
    from tests.conftest import register

    u, h = await register(client, "user", "im-u@t.test")
    tn = await make_shipment(client, h, "x")

    class Model:
        def __init__(self, *a, **k): ...
        def generate_content(self, contents, tools=None, **kw):
            if tools is not None and not any("get_shipment_status" in str(p) for p in contents[-1:]):
                part = SimpleNamespace(function_call=SimpleNamespace(name="get_shipment_status", args={"trackingNumber": tn}))
                return SimpleNamespace(candidates=[SimpleNamespace(content=SimpleNamespace(parts=[part]))])
            return SimpleNamespace(text="It is on its way.")
    monkeypatch.setattr(config, "GEMINI_API_KEY", "test-key-not-real")
    monkeypatch.setattr(genai, "configure", lambda **k: None)
    monkeypatch.setattr(genai, "GenerativeModel", Model)
    monkeypatch.setattr(genai.protos, "FunctionResponse", lambda name, response: SimpleNamespace(name=name, response=response))
    monkeypatch.setattr(genai.protos, "Part", lambda function_response=None, **k: SimpleNamespace(function_response=function_response))
    gemini_client.reset()
    r = await client.post("/api/chat", json={"message": f"Where is {tn}?", "sessionId": "im-3"}, headers=h)
    assert r.status_code == 200
    row = await ChatAnalytics.find_one(ChatAnalytics.sessionId == "im-3")
    assert row.metrics["counts"]["tool_calls"] == 1 and row.metrics["counts"]["gemini_calls"] >= 2 and "tool_ms" in row.metrics["ms"]
