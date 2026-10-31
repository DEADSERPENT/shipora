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
    if (config.STT_PROVIDER or "").lower() == "onnx_local":
        steps.append(_timed("stt", asyncio.to_thread(stt._load_onnx_model)))
    if (config.TTS_PROVIDER or "").lower() == "piper":
        steps.append(_timed("tts", tts.synthesize_speech("Ready.")))
    if (config.STT_PROVIDER or "").lower() == "faster_whisper":
        steps.append(_timed("stt", asyncio.to_thread(stt._load_whisper_model)))
    steps.append(_timed("llm", ollama_client.chat([{"role": "user", "content": "hi"}], max_tokens=1)))
    results = await asyncio.gather(*steps)
    log.info("voice stack warmed", extra={"event": "warmup_done", "steps": str(results)})
    return list(results)
