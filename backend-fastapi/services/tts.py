"""Text-to-speech. ONLY OpenAI TTS is implemented today — TTS_PROVIDER
exists and this is structured as a Provider interface so a second provider
(e.g. ElevenLabs, Azure) can be added later by writing one class and
registering it in _PROVIDERS, without touching synthesize_speech() or any
caller. Do not read "provider interface" as "multiple providers already
work" — right now it's exactly one. See docs/VOICE_ARCHITECTURE.md.
"""

import asyncio
from abc import ABC, abstractmethod
from typing import Optional, Type

import config

_MAX_CHARS = 800  # long agent replies cost real money to synthesize; trim before calling out


class TTSProvider(ABC):
    @abstractmethod
    def speak(self, text: str) -> Optional[bytes]:
        """Sync on purpose — called via asyncio.to_thread by synthesize_speech()."""


class OpenAITTSProvider(TTSProvider):
    def speak(self, text: str) -> Optional[bytes]:
        if config.OPENAI_API_KEY in config.PLACEHOLDER_VALUES:
            return None
        from openai import OpenAI

        client = OpenAI(api_key=config.OPENAI_API_KEY)
        response = client.audio.speech.create(model="tts-1", voice=config.TTS_VOICE, input=text)
        return response.read()


# To add a provider: implement TTSProvider and add one line here. Nothing
# else in this file, or any caller of synthesize_speech(), needs to change.
_PROVIDERS: dict[str, Type[TTSProvider]] = {
    "openai": OpenAITTSProvider,
}


async def synthesize_speech(text: str) -> Optional[bytes]:
    """Returns MP3 audio bytes, or None if the configured provider isn't
    implemented, no usable API key is set, or synthesis failed (caller
    should just skip playback)."""
    provider_name = (config.TTS_PROVIDER or "openai").lower()
    provider_cls = _PROVIDERS.get(provider_name)
    if provider_cls is None:
        print(f"TTS_PROVIDER='{provider_name}' has no implementation — only {list(_PROVIDERS)} exist today.")
        return None
    try:
        return await asyncio.to_thread(provider_cls().speak, text[:_MAX_CHARS])
    except Exception as err:
        print(f"{provider_name} TTS error: {err}")
        return None
