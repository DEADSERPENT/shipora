from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from auth_utils import get_current_user
from models.support_config import SupportConfig
from serializers import support_config_json

router = APIRouter(prefix="/api/support", tags=["Support"])


@router.get("/config", summary="Public: get support config")
async def get_config():
    doc = await SupportConfig.find_one(SupportConfig.singleton == "config")
    return support_config_json(doc)


class SupportConfigBody(BaseModel):
    phone: Optional[str] = None
    email: Optional[str] = None
    whatsapp: Optional[str] = None
    officeAddress: Optional[str] = None
    officeHours: Optional[str] = None


@router.put("/config", summary="Admin: update support config")
async def update_config(body: SupportConfigBody, current_user: dict = Depends(get_current_user)):
    if current_user["role"] != "admin":
        raise HTTPException(status_code=403, detail="Admin only.")

    doc = await SupportConfig.find_one(SupportConfig.singleton == "config")
    updates = body.model_dump(exclude_unset=True)
    if doc is None:
        doc = SupportConfig(**updates)
        await doc.insert()
    else:
        for field, value in updates.items():
            setattr(doc, field, value)
        await doc.save()
    return support_config_json(doc)
