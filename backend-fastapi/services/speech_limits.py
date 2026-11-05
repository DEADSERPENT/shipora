"""Concurrency + time budget for the local speech models.

A 6 GB GPU hosts the Ollama model, Whisper and (optionally) Kokoro at once, so simultaneous requests must not each run a model:
at most VOICE_STT_CONCURRENCY / VOICE_TTS_CONCURRENCY run, the rest queue, and a request that cannot finish inside its budget gives up
with SpeechTimeout. The slot is held until the worker thread really finishes (a timed-out call keeps running — a thread cannot be
killed), so a timeout never lets a second model run on top of the first."""

import asyncio
import time
import weakref
from typing import Callable

import config


class SpeechTimeout(TimeoutError):
    pass


class SpeechModelError(RuntimeError):
    """A local speech model is missing or cannot start. The message says what to do about it."""


_semaphores: "weakref.WeakKeyDictionary[asyncio.AbstractEventLoop, dict]" = weakref.WeakKeyDictionary()


def _limits(kind: str) -> tuple[int, float]:
    if kind == "stt":
        return config.VOICE_STT_CONCURRENCY, config.VOICE_STT_TIMEOUT_SECONDS
    return config.VOICE_TTS_CONCURRENCY, config.VOICE_TTS_TIMEOUT_SECONDS


def _semaphore(kind: str) -> asyncio.Semaphore:
    per_loop = _semaphores.setdefault(asyncio.get_running_loop(), {})   # asyncio primitives belong to one event loop
    limit, _ = _limits(kind)
    entry = per_loop.get(kind)
    if entry is None or entry[0] != limit:
        entry = per_loop[kind] = (limit, asyncio.Semaphore(limit))
    return entry[1]


async def run_limited(kind: str, fn: Callable, *args):
    """Runs the blocking `fn(*args)` in a thread, subject to the `kind` ("stt" | "tts") concurrency limit and time budget."""
    _, budget = _limits(kind)
    deadline = time.monotonic() + budget
    sem = _semaphore(kind)
    try:
        await asyncio.wait_for(sem.acquire(), timeout=budget)
    except asyncio.TimeoutError:
        raise SpeechTimeout(f"{kind.upper()} queue wait exceeded {budget:g}s (raise VOICE_{kind.upper()}_TIMEOUT_SECONDS or VOICE_{kind.upper()}_CONCURRENCY)") from None
    task = asyncio.ensure_future(asyncio.to_thread(fn, *args))
    task.add_done_callback(lambda _t: sem.release())   # released only when the thread is really done
    try:
        return await asyncio.wait_for(asyncio.shield(task), timeout=max(0.0, deadline - time.monotonic()))
    except asyncio.TimeoutError:
        task.add_done_callback(lambda t: t.cancelled() or t.exception())   # mark a late error as retrieved
        raise SpeechTimeout(f"{kind.upper()} did not finish within {budget:g}s") from None
