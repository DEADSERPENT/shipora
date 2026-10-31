"""Tool schemas + executors for delivery-issue status lookup and delivery-issue
creation. execute_create_complaint's actual DB write goes through
insert_complaint(), the same helper routes/complaints.py's REST endpoint
uses — the tool and the REST API never duplicate the write logic."""

from datetime import datetime, timedelta
from functools import partial
from typing import Optional

from beanie import PydanticObjectId
from fastapi import HTTPException

from models.delivery_issue import DeliveryIssue, IssueCategory
from models.shipment import Shipment

TOOL_GET_COMPLAINT_STATUS = {
    "name": "get_complaint_status",
    "description": "Look up the logged-in customer's own delivery issues (complaints) and their current status.",
    "input_schema": {"type": "object", "properties": {}, "required": []},
}

TOOL_LIST_COMPLAINTS_ADMIN = {
    "name": "list_complaints_admin",
    "description": (
        "Admin-only: list/filter delivery issues across ALL customers by status and/or category — "
        "for questions like 'how many delivery issues are pending today', 'show damaged-parcel issues', "
        "or 'delayed deliveries this week'. Not for the logged-in customer's own issues "
        "(use get_complaint_status for that)."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "status": {"type": "string", "enum": ["open", "in_progress", "resolved", "closed"], "description": "Omit for all statuses."},
            "category": {
                "type": "string",
                "enum": ["delayed_delivery", "lost_parcel", "damaged_parcel", "wrong_address", "agent_behaviour", "failed_delivery", "other"],
                "description": "Omit for all categories.",
            },
            "days": {"type": "integer", "description": "Only include complaints from the last N days. Omit for all time."},
        },
        "required": [],
    },
}

TOOL_DRAFT_COMPLAINT = {
    "name": "draft_complaint",
    "description": (
        "Prepare a delivery issue for the logged-in customer to confirm. This does NOT file anything: the system shows the customer a summary and files it only "
        "if they reply yes. Call it as soon as the customer describes a problem. Optionally link one of their shipments by trackingNumber."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "subject": {"type": "string", "description": "Short summary of the complaint."},
            "category": {
                "type": "string",
                "enum": ["delayed_delivery", "lost_parcel", "damaged_parcel", "wrong_address", "agent_behaviour", "failed_delivery", "other"],
            },
            "trackingNumber": {"type": "string", "description": "Tracking number of the affected shipment, if the user mentioned one."},
            "description": {"type": "string", "description": "Full description of the issue."},
            "isAnonymous": {"type": "boolean", "description": "Whether to hide the customer's identity from admin. Defaults to false."},
        },
        "required": ["subject", "category", "description"],
    },
}


async def insert_complaint(
    subject: str,
    category: IssueCategory,
    description: str,
    is_anonymous: bool,
    current_user: dict,
    tracking_number: Optional[str] = None,
) -> DeliveryIssue:
    """Shared with routes/complaints.py's REST create-complaint endpoint —
    the tool and the API never diverge on how a complaint gets written."""
    shipment = None
    if tracking_number:
        shipment = await Shipment.find_one(Shipment.trackingNumber == tracking_number.upper())
        if shipment is None or str(shipment.customerId) != current_user["id"]:
            raise HTTPException(status_code=404, detail="No shipment with that tracking number on your account.")

    complaint = DeliveryIssue(
        shipmentId=shipment.id if shipment else None,
        trackingNumber=shipment.trackingNumber if shipment else None,
        subject=subject,
        category=category,
        description=description,
        isAnonymous=is_anonymous,
        customerId=None if is_anonymous else PydanticObjectId(current_user["id"]),
        customerName=None if is_anonymous else current_user["name"],
        customerEmail=None if is_anonymous else current_user["email"],
    )
    await complaint.insert()
    return complaint


async def execute_get_complaint_status(current_user: dict = None) -> dict:
    if not current_user or current_user.get("role") != "user":
        return {"note": "The user is not logged in as a customer, so their issue history isn't accessible. Tell them to log in to check status."}

    complaints = (
        await DeliveryIssue.find(DeliveryIssue.customerId == PydanticObjectId(current_user["id"]))
        .sort(-DeliveryIssue.createdAt)
        .limit(5)
        .to_list()
    )
    if not complaints:
        return {"complaints": [], "note": "No delivery issues on file for this customer."}

    return {
        "complaints": [
            {"subject": c.subject, "category": c.category, "status": c.status, "adminReply": c.adminReply}
            for c in complaints
        ]
    }


async def execute_list_complaints_admin(
    status: Optional[str] = None,
    category: Optional[str] = None,
    days: Optional[int] = None,
    current_user: Optional[dict] = None,
) -> dict:
    if not current_user or current_user.get("role") != "admin":
        return {"note": "Only admins can list delivery issues across all customers. Tell the user to log in as an admin, or ask about their own complaints instead."}

    query = {}
    if status:
        query["status"] = status
    if category:
        query["category"] = category
    if days:
        query["createdAt"] = {"$gte": datetime.utcnow() - timedelta(days=days)}

    complaints = await DeliveryIssue.find(query).sort(-DeliveryIssue.createdAt).to_list()
    if not complaints:
        return {"complaints": [], "count": 0, "note": "No complaints match those filters."}

    return {
        "count": len(complaints),
        "complaints": [
            {
                "subject": c.subject,
                "category": c.category,
                "status": c.status,
                "customerName": c.customerName or "Anonymous",
                "createdAt": c.createdAt.isoformat() if c.createdAt else None,
            }
            for c in complaints[:20]
        ],
    }


async def execute_create_complaint(
    subject: str,
    category: str,
    description: str,
    isAnonymous: bool = False,
    trackingNumber: Optional[str] = None,
    current_user: Optional[dict] = None,
) -> dict:
    if not current_user or current_user.get("role") != "user":
        return {"created": False, "note": "The user is not logged in as a customer, so an issue can't be filed. Tell them to log in first."}

    try:
        complaint = await insert_complaint(subject, category, description, isAnonymous, current_user, trackingNumber)
    except HTTPException as err:
        return {"created": False, "note": err.detail}
    return {"created": True, "complaintId": str(complaint.id), "subject": complaint.subject, "status": complaint.status}


async def execute_draft_complaint(
    subject: str,
    category: str,
    description: str,
    isAnonymous: bool = False,
    trackingNumber: Optional[str] = None,
    current_user: Optional[dict] = None,
    session_id: Optional[str] = None,
) -> dict:
    """Creates a draft only (services/complaint_drafts.py files it after confirmation). Validates what can be checked now,
    so the customer is never asked to confirm something that is bound to fail."""
    from services import complaint_drafts

    if not current_user or current_user.get("role") != "user":
        return {"drafted": False, "note": "Only a signed-in customer can report a delivery issue."}
    if category not in complaint_drafts.CATEGORY_LABELS:
        return {"drafted": False, "note": "That category isn't one I can file."}
    if not subject.strip() or not description.strip():
        return {"drafted": False, "note": "A subject and a description are needed."}
    if trackingNumber:
        shipment = await Shipment.find_one(Shipment.trackingNumber == trackingNumber.strip().upper())
        if shipment is None or str(shipment.customerId) != current_user["id"]:
            return {"drafted": False, "note": "No shipment with that tracking number is on your account."}
    d = await complaint_drafts.create_draft(current_user, session_id, subject, category, description, trackingNumber, isAnonymous)
    return {"drafted": True, "draftId": d.draftId, "summary": complaint_drafts.summary_text(d)}


def bind_complaint_tools(current_user: Optional[dict], session_id: Optional[str] = None):
    """Returns (tool_schemas, executors) for agents/complaints_agent.py, with
    current_user bound server-side so the model can never supply/spoof one."""
    tools = [TOOL_GET_COMPLAINT_STATUS, TOOL_DRAFT_COMPLAINT, TOOL_LIST_COMPLAINTS_ADMIN]
    executors = {
        "get_complaint_status": partial(execute_get_complaint_status, current_user=current_user),
        "draft_complaint": partial(execute_draft_complaint, current_user=current_user, session_id=session_id),
        "list_complaints_admin": partial(execute_list_complaints_admin, current_user=current_user),
    }
    return tools, executors
