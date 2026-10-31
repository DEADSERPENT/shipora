"""Plain-text LLM call for ShipBot's second tier (general_agent), served by the local Ollama model.

agents/base.py owns classification and tool-calling; this is the tier below it, used when a tool-calling turn produced nothing.
routes/chat.py reaches it indirectly via general_agent.handle(). OPENAI_API_KEY exists in config.py only for the optional OpenAI
speech providers (services/stt.py / tts.py) — an unrelated code path.
"""

import logging
from typing import List, Optional

from services import ollama_client
log = logging.getLogger("shipora.llm")


async def get_llm_reply(message: str, history: List[dict], system_prompt: str) -> Optional[str]:
    """Returns the model's reply, or None when Ollama is unavailable (caller falls back to the rule-based knowledge base)."""
    if ollama_client.is_unavailable():
        return None
    try:
        return await ollama_client.reply(message, history, system_prompt)
    except Exception as err:
        log.warning("Ollama plain-text call failed; falling back to built-in replies", extra={"event": "llm_failed", "provider": "ollama", "error_type": type(err).__name__})
        return None
