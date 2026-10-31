"""Tool schema + executor for the logged-in customer's own shipments —
real per-user data from models/shipment.py (status, pickup time, estimated
delivery), as opposed to the generic knowledge-base text about service types."""

from typing import Optional

from beanie import PydanticObjectId

from models.shipment import TERMINAL_STATUSES, Shipment
from utils.dates import friendly_date

TOOL_GET_MY_SHIPMENTS = {
    "name": "get_my_shipments",
    "description": "Look up the logged-in customer's own recent shipments: tracking number, status, scheduled pickup time and estimated delivery. Call this when the user asks about THEIR parcels, pickups or delivery dates without giving a tracking number. Each shipment has isActive (false once delivered, cancelled or returned).",
    "input_schema": {"type": "object", "properties": {}, "required": []},
}


async def execute_get_my_shipments(current_user: Optional[dict] = None) -> dict:
    if not current_user or current_user.get("role") != "user":
        return {"note": "The user is not logged in as a customer, so their shipments aren't accessible. Tell them to log in, or ask for a tracking number instead."}

    shipments = (
        await Shipment.find(Shipment.customerId == PydanticObjectId(current_user["id"]))
        .sort(-Shipment.createdAt)
        .limit(5)
        .to_list()
    )
    if not shipments:
        return {"shipments": [], "note": "No shipments on file for this customer."}

    return {
        "shipments": [
            {
                "trackingNumber": s.trackingNumber,
                "status": s.status,
                "isActive": s.status not in TERMINAL_STATUSES,
                "serviceType": s.serviceType,
                "pickupScheduledAt": s.pickupScheduledAt.isoformat() if s.pickupScheduledAt else None,
                "estimatedDelivery": s.estimatedDelivery.isoformat() if s.estimatedDelivery else None,
                # Ready-made customer-facing dates: quote these exactly (never "today"/"tomorrow"/"in N days").
                "pickupScheduledText": friendly_date(s.pickupScheduledAt),
                "estimatedDeliveryText": friendly_date(s.estimatedDelivery),
            }
            for s in shipments
        ]
    }
