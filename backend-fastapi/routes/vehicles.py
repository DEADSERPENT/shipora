from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from beanie import PydanticObjectId
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from pymongo import ReturnDocument

from auth_utils import get_current_user
from models.driver import Driver
from models.vehicle_log import VehicleLog
from serializers import vehicle_log_json
from sockets import sio, vehicle_locations
from utils.dates import js_date_string, today_string

router = APIRouter(prefix="/api/vehicles", tags=["Vehicles"])


async def _populate(logs: List[VehicleLog], fields: List[str]) -> List[dict]:
    driver_ids = {log.driverId for log in logs}
    drivers = await Driver.find({"_id": {"$in": list(driver_ids)}}).to_list()
    driver_map = {d.id: d for d in drivers}
    return [vehicle_log_json(log, driver_map.get(log.driverId), fields) for log in logs]


@router.get("/locations", summary="Get current live vehicle locations (in-memory)")
async def get_locations():
    return vehicle_locations


@router.get("/today", summary="Get today's logs")
async def get_today(_current_user: dict = Depends(get_current_user)):
    logs = await VehicleLog.find(VehicleLog.date == today_string()).to_list()
    return await _populate(logs, ["name", "vehicleNo", "assignedArea", "phone"])


@router.get("/history", summary="30-day history (driver: own logs; resident/admin: all logs)")
async def get_history(days: int = Query(30), current_user: dict = Depends(get_current_user)):
    days = min(days, 30)
    today = datetime.now()
    dates = [js_date_string(today - timedelta(days=i)) for i in range(days)]

    if current_user["role"] == "driver":
        logs = (
            await VehicleLog.find(
                VehicleLog.driverId == PydanticObjectId(current_user["id"]),
                {"date": {"$in": dates}},
            )
            .sort(-VehicleLog.createdAt)
            .to_list()
        )
        return [vehicle_log_json(log) for log in logs]

    logs = await VehicleLog.find({"date": {"$in": dates}}).sort(-VehicleLog.createdAt).to_list()
    return await _populate(logs, ["name", "vehicleNo", "assignedArea"])


async def _upsert_log(driver_id: PydanticObjectId, update: Dict[str, Any]) -> VehicleLog:
    collection = VehicleLog.get_motor_collection()
    raw = await collection.find_one_and_update(
        {"driverId": driver_id, "date": today_string()},
        update,
        upsert=True,
        return_document=ReturnDocument.AFTER,
    )
    return await VehicleLog.get(raw["_id"])


class StatusBody(BaseModel):
    currentArea: Optional[str] = None
    eta: Optional[str] = None
    areasCompleted: Optional[List[str]] = None


@router.post("/status", summary="Driver: update status (area + ETA)")
async def update_status(body: StatusBody, current_user: dict = Depends(get_current_user)):
    if current_user["role"] != "driver":
        raise HTTPException(status_code=403, detail="Drivers only")

    driver_id = PydanticObjectId(current_user["id"])
    now = datetime.utcnow()

    update: Dict[str, Any] = {
        "$set": {"currentArea": body.currentArea, "eta": body.eta, "lastUpdated": now, "updatedAt": now},
        "$setOnInsert": {"createdAt": now, "isActive": True, "lat": None, "lng": None, "areasCompleted": []},
    }
    if body.areasCompleted:
        update["$addToSet"] = {"areasCompleted": {"$each": body.areasCompleted}}

    log = await _upsert_log(driver_id, update)

    driver_id_str = current_user["id"]
    if driver_id_str in vehicle_locations:
        vehicle_locations[driver_id_str] = {
            **vehicle_locations[driver_id_str],
            "currentArea": body.currentArea,
            "eta": body.eta,
            "areasCompleted": log.areasCompleted,
        }
        await sio.emit("vehicles:update", vehicle_locations)

    return vehicle_log_json(log)


class AreaCompleteBody(BaseModel):
    area: str


@router.post("/area-complete", summary="Driver: add completed area")
async def area_complete(body: AreaCompleteBody, current_user: dict = Depends(get_current_user)):
    if current_user["role"] != "driver":
        raise HTTPException(status_code=403, detail="Drivers only")

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
        await sio.emit("vehicles:update", vehicle_locations)

    return vehicle_log_json(log)
