"""Tool schemas + executors for complaint status lookup and complaint
creation. execute_create_complaint's actual DB write goes through
insert_complaint(), the same helper routes/complaints.py's REST endpoint
uses — the tool and the REST API never duplicate the write logic."""

from functools import partial
from typing import Literal, Optional

from beanie import PydanticObjectId

from models.complaint import Complaint

TOOL_GET_COMPLAINT_STATUS = {
    "name": "get_complaint_status",
    "description": "Look up the logged-in resident's own complaints and their current status.",
    "input_schema": {"type": "object", "properties": {}, "required": []},
}

TOOL_CREATE_COMPLAINT = {
    "name": "create_complaint",
    "description": (
        "File a new complaint for the logged-in resident. Only call this AFTER the user has "
        "explicitly confirmed you should file it — never call it on the first mention of a problem."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "subject": {"type": "string", "description": "Short summary of the complaint."},
            "category": {
                "type": "string",
                "enum": ["missed_pickup", "vehicle_issue", "timing", "cleanliness", "driver_behaviour", "other"],
            },
            "description": {"type": "string", "description": "Full description of the issue."},
            "isAnonymous": {"type": "boolean", "description": "Whether to hide the resident's identity from admin. Defaults to false."},
        },
        "required": ["subject", "category", "description"],
    },
}


async def insert_complaint(
    subject: str,
    category: Literal["missed_pickup", "vehicle_issue", "timing", "cleanliness", "driver_behaviour", "other"],
    description: str,
    is_anonymous: bool,
    current_user: dict,
) -> Complaint:
    """Shared with routes/complaints.py's REST create-complaint endpoint —
    the tool and the API never diverge on how a complaint gets written."""
    complaint = Complaint(
        subject=subject,
        category=category,
        description=description,
        isAnonymous=is_anonymous,
        residentId=None if is_anonymous else PydanticObjectId(current_user["id"]),
        residentName=None if is_anonymous else current_user["name"],
        residentEmail=None if is_anonymous else current_user["email"],
    )
    await complaint.insert()
    return complaint


async def execute_get_complaint_status(current_user: dict = None) -> dict:
    if not current_user or current_user.get("role") != "user":
        return {"note": "The user is not logged in as a resident, so their complaint history isn't accessible. Tell them to log in to check status."}

    complaints = (
        await Complaint.find(Complaint.residentId == PydanticObjectId(current_user["id"]))
        .sort(-Complaint.createdAt)
        .limit(5)
        .to_list()
    )
    if not complaints:
        return {"complaints": [], "note": "No complaints on file for this resident."}

    return {
        "complaints": [
            {"subject": c.subject, "category": c.category, "status": c.status, "adminReply": c.adminReply}
            for c in complaints
        ]
    }


async def execute_create_complaint(
    subject: str,
    category: str,
    description: str,
    isAnonymous: bool = False,
    current_user: Optional[dict] = None,
) -> dict:
    if not current_user or current_user.get("role") != "user":
        return {"created": False, "note": "The user is not logged in as a resident, so a complaint can't be filed. Tell them to log in first."}

    complaint = await insert_complaint(subject, category, description, isAnonymous, current_user)
    return {"created": True, "complaintId": str(complaint.id), "subject": complaint.subject, "status": complaint.status}


def bind_complaint_tools(current_user: Optional[dict]):
    """Returns (tool_schemas, executors) for agents/complaints_agent.py, with
    current_user bound server-side so the model can never supply/spoof one."""
    tools = [TOOL_GET_COMPLAINT_STATUS, TOOL_CREATE_COMPLAINT]
    executors = {
        "get_complaint_status": partial(execute_get_complaint_status, current_user=current_user),
        "create_complaint": partial(execute_create_complaint, current_user=current_user),
    }
    return tools, executors
