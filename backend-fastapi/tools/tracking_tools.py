"""Tool schema + executor for live vehicle tracking. No prompts, no dispatch
logic — agents/tracking_agent.py owns the prompt and binds this tool."""

from models.driver import Driver
from models.vehicle_log import VehicleLog
from utils.dates import today_string

TOOL_GET_VEHICLE_STATUS = {
    "name": "get_vehicle_status",
    "description": "Look up live status of active waste-collection vehicles today. Call this whenever the user asks where a truck is, its ETA, completed areas, or when a specific vehicle was last updated.",
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


async def execute_get_vehicle_status(area: str = None, vehicleNo: str = None) -> dict:
    logs = await VehicleLog.find(VehicleLog.date == today_string(), VehicleLog.isActive == True).to_list()  # noqa: E712
    if area:
        logs = [log for log in logs if area.lower() in (log.currentArea or "").lower()]

    driver_ids = {log.driverId for log in logs}
    drivers = await Driver.find({"_id": {"$in": list(driver_ids)}}).to_list()
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
