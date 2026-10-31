from collections import Counter
from datetime import datetime, timedelta
from typing import List, Literal, Optional

from beanie import PydanticObjectId
from fastapi import APIRouter, Depends, Header, HTTPException, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

import config
import ratelimit
from auth_utils import get_current_user, require_role
from services import booking, dispatch, geo, idempotency, pricing
from models.customer import Customer, Location
from models.delivery_agent import DeliveryAgent
from models.shipment import ParcelDetails, Party, Shipment, ShipmentStatus
from serializers import shipment_json, shipment_public_json
from validation import SHIPMENT_REF_RE, is_object_id
from services.shipments import ShipmentError, assign_agent, can_view, change_status, permitted_next_statuses

router = APIRouter(prefix="/api/shipments", tags=["Shipments"])

admin_only = require_role("admin", "Admin access required")



def _http(err: ShipmentError) -> HTTPException:
    return HTTPException(status_code=err.status_code, detail=err.message)


async def _find(id_or_tracking: str) -> Shipment:
    shipment = None
    ref = (id_or_tracking or "").strip()
    if is_object_id(ref):
        shipment = await Shipment.get(PydanticObjectId(ref))
    elif SHIPMENT_REF_RE.match(ref.upper()):
        shipment = await Shipment.find_one(Shipment.trackingNumber == ref.upper())
    if shipment is None:
        raise HTTPException(status_code=404, detail="Shipment not found.")
    return shipment


def _out(shipment: Shipment, agents: dict, actor: dict) -> dict:
    data = shipment_json(shipment, agents.get(shipment.assignedAgentId))
    data["allowedNextStatuses"] = permitted_next_statuses(shipment, actor)
    return data


async def _agent_map(shipments: List[Shipment]) -> dict:
    ids = {s.assignedAgentId for s in shipments if s.assignedAgentId}
    if not ids:
        return {}
    agents = await DeliveryAgent.find({"_id": {"$in": list(ids)}}).to_list()
    return {a.id: a for a in agents}


# ─── Create ────────────────────────────────────────────────────────────────
class CreateShipmentBody(BaseModel):
    sender: Optional[Party] = None  # defaults to the customer's own profile address
    recipient: Party
    parcel: ParcelDetails = Field(default_factory=ParcelDetails)
    serviceType: Literal["same_day"] = "same_day"  # Shipora is same-day only
    paymentMethod: Literal["cash", "upi"] = "cash"


class EstimateBody(BaseModel):
    pickup: Location
    drop: Location
    weightKg: Optional[float] = Field(default=None, gt=0, allow_inf_nan=False)


@router.post("/estimate", summary="Public: fare, distance and ETA for a pickup -> drop (Bengaluru only)", dependencies=[Depends(ratelimit.limited("track"))])
async def estimate_fare(body: EstimateBody):
    for loc, what in ((body.pickup, "pickup location"), (body.drop, "delivery location")):
        problem = geo.outside_reason(loc, what)
        if problem:
            raise HTTPException(status_code=422, detail=problem)
    try:
        return pricing.estimate(body.pickup, body.drop, body.weightKg)
    except pricing.EstimateError as err:
        raise HTTPException(status_code=422, detail=str(err))


@router.post("", status_code=201, summary="Customer: create a shipment", dependencies=[Depends(ratelimit.limited("shipment_create", by="actor"))])
async def create_shipment(body: CreateShipmentBody, current_user: dict = Depends(get_current_user),
                          idempotency_key: Optional[str] = Header(default=None, alias="Idempotency-Key")):
    """Send an `Idempotency-Key` header (8–128 chars) to make retries safe: repeating the same key returns the
    original shipment (HTTP 200, `Idempotent-Replay: true`) instead of creating another. Without a key,
    an identical request within DUPLICATE_WINDOW_SECONDS is treated as a double-click and answered the same way."""
    if current_user["role"] != "user":
        raise HTTPException(status_code=403, detail="Only customers can create shipments.")
    if idempotency_key is not None and not idempotency.KEY_RE.match(idempotency_key):
        raise HTTPException(status_code=422, detail="Idempotency-Key must be 8-128 characters: letters, digits, - _ : .")

    fp = idempotency.fingerprint(current_user["id"], body.model_dump(mode="json"))
    scope = None
    if idempotency_key:
        scope, ttl = f"{current_user['id']}:key:{idempotency_key}", timedelta(hours=config.idempotency_ttl_hours())
    elif config.duplicate_window_seconds() > 0:
        scope, ttl = f"{current_user['id']}:auto:{fp}", timedelta(seconds=config.duplicate_window_seconds())
    if scope:
        owned, record = await idempotency.claim(scope, fp, ttl)
        if not owned:
            if idempotency_key and record.get("fingerprint") != fp:
                raise HTTPException(status_code=422, detail="This Idempotency-Key was already used with a different request.")
            shipment_id = record.get("shipmentId") or await idempotency.wait_for_owner(scope)
            existing = await Shipment.get(shipment_id) if shipment_id else None
            if existing is None:
                raise HTTPException(status_code=409, detail="Your previous identical request is still being processed — retry in a moment.")
            agents = await _agent_map([existing])
            return JSONResponse(content=_out(existing, agents, current_user), status_code=200, headers={"Idempotent-Replay": "true"})

    try:
        return await _create_shipment(body, current_user, scope)
    except Exception:
        if scope:
            await idempotency.release(scope)
        raise


async def _create_shipment(body: CreateShipmentBody, current_user: dict, scope: Optional[str]):

    customer = await Customer.get(PydanticObjectId(current_user["id"]))
    if not customer:
        raise HTTPException(status_code=404, detail="Account not found")
    try:
        shipment = await booking.book(customer, body.recipient, body.parcel, body.paymentMethod, sender=body.sender,
                                      service_type=body.serviceType, created_by_id=current_user["id"])
    except ShipmentError as err:
        raise _http(err)
    if scope:
        await idempotency.complete(scope, shipment.id)
    dispatch.schedule(shipment.id)         # an agent is matched automatically a moment from now (AUTO_ASSIGN_ENABLED)
    return _out(shipment, {}, current_user)


# ─── Read ──────────────────────────────────────────────────────────────────
@router.get("/track/{tracking_number}", summary="Public: track a shipment by tracking number", dependencies=[Depends(ratelimit.limited("track"))])
async def track(tracking_number: str):
    ref = tracking_number.strip().upper()
    shipment = await Shipment.find_one(Shipment.trackingNumber == ref) if SHIPMENT_REF_RE.match(ref) else None
    if not shipment:
        raise HTTPException(status_code=404, detail="No shipment found with that tracking number.")
    return shipment_public_json(shipment)


@router.get("/stats/summary", summary="Admin: shipment counts by status")
async def stats(_admin: dict = Depends(admin_only)):
    shipments = await Shipment.find_all().to_list()
    by_status = Counter(s.status for s in shipments)
    return {
        "total": len(shipments),
        "byStatus": dict(by_status),
        "unassigned": sum(1 for s in shipments if s.assignedAgentId is None and s.status == "CREATED"),
    }


@router.get("", summary="List shipments (customer: own; agent: assigned; admin: all)")
async def list_shipments(status: Optional[ShipmentStatus] = Query(None), current_user: dict = Depends(get_current_user)):
    role, uid = current_user["role"], PydanticObjectId(current_user["id"])
    query: dict = {}
    if role == "user":
        query["customerId"] = uid
    elif role == "driver":
        query["assignedAgentId"] = uid
    if status:
        query["status"] = status
    shipments = await Shipment.find(query).sort(-Shipment.createdAt).to_list()
    agents = await _agent_map(shipments)
    return [_out(s, agents, current_user) for s in shipments]


@router.get("/{id_or_tracking}", summary="Get one shipment by id or tracking number")
async def get_shipment(id_or_tracking: str, current_user: dict = Depends(get_current_user)):
    shipment = await _find(id_or_tracking)
    if not can_view(shipment, current_user):
        raise HTTPException(status_code=403, detail="You do not have access to this shipment.")
    agents = await _agent_map([shipment])
    return _out(shipment, agents, current_user)


# ─── Update ────────────────────────────────────────────────────────────────
class AssignBody(BaseModel):
    agentId: str = Field(max_length=64)
    pickupScheduledAt: Optional[datetime] = None


@router.put("/{id_or_tracking}/assign", summary="Admin: assign a delivery agent (schedules pickup if new)")
async def assign(id_or_tracking: str, body: AssignBody, current_user: dict = Depends(admin_only)):
    if not is_object_id(body.agentId):
        raise HTTPException(status_code=400, detail="Invalid agentId.")
    shipment = await _find(id_or_tracking)
    try:
        shipment = await assign_agent(shipment, PydanticObjectId(body.agentId), current_user, body.pickupScheduledAt)
    except ShipmentError as err:
        raise _http(err)
    agents = await _agent_map([shipment])
    return _out(shipment, agents, current_user)


class StatusBody(BaseModel):
    status: ShipmentStatus
    note: str = Field(default="", max_length=500)


@router.post("/{id_or_tracking}/status", summary="Change shipment status (role-gated, transition-validated)")
async def update_status(id_or_tracking: str, body: StatusBody, current_user: dict = Depends(get_current_user)):
    shipment = await _find(id_or_tracking)
    try:
        shipment = await change_status(shipment, body.status, current_user, body.note)
    except ShipmentError as err:
        raise _http(err)
    agents = await _agent_map([shipment])
    return _out(shipment, agents, current_user)
