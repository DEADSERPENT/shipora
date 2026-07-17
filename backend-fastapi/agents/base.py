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
from typing import Callable, Optional

import config

AGENT_MODEL = "gemini-flash-lite-latest"  # same model services/llm.py already picks for chat — avoids the ~1.5s "thinking" overhead of gemini-2.5-flash

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
    if config.GEMINI_API_KEY in config.PLACEHOLDER_VALUES:
        return None
    try:
        return await asyncio.to_thread(_run_sync, system_prompt, tools, executors, message, history, sentiment, on_stage)
    except Exception as err:
        print(f"tool agent error: {err}")
        return None


def _run_sync(system_prompt, tools, executors, message, history, sentiment, on_stage: OnStage) -> Optional[str]:
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

    response = model.generate_content(contents, tools=gemini_tools)
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
    # _run_sync executes inside asyncio.to_thread, i.e. on a worker thread with
    # no running event loop — asyncio.run() here is safe. Tool executors are
    # async because they call Beanie's async DB API. dict(fc.args) converts
    # the protobuf Struct into plain kwargs.
    tool_result = asyncio.run(executor(**dict(fc.args)))

    contents.append(response.candidates[0].content)
    contents.append({"role": "user", "parts": [
        genai.protos.Part(function_response=genai.protos.FunctionResponse(name=fc.name, response=tool_result))
    ]})

    if on_stage:
        on_stage("generating_response", None)

    final = model.generate_content(contents)  # no tools kwarg -> forces a text answer, mirrors the old "no tools" 2nd call
    return final.text
