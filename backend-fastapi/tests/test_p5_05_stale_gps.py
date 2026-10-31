"""Phase 5 / item 5 — a vehicle that stops reporting must stop being "live"."""
import asyncio
import socket
from datetime import datetime, timedelta

import pytest
import socketio
import uvicorn

import config
import sockets
from main import app
from tests.conftest import register

pytestmark = pytest.mark.anyio

AID = "6ac600000000000000000001"


def put(driver_id=AID, age_seconds=0.0, active=True, now=None):
    now = now or datetime.utcnow()
    sockets.vehicle_locations[driver_id] = {
        "driverId": driver_id, "lat": 12.9, "lng": 77.6, "driverName": "A", "vehicleNo": "KA01", "currentArea": "X", "eta": "5",
        "areasCompleted": [], "isActive": active,
        "lastUpdated": (now - timedelta(seconds=age_seconds)).isoformat(timespec="milliseconds") + "Z",
    }
    return now


# ─── configuration ─────────────────────────────────────────────────────────
def test_threshold_is_configurable_not_hardcoded(monkeypatch):
    monkeypatch.delenv("GPS_STALE_AFTER_SECONDS", raising=False)
    assert config.gps_stale_after_seconds() == 90
    monkeypatch.setenv("GPS_STALE_AFTER_SECONDS", "30")
    assert config.gps_stale_after_seconds() == 30
    for bad in ("abc", "0", "-5", ""):
        monkeypatch.setenv("GPS_STALE_AFTER_SECONDS", bad)
        assert config.gps_stale_after_seconds() == 90, bad
    monkeypatch.setenv("GPS_SWEEP_INTERVAL_SECONDS", "5")
    assert config.gps_sweep_interval_seconds() == 5


# ─── pure expiry logic ─────────────────────────────────────────────────────
def test_fresh_location_is_live(monkeypatch):
    monkeypatch.setenv("GPS_STALE_AFTER_SECONDS", "90")
    now = put(age_seconds=10)
    snap = sockets.vehicles_snapshot(now)
    assert snap[AID]["isActive"] is True and snap[AID]["state"] == "live"


def test_old_location_becomes_stale(monkeypatch):
    monkeypatch.setenv("GPS_STALE_AFTER_SECONDS", "90")
    now = put(age_seconds=91)
    snap = sockets.vehicles_snapshot(now)
    assert snap[AID]["isActive"] is False and snap[AID]["state"] == "stale"
    assert snap[AID]["lat"] == 12.9                      # last known position is kept, just not "live"


def test_boundary_is_inclusive_of_the_threshold(monkeypatch):
    monkeypatch.setenv("GPS_STALE_AFTER_SECONDS", "90")
    now = put(age_seconds=89.9)
    assert sockets.vehicles_snapshot(now)[AID]["state"] == "live"
    now = put(age_seconds=90.1)
    assert sockets.vehicles_snapshot(now)[AID]["state"] == "stale"


def test_offline_is_distinct_from_stale_and_never_resurrects(monkeypatch):
    monkeypatch.setenv("GPS_STALE_AFTER_SECONDS", "90")
    now = put(age_seconds=5, active=False)
    sockets.vehicle_locations[AID]["state"] = "offline"
    assert sockets.vehicles_snapshot(now)[AID]["state"] == "offline"
    assert sockets.vehicles_snapshot(now)[AID]["isActive"] is False


def test_heartbeats_keep_a_stationary_vehicle_live(monkeypatch):
    monkeypatch.setenv("GPS_STALE_AFTER_SECONDS", "90")
    t0 = datetime.utcnow()
    for tick in range(10):                                # a parked agent re-sends every 30 s for 5 minutes
        now = t0 + timedelta(seconds=30 * tick)
        put(now=now)
        assert sockets.vehicles_snapshot(now + timedelta(seconds=29))[AID]["state"] == "live"
    assert sockets.vehicles_snapshot(t0 + timedelta(seconds=30 * 9 + 120))[AID]["state"] == "stale"   # ...until it stops


def test_expire_reports_only_what_changed(monkeypatch):
    monkeypatch.setenv("GPS_STALE_AFTER_SECONDS", "60")
    now = put("a" * 24, age_seconds=5)
    put("b" * 24, age_seconds=120, now=now)
    put("c" * 24, age_seconds=500, active=False, now=now)
    assert sockets.expire_stale_vehicles(now) == ["b" * 24]
    assert sockets.expire_stale_vehicles(now) == []       # idempotent: already stale


# ─── HTTP + AI tool honour it ──────────────────────────────────────────────
async def test_locations_endpoint_never_serves_stale_as_live(client, monkeypatch):
    monkeypatch.setenv("GPS_STALE_AFTER_SECONDS", "90")
    _, h = await register(client, "user", "c@t.test")
    put(age_seconds=300)
    r = await client.get("/api/vehicles/locations", headers=h)
    assert r.json()[AID]["isActive"] is False and r.json()[AID]["state"] == "stale"
    put(age_seconds=2)                                    # recovery
    assert (await client.get("/api/vehicles/locations", headers=h)).json()[AID]["isActive"] is True


async def test_ai_vehicle_tool_ignores_stale_vehicles(client, monkeypatch):
    from tools.tracking_tools import execute_get_vehicle_status
    from models.tracking_log import TrackingLog
    from utils.dates import today_string
    monkeypatch.setenv("GPS_STALE_AFTER_SECONDS", "90")
    agent, _ = await register(client, "driver", "a@t.test")
    from beanie import PydanticObjectId
    now = datetime.utcnow()
    log = TrackingLog(driverId=PydanticObjectId(agent["id"]), date=today_string(), currentArea="Koramangala", eta="5", isActive=True,
                      lastUpdated=now - timedelta(seconds=600))
    await log.insert()
    res = await execute_get_vehicle_status(area="Koramangala", current_user={"id": "0" * 24, "role": "admin"})
    assert res["vehicles"] == []                          # last ping 10 minutes ago -> not reported as running
    await TrackingLog.get_motor_collection().update_one({"_id": log.id}, {"$set": {"lastUpdated": now}})
    assert len((await execute_get_vehicle_status(area="Koramangala", current_user={"id": "0" * 24, "role": "admin"}))["vehicles"]) == 1


# ─── live sockets: sweeper pushes the change, offline/recovery paths ───────
def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture
async def live(client):
    port = _free_port()
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning", lifespan="off"))
    task = asyncio.create_task(server.serve())
    while not server.started:
        await asyncio.sleep(0.05)
    yield f"http://127.0.0.1:{port}"
    server.should_exit = True
    await task


async def _wait(cond, timeout=5.0):
    for _ in range(int(timeout / 0.05)):
        if cond():
            return True
        await asyncio.sleep(0.05)
    return False


async def test_sweeper_pushes_stale_transition_and_recovery(client, live, monkeypatch):
    monkeypatch.setenv("GPS_STALE_AFTER_SECONDS", "1")
    monkeypatch.setenv("GPS_SWEEP_INTERVAL_SECONDS", "0.2")
    agent, ah = await register(client, "driver", "a@t.test")
    _, ch = await register(client, "user", "c@t.test")
    updates = []
    watcher, agent_sock = socketio.AsyncClient(), socketio.AsyncClient()
    watcher.on("vehicles:update", lambda d: updates.append(d))
    await watcher.connect(live, auth={"token": ch["Authorization"].split()[1]})
    await agent_sock.connect(live, auth={"token": ah["Authorization"].split()[1]})
    sweeper = asyncio.create_task(sockets.sweep_stale_forever())

    loc = {"driverId": agent["id"], "lat": 12.9, "lng": 77.6, "driverName": "A", "vehicleNo": "KA09ZZ0001", "currentArea": "X", "eta": "1"}
    await agent_sock.emit("driver:location", loc)
    assert await _wait(lambda: updates and updates[-1].get(agent["id"], {}).get("state") == "live")

    # no further pings -> the server (not a client event) flips it to stale and tells the watchers
    assert await _wait(lambda: updates[-1].get(agent["id"], {}).get("state") == "stale", timeout=6)
    assert updates[-1][agent["id"]]["isActive"] is False
    from models.tracking_log import TrackingLog
    logs = await TrackingLog.find_all().to_list()
    assert logs and logs[0].isActive is False                       # persisted too (admin "active today" stays honest)

    # recovery: the next location report makes it live again
    await agent_sock.emit("driver:location", loc)
    assert await _wait(lambda: updates[-1].get(agent["id"], {}).get("state") == "live")
    assert (await TrackingLog.find_all().to_list())[0].isActive is True

    # explicit offline is reported as offline, not stale
    await agent_sock.emit("driver:offline", agent["id"])
    assert await _wait(lambda: updates[-1].get(agent["id"], {}).get("state") == "offline")

    sweeper.cancel()
    await watcher.disconnect()
    await agent_sock.disconnect()
