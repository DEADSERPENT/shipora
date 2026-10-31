import base64
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, Response, UploadFile
from pydantic import BaseModel, Field

import config
import ratelimit
from auth_utils import get_optional_user
from services.stt import transcribe_audio
from services.tts import audio_mime_type, synthesize_speech
from voice.transcript_fix import fix_transcript
from voice.pipeline import run_voice_turn

router = APIRouter(prefix="/api/voice", tags=["Voice"])


@router.post("/chat", summary="Voice round-trip: STT -> orchestrator -> TTS", dependencies=[Depends(ratelimit.limited("voice", by="actor"))])
async def voice_chat(
    audio: UploadFile = File(...),
    sessionId: Optional[str] = Form(None, max_length=100, pattern=r"^[A-Za-z0-9_\-:.]+$"),
    speak: bool = Form(True),
    current_user: Optional[dict] = Depends(get_optional_user),
):
    # Read in chunks and stop at the cap so an oversized upload can't be pulled fully into memory first.
    limit = config.VOICE_MAX_UPLOAD_BYTES
    chunks, size = [], 0
    while chunk := await audio.read(64 * 1024):
        size += len(chunk)
        if size > limit:
            raise HTTPException(status_code=413, detail="Recording too large.")
        chunks.append(chunk)
    raw = b"".join(chunks)

    result = await run_voice_turn(raw, audio.filename or "input.webm", sessionId, current_user, speak=speak)

    return {
        "reply": result["reply"],
        "source": result["source"],
        "agent": result["agent"],
        "sentiment": result["sentiment"],
        "transcript": result["transcript"],
        "audioBase64": base64.b64encode(result["audioBytes"]).decode() if result["audioBytes"] else None,
        "audioMimeType": audio_mime_type(result["audioBytes"]) if result["audioBytes"] else None,
        "latencyMs": result["latencyMs"],
    }


async def _read_capped(audio: UploadFile) -> bytes:
    limit = config.VOICE_MAX_UPLOAD_BYTES
    chunks, size = [], 0
    while chunk := await audio.read(64 * 1024):
        size += len(chunk)
        if size > limit:
            raise HTTPException(status_code=413, detail="Recording too large.")
        chunks.append(chunk)
    return b"".join(chunks)


@router.post("/transcribe", summary="Dictation: speech -> text only. Nothing is stored and nothing is sent to the assistant",
             dependencies=[Depends(ratelimit.limited("voice", by="actor"))])
async def transcribe(audio: UploadFile = File(...)):
    """Used when the browser cannot recognise speech itself. Returns the text for the person to review and edit in the chat
    box; they send it (or not) through the normal chat endpoint, so every authorization and confirmation rule applies to it
    exactly as to typed text. The recording lives only in memory for this request."""
    raw = await _read_capped(audio)
    if not raw:
        raise HTTPException(status_code=422, detail="That recording was empty — please try again.")
    text = await transcribe_audio(raw, audio.filename or "input.webm")
    if not text or not text.strip():
        raise HTTPException(status_code=422, detail="I couldn't make out any speech. Please try again, or type your question instead.")
    return {"text": fix_transcript(text.strip())}


class SpeakBody(BaseModel):
    text: str = Field(min_length=1, max_length=800)


@router.post("/speak", summary="Read-aloud: text -> audio. Nothing is stored", dependencies=[Depends(ratelimit.limited("speak", by="actor"))])
async def speak(body: SpeakBody):
    audio = await synthesize_speech(body.text.strip())
    if not audio:
        raise HTTPException(status_code=503, detail="Spoken replies aren't available right now.")
    return Response(content=audio, media_type=audio_mime_type(audio), headers={"Cache-Control": "no-store"})
