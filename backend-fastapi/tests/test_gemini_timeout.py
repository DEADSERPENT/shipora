"""Gemini calls must fail fast and degrade to the built-in fallbacks.

Regression for a ~29 minute freeze: google-generativeai retries for up to 600 s by default (a bare `timeout=` does not
shorten that), and one voice turn chains several Gemini calls. See services/gemini_client.py."""
import subprocess
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import pytest
from google.api_core import exceptions as gexc

import config
from agents import base, orchestrator
from services import gemini_client, llm

pytestmark = pytest.mark.anyio

BACKEND = Path(__file__).resolve().parent.parent


@pytest.fixture(autouse=True)
def fresh_gemini_state():
    gemini_client.reset()
    yield
    gemini_client.reset()


# ─── the budget ─────────────────────────────────────────────────────────────
def test_request_options_carry_a_hard_budget_not_the_600s_default(monkeypatch):
    monkeypatch.setattr(config, "GEMINI_TIMEOUT_SECONDS", 7.0)
    opts = gemini_client.request_options()
    assert opts["timeout"] == 7.0
    assert opts["retry"] is not None and opts["retry"]._timeout == 7.0               # retries only happen inside the budget



def test_default_budget_is_voice_friendly():
    source = (BACKEND / "config.py").read_text(encoding="utf-8")
    assert 'os.getenv("GEMINI_TIMEOUT_SECONDS", "20")' in source and 'os.getenv("GEMINI_COOLDOWN_SECONDS", "30")' in source


def test_a_dns_failure_fails_in_about_the_budget_with_the_real_library():
    """Real google-generativeai against a host that cannot resolve (the same failure class as the original outage).
    Subprocess so the library's global configuration can't leak into other tests. Without the fix this runs ~10 minutes."""
    code = (
        "import sys, time; sys.path.insert(0, '.')\n"
        "import config; config.GEMINI_TIMEOUT_SECONDS = 3.0\n"
        "import google.generativeai as genai\n"
        "from services import gemini_client\n"
        "genai.configure(api_key='not-a-real-key', client_options={'api_endpoint': 'no-such-host.invalid:443'})\n"
        "m = genai.GenerativeModel('gemini-flash-lite-latest')\n"
        "t = time.perf_counter()\n"
        "try:\n"
        "    m.generate_content('hi', request_options=gemini_client.request_options())\n"
        "except BaseException as e:\n"
        "    print('ELAPSED', round(time.perf_counter() - t, 1), type(e).__name__, gemini_client.is_availability_error(e))\n"
    )
    out = subprocess.run([sys.executable, "-I", "-c", code], cwd=BACKEND, capture_output=True, text=True, timeout=60)
    line = next((l for l in out.stdout.splitlines() if l.startswith("ELAPSED")), None)
    assert line, out.stdout + out.stderr
    _, elapsed, _name, is_availability = line.split()
    assert float(elapsed) < 8 and is_availability == "True"                           # ~3 s budget, and classified as an outage


# ─── the cooldown ───────────────────────────────────────────────────────────
def test_only_outage_type_errors_open_the_cooldown():
    for err in (gexc.ServiceUnavailable("x"), gexc.DeadlineExceeded("x"), gexc.RetryError("x", None), gexc.TooManyRequests("x"), TimeoutError(), ConnectionError()):
        gemini_client.reset()
        gemini_client.note_failure(err)
        assert gemini_client.is_unavailable(), type(err).__name__
    for err in (gexc.InvalidArgument("bad request"), ValueError("bad tool args"), RuntimeError("tool 'x' timed out"), KeyError("agent")):
        gemini_client.reset()
        gemini_client.note_failure(err)
        assert not gemini_client.is_unavailable(), type(err).__name__


def test_cooldown_expires_and_success_clears_it(monkeypatch):
    clock = {"t": 1000.0}
    monkeypatch.setattr(gemini_client.time, "monotonic", lambda: clock["t"])
    monkeypatch.setattr(config, "GEMINI_COOLDOWN_SECONDS", 30.0)
    gemini_client.note_failure(gexc.ServiceUnavailable("x"))
    assert gemini_client.is_unavailable()
    clock["t"] += 29
    assert gemini_client.is_unavailable()
    clock["t"] += 2
    assert not gemini_client.is_unavailable()                                         # expired by itself
    gemini_client.note_failure(gexc.ServiceUnavailable("x"))
    gemini_client.note_success()
    assert not gemini_client.is_unavailable()


# ─── a failing Gemini degrades the whole turn immediately ───────────────────
@pytest.fixture
def down_gemini(monkeypatch):
    """Gemini whose every call fails like an outage; counts how often it is actually called."""
    import google.generativeai as genai

    calls = {"n": 0}

    class Model:
        def __init__(self, *a, **k): ...
        def generate_content(self, *a, **k):
            calls["n"] += 1
            raise gexc.ServiceUnavailable("503 errors resolving generativelanguage.googleapis.com")
        def start_chat(self, *a, **k):
            return SimpleNamespace(send_message=self.generate_content)

    monkeypatch.setattr(config, "GEMINI_API_KEY", "test-key-not-real")
    monkeypatch.setattr(genai, "configure", lambda **k: None)
    monkeypatch.setattr(genai, "GenerativeModel", Model)
    return calls


async def test_one_outage_failure_skips_every_other_gemini_call_in_the_turn(client, down_gemini):
    start = time.perf_counter()
    r = await client.post("/api/chat", json={"message": "Where is shipment SHP1A2B3C4D5E?", "sessionId": "t-down-1"})
    assert r.status_code == 200 and r.json()["source"] == "builtin" and r.json()["reply"]     # the existing rule-based reply
    assert down_gemini["n"] == 1                       # only the classifier was attempted; tool agent, general agent, plain-text tier all skipped
    assert gemini_client.is_unavailable()
    assert time.perf_counter() - start < 5

    r = await client.post("/api/chat", json={"message": "Where is my parcel?", "sessionId": "t-down-1"})
    assert r.status_code == 200 and r.json()["source"] == "builtin" and down_gemini["n"] == 1  # still in cooldown: Gemini not touched at all


async def test_each_gemini_entry_point_is_skipped_during_the_cooldown(down_gemini):
    gemini_client.note_failure(gexc.ServiceUnavailable("x"))
    assert (await orchestrator.classify("where is my parcel", []))["agent"] in {"tracking", "general", "schedule", "support", "complaints"}
    assert await base.run_tool_agent("s", [], {}, "hi", [], "neutral") is None
    assert await llm.get_llm_reply("hi", [], "system") is None
    assert down_gemini["n"] == 0


async def test_a_request_level_error_does_not_disable_gemini_for_everyone(monkeypatch):
    import google.generativeai as genai

    class Model:
        def __init__(self, *a, **k): ...
        def generate_content(self, *a, **k):
            raise gexc.InvalidArgument("400 bad request for this one message")

    monkeypatch.setattr(config, "GEMINI_API_KEY", "test-key-not-real")
    monkeypatch.setattr(genai, "configure", lambda **k: None)
    monkeypatch.setattr(genai, "GenerativeModel", Model)
    assert await base.run_tool_agent("s", [], {}, "hi", [], "neutral") is None
    assert not gemini_client.is_unavailable()


async def test_a_slow_tool_is_not_mistaken_for_a_gemini_outage(monkeypatch):
    import asyncio
    import google.generativeai as genai

    class Model:
        def __init__(self, *a, **k): ...
        def generate_content(self, contents, tools=None, **k):
            part = SimpleNamespace(function_call=SimpleNamespace(name="probe", args={}))
            return SimpleNamespace(candidates=[SimpleNamespace(content=SimpleNamespace(parts=[part]))])

    async def hangs():
        await asyncio.sleep(30)

    monkeypatch.setattr(config, "GEMINI_API_KEY", "test-key-not-real")
    monkeypatch.setattr(base, "TOOL_TIMEOUT_SECONDS", 0.2)
    monkeypatch.setattr(genai, "configure", lambda **k: None)
    monkeypatch.setattr(genai, "GenerativeModel", Model)
    tool = {"name": "probe", "description": "d", "input_schema": {"type": "object", "properties": {}, "required": []}}
    assert await base.run_tool_agent("s", [tool], {"probe": hangs}, "hi", [], "neutral") is None
    assert not gemini_client.is_unavailable()                                          # Gemini answered fine; the database was slow
