"""Socket.IO tests against a real uvicorn server on an ephemeral port — the
HTTP-only ASGI transport can't exercise websockets."""

import asyncio
import socket

import httpx
import pytest
import socketio
import uvicorn

from main import app
from tests.conftest import RECIPIENT, register

pytestmark = pytest.mark.anyio


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture
async def live_server(client):  # `client` fixture initialises the in-memory DB first
    port = _free_port()
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning", lifespan="off"))
    task = asyncio.create_task(server.serve())
    while not server.started:
        await asyncio.sleep(0.05)
    yield f"http://127.0.0.1:{port}"
    server.should_exit = True
    await task


async def _wait_for(cond, timeout=3.0):
    for _ in range(int(timeout / 0.05)):
        if cond():
            return True
        await asyncio.sleep(0.05)
    return False


async def test_vehicle_location_broadcast_and_persistence(client, live_server):
    agent, ah = await register(client, "driver", "ws-a@t.test")
    _, ch = await register(client, "user", "ws-w@t.test")
    tok = lambda h: {"token": h["Authorization"].split()[1]}      # sockets authenticate with the same JWT as the REST API
    watcher, agent_sock = socketio.AsyncClient(), socketio.AsyncClient()
    updates = []
    watcher.on("vehicles:update", lambda d: updates.append(d))
    await watcher.connect(live_server, auth=tok(ch))
    await agent_sock.connect(live_server, auth=tok(ah))

    await agent_sock.emit("driver:location", {"driverId": agent["id"], "lat": 12.93, "lng": 77.62, "driverName": "Agent",
                                              "vehicleNo": "KA09ZZ0001", "currentArea": "Koramangala", "eta": "9 mins", "areasCompleted": ["1st Block"]})
    assert await _wait_for(lambda: updates), "watcher never received vehicles:update"
    assert updates[-1][agent["id"]]["currentArea"] == "Koramangala" and updates[-1][agent["id"]]["isActive"] is True

    # persisted into the tracking log (vehicle_logs collection)
    assert await _wait_for(lambda: True)
    await asyncio.sleep(0.3)
    logs = (await client.get("/api/vehicles/history", headers=ah)).json()
    assert logs and logs[0]["lat"] == 12.93 and logs[0]["areasCompleted"] == ["1st Block"]

    await agent_sock.emit("driver:offline", agent["id"])
    assert await _wait_for(lambda: updates[-1][agent["id"]]["isActive"] is False)
    await watcher.disconnect()
    await agent_sock.disconnect()


async def test_shipment_status_pushed_to_tracking_room(client, live_server):
    _, ch = await register(client, "user", "ws-c@t.test")
    agent, ah = await register(client, "driver", "ws-a2@t.test")
    _, adm = await register(client, "admin", "ws-adm@t.test")
    s = (await client.post("/api/shipments", json={"recipient": RECIPIENT}, headers=ch)).json()

    watcher, stranger = socketio.AsyncClient(), socketio.AsyncClient()
    got, stray = [], []
    watcher.on("shipment:update", lambda d: got.append(d))
    stranger.on("shipment:update", lambda d: stray.append(d))
    await watcher.connect(live_server)
    await stranger.connect(live_server)
    await watcher.emit("shipment:join", {"trackingNumber": s["trackingNumber"].lower()})
    await asyncio.sleep(0.2)

    await client.put(f"/api/shipments/{s['_id']}/assign", json={"agentId": agent["id"]}, headers=adm)
    assert await _wait_for(lambda: got)
    assert got[-1] == {**got[-1], "trackingNumber": s["trackingNumber"], "status": "PICKUP_SCHEDULED"}

    await client.post(f"/api/shipments/{s['_id']}/status", json={"status": "PICKED_UP"}, headers=ah)
    assert await _wait_for(lambda: len(got) == 2) and got[-1]["status"] == "PICKED_UP"
    assert stray == []  # not joined -> receives nothing

    await watcher.emit("shipment:leave", {"trackingNumber": s["trackingNumber"]})
    await asyncio.sleep(0.2)
    await client.post(f"/api/shipments/{s['_id']}/status", json={"status": "IN_TRANSIT"}, headers=ah)
    await asyncio.sleep(0.5)
    assert len(got) == 2
    await watcher.disconnect()
    await stranger.disconnect()
