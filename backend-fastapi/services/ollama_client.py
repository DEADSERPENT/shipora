"""Local LLM provider (Ollama) — selected with LLM_PROVIDER=ollama.

Why: no cloud dependency or per-call cost, data never leaves the machine (the on-prem / air-gapped deployment story
voice-AI customers ask about), and no 20 s cloud timeouts in the middle of a phone call. Same three jobs Gemini does:

  classify()        intent + sentiment, via Ollama structured output (a JSON schema, so the model cannot return
                    anything but a valid agent name)
  run_tool_agent()  the tool-calling loop used by every specialist agent: one model call that may request a tool,
                    the tool runs on the app's event loop (no worker-thread hop needed — this client is async),
                    one more call without tools to phrase the answer. Same 2-call bound as the Gemini path.
  reply()           plain text, the general agent's second tier

Every function returns None / raises on failure and callers fall back exactly as they do for Gemini
(keyword router -> database fallback -> rule-based knowledge base). Models must support tool calling
(`ollama show <model>` lists "tools" under Capabilities)."""

import json
import logging
from typing import Optional

import httpx

from services import metrics

import config
from services import gemini_client

log = logging.getLogger("shipora.ollama")

_transport: Optional[httpx.AsyncBaseTransport] = None   # tests inject httpx.MockTransport
AGENTS = ["tracking", "complaints", "schedule", "support", "general"]
SENTIMENTS = ["positive", "neutral", "negative"]


def enabled() -> bool:
    return (config.LLM_PROVIDER or "").lower() == "ollama"


def _timeout() -> float:
    override = gemini_client.budget_override.get()   # the voice channel's tighter per-call budget applies to any LLM
    return float(min(override, config.OLLAMA_TIMEOUT_SECONDS) if override else config.OLLAMA_TIMEOUT_SECONDS)


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
                return r.json()["message"]
    except Exception as err:
        metrics.error("ollama", err)
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
        return (first.get("content") or "").strip() or None

    messages.append({k: v for k, v in first.items() if k in ("role", "content", "tool_calls")})
    for call in calls[:2]:                                  # bound the work a (small) model can ask for in one turn
        fn = call["function"]
        name, args = fn["name"], fn.get("arguments") or {}
        if isinstance(args, str):
            args = json.loads(args or "{}")
        if on_stage:
            on_stage("tool_execution", name)
        executor = executors.get(name)
        result = await executor(**args) if executor else {"error": f"unknown tool {name}"}
        messages.append({"role": "tool", "tool_name": name, "content": json.dumps(result, default=str)})
    if on_stage:
        on_stage("generating_response", None)
    final = await chat(messages)                            # no tools -> must answer in text
    return (final.get("content") or "").strip() or None


async def reply(message: str, history: list, system_prompt: str) -> Optional[str]:
    msg = await chat([{"role": "system", "content": system_prompt}, *_history(history), {"role": "user", "content": message}])
    return (msg.get("content") or "").strip() or None
