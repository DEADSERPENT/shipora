"""Text-to-speech. Providers, selected by TTS_PROVIDER:

  kokoro  DEFAULT. Local Kokoro-82M (Apache-2.0) via the official `kokoro` package — English, 24 kHz, returns WAV. No API key.
          Weights come from Hugging Face at a pinned commit (config.KOKORO_REVISION) into LOCAL_MODELS_DIR/kokoro.
  piper   local Piper voice, no API key — returns WAV. Optional install, see requirements-local-voice.txt and
          docs/LOCAL_VOICE.md. English is the tested language.
  openai  OpenAI TTS API — hosted, paid, OPT-IN only (TTS_PROVIDER=openai + OPENAI_API_KEY) — returns MP3. Never used as a fallback.

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
from services.speech_limits import SpeechModelError, SpeechTimeout, run_limited
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


_KOKORO_SAMPLE_RATE = 24000   # Kokoro's native output rate
_kokoro_state = None          # (KPipeline, device, voice file) — one instance per process
_kokoro_lock = threading.Lock()   # the model is not thread-safe: load and every synthesis hold this


def _kokoro_files(voice: str) -> dict:
    """Downloads (first use only) and returns the pinned Kokoro files: weights, config and the voice pack."""
    from huggingface_hub import hf_hub_download

    from services import local_models

    cache = str(local_models.models_dir() / "kokoro")

    def fetch(name):
        return hf_hub_download(config.KOKORO_REPO, name, revision=config.KOKORO_REVISION, cache_dir=cache)
    return {"model": fetch("kokoro-v1_0.pth"), "config": fetch("config.json"), "voice": fetch(f"voices/{voice}.pt")}


def _load_kokoro():
    """Loads (once per process) the Kokoro pipeline. Isolated so tests can replace it. CUDA when available (KOKORO_DEVICE=auto|cuda),
    CPU otherwise or on any CUDA failure. Raises SpeechModelError with the fix when the package or weights are missing."""
    global _kokoro_state
    with _kokoro_lock:
        if _kokoro_state is None:
            voice = config.KOKORO_VOICE
            try:
                import torch
                from kokoro import KModel, KPipeline  # optional dependency, imported only when this provider is used
            except ImportError as err:
                raise SpeechModelError(f"Kokoro is not installed ({str(err)[:150]}). Run: pip install -r requirements-local-voice.txt (docs/LOCAL_VOICE.md).") from err
            try:
                files = _kokoro_files(voice)
            except Exception as err:
                raise SpeechModelError(f"Could not fetch Kokoro '{config.KOKORO_REPO}' (revision {config.KOKORO_REVISION or 'latest'}, voice '{voice}'): {str(err)[:200]}. "
                                       "Check the voice name and network access to huggingface.co (docs/LOCAL_VOICE.md).") from err
            wanted = (config.KOKORO_DEVICE or "auto").lower()
            devices = ["cpu"] if wanted == "cpu" else (["cuda", "cpu"] if torch.cuda.is_available() else ["cpu"])
            last_err = None
            for device in devices:
                try:
                    model = KModel(repo_id=config.KOKORO_REPO, config=files["config"], model=files["model"]).to(device).eval()
                    pipeline = KPipeline(lang_code=voice[0], repo_id=config.KOKORO_REPO, model=model)   # lang code = first letter of the voice id: a=US, b=UK English
                    list(pipeline("Ready.", voice=files["voice"], speed=config.KOKORO_SPEED))            # CUDA/phonemizer errors only surface on first use
                    _kokoro_state = (pipeline, device, files["voice"])
                    log.info("Kokoro ready", extra={"event": "tts_ready", "provider": "kokoro", "device": device, "voice": voice})
                    break
                except Exception as err:
                    last_err = err
                    log.warning("Kokoro load attempt failed", extra={"event": "tts_load_attempt_failed", "provider": "kokoro", "device": device, "error": str(err)[:200]})
            if _kokoro_state is None:
                raise SpeechModelError(f"Kokoro could not start ({str(last_err)[:200]}). Set KOKORO_DEVICE=cpu; if phonemizing fails, see docs/LOCAL_VOICE.md (misaki / espeak).") from last_err
        return _kokoro_state


def encode_wav_pcm16(samples, sample_rate: int) -> bytes:
    """float samples in [-1, 1] -> 16-bit mono PCM WAV."""
    import numpy as np

    pcm = (np.clip(np.asarray(samples, dtype=np.float32), -1.0, 1.0) * 32767).astype("<i2")
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sample_rate)
        w.writeframes(pcm.tobytes())
    return buf.getvalue()


def _kokoro_run(pipeline, voice_path: str, text: str) -> list:
    return [r.audio.detach().cpu().numpy().reshape(-1) for r in pipeline(text, voice=voice_path, speed=config.KOKORO_SPEED) if r.audio is not None]


class KokoroTTSProvider(TTSProvider):
    def speak(self, text: str) -> Optional[bytes]:
        global _kokoro_state
        import numpy as np

        pipeline, device, voice_path = _load_kokoro()
        with _kokoro_lock:
            try:
                chunks = _kokoro_run(pipeline, voice_path, text)
            except RuntimeError as err:
                if device == "cpu" or "out of memory" not in str(err).lower():
                    raise
                # GPU memory exhausted: move the model to the CPU for good and retry once.
                import torch
                pipeline.model.to("cpu")
                torch.cuda.empty_cache()
                _kokoro_state = (pipeline, "cpu", voice_path)
                log.warning("Kokoro GPU out of memory; continuing on CPU", extra={"event": "tts_gpu_fallback", "provider": "kokoro"})
                chunks = _kokoro_run(pipeline, voice_path, text)
        if not chunks:
            return None
        return encode_wav_pcm16(np.concatenate(chunks), _KOKORO_SAMPLE_RATE)


# To add a provider: implement TTSProvider and add one line here. Nothing
# else in this file, or any caller of synthesize_speech(), needs to change.
_PROVIDERS: dict[str, Type[TTSProvider]] = {
    "kokoro": KokoroTTSProvider,
    "piper": PiperTTSProvider,
    "openai": OpenAITTSProvider,
}


async def synthesize_speech(text: str) -> Optional[bytes]:
    """Returns encoded audio bytes (WAV for kokoro/piper, MP3 for openai — see audio_mime_type()), or None if the configured
    provider isn't implemented, isn't usable (model not installed / no API key), timed out, or synthesis failed (caller should just
    skip playback). The reason is logged with what to do about it. Only the provider named in TTS_PROVIDER is ever called —
    there is no fallback to another (least of all a paid) provider."""
    provider_name = (config.TTS_PROVIDER or "kokoro").lower()
    provider_cls = _PROVIDERS.get(provider_name)
    if provider_cls is None:
        log.error("unknown TTS provider", extra={"event": "tts_unknown_provider", "provider": provider_name, "available": str(list(_PROVIDERS))})
        return None
    try:
        spoken = trim_for_ear(speech_text(text), min(_MAX_CHARS, config.VOICE_MAX_SPOKEN_CHARS))
        if not spoken:
            return None
        return await run_limited("tts", provider_cls().speak, spoken)
    except SpeechTimeout as err:
        log.warning("TTS timed out", extra={"event": "tts_timeout", "provider": provider_name, "error": str(err)})
        return None
    except SpeechModelError as err:
        log.error("TTS model unavailable", extra={"event": "tts_provider_unavailable", "provider": provider_name, "error": str(err)[:400]})
        return None
    except Exception as err:
        log.warning("TTS call failed", extra={"event": "tts_failed", "provider": provider_name, "error_type": type(err).__name__, "error": str(err)[:200]})
        return None
