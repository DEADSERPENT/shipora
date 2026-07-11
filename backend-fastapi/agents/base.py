"""Shared tool-calling loop for specialist agents, built directly against
Anthropic's tool-use API (not a 3-provider-agnostic abstraction — OpenAI/Gemini
function-calling differ enough in shape that abstracting all three is excess
scope here; see docs/VOICE_ARCHITECTURE.md for the tradeoff writeup).

Message flow per call:
  1. messages.create(tools=[...], messages=[...]) - if stop_reason is
     "tool_use", the model wants to call one of the offered tools.
  2. Execute that tool's Python function (looked up by name in `executors`)
     with the model-supplied arguments.
  3. Append the full assistant response.content (not just text) as an
     assistant turn, then a user turn containing exactly one tool_result
     block referencing the tool_use id.
  4. Call messages.create(...) again WITHOUT tools to force a final text
     answer - this bounds cost/latency at exactly 2 Anthropic calls per turn.

If the model answers directly without invoking any tool (stop_reason != "tool_use"),
its text is returned as-is from the first call.

Callers may pass an `on_stage(stage, detail=None)` callback to report
progress (used by voice/pipeline.py to push Socket.IO events during a voice
turn — see sockets.py). It's a plain synchronous function, not a coroutine:
_run_sync executes inside asyncio.to_thread (a worker thread with no running
event loop), so on_stage's job is to bridge back to the event loop itself
(e.g. via asyncio.run_coroutine_threadsafe) — agents/base.py stays agnostic
of that plumbing and just calls on_stage(...) at the right moments.
"""

import asyncio
import json
from typing import Awaitable, Callable, Optional

import config

AGENT_MODEL = "claude-haiku-4-5-20251001"  # same model services/llm.py already hardcodes for chat

OnStage = Optional[Callable[[str, Optional[str]], None]]


async def run_tool_agent(
    system_prompt: str,
    tools: list,
    executors: dict,
    message: str,
    history: list,
    sentiment: str,
    on_stage: OnStage = None,
) -> Optional[str]:
    """Runs one tool-calling turn, offering possibly several `tools` and
    dispatching to whichever one (if any) the model picks via `executors`
    (keyed by tool name). Returns None on any failure or missing key — the
    orchestrator falls through to general_agent.handle() in that case."""
    if config.ANTHROPIC_API_KEY in config.PLACEHOLDER_VALUES:
        return None
    try:
        return await asyncio.to_thread(_run_sync, system_prompt, tools, executors, message, history, sentiment, on_stage)
    except Exception as err:
        print(f"tool agent error: {err}")
        return None


def _run_sync(system_prompt, tools, executors, message, history, sentiment, on_stage: OnStage) -> Optional[str]:
    from anthropic import Anthropic

    client = Anthropic(api_key=config.ANTHROPIC_API_KEY)

    effective_system = system_prompt
    if sentiment == "negative":
        effective_system += "\n\nThe user seems frustrated — briefly acknowledge that before answering."

    messages = [{"role": h["role"], "content": h["content"]} for h in history[-10:]]
    messages.append({"role": "user", "content": message})

    response = client.messages.create(
        model=AGENT_MODEL, max_tokens=500, system=effective_system,
        tools=tools, messages=messages,
    )

    if response.stop_reason != "tool_use":
        if on_stage:
            on_stage("generating_response", None)
        text_block = next((b for b in response.content if b.type == "text"), None)
        return text_block.text if text_block else None

    tool_use_block = next(b for b in response.content if b.type == "tool_use")
    if on_stage:
        on_stage("tool_execution", tool_use_block.name)

    executor = executors[tool_use_block.name]
    # _run_sync executes inside asyncio.to_thread, i.e. on a worker thread with
    # no running event loop — asyncio.run() here is safe. Tool executors are
    # async because they call Beanie's async DB API.
    tool_result = asyncio.run(executor(**tool_use_block.input))

    messages.append({"role": "assistant", "content": response.content})
    messages.append({"role": "user", "content": [
        {"type": "tool_result", "tool_use_id": tool_use_block.id, "content": json.dumps(tool_result)}
    ]})

    if on_stage:
        on_stage("generating_response", None)

    final = client.messages.create(
        model=AGENT_MODEL, max_tokens=500, system=effective_system, messages=messages,
    )
    text_block = next((b for b in final.content if b.type == "text"), None)
    return text_block.text if text_block else None
