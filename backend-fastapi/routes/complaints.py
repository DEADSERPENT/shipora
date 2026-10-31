from datetime import datetime
from typing import Literal, Optional

from beanie import PydanticObjectId
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from auth_utils import get_current_user
from models.delivery_issue import DeliveryIssue, IssueCategory
from validation import LongText, ShortText, TrackingRef, is_object_id
from serializers import delivery_issue_json
from tools.complaint_tools import insert_complaint

router = APIRouter(prefix="/api/complaints", tags=["Delivery Issues"])


class ComplaintBody(BaseModel):
    subject: ShortText
    category: IssueCategory
    description: LongText
    isAnonymous: bool = False
    trackingNumber: Optional[TrackingRef] = None  # link the issue to a shipment (must belong to the customer)


@router.post("", status_code=201, summary="Customer: report a delivery issue")
async def create_complaint(body: ComplaintBody, current_user: dict = Depends(get_current_user)):
    if current_user["role"] != "user":
        raise HTTPException(status_code=403, detail="Only customers can report delivery issues.")

    complaint = await insert_complaint(body.subject, body.category, body.description, body.isAnonymous, current_user, body.trackingNumber)
    return delivery_issue_json(complaint)


@router.get("", summary="Get delivery issues (admin: all; customer: own)")
async def get_complaints(current_user: dict = Depends(get_current_user)):
    if current_user["role"] == "admin":
        complaints = await DeliveryIssue.find_all().sort(-DeliveryIssue.createdAt).to_list()
        return [delivery_issue_json(c, mask_anonymous=True) for c in complaints]

    complaints = (
        await DeliveryIssue.find(DeliveryIssue.customerId == PydanticObjectId(current_user["id"]))
        .sort(-DeliveryIssue.createdAt)
        .to_list()
    )
    return [delivery_issue_json(c) for c in complaints]


class UpdateComplaintBody(BaseModel):
    status: Optional[Literal["open", "in_progress", "resolved", "closed"]] = None
    adminReply: Optional[str] = Field(default=None, max_length=2000)


@router.put("/{complaint_id}", summary="Admin: update status and reply")
async def update_complaint(complaint_id: str, body: UpdateComplaintBody, current_user: dict = Depends(get_current_user)):
    if current_user["role"] != "admin":
        raise HTTPException(status_code=403, detail="Admin only.")

    if not is_object_id(complaint_id):
        raise HTTPException(status_code=404, detail="Delivery issue not found.")
    complaint = await DeliveryIssue.get(PydanticObjectId(complaint_id))
    if not complaint:
        raise HTTPException(status_code=404, detail="Delivery issue not found.")

    if body.status:
        complaint.status = body.status
    if body.adminReply is not None:
        complaint.adminReply = body.adminReply
    if body.status in ("resolved", "closed"):
        complaint.resolvedAt = datetime.utcnow()

    await complaint.save()
    return delivery_issue_json(complaint)
