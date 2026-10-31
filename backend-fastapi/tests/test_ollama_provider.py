"""Local-LLM provider (LLM_PROVIDER=ollama), exercised against a fake Ollama so it runs anywhere. The real GPU run is
a live Gemini-vs-Ollama run with LLM_PROVIDER=ollama."""
import json

import httpx
import pytest

import config
from agents import orchestrator
from services import ollama_client
from tests.test_voice_sandwich import _shipment
from tests.conftest import register
from models.customer import Customer

pytestmark = pytest.mark.anyio


@pytest.fixture(autouse=True)
def use_ollama(monkeypatch):
    monkeypatch.setattr(config, "LLM_PROVIDER", "ollama")
    yield
    ollama_client._transport = None


class FakeOllama:
    def __init__(self, script):
        self.script, self.requests = list(script), []
        ollama_client._transport = httpx.MockTransport(self.handle)

    def handle(self, request):
        body = json.loads(request.content)
        self.requests.append(body)
        step = self.script.pop(0)
        if isinstance(step, int):
            return httpx.Response(step)
        return httpx.Response(200, json={"message": step})


async def test_classifier_uses_a_json_schema_and_returns_a_valid_agent():
    fake = FakeOllama([{"role": "assistant", "content": '{"agent": "complaints", "sentiment": "negative"}'}])
    assert await orchestrator.classify("my parcel is broken", []) == {"agent": "complaints", "sentiment": "negative"}
    assert fake.requests[0]["format"]["properties"]["agent"]["enum"] == ["tracking", "complaints", "schedule", "support", "general"]
    assert fake.requests[0]["options"]["temperature"] == 0 and fake.requests[0]["stream"] is False


async def test_bad_classifier_output_falls_back_to_keywords():
    FakeOllama([{"role": "assistant", "content": '{"agent": "banana", "sentiment": "neutral"}'}])
    assert (await orchestrator.classify("where is my parcel", []))["agent"] == "tracking"
    FakeOllama([500])
    assert (await orchestrator.classify("contact details for customer care", []))["agent"] == "support"


async def test_tool_loop_runs_the_tool_and_answers_from_its_result(client):
    await register(client, "user", "o@x.test")
    cust = await Customer.find_one(Customer.email == "o@x.test")
    await _shipment(cust.id, "SHP1A2B3C4D5E", "IN_TRANSIT")
    fake = FakeOllama([
        {"role": "assistant", "content": '{"agent": "tracking", "sentiment": "neutral"}'},                       # classifier
        {"role": "assistant", "content": "", "tool_calls": [{"function": {"name": "get_shipment_status", "arguments": {"trackingNumber": "SHP1A2B3C4D5E"}}}]},
        {"role": "assistant", "content": "Your parcel is in transit."},
    ])
    stages = []
    result = await orchestrator.route_and_reply("where is SHP1A2B3C4D5E", [], None, on_stage=lambda s, d=None: stages.append(s))
    assert result["reply"] == "Your parcel is in transit." and result["agent"] == "tracking" and result["source"] == "ai"
    assert len(fake.requests) == 3                                     # classifier + tool request + final answer
    final_call = fake.requests[-1]
    tool_msg = next(m for m in final_call["messages"] if m["role"] == "tool")
    assert json.loads(tool_msg["content"])["status"] == "IN_TRANSIT"   # the model was shown the database's answer
    assert "tools" not in final_call                                   # the second call must answer in text
    assert "tool_execution" in stages and "generating_response" in stages


async def test_ollama_down_still_answers_tracking_from_the_database(client):
    await register(client, "user", "o2@x.test")
    cust = await Customer.find_one(Customer.email == "o2@x.test")
    await _shipment(cust.id, "SHP1A2B3C4D5E", "OUT_FOR_DELIVERY")
    ollama_client._transport = httpx.MockTransport(lambda r: (_ for _ in ()).throw(httpx.ConnectError("down")))
    result = await orchestrator.route_and_reply("where is SHP1A2B3C4D5E", [], None)
    assert result["source"] == "builtin" and "out for delivery" in result["reply"]


async def test_qwen3_thinking_is_switched_off(monkeypatch):
    monkeypatch.setattr(config, "OLLAMA_MODEL", "qwen3:8b")
    fake = FakeOllama([{"role": "assistant", "content": "hi"}])
    await ollama_client.chat([{"role": "user", "content": "x"}])
    assert fake.requests[0]["think"] is False
    monkeypatch.setattr(config, "OLLAMA_MODEL", "qwen2.5:3b")
    fake = FakeOllama([{"role": "assistant", "content": "hi"}])
    await ollama_client.chat([{"role": "user", "content": "x"}])
    assert "think" not in fake.requests[0]
