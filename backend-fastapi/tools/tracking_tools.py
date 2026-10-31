"""Tool schema + executor for live delivery-vehicle tracking. No prompts, no dispatch
logic — agents/tracking_agent.py owns the prompt and binds this tool."""

from datetime import datetime, timedelta

import config
from models.delivery_agent import DeliveryAgent
from models.tracking_log import TrackingLog
from utils.dates import today_string

TOOL_GET_VEHICLE_STATUS = {
    "name": "get_vehicle_status",
    "description": "Look up live status of active delivery vehicles today. Call this whenever the user asks where a delivery vehicle/agent is, its ETA, areas covered, or when a specific vehicle was last updated.",
    "input_schema": {
        "type": "object",
        "properties": {
            "area": {
                "type": "string",
                "description": "Area name to filter by, e.g. 'Koramangala'. Omit for all active vehicles.",
            },
            "vehicleNo": {
                "type": "string",
                "description": "A specific vehicle registration number to look up, e.g. 'KA01AB1234' — use this to re-check a vehicle already mentioned earlier in the conversation (e.g. the user asks 'when was it last updated') rather than guessing from memory.",
            },
        },
        "required": [],
    },
}


async def execute_get_vehicle_status(area: str = None, vehicleNo: str = None, current_user: dict = None) -> dict:
    if (current_user or {}).get("role") != "admin":
        return {"vehicles": [], "note": "The live fleet view is available to Operations accounts only."}
    # "Active" means reporting recently: a vehicle that stopped sending GPS is not running as far as the assistant is concerned.
    fresh_after = datetime.utcnow() - timedelta(seconds=config.gps_stale_after_seconds())
    logs = await TrackingLog.find(TrackingLog.date == today_string(), TrackingLog.isActive == True,  # noqa: E712
                                  TrackingLog.lastUpdated >= fresh_after).to_list()
    if area:
        logs = [log for log in logs if area.lower() in (log.currentArea or "").lower()]

    driver_ids = {log.driverId for log in logs}
    drivers = await DeliveryAgent.find({"_id": {"$in": list(driver_ids)}}).to_list()
    driver_map = {d.id: d for d in drivers}

    if vehicleNo:
        logs = [log for log in logs if driver_map.get(log.driverId) and driver_map[log.driverId].vehicleNo == vehicleNo.upper()]

    if not logs:
        return {"vehicles": [], "note": f"No active vehicles found{f' for {area}' if area else ''}{f' matching {vehicleNo}' if vehicleNo else ''}."}

    return {
        "vehicles": [
            {
                "vehicleNo": driver_map[log.driverId].vehicleNo if log.driverId in driver_map else None,
                "driverName": driver_map[log.driverId].name if log.driverId in driver_map else None,
                "currentArea": log.currentArea,
                "eta": log.eta,
                "areasCompleted": log.areasCompleted,
                "lastUpdated": log.lastUpdated.isoformat() if log.lastUpdated else None,
            }
            for log in logs
        ]
    }
