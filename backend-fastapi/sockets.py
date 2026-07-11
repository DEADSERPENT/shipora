from datetime import datetime
from typing import Any, Dict

import socketio
from pymongo import ReturnDocument

import config
from utils.dates import today_string

sio = socketio.AsyncServer(async_mode="asgi", cors_allowed_origins=config.CLIENT_URL)

# In-memory store for active vehicle locations, mirrors server.js's vehicleLocations
vehicle_locations: Dict[str, Any] = {}


@sio.event
async def connect(sid, environ):
    print(f"📡 Client connected: {sid}")
    await sio.emit("vehicles:initial", vehicle_locations, to=sid)


@sio.event
async def disconnect(sid):
    print(f"📡 Client disconnected: {sid}")


@sio.on("driver:location")
async def driver_location(sid, data):
    driver_id = data.get("driverId")
    if not driver_id:
        return

    now_iso = datetime.utcnow().isoformat(timespec="milliseconds") + "Z"
    vehicle_locations[driver_id] = {
        "driverId": driver_id,
        "lat": data.get("lat"),
        "lng": data.get("lng"),
        "driverName": data.get("driverName"),
        "vehicleNo": data.get("vehicleNo"),
        "currentArea": data.get("currentArea") or "N/A",
        "eta": data.get("eta") or "N/A",
        "areasCompleted": data.get("areasCompleted") or [],
        "lastUpdated": now_iso,
        "isActive": True,
    }

    await sio.emit("vehicles:update", vehicle_locations)

    try:
        from beanie import PydanticObjectId

        from models.vehicle_log import VehicleLog

        areas_completed = data.get("areasCompleted") or []
        now = datetime.utcnow()
        update = {
            "$set": {
                "lat": data.get("lat"),
                "lng": data.get("lng"),
                "currentArea": data.get("currentArea"),
                "eta": data.get("eta"),
                "lastUpdated": now,
                "isActive": True,
                "updatedAt": now,
            },
            "$addToSet": {"areasCompleted": {"$each": areas_completed}},
            "$setOnInsert": {"createdAt": now},
        }
        collection = VehicleLog.get_motor_collection()
        await collection.find_one_and_update(
            {"driverId": PydanticObjectId(driver_id), "date": today_string()},
            update,
            upsert=True,
            return_document=ReturnDocument.AFTER,
        )
    except Exception as err:
        print(f"VehicleLog save error: {err}")


@sio.on("driver:offline")
async def driver_offline(sid, driver_id):
    if driver_id in vehicle_locations:
        vehicle_locations[driver_id]["isActive"] = False
        vehicle_locations[driver_id]["lastUpdated"] = datetime.utcnow().isoformat(timespec="milliseconds") + "Z"
        await sio.emit("vehicles:update", vehicle_locations)


# ─── Voice conversation stage events ────────────────────────────────────────
# Scoped per-session (room), never broadcast — unlike vehicle updates, a
# conversation's stage events are private to whoever's driving that session.

def _voice_room(session_id: str) -> str:
    return f"voice:{session_id}"


@sio.on("voice:join")
async def voice_join(sid, data):
    session_id = (data or {}).get("sessionId")
    if session_id:
        await sio.enter_room(sid, _voice_room(session_id))


@sio.on("voice:leave")
async def voice_leave(sid, data):
    session_id = (data or {}).get("sessionId")
    if session_id:
        await sio.leave_room(sid, _voice_room(session_id))


async def emit_voice_stage(session_id: str, stage: str, detail: str = None) -> None:
    """Called from voice/pipeline.py as a voice turn progresses through
    STT -> orchestrator -> tool-calling -> TTS, so the frontend's
    conversation state machine can transition on real backend events
    instead of guessed client-side timing."""
    if not session_id:
        return
    await sio.emit("voice:stage", {"stage": stage, "detail": detail}, room=_voice_room(session_id))
