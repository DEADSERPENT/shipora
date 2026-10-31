"""Tools execute on the application's event loop and a misbehaving tool never hangs or crashes a turn.

The real MongoDB driver (Motor) is bound to the app's loop, so a tool that ran in a different loop would hang and then raise
against a real database ("Task ... attached to a different loop") — the in-memory test database has no loop binding, so the
loop is asserted directly. The model is faked at the HTTP layer (tests/fake_ollama.py); the tool loop is the real one."""
import asyncio

import pytest

from agents import base
from services import ollama_client
from tests import fake_ollama

pytestmark = pytest.mark.anyio

TOOL = {"name": "probe", "description": "d", "input_schema": {"type": "object", "properties": {"x": {"type": "integer"}}, "required": []}}


@pytest.fixture
def model(monkeypatch):
    captured = {}
    fake_ollama.tool_model(monkeypatch, {"tool": "probe", "args": {"x": 1}}, captured, final="grounded answer")
    return captured


async def test_tool_runs_on_the_app_event_loop_not_a_new_one(model):
    app_loop = asyncio.get_running_loop()
    seen = {}

    async def probe(x):
        seen["loop"] = asyncio.get_running_loop()
        await asyncio.sleep(0)                                   # a real suspension point, like a DB round-trip
        return {"ok": True, "x": x}

    reply = await base.run_tool_agent("sys", [TOOL], {"probe": probe}, "hi", [], "neutral")
    assert reply == "grounded answer"
    assert seen["loop"] is app_loop and model["result"] == {"ok": True, "x": 1}   # the model was shown the tool's real result


async def test_a_hung_tool_times_out_and_falls_back_instead_of_blocking_forever(model, monkeypatch):
    monkeypatch.setattr(ollama_client, "TOOL_TIMEOUT_SECONDS", 0.2)

    async def hangs(x):
        await asyncio.sleep(30)

    assert await base.run_tool_agent("sys", [TOOL], {"probe": hangs}, "hi", [], "neutral") is None
    assert not ollama_client.is_unavailable()                    # a slow tool is a database problem, not an Ollama outage


async def test_a_failing_tool_still_degrades_to_none(model):
    async def boom(x):
        raise RuntimeError("db down")

    assert await base.run_tool_agent("sys", [TOOL], {"probe": boom}, "hi", [], "neutral") is None
