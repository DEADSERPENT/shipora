"""Tools must execute on the application's event loop.

The real MongoDB driver (Motor) is bound to the app's loop. agents/base.py used to run each tool with asyncio.run() on
its worker thread — a *new* loop — which hangs and then raises against a real database ("Task ... attached to a
different loop") and silently degraded every tool-calling turn to the general agent. The in-memory test database has no
loop binding, so nothing caught it; this test asserts the loop directly."""
import asyncio
from types import SimpleNamespace

import pytest

import config
from agents import base

pytestmark = pytest.mark.anyio


class FakeModel:
    """First call asks for the tool, second call answers — the shape agents/base.py expects from Gemini."""
    def __init__(self, *a, **k):
        self.calls = 0

    def generate_content(self, contents, tools=None, **kwargs):
        self.calls += 1
        if tools is not None:
            part = SimpleNamespace(function_call=SimpleNamespace(name="probe", args={"x": 1}))
            return SimpleNamespace(candidates=[SimpleNamespace(content=SimpleNamespace(parts=[part]))])
        return SimpleNamespace(text="grounded answer")


@pytest.fixture
def fake_gemini(monkeypatch):
    import google.generativeai as genai

    monkeypatch.setattr(config, "GEMINI_API_KEY", "test-key-not-real")
    monkeypatch.setattr(genai, "configure", lambda **k: None)
    monkeypatch.setattr(genai, "GenerativeModel", FakeModel)
    # google.protobuf needs a dict-like response; the real genai.protos are used for that
    return genai


TOOL = {"name": "probe", "description": "d", "input_schema": {"type": "object", "properties": {"x": {"type": "integer"}}, "required": []}}


async def test_tool_runs_on_the_app_event_loop_not_a_new_one(fake_gemini):
    app_loop = asyncio.get_running_loop()
    seen = {}

    async def probe(x):
        seen["loop"] = asyncio.get_running_loop()
        await asyncio.sleep(0)                                   # a real suspension point, like a DB round-trip
        return {"ok": True, "x": x}

    reply = await base.run_tool_agent("sys", [TOOL], {"probe": probe}, "hi", [], "neutral")
    assert reply == "grounded answer"
    assert seen["loop"] is app_loop


async def test_a_hung_tool_times_out_and_falls_back_instead_of_blocking_forever(fake_gemini, monkeypatch):
    monkeypatch.setattr(base, "TOOL_TIMEOUT_SECONDS", 0.2)

    async def hangs(x):
        await asyncio.sleep(30)

    assert await base.run_tool_agent("sys", [TOOL], {"probe": hangs}, "hi", [], "neutral") is None


async def test_a_failing_tool_still_degrades_to_none(fake_gemini):
    async def boom(x):
        raise RuntimeError("db down")

    assert await base.run_tool_agent("sys", [TOOL], {"probe": boom}, "hi", [], "neutral") is None
