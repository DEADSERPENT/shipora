from fastapi import APIRouter, Depends, Query

from auth_utils import require_role
from models.customer import Customer
from models.delivery_agent import DeliveryAgent
from models.shipment import Shipment
from models.tracking_log import TrackingLog
from serializers import driver_profile_json, vehicle_log_json
from utils.dates import today_string

router = APIRouter(prefix="/api/admin", tags=["Admin"])

admin_only = require_role("admin", "Admin access required")


async def _populate(logs, fields):
    driver_ids = {log.driverId for log in logs}
    drivers = await DeliveryAgent.find({"_id": {"$in": list(driver_ids)}}).to_list()
    driver_map = {d.id: d for d in drivers}
    return [vehicle_log_json(log, driver_map.get(log.driverId), fields) for log in logs]


@router.get("/stats", summary="Overall stats + today's logs")
async def get_stats(_admin: dict = Depends(admin_only)):
    today = today_string()
    total_drivers = await DeliveryAgent.find_all().count()
    total_customers = await Customer.find_all().count()
    today_logs = await TrackingLog.find(TrackingLog.date == today).to_list()

    active_today = sum(1 for log in today_logs if log.isActive)
    total_areas_completed = sum(len(log.areasCompleted) for log in today_logs)
    populated_logs = await _populate(today_logs, ["name", "vehicleNo", "assignedArea", "phone"])

    shipments = await Shipment.find_all().to_list()
    active_shipments = sum(1 for s in shipments if s.status not in ("DELIVERED", "CANCELLED", "RETURN_TO_ORIGIN"))

    return {
        "totalDrivers": total_drivers,
        "totalCustomers": total_customers,
        "totalShipments": len(shipments),
        "activeShipments": active_shipments,
        "deliveredToday": sum(log.deliveredCount for log in today_logs),
        "activeToday": active_today,
        "totalAreasCompleted": total_areas_completed,
        "todayLogs": populated_logs,
    }


@router.get("/logs", summary="Logs filtered by date")
async def get_logs(date: str = Query(None), _admin: dict = Depends(admin_only)):
    date = date or today_string()
    logs = await TrackingLog.find(TrackingLog.date == date).sort(-TrackingLog.lastUpdated).to_list()
    return await _populate(logs, ["name", "vehicleNo", "assignedArea", "phone", "email"])


@router.get("/drivers", summary="All delivery agents with today's log")
async def get_drivers(_admin: dict = Depends(admin_only)):
    drivers = await DeliveryAgent.find_all().sort(-DeliveryAgent.createdAt).to_list()
    today_logs = await TrackingLog.find(TrackingLog.date == today_string()).to_list()
    log_map = {log.driverId: log for log in today_logs}

    result = []
    for d in drivers:
        entry = driver_profile_json(d)
        log = log_map.get(d.id)
        entry["todayLog"] = vehicle_log_json(log) if log else None
        result.append(entry)
    return result
