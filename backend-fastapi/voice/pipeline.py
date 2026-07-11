"""Business logic for both chat channels — routes/chat.py and
routes/voice.py are thin HTTP-only wrappers around run_text_turn() and
run_voice_turn() respectively. Centralizing it here means neither route
duplicates the memory/orchestrator/analytics sequence, and it's the one
place that needs to change if that sequence ever changes.
"""

import asyncio
import time
from typing import Optional

from beanie import PydanticObjectId
from fastapi import HTTPException

from agents.orchestrator import route_and_reply
from memory.conversation_memory import append_turn, get_history
from models.chat_analytics import ChatAnalytics
from services.stt import transcribe_audio
from services.tts import synthesize_speech
from sockets import emit_voice_stage

_TRANSCRIPT_MAX = 500
_REPLY_MAX = 800


async def log_analytics(session_id: Optional[str], current_user: Optional[dict], channel: str,
                         transcript: str, result: dict, latency_ms: dict) -> None:
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
        ).insert()
    except Exception as err:
        print(f"analytics logging failed: {err}")


async def _remember_turn(session_id: Optional[str], message: str, result: dict) -> None:
    await append_turn(session_id, "user", message)
    await append_turn(session_id, "assistant", result["reply"], agent=result["agent"])


async def run_text_turn(message: str, session_id: Optional[str], current_user: Optional[dict]) -> dict:
    """Used by routes/chat.py. Conversation context comes from MongoDB
    (memory/conversation_memory.py) keyed by session_id, not from a
    client-sent history array — the backend is the source of truth once a
    session_id exists, so a follow-up ("KA01AB1234" after "which truck?")
    resolves correctly regardless of what the client remembers."""
    t0 = time.perf_counter()
    history = await get_history(session_id)
    result = await route_and_reply(message, history, current_user)
    total_ms = int((time.perf_counter() - t0) * 1000)

    await _remember_turn(session_id, message, result)
    await log_analytics(
        session_id, current_user, "text", message, result,
        {"stt": None, "llm": total_ms, "tts": None, "total": total_ms},
    )
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
    await emit_voice_stage(session_id, "transcribing")

    t0 = time.perf_counter()
    transcript = await transcribe_audio(audio_bytes, filename)
    stt_ms = int((time.perf_counter() - t0) * 1000)
    if not transcript or not transcript.strip():
        raise HTTPException(status_code=422, detail="Voice input isn't available right now — please type your question instead.")
    transcript = transcript.strip()

    loop = asyncio.get_running_loop()

    def on_stage(stage: str, detail: str = None) -> None:
        # Called both from this coroutine's own thread (orchestrator's
        # "thinking" stage) and from agents/base.py's worker thread (tool
        # execution / generating_response) — run_coroutine_threadsafe is
        # legal (and thread-safe) from either.
        asyncio.run_coroutine_threadsafe(emit_voice_stage(session_id, stage, detail), loop)

    t1 = time.perf_counter()
    history = await get_history(session_id)
    result = await route_and_reply(transcript, history, current_user, on_stage=on_stage)
    llm_ms = int((time.perf_counter() - t1) * 1000)

    t2 = time.perf_counter()
    audio_reply = await synthesize_speech(result["reply"]) if speak else None
    tts_ms = int((time.perf_counter() - t2) * 1000) if audio_reply else None

    latency = {"stt": stt_ms, "llm": llm_ms, "tts": tts_ms, "total": stt_ms + llm_ms + (tts_ms or 0)}

    await _remember_turn(session_id, transcript, result)
    await log_analytics(session_id, current_user, "voice", transcript, result, latency)

    return {**result, "transcript": transcript, "audioBytes": audio_reply, "latencyMs": latency}
