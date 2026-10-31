"""Gemini-only LLM abstraction for ShipBot's plain-text fallback tier
(general_agent's tier 2, reached only if Gemini tool-calling AND Gemini
plain-text both somehow fail elsewhere — see agents/base.py, which owns
classification and tool-calling).

routes/chat.py calls get_llm_reply() indirectly via general_agent.handle().
OPENAI_API_KEY still exists in config.py, but only for STT/TTS
(services/stt.py/tts.py) — an unrelated code path, not this file.
"""

import logging
import asyncio
from typing import List, Optional

import config
from services import gemini_client, ollama_client
log = logging.getLogger("shipora.llm")


async def get_llm_reply(message: str, history: List[dict], system_prompt: str) -> Optional[str]:
    """Returns the Gemini reply, or None if no usable API key is configured
    (caller should fall back to the rule-based knowledge base)."""
    if ollama_client.enabled():
        try:
            return await ollama_client.reply(message, history, system_prompt)
        except Exception as err:
            log.warning("Ollama plain-text call failed; falling back to built-in replies", extra={"event": "llm_failed", "provider": "ollama", "error_type": type(err).__name__})
            return None
    if gemini_client.is_unavailable():
        return None
    try:
        return await asyncio.to_thread(_gemini_reply, message, history, system_prompt)
    except Exception as err:
        gemini_client.note_failure(err)
        log.warning("Gemini plain-text call failed; falling back to built-in replies", extra={"event": "llm_failed", "error_type": type(err).__name__, "error": str(err)[:200]})
        return None


def _gemini_reply(message: str, history: List[dict], system_prompt: str) -> Optional[str]:
    if config.GEMINI_API_KEY in config.PLACEHOLDER_VALUES:
        return None
    import google.generativeai as genai

    genai.configure(api_key=config.GEMINI_API_KEY)
    # gemini-2.5-flash does internal "thinking" by default, adding ~1.5s+ of
    # latency even for trivial replies (measured: ~2.7s vs ~1.2s below, over
    # multiple runs with this exact system prompt) — flash-lite doesn't, and
    # this app has no use for extended reasoning on short conversational
    # replies.
    model = genai.GenerativeModel(
        "gemini-flash-lite-latest",
        system_instruction=system_prompt,
        generation_config=genai.types.GenerationConfig(max_output_tokens=400),
    )
    convo = model.start_chat(
        history=[
            {"role": "user" if h["role"] == "user" else "model", "parts": [h["content"]]}
            for h in history[-10:]
        ]
    )
    response = convo.send_message(message, request_options=gemini_client.request_options())
    gemini_client.note_success()
    return response.text
