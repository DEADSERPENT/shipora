"""Text-to-speech. Two providers, selected by TTS_PROVIDER:

  openai  OpenAI TTS API (default; needs OPENAI_API_KEY) — returns MP3
  piper   local Piper voice, no API key — returns WAV. Optional install, see
          requirements-local-voice.txt and docs/LOCAL_VOICE.md. English is the
          tested language; other languages need a Piper voice for that language,
          which has to be listened to before being relied on.

Adding another provider means writing one TTSProvider class and registering it in
_PROVIDERS, without touching synthesize_speech() or any caller. Providers return
encoded audio bytes; audio_mime_type() reports which format a result is in.
See docs/VOICE_ARCHITECTURE.md.
"""

import io
import logging
import asyncio
import re
import threading
import wave
from abc import ABC, abstractmethod
from typing import Optional, Type

import config
log = logging.getLogger("shipora.tts")

_MAX_CHARS = 800  # long agent replies cost real money to synthesize; trim before calling out


_MD_LINK = re.compile(r"\[([^\]]+)\]\([^)]*\)")
_MD_FENCE = re.compile(r"```.*?```", re.S)
_MD_BULLET = re.compile(r"^\s*(?:[•·▪●◦\-*+]|\d+[.)])\s+", re.M)
_MD_HEADING = re.compile(r"^\s{0,3}#{1,6}\s+", re.M)
# Emphasis markers only: ** __ ~~ ` always; a lone * or _ only when it hugs a word's edge, so snake_case and 5*3 survive.
_MD_EMPHASIS = re.compile(r"\*\*|__|~~|`|(?<![\w*])\*+(?=\S)|(?<=\S)\*+(?![\w*])|(?<!\w)_(?=\S)|(?<=\S)_(?!\w)")


_ID = re.compile(r"\bSHP([0-9]{8}|[0-9A-F]{10})\b")
_VEHICLE = re.compile(r"\b([A-Z]{2})\s?(\d{2})\s?([A-Z]{1,2})\s?(\d{4})\b")
_PHONE = re.compile(r"(?<![\d.])(?:\+91[\s-]?)?([6-9]\d{4})[\s-]?(\d{5})(?!\d)")
_RUPEE = re.compile(r"(?:₹|\bRs\.?|\bINR)\s?(\d[\d,]*(?:\.\d+)?)", re.I)
_UNITS = [(re.compile(r"(\d)\s?km\b", re.I), r"\1 kilometres"), (re.compile(r"(\d)\s?kg\b", re.I), r"\1 kilograms"),
          (re.compile(r"(\d)\s?(?:h|hrs?)\b"), r"\1 hours"), (re.compile(r"(\d)\s?(?:mins?)\b", re.I), r"\1 minutes")]
_ACRONYMS = re.compile(r"\b(ETA|UPI|COD|GPS|OTP|KYC|SMS|ID)\b")


def _spell(chars: str) -> str:
    return " ".join(chars)


def spoken_forms(text: str) -> str:
    """Written-for-the-eye tokens -> words a voice reads correctly. A TTS voice reads "SHP1A2B3C4D5E" as gibberish and
    "₹48" as a symbol; a listener needs the ID spelled in short groups (they will write it down) and money as words."""
    text = _ID.sub(lambda m: "S H P, " + ", ".join(_spell(m.group(1)[i:i + n]) for n in [4 if len(m.group(1)) == 8 else 3] for i in range(0, len(m.group(1)), n)), text)
    text = _VEHICLE.sub(lambda m: ", ".join([_spell(m.group(1)), _spell(m.group(2)), _spell(m.group(3) + m.group(4))]), text)
    text = _PHONE.sub(lambda m: f"{_spell(m.group(1))}, {_spell(m.group(2))}", text)
    text = _RUPEE.sub(lambda m: f"{m.group(1).replace(',', '')} rupees", text)
    for pattern, repl in _UNITS:
        text = pattern.sub(repl, text)
    return _ACRONYMS.sub(lambda m: _spell(m.group(1)), text)


def trim_for_ear(text: str, limit: int) -> str:
    """Long answers are fine to read and painful to listen to (and slow to synthesise). Keep whole sentences up to
    `limit` characters; the chat bubble still shows the full reply."""
    if len(text) <= limit:
        return text
    cut = text[:limit]
    end = max(cut.rfind(". "), cut.rfind("? "), cut.rfind("! "))
    return (cut[:end + 1] if end > limit * 0.4 else cut.rsplit(" ", 1)[0]).strip()


def speech_text(text: str) -> str:
    """Reply text -> text meant to be *heard*. Replies are written for the chat bubble (markdown, bullets); read aloud,
    that becomes "star star Tracking a parcel star star". Strips the syntax, keeps the words, and turns line breaks
    into sentence pauses."""
    text = _MD_FENCE.sub(" ", text)
    text = _MD_LINK.sub(lambda m: m.group(1), text)
    text = _MD_HEADING.sub("", text)
    text = _MD_BULLET.sub("", text)
    text = _MD_EMPHASIS.sub("", text)
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    text = " ".join(ln if ln[-1] in ".!?:;," else ln + "." for ln in lines)
    return re.sub(r"\s+", " ", spoken_forms(text)).strip()


def audio_mime_type(data: bytes) -> str:
    """MIME type of audio returned by synthesize_speech(), from its magic bytes — providers differ (MP3 vs WAV)."""
    if data[:4] == b"RIFF" and data[8:12] == b"WAVE":
        return "audio/wav"
    return "audio/mpeg"


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


_piper_voice = None
_piper_lock = threading.Lock()


def _load_piper_voice():
    """Loads (once per process) the Piper voice. Returns None if the voice file is missing.
    Isolated so tests can replace it."""
    global _piper_voice
    with _piper_lock:
        if _piper_voice is None:
            from piper import PiperVoice  # optional dependency, imported only when this provider is used

            from services import local_models

            path = local_models.resolve(config.PIPER_VOICE, "piper")
            if not path.is_file():
                log.error("Piper voice file not found", extra={"event": "tts_provider_unavailable", "provider": "piper", "path": str(path), "hint": "see docs/LOCAL_VOICE.md"})
                return None
            _piper_voice = PiperVoice.load(str(path))
        return _piper_voice


class PiperTTSProvider(TTSProvider):
    def speak(self, text: str) -> Optional[bytes]:
        try:
            voice = _load_piper_voice()
        except ImportError as err:  # not installed, or installed but its native library failed to load
            log.error("piper-tts could not be imported", extra={"event": "tts_provider_unavailable", "provider": "piper", "error": str(err)[:300], "hint": "pip install -r requirements-local-voice.txt; see docs/LOCAL_VOICE.md"})
            return None
        if voice is None:
            return None
        buf = io.BytesIO()
        with wave.open(buf, "wb") as wav_file:
            # piper-tts >= 1.3 renamed synthesize() -> synthesize_wav(); support both
            synthesize = getattr(voice, "synthesize_wav", None) or voice.synthesize
            synthesize(text, wav_file)
        data = buf.getvalue()
        return data if len(data) > 44 else None  # 44 bytes = bare WAV header: nothing was synthesized


# To add a provider: implement TTSProvider and add one line here. Nothing
# else in this file, or any caller of synthesize_speech(), needs to change.
_PROVIDERS: dict[str, Type[TTSProvider]] = {
    "openai": OpenAITTSProvider,
    "piper": PiperTTSProvider,
}


async def synthesize_speech(text: str) -> Optional[bytes]:
    """Returns encoded audio bytes (MP3 for openai, WAV for piper — see audio_mime_type()),
    or None if the configured provider isn't implemented, isn't usable (no API key /
    model not installed), or synthesis failed (caller should just skip playback)."""
    provider_name = (config.TTS_PROVIDER or "openai").lower()
    provider_cls = _PROVIDERS.get(provider_name)
    if provider_cls is None:
        log.error("unknown TTS provider", extra={"event": "tts_unknown_provider", "provider": provider_name, "available": str(list(_PROVIDERS))})
        return None
    try:
        spoken = trim_for_ear(speech_text(text), min(_MAX_CHARS, config.VOICE_MAX_SPOKEN_CHARS))
        if not spoken:
            return None
        return await asyncio.to_thread(provider_cls().speak, spoken)
    except Exception as err:
        log.warning("TTS call failed", extra={"event": "tts_failed", "provider": provider_name, "error_type": type(err).__name__, "error": str(err)[:200]})
        return None
