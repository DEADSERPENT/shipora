"""Per-turn instrumentation: stage timings, provider call counts and provider errors are recorded with each chat turn."""
import pytest
import httpx

from models.chat_analytics import ChatAnalytics
from services import metrics
from tests import fake_ollama

pytestmark = pytest.mark.anyio


def test_metrics_accumulate_counts_timings_and_errors_per_turn():
    m = metrics.start()
    metrics.count("tool_calls")
    metrics.count("tool_calls")
    with metrics.timed("tool_ms"):
        pass
    metrics.error("ollama", httpx.ReadTimeout("timed out"))
    snap = m.snapshot()
    assert snap["counts"]["tool_calls"] == 2 and "tool_ms" in snap["ms"]
    assert len(snap["errors"]) == 1 and snap["errors"][0]["provider"] == "ollama" and snap["errors"][0]["type"] == "ReadTimeout"
    assert "timed out" in snap["errors"][0]["message"]


def test_recording_outside_a_turn_is_a_harmless_no_op():
    metrics._current.set(None)
    metrics.count("x")
    metrics.add_ms("y", 1)
    metrics.error("z", ValueError("v"))


async def test_a_text_turn_stores_its_stage_timings(client, monkeypatch):
    fake_ollama.says(monkeypatch, "Open the Create Shipment page and fill in the recipient.")
    r = await client.post("/api/chat", json={"message": "How do I create a shipment?", "sessionId": "im-1"})
    assert r.status_code == 200
    row = await ChatAnalytics.find_one(ChatAnalytics.sessionId == "im-1")
    assert {"classify_ms", "db_history_ms"} <= set(row.metrics["ms"])
    assert row.metrics["errors"] == []


async def test_an_ollama_outage_is_counted_and_recorded(client, monkeypatch):
    fake_ollama.failing(monkeypatch, httpx.ConnectError("connection refused"))
    r = await client.post("/api/chat", json={"message": "Where is shipment SHP1A2B3C4D5E?", "sessionId": "im-2"})
    assert r.status_code == 200 and r.json()["source"] == "builtin"
    row = await ChatAnalytics.find_one(ChatAnalytics.sessionId == "im-2")
    assert row.metrics["counts"]["ollama_calls"] == 1
    assert row.metrics["errors"][0]["provider"] == "ollama" and row.metrics["errors"][0]["type"] == "ConnectError"


async def test_tool_time_and_call_counts_are_recorded(client, monkeypatch):
    from tests.test_tracking_agent_my_shipments import make_shipment
    from tests.conftest import register

    u, h = await register(client, "user", "im-u@t.test")
    tn = await make_shipment(client, h, "x")
    fake_ollama.tool_model(monkeypatch, {"tool": "get_shipment_status", "args": {"trackingNumber": tn}}, {}, final="It is on its way.")
    r = await client.post("/api/chat", json={"message": f"Where is {tn}?", "sessionId": "im-3"}, headers=h)
    assert r.status_code == 200
    row = await ChatAnalytics.find_one(ChatAnalytics.sessionId == "im-3")
    assert row.metrics["counts"]["tool_calls"] == 1 and row.metrics["counts"]["ollama_calls"] >= 2 and "tool_ms" in row.metrics["ms"]
