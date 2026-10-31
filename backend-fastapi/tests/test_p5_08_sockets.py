"""Phase 5 / item 8 — Socket.IO authentication, disconnect handling, reconnection and delivery guarantees."""
import asyncio
import socket

import pytest
import socketio
import uvicorn

import config
import sockets
from main import app
from tests.conftest import RECIPIENT, register

pytestmark = pytest.mark.anyio


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


async def wait(cond, timeout=4.0):
    for _ in range(int(timeout / 0.05)):
        if cond():
            return True
        await asyncio.sleep(0.05)
    return False


async def connect(url, headers=None):
    c = socketio.AsyncClient()
    box = {"updates": [], "initial": []}
    c.on("vehicles:update", lambda d: box["updates"].append(d))
    c.on("vehicles:initial", lambda d: box["initial"].append(d))
    c.box = box
    auth = {"token": headers["Authorization"].split()[1]} if headers else None
    await c.connect(url, auth=auth)
    return c


def loc(agent, **over):
    return {"driverId": agent["id"], "lat": 12.9, "lng": 77.6, "driverName": "SPOOFED NAME", "vehicleNo": "SPOOF-1", "currentArea": "Koramangala", "eta": "5", **over}


class W: ...


@pytest.fixture
async def w(client, live):
    w = W()
    w.c, w.url = client, live
    w.cust, w.ch = await register(client, "user", "c@t.test")
    w.a1, w.h1 = await register(client, "driver", "a1@t.test", vehicleNo="KA09ZZ1111", licenseNo="DL1")
    w.a2, w.h2 = await register(client, "driver", "a2@t.test", vehicleNo="KA09ZZ2222", licenseNo="DL2")
    w.admin, w.adm = await register(client, "admin", "boss@t.test")
    return w


# ─── who may publish positions ─────────────────────────────────────────────
async def test_anonymous_and_non_agent_sockets_cannot_publish_locations(w):
    anon, cust = await connect(w.url), await connect(w.url, w.ch)
    for s in (anon, cust):
        await s.emit("driver:location", loc(w.a1))
    await asyncio.sleep(0.4)
    assert sockets.vehicle_locations == {}
    from models.tracking_log import TrackingLog
    assert await TrackingLog.find_all().count() == 0                     # and nothing was written to the database
    await anon.disconnect(); await cust.disconnect()


async def test_an_agent_cannot_publish_as_another_agent(w):
    a1 = await connect(w.url, w.h1)
    await a1.emit("driver:location", loc(w.a2))                           # agent 1 pretends to be agent 2
    await asyncio.sleep(0.4)
    assert w.a2["id"] not in sockets.vehicle_locations
    await a1.emit("driver:location", loc(w.a1))
    assert await wait(lambda: w.a1["id"] in sockets.vehicle_locations)
    assert sockets.vehicle_locations[w.a1["id"]]["state"] == "live"
    await a1.disconnect()


async def test_display_identity_comes_from_the_token_not_the_payload(w):
    a1 = await connect(w.url, w.h1)
    await a1.emit("driver:location", loc(w.a1))
    assert await wait(lambda: w.a1["id"] in sockets.vehicle_locations)
    v = sockets.vehicle_locations[w.a1["id"]]
    assert v["driverName"] == w.a1["name"] and v["vehicleNo"] == w.a1["vehicleNo"]
    await a1.disconnect()


async def test_only_the_owner_can_take_a_vehicle_offline(w):
    a1, a2 = await connect(w.url, w.h1), await connect(w.url, w.h2)
    await a1.emit("driver:location", loc(w.a1))
    assert await wait(lambda: w.a1["id"] in sockets.vehicle_locations)
    await a2.emit("driver:offline", w.a1["id"])
    await asyncio.sleep(0.4)
    assert sockets.vehicle_locations[w.a1["id"]]["state"] == "live"
    await a1.emit("driver:offline", w.a1["id"])
    assert await wait(lambda: sockets.vehicle_locations[w.a1["id"]]["state"] == "offline")
    await a1.disconnect(); await a2.disconnect()


@pytest.mark.parametrize("bad", [
    {"lat": 91, "lng": 0}, {"lat": 0, "lng": 181}, {"lat": "x", "lng": 0}, {"lat": None, "lng": 0}, {"lat": float("nan"), "lng": 0}, {"lat": True, "lng": 0},
])
async def test_invalid_coordinates_are_ignored(w, bad):
    a1 = await connect(w.url, w.h1)
    await a1.emit("driver:location", {**loc(w.a1), **bad})
    await asyncio.sleep(0.4)
    assert w.a1["id"] not in sockets.vehicle_locations
    await a1.disconnect()


async def test_oversized_fields_are_bounded(w):
    a1 = await connect(w.url, w.h1)
    await a1.emit("driver:location", loc(w.a1, currentArea="A" * 5000, eta="9" * 500, areasCompleted=["z" * 300] * 100))
    assert await wait(lambda: w.a1["id"] in sockets.vehicle_locations)
    v = sockets.vehicle_locations[w.a1["id"]]
    assert len(v["currentArea"]) <= 100 and len(v["eta"]) <= 30 and len(v["areasCompleted"]) <= 50 and all(len(a) <= 100 for a in v["areasCompleted"])
    await a1.disconnect()


# ─── who may watch the fleet ───────────────────────────────────────────────
async def test_fleet_feed_requires_a_signed_in_socket(w):
    a1 = await connect(w.url, w.h1)
    await a1.emit("driver:location", loc(w.a1))
    assert await wait(lambda: w.a1["id"] in sockets.vehicle_locations)
    anon = await connect(w.url)
    bad = socketio.AsyncClient(); bad.on("vehicles:initial", lambda d: None)
    bad_box = []
    bad.on("vehicles:update", lambda d: bad_box.append(d))
    await bad.connect(w.url, auth={"token": "not-a-real-token"})
    cust = await connect(w.url, w.ch)
    assert await wait(lambda: cust.box["initial"] and w.a1["id"] in cust.box["initial"][0])   # signed in -> gets the feed
    await a1.emit("driver:location", loc(w.a1, lat=12.91))
    assert await wait(lambda: cust.box["updates"])
    await asyncio.sleep(0.3)
    assert anon.box["initial"] == [] and anon.box["updates"] == []                           # anonymous -> nothing
    assert bad_box == []                                                                     # invalid token behaves as anonymous
    for s in (a1, anon, bad, cust):
        await s.disconnect()


async def test_public_shipment_tracking_still_works_without_signing_in(w):
    s = (await w.c.post("/api/shipments", json={"recipient": RECIPIENT}, headers=w.ch)).json()
    anon = socketio.AsyncClient(); got = []
    anon.on("shipment:update", lambda d: got.append(d))
    await anon.connect(w.url)
    await anon.emit("shipment:join", {"trackingNumber": s["trackingNumber"]})
    await asyncio.sleep(0.2)
    await w.c.put(f"/api/shipments/{s['_id']}/assign", json={"agentId": w.a1["id"]}, headers=w.adm)
    assert await wait(lambda: got) and got[0]["status"] == "PICKUP_SCHEDULED"
    await anon.disconnect()


# ─── disconnects, reconnects, duplicates ───────────────────────────────────
async def test_abrupt_disconnect_takes_the_vehicle_offline_and_tells_watchers(w):
    watcher, a1 = await connect(w.url, w.ch), await connect(w.url, w.h1)
    await a1.emit("driver:location", loc(w.a1))
    assert await wait(lambda: w.a1["id"] in sockets.vehicle_locations)
    await a1.disconnect()                                                # no driver:offline event was sent
    assert await wait(lambda: sockets.vehicle_locations[w.a1["id"]]["state"] == "offline")
    assert await wait(lambda: watcher.box["updates"] and watcher.box["updates"][-1][w.a1["id"]]["isActive"] is False)
    await watcher.disconnect()


async def test_a_second_tab_keeps_the_vehicle_live_when_one_connection_drops(w):
    tab1, tab2 = await connect(w.url, w.h1), await connect(w.url, w.h1)
    await tab1.emit("driver:location", loc(w.a1))
    assert await wait(lambda: w.a1["id"] in sockets.vehicle_locations)
    await tab1.disconnect()
    await asyncio.sleep(0.5)
    assert sockets.vehicle_locations[w.a1["id"]]["state"] == "live"
    await tab2.disconnect()
    assert await wait(lambda: sockets.vehicle_locations[w.a1["id"]]["state"] == "offline")


async def test_reconnecting_agent_is_live_again_after_the_next_location(w):
    a1 = await connect(w.url, w.h1)
    await a1.emit("driver:location", loc(w.a1))
    assert await wait(lambda: w.a1["id"] in sockets.vehicle_locations)
    await a1.disconnect()
    assert await wait(lambda: sockets.vehicle_locations[w.a1["id"]]["state"] == "offline")
    again = await connect(w.url, w.h1)                                   # new connection, new sid
    await again.emit("driver:location", loc(w.a1, lat=12.95))
    assert await wait(lambda: sockets.vehicle_locations[w.a1["id"]]["state"] == "live")
    assert sockets.vehicle_locations[w.a1["id"]]["lat"] == 12.95
    await again.disconnect()


async def test_reconnecting_viewer_gets_current_state_immediately(w):
    a1 = await connect(w.url, w.h1)
    await a1.emit("driver:location", loc(w.a1))
    assert await wait(lambda: w.a1["id"] in sockets.vehicle_locations)
    v1 = await connect(w.url, w.ch)
    await v1.disconnect()
    v2 = await connect(w.url, w.ch)
    assert await wait(lambda: v2.box["initial"] and v2.box["initial"][0][w.a1["id"]]["state"] == "live")
    await a1.disconnect(); await v2.disconnect()


async def test_shipment_events_are_delivered_once_even_after_reconnect_and_double_join(w):
    s = (await w.c.post("/api/shipments", json={"recipient": RECIPIENT}, headers=w.ch)).json()
    tn = s["trackingNumber"]
    got = []
    first = socketio.AsyncClient()
    first.on("shipment:update", lambda d: got.append(("first", d)))
    await first.connect(w.url)
    await first.emit("shipment:join", {"trackingNumber": tn})
    await first.disconnect()                                             # network drop
    second = socketio.AsyncClient()
    second.on("shipment:update", lambda d: got.append(("second", d)))
    await second.connect(w.url)
    for _ in range(3):                                                   # client re-joins on connect (maybe more than once)
        await second.emit("shipment:join", {"trackingNumber": tn.lower()})
    await asyncio.sleep(0.3)
    await w.c.put(f"/api/shipments/{s['_id']}/assign", json={"agentId": w.a1["id"]}, headers=w.adm)
    assert await wait(lambda: got)
    await asyncio.sleep(0.4)
    assert [who for who, _ in got] == ["second"]                         # exactly one delivery, none to the dead connection
    await second.emit("shipment:leave", {"trackingNumber": tn})
    await asyncio.sleep(0.2)
    await w.c.post(f"/api/shipments/{s['_id']}/status", json={"status": "PICKED_UP"}, headers=w.h1)
    await asyncio.sleep(0.4)
    assert len(got) == 1                                                 # left the room -> no more events
    await second.disconnect()


async def test_shipment_join_is_validated(w):
    c = socketio.AsyncClient(); got = []
    c.on("shipment:update", lambda d: got.append(d))
    await c.connect(w.url)
    for bad in ({"trackingNumber": "x" * 5000}, {"trackingNumber": "../../etc"}, {"trackingNumber": None}, "nonsense", None, {}):
        await c.emit("shipment:join", bad)
    await asyncio.sleep(0.3)
    from sockets import sio
    assert [r for r in sio.manager.rooms.get("/", {}) if r and str(r).startswith("shipment:") and str(r) != "shipment:"] == []
    await c.disconnect()


# ─── liveness and abuse controls ───────────────────────────────────────────
def test_stale_connections_are_reaped_by_configured_heartbeats():
    assert sockets.sio.eio.ping_interval == config.socket_ping_interval()
    assert sockets.sio.eio.ping_timeout == config.socket_ping_timeout()
    assert sockets.sio.eio.max_http_buffer_size <= 256 * 1024            # a socket cannot push megabytes at us


def test_heartbeat_settings_are_configurable(monkeypatch):
    monkeypatch.setenv("SOCKET_PING_INTERVAL", "10")
    monkeypatch.setenv("SOCKET_PING_TIMEOUT", "7")
    assert config.socket_ping_interval() == 10 and config.socket_ping_timeout() == 7
    monkeypatch.setenv("SOCKET_PING_INTERVAL", "junk")
    assert config.socket_ping_interval() == 25


async def test_location_flood_from_one_agent_is_throttled(w, monkeypatch):
    monkeypatch.setenv("GPS_MIN_INTERVAL_SECONDS", "0.5")
    a1 = await connect(w.url, w.h1)
    await a1.emit("driver:location", loc(w.a1, lat=10.0))
    assert await wait(lambda: sockets.vehicle_locations.get(w.a1["id"], {}).get("lat") == 10.0)
    for i in range(20):                                                  # a burst well inside the interval
        await a1.emit("driver:location", loc(w.a1, lat=11.0 + i / 100))
    await asyncio.sleep(0.2)
    assert sockets.vehicle_locations[w.a1["id"]]["lat"] == 10.0          # burst ignored
    await asyncio.sleep(0.6)
    await a1.emit("driver:location", loc(w.a1, lat=13.0))                # next legitimate report is accepted
    assert await wait(lambda: sockets.vehicle_locations[w.a1["id"]]["lat"] == 13.0)
    await a1.disconnect()
