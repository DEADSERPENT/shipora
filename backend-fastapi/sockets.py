import asyncio
import logging
import math
import re
import time
from datetime import datetime
from typing import Any, Dict, List, Optional, Set

import socketio
from pymongo import ReturnDocument

import config
from auth_utils import verify_token
from utils.dates import today_string
from validation import SHIPMENT_REF_RE

log = logging.getLogger("shipora.sockets")

# Heartbeats make the server notice dead connections (ping/pong) instead of holding them forever,
# and the small buffer keeps a single socket from pushing megabytes at us.
sio = socketio.AsyncServer(
    async_mode="asgi",
    cors_allowed_origins=config.cors_origins(),
    ping_interval=config.socket_ping_interval(),
    ping_timeout=config.socket_ping_timeout(),
    max_http_buffer_size=64 * 1024,
)

FLEET_ROOM = "fleet"          # signed-in sockets only: the live delivery-vehicle feed
FLEET_ROLES = ("user", "driver", "admin")
_SESSION_ID_RE = re.compile(r"^[A-Za-z0-9_\-:.]{1,100}$")

# In-memory store for active delivery-vehicle locations, mirrors server.js's vehicleLocations.
# Each entry: position + `lastUpdated` (time of the last GPS report) + `state`:
#   "live"    – reported within GPS_STALE_AFTER_SECONDS
#   "stale"   – stopped reporting (silently dropped off) — kept for "last seen", but not live
#   "offline" – the agent explicitly stopped sharing (or every connection dropped)
# `isActive` stays the field existing clients read: True only while state == "live".
vehicle_locations: Dict[str, Any] = {}

# sid -> decoded JWT claims for sockets that authenticated at connect time (None = anonymous).
socket_identity: Dict[str, Optional[dict]] = {}
_driver_sids: Dict[str, Set[str]] = {}      # agent id -> live connections publishing for them
_sid_driver: Dict[str, str] = {}            # reverse lookup
_last_accept: Dict[str, float] = {}         # agent id -> monotonic time of the last accepted location


def reset_state() -> None:
    """Clears in-memory socket bookkeeping (used by tests between runs)."""
    vehicle_locations.clear()
    socket_identity.clear()
    _driver_sids.clear()
    _sid_driver.clear()
    _last_accept.clear()


def _iso(dt: datetime) -> str:
    return dt.isoformat(timespec="milliseconds") + "Z"


def _parse(ts: Optional[str]) -> Optional[datetime]:
    try:
        return datetime.fromisoformat(ts.rstrip("Z")) if ts else None
    except (ValueError, AttributeError):
        return None


def _state_of(entry: dict) -> str:
    return entry.get("state") or ("live" if entry.get("isActive") else "offline")


def expire_stale_vehicles(now: Optional[datetime] = None) -> List[str]:
    """Marks vehicles that stopped reporting as stale. Returns the ids that changed."""
    now = now or datetime.utcnow()
    threshold = config.gps_stale_after_seconds()
    changed = []
    for driver_id, entry in vehicle_locations.items():
        if _state_of(entry) != "live":
            continue
        last = _parse(entry.get("lastUpdated"))
        if last is None or (now - last).total_seconds() > threshold:
            entry["state"] = "stale"
            entry["isActive"] = False
            changed.append(driver_id)
    return changed


def vehicles_snapshot(now: Optional[datetime] = None) -> Dict[str, Any]:
    """What clients are shown. Always applies expiry first, so a stale vehicle is never served as live
    even if the periodic sweeper hasn't run yet."""
    expire_stale_vehicles(now)
    return {k: {**v, "state": _state_of(v)} for k, v in vehicle_locations.items()}


async def broadcast_vehicles(now: Optional[datetime] = None) -> None:
    await sio.emit("vehicles:update", vehicles_snapshot(now), room=FLEET_ROOM)


async def _persist_inactive(driver_ids: List[str]) -> None:
    """Keeps the day's tracking log honest (admin 'active today' counts it)."""
    if not driver_ids:
        return
    try:
        from beanie import PydanticObjectId
        from models.tracking_log import TrackingLog

        await TrackingLog.get_motor_collection().update_many(
            {"driverId": {"$in": [PydanticObjectId(i) for i in driver_ids]}, "date": today_string()},
            {"$set": {"isActive": False, "updatedAt": datetime.utcnow()}},
        )
    except Exception as err:
        log.warning("could not persist vehicle inactivity", extra={"event": "persist_inactive_failed", "error_type": type(err).__name__})


async def sweep_stale_once(now: Optional[datetime] = None) -> List[str]:
    changed = expire_stale_vehicles(now)
    if changed:
        log.info("vehicles went stale", extra={"event": "vehicles_stale", "count": len(changed)})
        await _persist_inactive(changed)
        await broadcast_vehicles(now)
    return changed


async def sweep_stale_forever() -> None:
    """Background task (started by the app lifespan): without it, a vehicle whose app was killed would
    look live to everyone until somebody else happened to trigger an update."""
    while True:
        try:
            await sweep_stale_once()
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("stale-vehicle sweep failed", extra={"event": "sweep_failed"})
        await asyncio.sleep(config.gps_sweep_interval_seconds())


# ─── input helpers ───────────────────────────────────────────────────────────
def _number(value, lo: float, hi: float) -> Optional[float]:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value) if math.isfinite(value) and lo <= value <= hi else None


def _text(value, limit: int, default: str = "") -> str:
    return str(value).strip()[:limit] if value not in (None, "") else default


def _claims(sid: str) -> Optional[dict]:
    return socket_identity.get(sid)


# ─── connection lifecycle ────────────────────────────────────────────────────
@sio.event
async def connect(sid, environ, auth=None):
    """Anonymous connections are allowed (public shipment tracking and the assistant's voice progress
    events need them) but only signed-in sockets get the fleet feed or may publish a position. An
    invalid token simply behaves as anonymous."""
    claims = None
    token = auth.get("token") if isinstance(auth, dict) else None
    if isinstance(token, str) and token:
        try:
            claims = verify_token(token)
        except Exception:
            claims = None
    socket_identity[sid] = claims
    if claims and claims.get("role") == "driver" and claims.get("id"):
        # count every connection an agent has open, so one tab/app dropping doesn't take a live vehicle offline
        _driver_sids.setdefault(claims["id"], set()).add(sid)
        _sid_driver[sid] = claims["id"]
    log.info("socket connected", extra={"event": "socket_connect", "sid": sid, "role": (claims or {}).get("role", "anonymous")})
    if claims and claims.get("role") in FLEET_ROLES:
        await sio.enter_room(sid, FLEET_ROOM)
        await sio.emit("vehicles:initial", vehicles_snapshot(), to=sid)


@sio.event
async def disconnect(sid):
    socket_identity.pop(sid, None)
    driver_id = _sid_driver.pop(sid, None)
    log.info("socket disconnected", extra={"event": "socket_disconnect", "sid": sid})
    if driver_id:
        sids = _driver_sids.get(driver_id, set())
        sids.discard(sid)
        if not sids:
            _driver_sids.pop(driver_id, None)
            entry = vehicle_locations.get(driver_id)
            if entry and _state_of(entry) in ("live", "stale"):
                # Every connection that was publishing for this agent is gone without a goodbye.
                entry["isActive"], entry["state"], entry["lastUpdated"] = False, "offline", _iso(datetime.utcnow())
                await _persist_inactive([driver_id])
                await broadcast_vehicles()
                log.info("vehicle offline after disconnect", extra={"event": "vehicle_disconnected", "agent_id": driver_id})


def _reject(sid: str, reason: str, event: str) -> None:
    log.warning("socket event rejected", extra={"event": "socket_rejected", "sid": sid, "reason": reason, "socket_event": event})


@sio.on("driver:location")
async def driver_location(sid, data=None):
    claims = _claims(sid)
    if not isinstance(data, dict):
        return _reject(sid, "malformed", "driver:location")
    driver_id = data.get("driverId")
    if not claims or claims.get("role") != "driver":
        return _reject(sid, "not_an_agent", "driver:location")
    if driver_id != claims.get("id"):
        return _reject(sid, "agent_id_mismatch", "driver:location")   # nobody can publish as someone else
    lat, lng = _number(data.get("lat"), -90, 90), _number(data.get("lng"), -180, 180)
    if lat is None or lng is None:
        return _reject(sid, "bad_coordinates", "driver:location")

    # Flood control: an agent's app reports about once a second at most — a faster stream is ignored.
    interval = config.gps_min_interval_seconds()
    mono = time.monotonic()
    if interval > 0 and mono - _last_accept.get(driver_id, -1e9) < interval:
        return
    _last_accept[driver_id] = mono

    areas = [_text(a, 100) for a in (data.get("areasCompleted") or [])[:50]] if isinstance(data.get("areasCompleted"), list) else []
    await publish_vehicle_location(
        driver_id, claims.get("name"), claims.get("vehicleNo"), lat, lng,
        # display identity is taken from the signed token, never from the (client-controlled) payload
        current_area=_text(data.get("currentArea"), 100, "") or None, eta=_text(data.get("eta"), 30, "") or None,
        eta_minutes=_number(data.get("etaMinutes"), 0, 1440), distance_km=_number(data.get("distanceKm"), 0, 500),
        target=_text(data.get("target"), 30) or None, areas=areas)


async def publish_vehicle_location(driver_id: str, name: Optional[str], vehicle_no: Optional[str], lat: float, lng: float, *,
                                   current_area: Optional[str] = None, eta: Optional[str] = None, eta_minutes: Optional[float] = None,
                                   distance_km: Optional[float] = None, target: Optional[str] = None,
                                   areas: Optional[List[str]] = None) -> None:
    """A delivery agent's position report: updates the live vehicle store, tells everyone watching the fleet, and saves the day's
    tracking log. The one path for a real rider's phone (the `driver:location` event above) and for the rider simulator
    (services/simulator.py), so a simulated rider is indistinguishable from a real one to every client."""
    now = datetime.utcnow()
    areas = areas or []
    vehicle_locations[driver_id] = {
        "driverId": driver_id,
        "lat": lat,
        "lng": lng,
        "driverName": name,
        "vehicleNo": vehicle_no,
        "currentArea": current_area or "N/A",
        "eta": eta or "N/A",
        # live navigation figures from the rider's route (optional; absent for older clients)
        "etaMinutes": eta_minutes,
        "distanceKm": distance_km,
        "target": target,
        "areasCompleted": areas,
        "lastUpdated": _iso(now),
        "isActive": True,
        "state": "live",
    }
    await broadcast_vehicles(now)

    try:
        from beanie import PydanticObjectId
        from models.tracking_log import TrackingLog

        update = {
            "$set": {"lat": lat, "lng": lng, "currentArea": current_area, "eta": eta,
                     "lastUpdated": now, "isActive": True, "updatedAt": now},
            "$addToSet": {"areasCompleted": {"$each": areas}},
            "$setOnInsert": {"createdAt": now},
        }
        await TrackingLog.get_motor_collection().find_one_and_update(
            {"driverId": PydanticObjectId(driver_id), "date": today_string()},
            update,
            upsert=True,
            return_document=ReturnDocument.AFTER,
        )
    except Exception as err:
        log.warning("tracking log save failed", extra={"event": "tracking_save_failed", "error_type": type(err).__name__})


@sio.on("driver:offline")
async def driver_offline(sid, driver_id=None):
    claims = _claims(sid)
    if not claims or claims.get("role") != "driver" or claims.get("id") != driver_id:
        return _reject(sid, "not_the_owner", "driver:offline")
    if driver_id in vehicle_locations:
        vehicle_locations[driver_id]["isActive"] = False
        vehicle_locations[driver_id]["state"] = "offline"
        vehicle_locations[driver_id]["lastUpdated"] = _iso(datetime.utcnow())
        await _persist_inactive([driver_id])
        await broadcast_vehicles()


# ─── Shipment tracking rooms ────────────────────────────────────────────────
# Clients join a per-shipment room by tracking number and receive
# "shipment:update" events (emitted from services/shipments.py) on every
# status change. The tracking number is the access token, same as the public
# GET /api/shipments/track/{trackingNumber} endpoint. Rooms are per connection, so a dead connection
# stops receiving the moment it disconnects and a reconnecting client must (and does) join again;
# joining the same room twice is harmless — a socket is a member once.

def _tracking_ref(data) -> Optional[str]:
    ref = ((data or {}).get("trackingNumber") if isinstance(data, dict) else None)
    ref = ref.strip().upper() if isinstance(ref, str) else ""
    return ref if SHIPMENT_REF_RE.match(ref) else None


@sio.on("shipment:join")
async def shipment_join(sid, data=None):
    ref = _tracking_ref(data)
    if ref:
        await sio.enter_room(sid, f"shipment:{ref}")


@sio.on("shipment:leave")
async def shipment_leave(sid, data=None):
    ref = _tracking_ref(data)
    if ref:
        await sio.leave_room(sid, f"shipment:{ref}")


# ─── Voice conversation stage events ────────────────────────────────────────
# Scoped per-session (room), never broadcast — unlike vehicle updates, a
# conversation's stage events are private to whoever's driving that session.

def _voice_room(session_id: str) -> str:
    return f"voice:{session_id}"


def _session_id(data) -> Optional[str]:
    sid = data.get("sessionId") if isinstance(data, dict) else None
    return sid if isinstance(sid, str) and _SESSION_ID_RE.match(sid) else None


@sio.on("voice:join")
async def voice_join(sid, data=None):
    session_id = _session_id(data)
    if session_id:
        await sio.enter_room(sid, _voice_room(session_id))


@sio.on("voice:leave")
async def voice_leave(sid, data=None):
    session_id = _session_id(data)
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
