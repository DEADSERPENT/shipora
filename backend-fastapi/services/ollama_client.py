"""The LLM provider: a local Ollama model (the only one Shipora uses).

Why: no cloud dependency or per-call cost, data never leaves the machine (the on-prem / air-gapped deployment story
voice-AI customers ask about), and no 20 s cloud timeouts in the middle of a phone call. Three jobs:

  classify()        intent + sentiment, via Ollama structured output (a JSON schema, so the model cannot return
                    anything but a valid agent name)
  run_tool_agent()  the tool-calling loop used by every specialist agent: one model call that may request a tool,
                    the tool runs on the app's event loop (no worker-thread hop needed — this client is async),
                    one more call without tools to phrase the answer. Bounded at two model calls per turn.
  reply()           plain text, the general agent's second tier

Every function returns None / raises on failure and callers fall back
(keyword router -> database fallback -> rule-based knowledge base). After an outage-type failure the provider is skipped for
OLLAMA_COOLDOWN_SECONDS (is_unavailable()) so one dead server does not make every remaining call in a turn wait out its timeout. Models must support tool calling
(`ollama show <model>` lists "tools" under Capabilities)."""

import asyncio
import contextvars
import json
import logging
import threading
import time
from typing import Optional

import httpx

import config
from services import metrics

log = logging.getLogger("shipora.ollama")

_transport: Optional[httpx.AsyncBaseTransport] = None   # tests inject httpx.MockTransport
AGENTS = ["tracking", "complaints", "schedule", "support", "general"]
SENTIMENTS = ["positive", "neutral", "negative"]
TOOL_TIMEOUT_SECONDS = 30   # a tool (one DB query) that hangs must not hang the turn


def leaked_tool_json(text: str) -> bool:
    """Small models sometimes put a tool call (or the tool schema itself) in the reply text instead of the tool_calls field.
    That is JSON for the machine, never an answer for a person."""
    t = (text or "").strip()
    if not t or t[0] not in "[{":
        return False
    try:
        data = json.loads(t)
    except ValueError:
        return False
    items = data if isinstance(data, list) else [data]
    return bool(items) and all(isinstance(i, dict) and ("function" in i or "arguments" in i or ("name" in i and "parameters" in i)) for i in items)


def degenerate(text: str) -> bool:
    """A small model asked for a language it barely knows (e.g. Kannada on a 3B model) can fall into a loop that repeats the same
    few words until the token limit. That is noise, not an answer."""
    words = (text or "").split()
    if len(words) < 24:
        return False
    if len(set(words)) / len(words) < 0.35:
        return True
    grams = [" ".join(words[i:i + 3]) for i in range(len(words) - 2)]
    return max(grams.count(g) for g in set(grams)) >= 5


def _answer(msg: dict) -> Optional[str]:
    text = (msg.get("content") or "").strip()
    if leaked_tool_json(text):
        log.warning("model returned a tool call as text; discarding", extra={"event": "ollama_leaked_tool_json"})
        return None                      # callers fall back to the database / rules instead of showing JSON to the user
    if degenerate(text):
        log.warning("model output is a repetition loop; discarding", extra={"event": "ollama_degenerate_output"})
        return None
    return text or None


# The voice channel sets a tighter per-call budget (voice/pipeline.py); None = OLLAMA_TIMEOUT_SECONDS.
budget_override: contextvars.ContextVar = contextvars.ContextVar("ollama_budget", default=None)
_lock = threading.Lock()
_down_until = 0.0   # time.monotonic() deadline; 0 = healthy


def _timeout() -> float:
    override = budget_override.get()
    return float(min(override, config.OLLAMA_TIMEOUT_SECONDS) if override else config.OLLAMA_TIMEOUT_SECONDS)


def is_unavailable() -> bool:
    return time.monotonic() < _down_until


def is_availability_error(err: BaseException) -> bool:
    """Server down, unreachable, too slow or failing (5xx) — as opposed to a request-specific problem (a 4xx)."""
    if isinstance(err, httpx.HTTPStatusError):
        return err.response.status_code >= 500
    return isinstance(err, (httpx.TransportError, TimeoutError, ConnectionError))


def note_failure(err: BaseException) -> None:
    global _down_until
    if not is_availability_error(err):
        return
    with _lock:
        already = time.monotonic() < _down_until
        _down_until = time.monotonic() + float(config.OLLAMA_COOLDOWN_SECONDS)
    if not already:
        log.warning("Ollama unavailable; using fallbacks", extra={"event": "ollama_unavailable", "error_type": type(err).__name__, "cooldown_seconds": config.OLLAMA_COOLDOWN_SECONDS})


def note_success() -> None:
    global _down_until
    _down_until = 0.0


def reset() -> None:
    note_success()


async def chat(messages: list, tools: Optional[list] = None, fmt: Optional[dict] = None, model: Optional[str] = None,
               max_tokens: int = 400) -> dict:
    """One /api/chat call; returns the `message` object. Raises httpx errors on failure."""
    model = model or config.OLLAMA_MODEL
    body = {"model": model, "messages": messages, "stream": False, "keep_alive": config.OLLAMA_KEEP_ALIVE,
            "options": {"temperature": 0, "num_predict": max_tokens, "num_ctx": config.OLLAMA_NUM_CTX}}
    if "qwen3" in model:
        body["think"] = False          # qwen3 "thinks" for seconds by default; a phone call can't wait for it
    if tools:
        body["tools"] = [{"type": "function", "function": {"name": t["name"], "description": t["description"], "parameters": t["input_schema"]}}
                         for t in tools]
    if fmt:
        body["format"] = fmt
    metrics.count("ollama_calls")
    try:
        with metrics.timed("ollama_ms"):
            async with httpx.AsyncClient(transport=_transport, base_url=config.OLLAMA_URL, timeout=_timeout()) as http:
                r = await http.post("/api/chat", json=body)
                r.raise_for_status()
                message = r.json()["message"]
        note_success()
        return message
    except Exception as err:
        metrics.error("ollama", err)
        note_failure(err)
        raise


def _history(history: list, n: int = 10) -> list:
    return [{"role": "user" if h["role"] == "user" else "assistant", "content": h["content"]} for h in history[-n:]]


async def classify(message: str, history: list, tool_schema: dict) -> dict:
    schema = {"type": "object", "properties": {"agent": {"type": "string", "enum": AGENTS}, "sentiment": {"type": "string", "enum": SENTIMENTS}},
              "required": ["agent", "sentiment"]}
    system = (tool_schema["description"] + "\n\nAgents: " + tool_schema["input_schema"]["properties"]["agent"]["description"]
              + "\n\nReply with JSON only: {\"agent\": ..., \"sentiment\": ...}.")
    msg = await chat([{"role": "system", "content": system}, *_history(history, 4), {"role": "user", "content": message}],
                     fmt=schema, model=config.OLLAMA_CLASSIFIER_MODEL or config.OLLAMA_MODEL, max_tokens=60)
    out = json.loads(msg["content"])
    if out.get("agent") not in AGENTS or out.get("sentiment") not in SENTIMENTS:
        raise ValueError(f"classifier returned an out-of-schema answer: {out}")
    return {"agent": out["agent"], "sentiment": out["sentiment"]}


async def run_tool_agent(system_prompt: str, tools: list, executors: dict, message: str, history: list, sentiment: str,
                         on_stage=None) -> Optional[str]:
    system = system_prompt + ("\n\nThe user seems frustrated — briefly acknowledge that before answering." if sentiment == "negative" else "")
    messages = [{"role": "system", "content": system}, *_history(history), {"role": "user", "content": message}]
    first = await chat(messages, tools=tools)
    calls = first.get("tool_calls") or []
    if not calls:
        if on_stage:
            on_stage("generating_response", None)
        return _answer(first)

    messages.append({k: v for k, v in first.items() if k in ("role", "content", "tool_calls")})
    for call in calls[:2]:                                  # bound the work a (small) model can ask for in one turn
        fn = call["function"]
        name, args = fn["name"], fn.get("arguments") or {}
        if isinstance(args, str):
            try:
                args = json.loads(args or "{}")
            except ValueError:
                args = None
        if on_stage:
            on_stage("tool_execution", name)
        executor = executors.get(name)
        if not executor:                    # a tool this role was never offered (or invented): nothing runs and the turn falls back
            raise RuntimeError(f"model requested unavailable tool {name!r}")
        elif not isinstance(args, dict):
            result = {"error": f"invalid arguments for tool {name}"}
        else:
            try:
                result = await asyncio.wait_for(executor(**args), TOOL_TIMEOUT_SECONDS)
            except TypeError:               # arguments the tool does not take (a small model invents parameter names)
                result = {"error": f"invalid arguments for tool {name}"}
            except asyncio.TimeoutError as err:
                raise RuntimeError(f"tool {name!r} timed out after {TOOL_TIMEOUT_SECONDS}s") from err
        messages.append({"role": "tool", "tool_name": name, "content": json.dumps(result, default=str)})
    if on_stage:
        on_stage("generating_response", None)
    final = await chat(messages)                            # no tools -> must answer in text
    return _answer(final)


async def reply(message: str, history: list, system_prompt: str) -> Optional[str]:
    msg = await chat([{"role": "system", "content": system_prompt}, *_history(history), {"role": "user", "content": message}])
    return (msg.get("content") or "").strip() or None


COMPLAINT_CATEGORIES = ["delayed_delivery", "lost_parcel", "damaged_parcel", "wrong_address", "agent_behaviour", "failed_delivery", "other"]


async def extract_complaint(message: str, history: list) -> Optional[dict]:
    """Structured-output read of a customer message that reports a delivery problem. A small model often chats about the problem
    instead of calling draft_complaint; a JSON schema cannot be answered with chat. Returns {subject, category, description,
    trackingNumber} or None when the message is not a report. Everything is taken from the customer's own words."""
    schema = {"type": "object", "properties": {
        "is_report": {"type": "boolean"}, "subject": {"type": "string"}, "category": {"type": "string", "enum": COMPLAINT_CATEGORIES},
        "description": {"type": "string"}, "trackingNumber": {"type": "string"}},
        "required": ["is_report", "subject", "category", "description"]}
    system = ("Extract a delivery-issue report from the customer's message. is_report is true only if they are reporting something that "
              "went wrong with a delivery (damaged, lost, late, wrong address, rude agent, failed delivery). subject: under 8 words. "
              "description: what they said happened, in their words, nothing invented. trackingNumber: only if they wrote one, else empty. "
              "Reply with JSON only.")
    msg = await chat([{"role": "system", "content": system}, *_history(history, 4), {"role": "user", "content": message}],
                     fmt=schema, model=config.OLLAMA_CLASSIFIER_MODEL or config.OLLAMA_MODEL, max_tokens=200)
    out = json.loads(msg["content"])
    if not out.get("is_report") or out.get("category") not in COMPLAINT_CATEGORIES or not (out.get("subject") or "").strip() or not (out.get("description") or "").strip():
        return None
    return {"subject": out["subject"].strip()[:120], "category": out["category"], "description": out["description"].strip()[:1000],
            "trackingNumber": (out.get("trackingNumber") or "").strip() or None}
