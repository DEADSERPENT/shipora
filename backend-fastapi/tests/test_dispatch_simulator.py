"""Automatic rider assignment (services/dispatch.py) and the rider simulator (services/simulator.py). Real database layer (in-memory
Mongo), real shipment rules; only time is sped up."""
import asyncio

import pytest

import config
import sockets
from models.delivery_agent import DeliveryAgent
from models.shipment import Shipment
from models.tracking_log import TrackingLog
from services import dispatch, simulator
from tests.conftest import RECIPIENT, register
from utils.dates import today_string

pytestmark = pytest.mark.anyio

PICKUP = (12.9352, 77.6245)          # the customer's pickup in these tests (set in make_shipment)


@pytest.fixture(autouse=True)
def clean_simulator_state():
    simulator._dwell.clear()
    simulator._passed.clear()
    yield
    simulator._dwell.clear()
    simulator._passed.clear()


async def make_agent(name, lat=None, lng=None, simulated=False, availability="available", n=[0]):
    n[0] += 1
    agent = DeliveryAgent(name=name, email=f"{name.lower()}{n[0]}@t.test", password="x", phone=f"98000{n[0]:05d}", vehicleNo=f"KA01XX{n[0]:04d}",
                          licenseNo=f"L{n[0]}", assignedArea="Koramangala", availability=availability, isSimulated=simulated)
    await agent.insert()
    if lat is not None:
        sockets.vehicle_locations[str(agent.id)] = {"lat": lat, "lng": lng, "isActive": True, "state": "live"}
    return agent


async def make_shipment(client, email="disp@t.test", pickup=PICKUP):
    user, headers = await register(client, "user", email, location={"lat": pickup[0], "lng": pickup[1]})
    r = await client.post("/api/shipments", json={"recipient": {**RECIPIENT, "name": "R"}, "parcel": {"description": "x"}}, headers=headers)
    assert r.status_code == 201, r.text
    body = r.json()
    return await Shipment.find_one(Shipment.trackingNumber == (body.get("shipment") or body)["trackingNumber"]), headers


# ── automatic assignment ─────────────────────────────────────────────────
async def test_the_nearest_available_agent_is_assigned_and_the_pickup_is_scheduled(client):
    near = await make_agent("Near", PICKUP[0] + 0.01, PICKUP[1])          # ~1 km
    await make_agent("Far", 13.05, 77.60)                                # ~13 km
    shipment, _ = await make_shipment(client)
    updated = await dispatch.auto_assign(shipment.id)
    assert updated.assignedAgentId == near.id and updated.status == "PICKUP_SCHEDULED"
    last = updated.statusHistory[-1]
    assert last.status == "PICKUP_SCHEDULED" and "Auto-assigned to Near" in last.note and last.byId == "system:dispatch"
    assert (await DeliveryAgent.get(near.id)).availability == "on_delivery"


async def test_a_busy_agent_loses_to_a_slightly_farther_free_one(client):
    busy = await make_agent("Busy", PICKUP[0] + 0.01, PICKUP[1])          # ~1 km but already carrying 2 parcels: 1 + 2*3 = 7
    free = await make_agent("Free", PICKUP[0] + 0.036, PICKUP[1])         # ~4 km, nothing on board: 4
    for i in range(2):
        s, _ = await make_shipment(client, f"load{i}@t.test")
        await dispatch.assign_agent(s, busy.id, dispatch.SYSTEM_ACTOR)
    shipment, _ = await make_shipment(client, "new@t.test")
    updated = await dispatch.auto_assign(shipment.id)
    assert updated.assignedAgentId == free.id


async def test_nobody_is_given_more_than_the_cap(client):
    only = await make_agent("Only", PICKUP[0], PICKUP[1])
    for i in range(dispatch.MAX_ACTIVE_PER_AGENT):
        s, _ = await make_shipment(client, f"cap{i}@t.test")
        await dispatch.assign_agent(s, only.id, dispatch.SYSTEM_ACTOR)
    shipment, _ = await make_shipment(client, "over@t.test")
    assert await dispatch.auto_assign(shipment.id) is None
    assert (await Shipment.get(shipment.id)).status == "CREATED"


async def test_off_duty_agents_are_skipped_and_a_late_agent_gets_the_waiting_shipment(client):
    await make_agent("Away", PICKUP[0], PICKUP[1], availability="off_duty")
    shipment, _ = await make_shipment(client)
    assert await dispatch.auto_assign(shipment.id) is None                # nobody is on duty: it waits, unassigned
    assert (await Shipment.get(shipment.id)).assignedAgentId is None
    arrived = await make_agent("Arrived", PICKUP[0], PICKUP[1])
    assert await dispatch.sweep_once() == 1                               # the periodic sweep picks it up
    assert (await Shipment.get(shipment.id)).assignedAgentId == arrived.id


async def test_an_assigned_or_moving_shipment_is_never_reassigned_automatically(client):
    a = await make_agent("A", PICKUP[0], PICKUP[1])
    await make_agent("B", PICKUP[0] + 0.001, PICKUP[1])
    shipment, _ = await make_shipment(client)
    first = await dispatch.auto_assign(shipment.id)
    assert first.assignedAgentId == a.id or first.assignedAgentId is not None
    assert await dispatch.auto_assign(shipment.id) is None                # already assigned: operations' manual choice or ours stays


async def test_booking_assigns_an_agent_by_itself(client, monkeypatch):
    monkeypatch.setenv("AUTO_ASSIGN_ENABLED", "true")
    monkeypatch.setenv("AUTO_ASSIGN_DELAY_SECONDS", "0")
    agent = await make_agent("Auto", PICKUP[0], PICKUP[1])
    shipment, headers = await make_shipment(client)
    for _ in range(40):                                                    # the match is a background task: give it a moment
        await asyncio.sleep(0.05)
        shipment = await Shipment.get(shipment.id)
        if shipment.assignedAgentId:
            break
    assert shipment.assignedAgentId == agent.id and shipment.status == "PICKUP_SCHEDULED"


async def test_auto_assignment_can_be_switched_off(client, monkeypatch):
    monkeypatch.setenv("AUTO_ASSIGN_ENABLED", "false")
    await make_agent("Idle", PICKUP[0], PICKUP[1])
    shipment, _ = await make_shipment(client)
    await asyncio.sleep(0.2)
    assert (await Shipment.get(shipment.id)).assignedAgentId is None


# ── configuration rules ───────────────────────────────────────────────────
def test_the_simulator_is_on_by_default_only_for_the_throwaway_database(monkeypatch):
    monkeypatch.delenv("SIMULATION_ENABLED", raising=False)
    monkeypatch.setenv("APP_ENV", "development")
    assert config.simulation_enabled(True) and not config.simulation_enabled(False)
    monkeypatch.setenv("SIMULATION_ENABLED", "true")
    assert config.simulation_enabled(False)                                # asked for explicitly: allowed on a real database
    monkeypatch.setenv("SIMULATION_ENABLED", "false")
    assert not config.simulation_enabled(True)
    monkeypatch.delenv("SIMULATION_ENABLED")
    monkeypatch.setenv("APP_ENV", "production")
    assert not config.simulation_enabled(True)                             # never implicit in production


def test_movement_math():
    lat, lng, left = simulator.move_toward(12.90, 77.60, 12.91, 77.60, 0.5)
    assert 12.90 < lat < 12.91 and lng == 77.60 and 0.5 < left < 0.7
    assert simulator.move_toward(12.90, 77.60, 12.9001, 77.60, 0.5) == (12.9001, 77.60, 0.0)
    assert simulator.nearest_area(12.9790, 77.6410) == "Indiranagar"
    assert simulator.eta_text(0)[0] == "Arrived" and simulator.eta_text(0.1)[0] == "1 mins"


# ── the rider simulator ────────────────────────────────────────────────────
async def test_the_fleet_is_created_once(client, monkeypatch):
    monkeypatch.setenv("SIM_FLEET_SIZE", "3")
    assert await simulator.seed_fleet() == 3
    assert await simulator.seed_fleet() == 0
    fleet = await DeliveryAgent.find(DeliveryAgent.isSimulated == True).to_list()  # noqa: E712
    assert len(fleet) == 3 and all(a.vehicleNo.startswith("KA01SIM") for a in fleet)
    assert len(sockets.vehicle_locations) == 3 and all(v["state"] == "live" for v in sockets.vehicle_locations.values())


async def test_a_simulated_rider_delivers_a_shipment_through_every_real_status(client, monkeypatch):
    monkeypatch.setenv("SIM_SPEED", "100000")                              # each tick covers the whole route: only the order of events matters here
    rider = await make_agent("Sim", PICKUP[0] + 0.02, PICKUP[1], simulated=True)
    shipment, _ = await make_shipment(client)
    await dispatch.auto_assign(shipment.id)
    for _ in range(30):
        await simulator.tick()
        current = await Shipment.get(shipment.id)
        if current.status == "DELIVERED":
            break
    assert current.status == "DELIVERED" and current.deliveredAt is not None
    assert [e.status for e in current.statusHistory] == ["CREATED", "PICKUP_SCHEDULED", "PICKED_UP", "IN_TRANSIT", "OUT_FOR_DELIVERY", "DELIVERED"]
    assert all(e.byRole == "driver" for e in current.statusHistory[2:])    # recorded as the rider's own updates, through the normal rules
    live = sockets.vehicle_locations[str(rider.id)]
    assert live["state"] == "live" and live["driverName"] == "Sim" and live["currentArea"] != "N/A"
    log = await TrackingLog.find_one(TrackingLog.driverId == rider.id, TrackingLog.date == today_string())
    assert log.deliveredCount == 1 and log.activeShipmentIds == [] and log.lat is not None
    await simulator.tick()
    assert (await DeliveryAgent.get(rider.id)).availability == "available"  # free for the next parcel


async def test_the_rider_really_drives_there_instead_of_teleporting(client, monkeypatch):
    monkeypatch.setenv("SIM_SPEED", "30")
    monkeypatch.setenv("SIM_TICK_SECONDS", "2")                            # 25 km/h x 30 x 2 s = ~0.42 km per tick
    rider = await make_agent("Drive", PICKUP[0] + 0.05, PICKUP[1], simulated=True)          # ~5.5 km from the pickup
    shipment, _ = await make_shipment(client)
    await dispatch.auto_assign(shipment.id)
    seen = []
    for _ in range(4):
        await simulator.tick()
        live = sockets.vehicle_locations[str(rider.id)]
        seen.append(round(live["distanceKm"], 2))
        assert live["target"] == "pickup" and live["eta"].endswith("mins")
    assert seen == sorted(seen, reverse=True) and seen[0] - seen[-1] > 1.0   # steadily closer
    assert (await Shipment.get(shipment.id)).status == "PICKUP_SCHEDULED"   # not there yet


async def test_real_riders_are_never_moved_by_the_simulator(client, monkeypatch):
    monkeypatch.setenv("SIM_SPEED", "100000")
    human = await make_agent("Human", PICKUP[0], PICKUP[1], simulated=False)
    shipment, _ = await make_shipment(client)
    await dispatch.assign_agent(shipment, human.id, dispatch.SYSTEM_ACTOR)
    for _ in range(5):
        await simulator.tick()
    assert (await Shipment.get(shipment.id)).status == "PICKUP_SCHEDULED"
    assert sockets.vehicle_locations[str(human.id)]["lat"] == PICKUP[0]     # position untouched


async def test_a_cancelled_shipment_is_left_alone(client, monkeypatch):
    monkeypatch.setenv("SIM_SPEED", "100000")
    await make_agent("Sim2", PICKUP[0], PICKUP[1], simulated=True)
    shipment, headers = await make_shipment(client)
    await dispatch.auto_assign(shipment.id)
    r = await client.post(f"/api/shipments/{shipment.id}/status", json={"status": "CANCELLED"}, headers=headers)
    assert r.status_code == 200, r.text
    for _ in range(5):
        await simulator.tick()
    assert (await Shipment.get(shipment.id)).status == "CANCELLED"


async def test_idle_simulated_riders_keep_sending_a_heartbeat(client):
    rider = await make_agent("Idle2", PICKUP[0], PICKUP[1], simulated=True)
    await simulator.tick()
    live = sockets.vehicle_locations[str(rider.id)]
    assert live["state"] == "live" and live["eta"] == "Idle"
