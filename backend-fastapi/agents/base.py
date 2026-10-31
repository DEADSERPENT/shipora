"""Shared tool-calling loop for specialist agents, built directly against
Gemini's function-calling API (google-generativeai). Not a 3-provider-agnostic
abstraction — Gemini is the only tool-calling/classification provider in this
codebase (see docs/VOICE_ARCHITECTURE.md); OpenAI remains selectable only for
services/llm.py's plain-text fallback tier, which never calls tools.

Message flow per call:
  1. model.generate_content(contents, tools=[...]) - if the response's first
     part is a function_call, the model wants to call one of the offered tools.
  2. Execute that tool's Python function (looked up by name in `executors`)
     with the model-supplied arguments.
  3. Append the model's response content (the function_call part) as a
     "model" turn, then a "user" turn containing a single function_response
     part (Gemini's function-response turns are role="user", not "function" -
     confirmed against the installed SDK's ChatSession internals).
  4. Call generate_content(...) again WITHOUT tools to force a final text
     answer - this bounds cost/latency at exactly 2 Gemini calls per turn.

If the model answers directly without invoking any tool, its text is
returned as-is from the first call.

Callers may pass an `on_stage(stage, detail=None)` callback to report
progress (used by voice/pipeline.py to push Socket.IO events during a voice
turn — see sockets.py). It's a plain synchronous function, not a coroutine:
_run_sync executes inside asyncio.to_thread (a worker thread with no running
event loop), so on_stage's job is to bridge back to the event loop itself
(e.g. via asyncio.run_coroutine_threadsafe) — agents/base.py stays agnostic
of that plumbing and just calls on_stage(...) at the right moments.
"""

import asyncio
import logging
import re
from typing import Callable, Optional

import config
from services import gemini_client, metrics, ollama_client
log = logging.getLogger("shipora.agents")

AGENT_MODEL = "gemini-flash-lite-latest"  # same model services/llm.py already picks for chat — avoids the ~1.5s "thinking" overhead of gemini-2.5-flash

OnStage = Optional[Callable[[str, Optional[str]], None]]

# A small model sometimes answers "let me check that for you" and never calls the tool. Such text promises data that is not
# coming, so it is never shown as an answer when no tool ran in the turn.
_PROMISE = re.compile(
    r"\b(?:let me|i'?ll|i will|i can|i need to|allow me to|give me|hold on)\b[^.!?\n]{0,60}\b(?:check|fetch|pull up|look up|lookup|retrieve|get that|get the|call the|get_\w+|run)\b"
    r"|\bjust a moment\b|\bone moment\b", re.I)
PROMISE_REPLACEMENT = "I wasn't able to fetch that just now. Please try again in a moment, or ask in a different way."


def is_empty_promise(text: Optional[str]) -> bool:
    return bool(text and _PROMISE.search(text))


TOOL_TIMEOUT_SECONDS = 30  # a tool (one DB query) that takes longer than this is treated as a failed turn -> general_agent fallback


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
    ran = []

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
    if ollama_client.enabled():
        try:
            return await ollama_client.run_tool_agent(system_prompt, tools, executors, message, history, sentiment, on_stage)
        except Exception as err:
            log.warning("ollama tool agent failed; falling back", extra={"event": "tool_agent_failed", "provider": "ollama",
                                                                        "error_type": type(err).__name__, "error": str(err)[:200]})
            return None
    if config.GEMINI_API_KEY in config.PLACEHOLDER_VALUES or gemini_client.is_unavailable():
        return None
    try:
        # _run_sync runs on a worker thread; hand it the app's event loop so tools execute ON that loop (see _run_sync).
        loop = asyncio.get_running_loop()
        return await asyncio.to_thread(_run_sync, system_prompt, tools, executors, message, history, sentiment, on_stage, loop)
    except Exception as err:
        gemini_client.note_failure(err)
        log.warning("tool agent failed; falling back", extra={"event": "tool_agent_failed", "error_type": type(err).__name__, "error": str(err)[:200]})
        return None


def _run_sync(system_prompt, tools, executors, message, history, sentiment, on_stage: OnStage, loop=None) -> Optional[str]:
    import google.generativeai as genai

    genai.configure(api_key=config.GEMINI_API_KEY)

    effective_system = system_prompt
    if sentiment == "negative":
        effective_system += "\n\nThe user seems frustrated — briefly acknowledge that before answering."

    # Tool schemas stay Anthropic-shaped ({"name","description","input_schema"})
    # everywhere in tools/*.py — only renamed at this boundary. Gemini's
    # FunctionDeclaration(parameters=...) recursively converts the JSON-Schema
    # dict itself (type->type_, etc), so the body needs no reshaping.
    gemini_tools = {"function_declarations": [
        {"name": t["name"], "description": t["description"], "parameters": t["input_schema"]}
        for t in tools
    ]}

    model = genai.GenerativeModel(
        AGENT_MODEL, system_instruction=effective_system,
        generation_config=genai.types.GenerationConfig(max_output_tokens=500),
    )

    contents = [{"role": "user" if h["role"] == "user" else "model", "parts": [h["content"]]} for h in history[-10:]]
    contents.append({"role": "user", "parts": [message]})

    response = model.generate_content(contents, tools=gemini_tools, request_options=gemini_client.request_options())
    gemini_client.note_success()
    parts = response.candidates[0].content.parts
    # response.text raises ValueError if the only part is a function_call —
    # must check for one before ever touching .text, same guard role as the
    # old stop_reason != "tool_use" check.
    fc_part = next((p for p in parts if p.function_call.name), None)

    if fc_part is None:
        if on_stage:
            on_stage("generating_response", None)
        return response.text

    fc = fc_part.function_call
    if on_stage:
        on_stage("tool_execution", fc.name)

    executor = executors[fc.name]
    # _run_sync executes inside asyncio.to_thread, i.e. on a worker thread with no running event loop.
    # Tool executors are async because they call Beanie's async DB API, and the real MongoDB driver (Motor)
    # is bound to the application's event loop: running the coroutine in a *new* loop (asyncio.run) hangs
    # and then raises "Task ... attached to a different loop" against a real database — the in-memory test
    # database has no such binding, which is how this stayed hidden. So run it on the app's loop and block
    # this worker thread (not the loop) until it finishes. dict(fc.args) converts the protobuf Struct into
    # plain kwargs.
    call = executor(**dict(fc.args))
    if loop is None:  # called without a running app loop (e.g. a script): no loop-bound resources to protect
        tool_result = asyncio.run(call)
    else:
        future = asyncio.run_coroutine_threadsafe(call, loop)
        try:
            tool_result = future.result(timeout=TOOL_TIMEOUT_SECONDS)
        except TimeoutError as err:  # a slow *tool* (database) is not a Gemini outage: keep it from tripping the Gemini cooldown
            future.cancel()
            raise RuntimeError(f"tool {fc.name!r} timed out after {TOOL_TIMEOUT_SECONDS}s") from err
        except BaseException:
            future.cancel()
            raise

    contents.append(response.candidates[0].content)
    contents.append({"role": "user", "parts": [
        genai.protos.Part(function_response=genai.protos.FunctionResponse(name=fc.name, response=tool_result))
    ]})

    if on_stage:
        on_stage("generating_response", None)

    final = model.generate_content(contents, request_options=gemini_client.request_options())  # no tools kwarg -> forces a text answer, mirrors the old "no tools" 2nd call
    return final.text
