from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from beanie import PydanticObjectId
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from pymongo import ReturnDocument

from auth_utils import get_current_user
from models.delivery_agent import DeliveryAgent
from models.tracking_log import TrackingLog
from serializers import vehicle_log_json
from validation import ShortText
from sockets import broadcast_vehicles, vehicle_locations, vehicles_snapshot
from utils.dates import js_date_string, today_string

router = APIRouter(prefix="/api/vehicles", tags=["Delivery Vehicles"])


async def _populate(logs: List[TrackingLog], fields: List[str]) -> List[dict]:
    driver_ids = {log.driverId for log in logs}
    drivers = await DeliveryAgent.find({"_id": {"$in": list(driver_ids)}}).to_list()
    driver_map = {d.id: d for d in drivers}
    return [vehicle_log_json(log, driver_map.get(log.driverId), fields) for log in logs]


@router.get("/locations", summary="Get current live delivery-vehicle locations (in-memory)")
async def get_locations(_current_user: dict = Depends(get_current_user)):
    # Agent names, plates and positions are not public: signed-in users only.
    return vehicles_snapshot()


@router.get("/today", summary="Get today's logs")
async def get_today(current_user: dict = Depends(get_current_user)):
    if current_user["role"] != "admin":
        raise HTTPException(status_code=403, detail="Operations access required")
    logs = await TrackingLog.find(TrackingLog.date == today_string()).to_list()
    return await _populate(logs, ["name", "vehicleNo", "assignedArea", "phone"])


@router.get("/history", summary="30-day tracking history (agent: own logs; customer/admin: all logs)")
async def get_history(days: int = Query(30), current_user: dict = Depends(get_current_user)):
    if current_user["role"] not in ("driver", "admin"):
        raise HTTPException(status_code=403, detail="Not available for this account type")
    days = max(1, min(days, 30))
    today = datetime.now()
    dates = [js_date_string(today - timedelta(days=i)) for i in range(days)]

    if current_user["role"] == "driver":
        logs = (
            await TrackingLog.find(
                TrackingLog.driverId == PydanticObjectId(current_user["id"]),
                {"date": {"$in": dates}},
            )
            .sort(-TrackingLog.createdAt)
            .to_list()
        )
        return [vehicle_log_json(log) for log in logs]

    logs = await TrackingLog.find({"date": {"$in": dates}}).sort(-TrackingLog.createdAt).to_list()
    return await _populate(logs, ["name", "vehicleNo", "assignedArea"])


async def _upsert_log(driver_id: PydanticObjectId, update: Dict[str, Any]) -> TrackingLog:
    collection = TrackingLog.get_motor_collection()
    raw = await collection.find_one_and_update(
        {"driverId": driver_id, "date": today_string()},
        update,
        upsert=True,
        return_document=ReturnDocument.AFTER,
    )
    return await TrackingLog.get(raw["_id"])


class StatusBody(BaseModel):
    currentArea: Optional[ShortText] = None
    eta: Optional[str] = Field(default=None, max_length=30)
    areasCompleted: Optional[List[ShortText]] = Field(default=None, max_length=50)


@router.post("/status", summary="Delivery agent: update status (area + ETA)")
async def update_status(body: StatusBody, current_user: dict = Depends(get_current_user)):
    if current_user["role"] != "driver":
        raise HTTPException(status_code=403, detail="Delivery agents only")

    driver_id = PydanticObjectId(current_user["id"])
    now = datetime.utcnow()

    update: Dict[str, Any] = {
        "$set": {"currentArea": body.currentArea, "eta": body.eta, "lastUpdated": now, "updatedAt": now},
        "$setOnInsert": {"createdAt": now, "isActive": True, "lat": None, "lng": None},
    }
    if body.areasCompleted:
        update["$addToSet"] = {"areasCompleted": {"$each": body.areasCompleted}}
    else:
        # Real MongoDB rejects $setOnInsert and $addToSet on the same path
        # (ConflictingUpdateOperators), so only default the array when not adding to it.
        update["$setOnInsert"]["areasCompleted"] = []

    log = await _upsert_log(driver_id, update)

    driver_id_str = current_user["id"]
    if driver_id_str in vehicle_locations:
        vehicle_locations[driver_id_str] = {
            **vehicle_locations[driver_id_str],
            "currentArea": body.currentArea,
            "eta": body.eta,
            "areasCompleted": log.areasCompleted,
        }
        await broadcast_vehicles()

    return vehicle_log_json(log)


class AreaCompleteBody(BaseModel):
    area: ShortText


@router.post("/area-complete", summary="Delivery agent: add covered area")
async def area_complete(body: AreaCompleteBody, current_user: dict = Depends(get_current_user)):
    if current_user["role"] != "driver":
        raise HTTPException(status_code=403, detail="Delivery agents only")

    driver_id = PydanticObjectId(current_user["id"])
    now = datetime.utcnow()

    update = {
        "$addToSet": {"areasCompleted": body.area},
        "$set": {"lastUpdated": now, "updatedAt": now},
        "$setOnInsert": {"createdAt": now, "isActive": True, "currentArea": None, "eta": None, "lat": None, "lng": None},
    }
    log = await _upsert_log(driver_id, update)

    driver_id_str = current_user["id"]
    if driver_id_str in vehicle_locations:
        vehicle_locations[driver_id_str]["areasCompleted"] = log.areasCompleted
        await broadcast_vehicles()

    return vehicle_log_json(log)
