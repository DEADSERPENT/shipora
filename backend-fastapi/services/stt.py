"""Speech-to-text. ONLY OpenAI Whisper is implemented today — STT_PROVIDER
exists and this is structured as a Provider interface so a second provider
(e.g. Deepgram) can be added later by writing one class and registering it
in _PROVIDERS, without touching transcribe_audio() or any caller. Do not
read "provider interface" as "multiple providers already work" — right now
it's exactly one. See docs/VOICE_ARCHITECTURE.md for the full writeup.
"""

import asyncio
from abc import ABC, abstractmethod
from typing import Optional, Type

import config


class STTProvider(ABC):
    @abstractmethod
    def transcribe(self, audio_bytes: bytes, filename: str) -> Optional[str]:
        """Sync on purpose — called via asyncio.to_thread by transcribe_audio()."""


class OpenAIWhisperProvider(STTProvider):
    def transcribe(self, audio_bytes: bytes, filename: str) -> Optional[str]:
        if config.OPENAI_API_KEY in config.PLACEHOLDER_VALUES:
            return None
        from openai import OpenAI

        client = OpenAI(api_key=config.OPENAI_API_KEY)
        response = client.audio.transcriptions.create(model="whisper-1", file=(filename, audio_bytes))
        return response.text


# To add a provider: implement STTProvider and add one line here. Nothing
# else in this file, or any caller of transcribe_audio(), needs to change.
_PROVIDERS: dict[str, Type[STTProvider]] = {
    "openai": OpenAIWhisperProvider,
}


async def transcribe_audio(audio_bytes: bytes, filename: str) -> Optional[str]:
    """Returns the transcript, or None if the configured provider isn't
    implemented, no usable API key is set, or transcription failed (caller
    should surface a "voice unavailable" error)."""
    provider_name = (config.STT_PROVIDER or "openai").lower()
    provider_cls = _PROVIDERS.get(provider_name)
    if provider_cls is None:
        print(f"STT_PROVIDER='{provider_name}' has no implementation — only {list(_PROVIDERS)} exist today.")
        return None
    try:
        return await asyncio.to_thread(provider_cls().transcribe, audio_bytes, filename)
    except Exception as err:
        print(f"{provider_name} STT error: {err}")
        return None
