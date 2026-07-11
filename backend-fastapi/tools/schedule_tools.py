"""Tool schema + executor for the logged-in resident's own collection
schedule — real per-user data from models/user.py, not the static
schedule-format text the knowledge base uses for the generic "what
schedules exist" question."""

from typing import Optional

from beanie import PydanticObjectId

from models.user import User

TOOL_GET_COLLECTION_SCHEDULE = {
    "name": "get_collection_schedule",
    "description": "Look up the logged-in resident's own pickup schedule, waste type, and residence type. Call this when the user asks about THEIR schedule, not the general schedule options.",
    "input_schema": {"type": "object", "properties": {}, "required": []},
}


async def execute_get_collection_schedule(current_user: Optional[dict] = None) -> dict:
    if not current_user or current_user.get("role") != "user":
        return {"note": "The user is not logged in as a resident, so their personal schedule isn't accessible. Tell them to log in, or explain the general schedule options instead."}

    user = await User.get(PydanticObjectId(current_user["id"]))
    if not user:
        return {"note": "Resident record not found."}

    return {
        "pickupSchedule": user.pickupSchedule,
        "wasteType": user.wasteType,
        "residentType": user.residentType,
    }
