from fastapi import APIRouter, Depends, Query

from auth_utils import require_role
from models.driver import Driver
from models.user import User
from models.vehicle_log import VehicleLog
from serializers import driver_profile_json, vehicle_log_json
from utils.dates import today_string

router = APIRouter(prefix="/api/admin", tags=["Admin"])

admin_only = require_role("admin", "Admin access required")


async def _populate(logs, fields):
    driver_ids = {log.driverId for log in logs}
    drivers = await Driver.find({"_id": {"$in": list(driver_ids)}}).to_list()
    driver_map = {d.id: d for d in drivers}
    return [vehicle_log_json(log, driver_map.get(log.driverId), fields) for log in logs]


@router.get("/stats", summary="Overall stats + today's logs")
async def get_stats(_admin: dict = Depends(admin_only)):
    today = today_string()
    total_drivers = await Driver.find_all().count()
    total_residents = await User.find_all().count()
    today_logs = await VehicleLog.find(VehicleLog.date == today).to_list()

    active_today = sum(1 for log in today_logs if log.isActive)
    total_areas_completed = sum(len(log.areasCompleted) for log in today_logs)
    populated_logs = await _populate(today_logs, ["name", "vehicleNo", "assignedArea", "phone"])

    return {
        "totalDrivers": total_drivers,
        "totalResidents": total_residents,
        "activeToday": active_today,
        "totalAreasCompleted": total_areas_completed,
        "todayLogs": populated_logs,
    }


@router.get("/logs", summary="Logs filtered by date")
async def get_logs(date: str = Query(None), _admin: dict = Depends(admin_only)):
    date = date or today_string()
    logs = await VehicleLog.find(VehicleLog.date == date).sort(-VehicleLog.lastUpdated).to_list()
    return await _populate(logs, ["name", "vehicleNo", "assignedArea", "phone", "email"])


@router.get("/drivers", summary="All drivers with today's log")
async def get_drivers(_admin: dict = Depends(admin_only)):
    drivers = await Driver.find_all().sort(-Driver.createdAt).to_list()
    today_logs = await VehicleLog.find(VehicleLog.date == today_string()).to_list()
    log_map = {log.driverId: log for log in today_logs}

    result = []
    for d in drivers:
        entry = driver_profile_json(d)
        log = log_map.get(d.id)
        entry["todayLog"] = vehicle_log_json(log) if log else None
        result.append(entry)
    return result
