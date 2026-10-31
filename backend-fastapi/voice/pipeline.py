"""Business logic for both chat channels — routes/chat.py and
routes/voice.py are thin HTTP-only wrappers around run_text_turn() and
run_voice_turn() respectively. Centralizing it here means neither route
duplicates the memory/orchestrator/analytics sequence, and it's the one
place that needs to change if that sequence ever changes.
"""

import logging
import asyncio
import time
from typing import Optional

import config
from beanie import PydanticObjectId
from fastapi import HTTPException

from agents.orchestrator import route_and_reply
from agents.roles import user_text
from memory.conversation_memory import append_turn, get_history
from models.chat_analytics import ChatAnalytics
from services import metrics, ollama_client
from services.stt import transcribe_audio
from services.tts import synthesize_speech
from voice.transcript_fix import fix_transcript
from sockets import emit_voice_stage
log = logging.getLogger("shipora.voice")

_TRANSCRIPT_MAX = 500
_REPLY_MAX = 800


async def log_analytics(session_id: Optional[str], current_user: Optional[dict], channel: str,
                         transcript: str, result: dict, latency_ms: dict, turn_metrics: Optional[dict] = None) -> None:
    """Analytics logging must never break the chat response — errors are
    swallowed, matching this app's existing tolerance for non-critical
    failures (e.g. the admin dashboard's bare `catch {}` around its own
    fetches)."""
    try:
        await ChatAnalytics(
            sessionId=session_id or "anonymous",
            userId=PydanticObjectId(current_user["id"]) if current_user else None,
            userRole=current_user.get("role") if current_user else None,
            channel=channel,
            transcript=transcript[:_TRANSCRIPT_MAX],
            reply=result["reply"][:_REPLY_MAX],
            agent=result["agent"],
            sentiment=result["sentiment"],
            source=result["source"],
            latencyMs=latency_ms,
            metrics=turn_metrics or {},
        ).insert()
    except Exception as err:
        log.warning("analytics logging failed", extra={"event": "analytics_failed", "error_type": type(err).__name__})


async def _remember_turn(session_id: Optional[str], message: str, result: dict) -> None:
    await append_turn(session_id, "user", message)
    await append_turn(session_id, "assistant", result["reply"], agent=result["agent"])


async def run_text_turn(message: str, session_id: Optional[str], current_user: Optional[dict]) -> dict:
    """Used by routes/chat.py. Conversation context comes from MongoDB
    (memory/conversation_memory.py) keyed by session_id, not from a
    client-sent history array — the backend is the source of truth once a
    session_id exists, so a follow-up ("KA01AB1234" after "which truck?")
    resolves correctly regardless of what the client remembers."""
    turn = metrics.start()
    t0 = time.perf_counter()
    with metrics.timed("db_history_ms"):
        history = await get_history(session_id)
    result = await route_and_reply(message, history, current_user, session_id=session_id)
    total_ms = int((time.perf_counter() - t0) * 1000)

    await _remember_turn(session_id, user_text(message), result)
    snap = turn.snapshot()
    await log_analytics(
        session_id, current_user, "text", user_text(message), result,
        {"stt": None, "llm": total_ms, "tts": None, "total": total_ms}, snap,
    )
    log.info("chat turn", extra={"event": "chat_turn", "channel": "text", "agent": result["agent"], "source": result["source"], "total_ms": total_ms, **snap})
    return result


async def run_voice_turn(
    audio_bytes: bytes,
    filename: str,
    session_id: Optional[str],
    current_user: Optional[dict],
    speak: bool = True,
) -> dict:
    """Used by routes/voice.py. Emits voice:stage Socket.IO events (see
    sockets.py) as it progresses through STT -> orchestrator (classify ->
    optional tool-calling -> final answer) -> TTS, so the frontend's
    conversation state machine transitions on real backend events."""
    turn = metrics.start()
    await emit_voice_stage(session_id, "transcribing")

    t0 = time.perf_counter()
    transcript = await transcribe_audio(audio_bytes, filename)
    stt_ms = int((time.perf_counter() - t0) * 1000)
    metrics.add_ms("stt_ms", stt_ms)
    if not transcript or not transcript.strip():
        raise HTTPException(status_code=422, detail="Voice input isn't available right now — please type your question instead.")
    raw_transcript = transcript.strip()
    transcript = fix_transcript(raw_transcript)
    if transcript != raw_transcript:
        log.info("transcript corrected", extra={"event": "transcript_corrected"})

    loop = asyncio.get_running_loop()

    def on_stage(stage: str, detail: str = None) -> None:
        # Called both from this coroutine's own thread (orchestrator's
        # "thinking" stage) and from agents/base.py's worker thread (tool
        # execution / generating_response) — run_coroutine_threadsafe is
        # legal (and thread-safe) from either.
        asyncio.run_coroutine_threadsafe(emit_voice_stage(session_id, stage, detail), loop)

    t1 = time.perf_counter()
    with metrics.timed("db_history_ms"):
        history = await get_history(session_id)
    budget = ollama_client.budget_override.set(config.OLLAMA_VOICE_TIMEOUT_SECONDS)
    try:
        result = await route_and_reply(transcript, history, current_user, on_stage=on_stage, session_id=session_id, channel="voice_auto")
    finally:
        ollama_client.budget_override.reset(budget)
    llm_ms = int((time.perf_counter() - t1) * 1000)

    t2 = time.perf_counter()
    audio_reply = await synthesize_speech(result["reply"]) if speak else None
    tts_ms = int((time.perf_counter() - t2) * 1000) if audio_reply else None
    metrics.add_ms("tts_ms", tts_ms or 0)

    latency = {"stt": stt_ms, "llm": llm_ms, "tts": tts_ms, "total": stt_ms + llm_ms + (tts_ms or 0)}

    await _remember_turn(session_id, transcript, result)
    snap = turn.snapshot()
    await log_analytics(session_id, current_user, "voice", transcript, result, latency, snap)
    log.info("chat turn", extra={"event": "chat_turn", "channel": "voice", "agent": result["agent"], "source": result["source"], "total_ms": latency["total"], **snap})

    return {**result, "transcript": transcript, "audioBytes": audio_reply, "latencyMs": latency}
