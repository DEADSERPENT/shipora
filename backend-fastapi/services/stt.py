"""Speech-to-text. Two providers, selected by STT_PROVIDER:

  openai          OpenAI Whisper API (default; needs OPENAI_API_KEY)
  faster_whisper  local faster-whisper (CTranslate2), no API key — optional install,
                  see requirements-local-voice.txt and docs/LOCAL_VOICE.md
  onnx_local      local Whisper on ONNX Runtime (onnx-asr), no API key — for machines where
                  CTranslate2 can't load (e.g. blocked by a Windows application-control policy)

Adding another provider means writing one STTProvider class and registering it in
_PROVIDERS, without touching transcribe_audio() or any caller. See
docs/VOICE_ARCHITECTURE.md for the full writeup.
"""

import io
import logging
import asyncio
import threading
from abc import ABC, abstractmethod
from typing import Optional, Type

import config
log = logging.getLogger("shipora.stt")


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


_whisper_model = None
_whisper_lock = threading.Lock()


def _load_whisper_model():
    """Loads (once per process) the faster-whisper model. Isolated so tests can replace it."""
    global _whisper_model
    with _whisper_lock:
        if _whisper_model is None:
            from faster_whisper import WhisperModel  # optional dependency, imported only when this provider is used

            from services import local_models

            name = config.FASTER_WHISPER_MODEL
            local_dir = local_models.resolve(name, "whisper")
            _whisper_model = WhisperModel(
                str(local_dir) if local_dir.is_dir() else name,  # a downloaded model dir wins; a bare size name is fetched by faster-whisper on first use
                device=config.FASTER_WHISPER_DEVICE,
                compute_type=config.FASTER_WHISPER_COMPUTE_TYPE,
                download_root=str(local_models.models_dir() / "whisper"),
            )
        return _whisper_model


class FasterWhisperProvider(STTProvider):
    def transcribe(self, audio_bytes: bytes, filename: str) -> Optional[str]:
        try:
            model = _load_whisper_model()
        except ImportError as err:  # not installed, or installed but its native library failed to load (e.g. blocked by an OS policy)
            log.error("faster-whisper could not be imported", extra={"event": "stt_provider_unavailable", "provider": "faster_whisper", "error": str(err)[:300], "hint": "pip install -r requirements-local-voice.txt; see docs/LOCAL_VOICE.md"})
            return None
        # Browser recordings (webm/opus, mp4) are decoded by faster-whisper's bundled PyAV — no ffmpeg needed.
        segments, _info = model.transcribe(io.BytesIO(audio_bytes), language=config.FASTER_WHISPER_LANGUAGE, vad_filter=True)
        text = " ".join(seg.text.strip() for seg in segments).strip()  # `segments` is lazy: decoding happens while iterating
        return text or None


_ONNX_REPOS = {"whisper-base": "istupakov/whisper-base-onnx"}  # models fetched automatically; any other model name must already be in local_models/onnx_stt/<name>/
_onnx_model = None
_onnx_lock = threading.Lock()


def _decode_to_mono_16k(audio_bytes: bytes):
    """Browser recordings (webm/opus, mp4, wav…) -> float32 mono 16 kHz, decoded in-process by PyAV (no ffmpeg binary)."""
    import av
    import numpy as np

    container = av.open(io.BytesIO(audio_bytes))
    try:
        resampler = av.AudioResampler(format="flt", layout="mono", rate=16000)
        chunks = []
        for frame in container.decode(audio=0):
            for out in resampler.resample(frame) or []:
                chunks.append(out.to_ndarray().reshape(-1))
        for out in resampler.resample(None) or []:  # flush
            chunks.append(out.to_ndarray().reshape(-1))
    finally:
        container.close()
    return np.concatenate(chunks).astype(np.float32) if chunks else np.zeros(0, dtype=np.float32)


def _load_onnx_model():
    """Loads (once per process) the ONNX speech model, downloading whisper-base into local_models/ on first use.
    Isolated so tests can replace it."""
    global _onnx_model
    with _onnx_lock:
        if _onnx_model is None:
            import onnx_asr  # optional dependency, imported only when this provider is used

            from services import local_models

            name, quantization = config.ONNX_STT_MODEL, config.ONNX_STT_QUANTIZATION
            model_dir = local_models.resolve(name, "onnx_stt")
            repo = _ONNX_REPOS.get(name)
            if repo and not (model_dir.is_dir() and any(model_dir.glob("*.onnx"))):
                from huggingface_hub import snapshot_download

                log.info("downloading ONNX STT model", extra={"event": "stt_model_download", "repo": repo, "dir": str(model_dir)})
                # only the requested precision (+ tokenizer files), not every variant in the repo
                patterns = ["*.json", "*.txt"] + ([f"*{quantization}.onnx"] if quantization else ["*[!8].onnx"])
                snapshot_download(repo, local_dir=str(model_dir), allow_patterns=patterns)
            providers = ["CUDAExecutionProvider", "CPUExecutionProvider"] if config.ONNX_STT_DEVICE == "cuda" else ["CPUExecutionProvider"]
            _onnx_model = onnx_asr.load_model(name, path=str(model_dir), quantization=quantization, providers=providers)
        return _onnx_model


class OnnxLocalProvider(STTProvider):
    def transcribe(self, audio_bytes: bytes, filename: str) -> Optional[str]:
        try:
            model = _load_onnx_model()
            samples = _decode_to_mono_16k(audio_bytes)
        except ImportError as err:  # not installed, or installed but its native library failed to load
            log.error("onnx STT could not be imported", extra={"event": "stt_provider_unavailable", "provider": "onnx_local", "error": str(err)[:300], "hint": "pip install -r requirements-local-voice.txt; see docs/LOCAL_VOICE.md"})
            return None
        if samples.size == 0:
            return None
        limit = config.ONNX_STT_MAX_SECONDS * 16000
        if samples.size > limit:
            log.warning("recording truncated for ONNX STT", extra={"event": "stt_truncated", "seconds": round(samples.size / 16000, 1), "max_seconds": config.ONNX_STT_MAX_SECONDS})
            samples = samples[:limit]
        result = model.recognize(samples, sample_rate=16000, language=config.ONNX_STT_LANGUAGE) if config.ONNX_STT_LANGUAGE else model.recognize(samples, sample_rate=16000)
        text = str(getattr(result, "text", result)).strip()
        return text or None


# To add a provider: implement STTProvider and add one line here. Nothing
# else in this file, or any caller of transcribe_audio(), needs to change.
_PROVIDERS: dict[str, Type[STTProvider]] = {
    "openai": OpenAIWhisperProvider,
    "faster_whisper": FasterWhisperProvider,
    "onnx_local": OnnxLocalProvider,
}


async def transcribe_audio(audio_bytes: bytes, filename: str) -> Optional[str]:
    """Returns the transcript, or None if the configured provider isn't
    implemented, no usable API key is set, or transcription failed (caller
    should surface a "voice unavailable" error)."""
    provider_name = (config.STT_PROVIDER or "openai").lower()
    provider_cls = _PROVIDERS.get(provider_name)
    if provider_cls is None:
        log.error("unknown STT provider", extra={"event": "stt_unknown_provider", "provider": provider_name, "available": str(list(_PROVIDERS))})
        return None
    try:
        return await asyncio.to_thread(provider_cls().transcribe, audio_bytes, filename)
    except Exception as err:
        log.warning("STT call failed", extra={"event": "stt_failed", "provider": provider_name, "error_type": type(err).__name__, "error": str(err)[:200]})
        return None
