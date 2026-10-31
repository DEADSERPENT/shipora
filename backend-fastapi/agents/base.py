"""Shared tool-calling loop for the specialist agents, run against the local Ollama model (services/ollama_client.py,
the only LLM Shipora uses).

Per turn: one model call that may request a tool, the tool (one database query) runs, then one more call WITHOUT tools to phrase the
answer — at most two model calls and two tool calls. If the model answers directly without a tool, its text is returned as-is.
Any failure returns None and the orchestrator falls through to the database fallback / general agent / rule-based replies.

Callers may pass an `on_stage(stage, detail=None)` callback to report progress (used by voice/pipeline.py to push Socket.IO
events during a voice turn — see sockets.py). It is a plain synchronous function; it is called on the event loop.
"""

import logging
import re
from typing import Callable, Optional

from services import metrics, ollama_client
log = logging.getLogger("shipora.agents")

OnStage = Optional[Callable[[str, Optional[str]], None]]

# A small model sometimes answers "let me check that for you" and never calls the tool. Such text promises data that is not
# coming, so it is never shown as an answer when no tool ran in the turn.
_PROMISE = re.compile(
    r"\b(?:let me|i'?ll|i will|i can|i need to|allow me to|give me|hold on)\b[^.!?\n]{0,60}\b(?:check|fetch|pull up|look up|lookup|retrieve|get that|get the|call the|get_\w+|run)\b"
    r"|\bjust a moment\b|\bone moment\b|\bplease wait\b|\bwait (?:while|a moment|a sec\w*)\b", re.I)
PROMISE_REPLACEMENT = "I wasn't able to fetch that just now. Please try again in a moment, or ask in a different way."


def is_empty_promise(text: Optional[str]) -> bool:
    return bool(text and _PROMISE.search(text))


async def run_tool_agent(
    system_prompt: str,
    tools: list,
    executors: dict,
    message: str,
    history: list,
    sentiment: str,
    on_stage: OnStage = None,
    ran_out: Optional[list] = None,
) -> Optional[str]:
    """Runs one tool-calling turn, offering `tools` and dispatching to whichever one (if any) the model picks via `executors`
    (keyed by tool name). Returns None on any failure or when Ollama is unavailable — the orchestrator falls through to
    general_agent.handle() in that case. If `ran_out` is a list, the names of the tools that actually ran are appended to it,
    so a caller can tell a grounded answer from one the model wrote without looking anything up."""
    ran = [] if ran_out is None else ran_out

    def tracked(name, fn):
        if not callable(fn):
            return fn

        async def call(**kwargs):
            ran.append(name)
            metrics.count("tool_calls")
            with metrics.timed("tool_ms"):          # includes the database queries the tool runs
                return await fn(**kwargs)
        return call
    executors = {name: tracked(name, fn) for name, fn in executors.items()}

    with metrics.timed("agent_ms"):             # model time ~ agent_ms - tool_ms
        reply = await _dispatch(system_prompt, tools, executors, message, history, sentiment, on_stage)
    if reply is not None and not ran and is_empty_promise(reply):
        log.warning("model promised data without calling a tool", extra={"event": "empty_promise"})
        return PROMISE_REPLACEMENT
    return reply


async def _dispatch(system_prompt, tools, executors, message, history, sentiment, on_stage) -> Optional[str]:
    if ollama_client.is_unavailable():
        return None
    try:
        return await ollama_client.run_tool_agent(system_prompt, tools, executors, message, history, sentiment, on_stage)
    except Exception as err:
        log.warning("tool agent failed; falling back", extra={"event": "tool_agent_failed", "provider": "ollama",
                                                              "error_type": type(err).__name__, "error": str(err)[:200]})
        return None
