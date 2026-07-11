"""Provider-agnostic LLM abstraction for EcoBot.

routes/chat.py calls get_llm_reply() without knowing which provider is
configured. Swap providers purely via the LLM_PROVIDER env var — no
route-level code changes needed.
"""

import asyncio
from typing import List, Optional

import config


async def get_llm_reply(message: str, history: List[dict], system_prompt: str) -> Optional[str]:
    """Returns the AI reply, or None if no usable API key is configured
    (caller should fall back to the rule-based knowledge base)."""
    provider = (config.LLM_PROVIDER or "anthropic").lower()
    try:
        if provider == "openai":
            return await asyncio.to_thread(_openai_reply, message, history, system_prompt)
        if provider == "gemini":
            return await asyncio.to_thread(_gemini_reply, message, history, system_prompt)
        return await asyncio.to_thread(_anthropic_reply, message, history, system_prompt)
    except Exception as err:
        print(f"{provider} API error, falling back to built-in: {err}")
        return None


def _anthropic_reply(message: str, history: List[dict], system_prompt: str) -> Optional[str]:
    if config.ANTHROPIC_API_KEY in config.PLACEHOLDER_VALUES:
        return None
    from anthropic import Anthropic

    client = Anthropic(api_key=config.ANTHROPIC_API_KEY)
    messages = [{"role": h["role"], "content": h["content"]} for h in history[-10:]]
    messages.append({"role": "user", "content": message})
    response = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=400,
        system=system_prompt,
        messages=messages,
    )
    return response.content[0].text


def _openai_reply(message: str, history: List[dict], system_prompt: str) -> Optional[str]:
    if config.OPENAI_API_KEY in config.PLACEHOLDER_VALUES:
        return None
    from openai import OpenAI

    client = OpenAI(api_key=config.OPENAI_API_KEY)
    messages = [{"role": "system", "content": system_prompt}]
    messages += [{"role": h["role"], "content": h["content"]} for h in history[-10:]]
    messages.append({"role": "user", "content": message})
    response = client.chat.completions.create(
        model="gpt-4o-mini",
        max_tokens=400,
        messages=messages,
    )
    return response.choices[0].message.content


def _gemini_reply(message: str, history: List[dict], system_prompt: str) -> Optional[str]:
    if config.GEMINI_API_KEY in config.PLACEHOLDER_VALUES:
        return None
    import google.generativeai as genai

    genai.configure(api_key=config.GEMINI_API_KEY)
    # gemini-2.5-flash does internal "thinking" by default, adding ~1.5s+ of
    # latency even for trivial replies (measured: ~2.7s vs ~1.2s below, over
    # multiple runs with this exact system prompt) — flash-lite doesn't, and
    # this app has no use for extended reasoning on short conversational
    # replies. max_output_tokens matches the cap _anthropic_reply/_openai_reply
    # already use, bounding worst-case latency/cost consistently across providers.
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
    response = convo.send_message(message)
    return response.text
