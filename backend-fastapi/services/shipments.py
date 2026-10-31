"""Shipment lifecycle logic shared by routes/shipments.py (REST) and the AI
tools. All status changes go through change_status(), so the transition
rules, role permissions, tracking-log side effects, and the real-time
Socket.IO notification live in exactly one place.

Concurrency: every mutation is a single conditional update guarded by the shipment's
`rev` counter (optimistic concurrency control). A request validates against the
snapshot it read; if another request changed the document in the meantime the
conditional update matches nothing and the request is re-validated against the fresh
state (assignment, cancellation) or rejected with 409 (a status report about a state
that has since moved on). Two requests can therefore never both "win" the same
transition, and one can never silently overwrite the other."""

import logging
from datetime import datetime
from typing import Any, Dict, Optional

from beanie import PydanticObjectId
from pymongo import ReturnDocument

from models.shipment import (
    AGENT_SETTABLE,
    CUSTOMER_CANCELLABLE,
    TERMINAL_STATUSES,
    Shipment,
    StatusEvent,
    allowed_next_statuses,
)
from models.tracking_log import TrackingLog
from sockets import sio
from utils.dates import today_string

MAX_DELIVERY_ATTEMPTS = 3
MAX_CAS_ATTEMPTS = 4
log = logging.getLogger("shipora.shipments")


class ShipmentError(Exception):
    def __init__(self, status_code: int, message: str):
        super().__init__(message)
        self.status_code = status_code
        self.message = message


def shipment_room(tracking_number: str) -> str:
    return f"shipment:{tracking_number}"


def can_view(shipment: Shipment, actor: dict) -> bool:
    role, uid = actor.get("role"), actor.get("id")
    if role == "admin":
        return True
    if role == "user":
        return str(shipment.customerId) == uid
    if role == "driver":
        return shipment.assignedAgentId is not None and str(shipment.assignedAgentId) == uid
    return False


def permitted_next_statuses(shipment: Shipment, actor: dict) -> list:
    """Statuses this actor may move the shipment to right now — the lifecycle
    table narrowed by role permissions and the preconditions change_status()
    enforces, so clients can render action buttons without mirroring the rules."""
    if not can_view(shipment, actor):
        return []
    allowed = allowed_next_statuses(shipment.status, shipment.statusHistory)
    role = actor.get("role")
    if role == "driver":
        allowed &= AGENT_SETTABLE
    elif role == "user":
        allowed = allowed & {"CANCELLED"} if shipment.status in CUSTOMER_CANCELLABLE else set()
    if shipment.assignedAgentId is None:
        allowed -= {"PICKED_UP", "IN_TRANSIT", "OUT_FOR_DELIVERY", "DELIVERED"}
    if shipment.deliveryAttempts >= MAX_DELIVERY_ATTEMPTS:
        allowed.discard("OUT_FOR_DELIVERY")
    return sorted(allowed)


async def _update_agent_log(agent_id: PydanticObjectId, update: Dict[str, Any]) -> None:
    # Deliberately does NOT touch `lastUpdated`: that field means "last GPS ping" (see the stale-GPS
    # logic) and a shipment status change is not a location report.
    now = datetime.utcnow()
    update.setdefault("$set", {}).update({"updatedAt": now})
    update.setdefault("$setOnInsert", {}).update({"createdAt": now, "isActive": True})
    await TrackingLog.get_motor_collection().find_one_and_update(
        {"driverId": agent_id, "date": today_string()},
        update,
        upsert=True,
        return_document=ReturnDocument.AFTER,
    )


async def notify(shipment: Shipment, event: str = "shipment.status_changed") -> None:
    await sio.emit(
        "shipment:update",
        {
            "trackingNumber": shipment.trackingNumber,
            "status": shipment.status,
            "updatedAt": shipment.updatedAt.isoformat(timespec="milliseconds") + "Z" if shipment.updatedAt else None,
        },
        room=shipment_room(shipment.trackingNumber),
    )


# ─── optimistic concurrency helpers ──────────────────────────────────────────
def _rev_filter(shipment: Shipment) -> dict:
    rev = shipment.rev or 0
    if rev == 0:  # documents written before the counter existed have no `rev` field
        return {"$or": [{"rev": 0}, {"rev": {"$exists": False}}]}
    return {"rev": rev}


async def _cas_update(shipment: Shipment, set_: Dict[str, Any], push: Optional[Dict[str, Any]] = None,
                      inc: Optional[Dict[str, Any]] = None) -> bool:
    """Applies the change only if the document still has the `rev` we validated against."""
    update: Dict[str, Any] = {"$set": {**set_, "updatedAt": datetime.utcnow()}, "$inc": {"rev": 1, **(inc or {})}}
    if push:
        update["$push"] = push
    raw = await Shipment.get_motor_collection().find_one_and_update({"_id": shipment.id, **_rev_filter(shipment)}, update)
    return raw is not None


def _event(status: str, role: str, actor_id: Optional[str], note: str) -> dict:
    return StatusEvent(status=status, at=datetime.utcnow(), byRole=role, byId=actor_id, note=note).model_dump()


def _validate_status_change(shipment: Shipment, new_status: str, actor: dict) -> None:
    role = actor.get("role")

    if role == "driver":
        if not can_view(shipment, actor):
            raise ShipmentError(403, "This shipment is not assigned to you.")
        if new_status not in AGENT_SETTABLE:
            raise ShipmentError(403, f"Delivery agents cannot set status {new_status}.")
    elif role == "user":
        if not can_view(shipment, actor):
            raise ShipmentError(403, "Not your shipment.")
        if new_status != "CANCELLED":
            raise ShipmentError(403, "Customers can only cancel a shipment.")
        if shipment.status not in CUSTOMER_CANCELLABLE:
            raise ShipmentError(409, f"A shipment can only be cancelled before pickup (current status: {shipment.status}).")
    elif role != "admin":
        raise ShipmentError(403, "Not allowed.")

    allowed = allowed_next_statuses(shipment.status, shipment.statusHistory)
    if new_status not in allowed:
        raise ShipmentError(
            409,
            f"Invalid transition {shipment.status} → {new_status}. Allowed: {', '.join(sorted(allowed)) or 'none (terminal state)'}.",
        )

    if new_status in ("PICKED_UP", "IN_TRANSIT", "OUT_FOR_DELIVERY", "DELIVERED") and shipment.assignedAgentId is None:
        raise ShipmentError(409, "Assign a delivery agent before moving this shipment forward.")
    if new_status == "OUT_FOR_DELIVERY" and shipment.deliveryAttempts >= MAX_DELIVERY_ATTEMPTS:
        raise ShipmentError(409, f"Maximum of {MAX_DELIVERY_ATTEMPTS} delivery attempts reached — return to origin instead.")


async def change_status(shipment: Shipment, new_status: str, actor: dict, note: str = "") -> Shipment:
    role = actor.get("role")
    observed_status = shipment.status
    for attempt in range(MAX_CAS_ATTEMPTS):
        _validate_status_change(shipment, new_status, actor)

        set_: Dict[str, Any] = {"status": new_status}
        if new_status == "DELIVERED":
            set_["deliveredAt"] = datetime.utcnow()
        inc = {"deliveryAttempts": 1} if new_status == "OUT_FOR_DELIVERY" else None
        if await _cas_update(shipment, set_, push={"statusHistory": _event(new_status, role, actor.get("id"), note)}, inc=inc):
            break

        # Lost the race. Re-read and decide: a status report about a state that has since moved on is
        # stale (409). Cancelling is state-independent within its window, and non-status edits (e.g. a
        # reassignment) don't invalidate the report, so those are re-validated against the new state.
        fresh = await Shipment.get(shipment.id)
        if fresh is None:
            raise ShipmentError(404, "Shipment not found.")
        log.info("shipment update conflict", extra={"event": "shipment_conflict", "tracking": shipment.trackingNumber,
                                                    "attempt": attempt + 1, "target": new_status})
        if fresh.status != observed_status and new_status != "CANCELLED":
            raise ShipmentError(409, "This shipment was updated by someone else just now — reload and check its current status.")
        shipment = fresh
    else:
        raise ShipmentError(409, "This shipment is being updated by someone else — please try again.")

    updated = await Shipment.get(shipment.id)
    if updated.assignedAgentId:
        sid = str(updated.id)
        if new_status == "OUT_FOR_DELIVERY":
            await _update_agent_log(updated.assignedAgentId, {"$addToSet": {"activeShipmentIds": sid}})
        elif new_status == "DELIVERED":
            await _update_agent_log(updated.assignedAgentId, {"$pull": {"activeShipmentIds": sid}, "$inc": {"deliveredCount": 1}})
        elif new_status in ("DELIVERY_FAILED", "CUSTOMER_UNAVAILABLE", "ADDRESS_ISSUE", "DAMAGED", "RETURN_TO_ORIGIN", "CANCELLED"):
            await _update_agent_log(updated.assignedAgentId, {"$pull": {"activeShipmentIds": sid}})

    log.info("shipment status changed", extra={"event": "shipment_status", "tracking": updated.trackingNumber, "status": new_status,
                                               "role": role, "user_id": actor.get("id")})
    await notify(updated)
    return updated


async def assign_agent(shipment: Shipment, agent_id: PydanticObjectId, actor: dict, pickup_at: Optional[datetime] = None,
                       note: Optional[str] = None) -> Shipment:
    from models.delivery_agent import DeliveryAgent

    if actor.get("role") != "admin":
        raise ShipmentError(403, "Admin only.")
    agent = await DeliveryAgent.get(agent_id)
    if not agent:
        raise ShipmentError(404, "Delivery agent not found.")

    previous_agent = shipment.assignedAgentId
    observed_status = shipment.status
    for attempt in range(MAX_CAS_ATTEMPTS):
        if shipment.status in TERMINAL_STATUSES:
            raise ShipmentError(409, f"Cannot assign an agent to a {shipment.status} shipment.")
        set_: Dict[str, Any] = {"assignedAgentId": agent.id}
        push = None
        if pickup_at:
            set_["pickupScheduledAt"] = pickup_at
        if shipment.status == "CREATED":
            # Assigning an agent is what schedules the pickup — exactly once: a concurrent assignment
            # that loses the race re-reads, sees PICKUP_SCHEDULED, and only changes the agent.
            set_["status"] = "PICKUP_SCHEDULED"
            set_.setdefault("pickupScheduledAt", datetime.utcnow())
            push = {"statusHistory": _event("PICKUP_SCHEDULED", "admin", actor.get("id"), note or f"Assigned to {agent.name}")}
        if await _cas_update(shipment, set_, push=push):
            break
        fresh = await Shipment.get(shipment.id)
        if fresh is None:
            raise ShipmentError(404, "Shipment not found.")
        previous_agent = fresh.assignedAgentId
        shipment = fresh
    else:
        raise ShipmentError(409, "This shipment is being updated by someone else — please try again.")

    updated = await Shipment.get(shipment.id)
    if previous_agent and previous_agent != agent.id:  # an in-flight stop moves with the shipment
        await _update_agent_log(previous_agent, {"$pull": {"activeShipmentIds": str(updated.id)}})
    log.info("shipment assigned", extra={"event": "shipment_assigned", "tracking": updated.trackingNumber,
                                         "agent_id": str(agent.id), "user_id": actor.get("id")})
    await notify(updated, "shipment.status_changed" if updated.status != observed_status else "shipment.agent_assigned")
    return updated
