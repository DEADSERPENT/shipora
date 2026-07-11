from datetime import datetime
from typing import Literal, Optional

from beanie import PydanticObjectId
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from auth_utils import get_current_user
from models.complaint import Complaint
from serializers import complaint_json
from tools.complaint_tools import insert_complaint

router = APIRouter(prefix="/api/complaints", tags=["Complaints"])


class ComplaintBody(BaseModel):
    subject: str
    category: Literal["missed_pickup", "vehicle_issue", "timing", "cleanliness", "driver_behaviour", "other"]
    description: str
    isAnonymous: bool = False


@router.post("", status_code=201, summary="Resident: submit complaint")
async def create_complaint(body: ComplaintBody, current_user: dict = Depends(get_current_user)):
    if current_user["role"] != "user":
        raise HTTPException(status_code=403, detail="Only residents can submit complaints.")
    if not body.subject or not body.category or not body.description:
        raise HTTPException(status_code=400, detail="Subject, category and description are required.")

    complaint = await insert_complaint(body.subject, body.category, body.description, body.isAnonymous, current_user)
    return complaint_json(complaint)


@router.get("", summary="Get complaints (admin: all; resident: own)")
async def get_complaints(current_user: dict = Depends(get_current_user)):
    if current_user["role"] == "admin":
        complaints = await Complaint.find_all().sort(-Complaint.createdAt).to_list()
        return [complaint_json(c, mask_anonymous=True) for c in complaints]

    complaints = (
        await Complaint.find(Complaint.residentId == PydanticObjectId(current_user["id"]))
        .sort(-Complaint.createdAt)
        .to_list()
    )
    return [complaint_json(c) for c in complaints]


class UpdateComplaintBody(BaseModel):
    status: Optional[Literal["open", "in_progress", "resolved", "closed"]] = None
    adminReply: Optional[str] = None


@router.put("/{complaint_id}", summary="Admin: update status and reply")
async def update_complaint(complaint_id: str, body: UpdateComplaintBody, current_user: dict = Depends(get_current_user)):
    if current_user["role"] != "admin":
        raise HTTPException(status_code=403, detail="Admin only.")

    complaint = await Complaint.get(PydanticObjectId(complaint_id))
    if not complaint:
        raise HTTPException(status_code=404, detail="Complaint not found.")

    if body.status:
        complaint.status = body.status
    if body.adminReply is not None:
        complaint.adminReply = body.adminReply
    if body.status in ("resolved", "closed"):
        complaint.resolvedAt = datetime.utcnow()

    await complaint.save()
    return complaint_json(complaint)
