import base64
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile

import config
from auth_utils import get_optional_user
from voice.pipeline import run_voice_turn

router = APIRouter(prefix="/api/voice", tags=["Voice"])


@router.post("/chat", summary="Voice round-trip: STT -> orchestrator -> TTS")
async def voice_chat(
    audio: UploadFile = File(...),
    sessionId: Optional[str] = Form(None),
    speak: bool = Form(True),
    current_user: Optional[dict] = Depends(get_optional_user),
):
    raw = await audio.read()
    if len(raw) > config.VOICE_MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="Recording too large.")

    result = await run_voice_turn(raw, audio.filename or "input.webm", sessionId, current_user, speak=speak)

    return {
        "reply": result["reply"],
        "source": result["source"],
        "agent": result["agent"],
        "sentiment": result["sentiment"],
        "transcript": result["transcript"],
        "audioBase64": base64.b64encode(result["audioBytes"]).decode() if result["audioBytes"] else None,
        "audioMimeType": "audio/mpeg",
        "latencyMs": result["latencyMs"],
    }
