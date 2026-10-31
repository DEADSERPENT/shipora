"""Tool for the delivery-agent role: the shipments assigned to the signed-in rider. Bound to the caller server-side."""

from typing import Optional

from beanie import PydanticObjectId

from models.shipment import TERMINAL_STATUSES, Shipment
from utils.dates import friendly_date

TOOL_GET_MY_ASSIGNMENTS = {
    "name": "get_my_assignments",
    "description": "List the shipments assigned to the signed-in delivery agent: tracking number, status, pickup and drop address, receiver name and phone, payment method, fare and estimated delivery. Call this for any question about 'my route', 'my deliveries', 'what's next' or 'what's pending'. isActive is false once delivered, cancelled or returned.",
    "input_schema": {"type": "object", "properties": {}, "required": []},
}


async def execute_get_my_assignments(current_user: Optional[dict] = None) -> dict:
    if not current_user or current_user.get("role") != "driver":
        return {"note": "Only a signed-in delivery agent has assigned deliveries."}
    rows = await Shipment.find(Shipment.assignedAgentId == PydanticObjectId(current_user["id"])).sort(-Shipment.createdAt).limit(15).to_list()
    if not rows:
        return {"shipments": [], "note": "Nothing is assigned to this agent right now. Operations assigns deliveries."}
    return {"shipments": [{
        "trackingNumber": s.trackingNumber,
        "status": s.status,
        "isActive": s.status not in TERMINAL_STATUSES,
        "pickupAddress": s.sender.address,
        "dropAddress": s.recipient.address,
        "receiverName": s.recipient.name,
        "receiverPhone": s.recipient.phone,
        "paymentMethod": s.paymentMethod,
        "fare": s.fare,
        "estimatedDeliveryText": friendly_date(s.estimatedDelivery),
    } for s in rows]}
