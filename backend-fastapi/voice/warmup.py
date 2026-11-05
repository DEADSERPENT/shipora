"""Loads the voice stack before the first caller does.

Measured on this project: the first TTS call took ~4 s and later ones ~0.7 s, because the model loads on first use; a local
LLM is similar (seconds to move weights onto the GPU). On a phone call the first turn is the one that matters, so the
server pays that cost at startup, in the background, and never blocks readiness on it. Failures are logged and ignored —
a missing optional model must not stop the API from starting."""

import asyncio
import logging
import time

import config
from services import ollama_client, stt, tts

log = logging.getLogger("shipora.warmup")


async def _timed(name: str, coro) -> dict:
    t = time.perf_counter()
    try:
        await coro
        ok = True
    except Exception as err:
        log.warning("warm-up step failed", extra={"event": "warmup_failed", "step": name, "error_type": type(err).__name__, "error": str(err)[:200]})
        ok = False
    return {"step": name, "ok": ok, "ms": int((time.perf_counter() - t) * 1000)}


async def warm_up() -> list:
    steps = []
    stt_name, tts_name = (config.STT_PROVIDER or "").lower(), (config.TTS_PROVIDER or "").lower()
    # Only local models are loaded; a hosted provider has nothing to warm. Loading is sequential on purpose (below): two models
    # moving onto a 6 GB GPU at once is how it runs out of memory.
    if stt_name == "onnx_local":
        steps.append(("stt", stt._load_onnx_model))
    elif stt_name == "faster_whisper":
        steps.append(("stt", stt._load_whisper_model))
    if tts_name == "kokoro":
        steps.append(("tts", tts._load_kokoro))
    elif tts_name == "piper":
        steps.append(("tts", tts._load_piper_voice))

    async def load_local_models():
        return [await _timed(name, asyncio.to_thread(fn)) for name, fn in steps]

    results = [*await load_local_models(), await _timed("llm", ollama_client.chat([{"role": "user", "content": "hi"}], max_tokens=1))]
    log.info("voice stack warmed", extra={"event": "warmup_done", "steps": str(results)})
    return results
