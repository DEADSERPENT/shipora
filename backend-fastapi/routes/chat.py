from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

import ratelimit
from agents import roles
from auth_utils import get_optional_user
from voice.pipeline import run_text_turn

router = APIRouter(prefix="/api/chat", tags=["Chat"])


class ChatBody(BaseModel):
    message: str = Field(max_length=2000)
    history: list = Field(default=[], max_length=50)  # kept for API compatibility; ignored once sessionId gives the backend real memory — see voice/pipeline.py
    sessionId: Optional[str] = Field(default=None, max_length=100, pattern=r"^[A-Za-z0-9_\-:.]+$")


@router.get("/profile", summary="Role-specific ShipBot setup: greeting, suggestions, what it can do")
async def chat_profile(current_user: Optional[dict] = Depends(get_optional_user)):
    return roles.profile_for(current_user)


@router.post("", summary="ShipBot chat", dependencies=[Depends(ratelimit.limited("chat", by="actor"))])
async def chat(body: ChatBody, current_user: Optional[dict] = Depends(get_optional_user)):
    message = body.message.strip()
    if not message:
        raise HTTPException(status_code=400, detail="Message is required.")
    return await run_text_turn(message, body.sessionId, current_user)
