from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from auth_utils import get_optional_user
from voice.pipeline import run_text_turn

router = APIRouter(prefix="/api/chat", tags=["Chat"])


class ChatBody(BaseModel):
    message: str
    history: list = []  # kept for API compatibility; ignored once sessionId gives the backend real memory — see voice/pipeline.py
    sessionId: Optional[str] = None


@router.post("", summary="EcoBot chat")
async def chat(body: ChatBody, current_user: Optional[dict] = Depends(get_optional_user)):
    message = body.message.strip()
    if not message:
        raise HTTPException(status_code=400, detail="Message is required.")
    return await run_text_turn(message, body.sessionId, current_user)
