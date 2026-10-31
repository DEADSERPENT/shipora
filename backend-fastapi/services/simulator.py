"""Rider simulator: simulated delivery agents that carry out their assigned shipments by themselves.

Underneath it is a simulation; from the outside it is indistinguishable from real riders, because it does nothing a real rider's
phone does not do. Each tick, every simulated agent that has a shipment
  * drives toward the pickup, then toward the drop, along a straight line at 25 km/h x SIM_SPEED,
  * publishes its position through sockets.publish_vehicle_location() - the same path a real rider's GPS events take - so the live map,
    the fleet list and the tracking log all show it moving, with a believable ETA and the neighbourhood it is passing, and
  * moves the shipment through PICKED_UP -> IN_TRANSIT -> OUT_FOR_DELIVERY -> DELIVERED with services.shipments.change_status(), the
    same call a real rider's "update status" button makes, so every rule, history entry and customer notification applies.
Idle simulated agents keep sending a heartbeat so they stay "live". Simulated agents are flagged DeliveryAgent.isSimulated and are
never touched by anything a person does; real riders are never moved by this module.

Off by default against a real database (config.simulation_enabled): it creates simulated agents, and it must be asked for."""

import asyncio
import logging
import math
import secrets
from typing import Dict, List, Optional, Tuple

import config
from auth_utils import hash_password
from models.delivery_agent import DeliveryAgent
from models.shipment import Shipment
from models.tracking_log import TrackingLog
from services import geo
from services.shipments import ShipmentError, change_status
from sockets import publish_vehicle_location, vehicle_locations
from utils.dates import today_string

log = logging.getLogger("shipora.simulator")

SPEED_KMH = 25.0                 # a city bike/scooter
ARRIVE_KM = 0.06                 # within 60 m counts as arrived
DWELL_TICKS = 2                  # the pause while a parcel is collected or handed over
OUT_FOR_DELIVERY_KM = 1.5        # the rider flips to "out for delivery" when this close to the drop
DRIVABLE = {"PICKUP_SCHEDULED", "PICKED_UP", "IN_TRANSIT", "OUT_FOR_DELIVERY"}

AREAS: List[Tuple[str, float, float]] = [
    ("Indiranagar", 12.9784, 77.6408), ("Koramangala", 12.9352, 77.6245), ("Whitefield", 12.9698, 77.7500),
    ("Jayanagar", 12.9308, 77.5838), ("HSR Layout", 12.9116, 77.6389), ("MG Road", 12.9756, 77.6066),
    ("Malleshwaram", 13.0035, 77.5643), ("Electronic City", 12.8452, 77.6602), ("Hebbal", 13.0358, 77.5970),
    ("BTM Layout", 12.9166, 77.6101), ("Yelahanka", 13.1007, 77.5963), ("JP Nagar", 12.9063, 77.5857),
]
RIDER_NAMES = ["Ravi", "Manjunath", "Suresh", "Kiran", "Naveen", "Prakash", "Deepak", "Mahesh", "Arun", "Vijay", "Harish", "Ganesh"]

_dwell: Dict[str, int] = {}       # agent id -> ticks left of the current pickup/handover pause
_passed: Dict[str, List[str]] = {}  # agent id -> neighbourhoods driven through today


def nearest_area(lat: float, lng: float) -> str:
    return min(AREAS, key=lambda a: geo.distance_km(lat, lng, a[1], a[2]))[0]


def step_km() -> float:
    return SPEED_KMH * config.sim_speed() / 3600.0 * config.sim_tick_seconds()


def move_toward(lat: float, lng: float, target_lat: float, target_lng: float, step: float) -> Tuple[float, float, float]:
    """One step along the straight line to the target. Returns (lat, lng, kilometres still to go)."""
    distance = geo.distance_km(lat, lng, target_lat, target_lng)
    if distance <= step:
        return target_lat, target_lng, 0.0
    fraction = step / distance
    return lat + (target_lat - lat) * fraction, lng + (target_lng - lng) * fraction, distance - step


def eta_text(remaining_km: float) -> Tuple[str, float]:
    minutes = remaining_km / (SPEED_KMH * config.sim_speed()) * 60.0      # consistent with how fast the simulation really runs
    return (f"{max(1, math.ceil(minutes))} mins" if minutes > 0 else "Arrived"), minutes


async def seed_fleet() -> int:
    """Makes sure SIM_FLEET_SIZE simulated agents exist. Returns how many were created."""
    existing = await DeliveryAgent.find(DeliveryAgent.isSimulated == True).count()  # noqa: E712
    created = 0
    for i in range(existing, config.sim_fleet_size()):
        area = AREAS[i % len(AREAS)]
        agent = DeliveryAgent(
            name=RIDER_NAMES[i % len(RIDER_NAMES)] + ("" if i < len(RIDER_NAMES) else f" {i // len(RIDER_NAMES) + 1}"),
            email=f"sim.rider{i + 1}@shipora.sim", password=hash_password(secrets.token_urlsafe(24)),     # nobody can sign in as one
            phone=f"98000000{i + 1:02d}", vehicleNo=f"KA01SIM{i + 1:03d}", vehicleType="bike", licenseNo=f"SIM{i + 1:05d}",
            assignedArea=area[0], availability="available", isSimulated=True,
        )
        try:
            await agent.insert()
        except Exception as err:                       # a duplicate e-mail from an earlier run: that agent already exists
            log.info("simulated agent already present", extra={"event": "sim_seed_skipped", "error_type": type(err).__name__})
            continue
        await publish_vehicle_location(str(agent.id), agent.name, agent.vehicleNo, area[1], area[2], current_area=area[0], eta="Idle")
        created += 1
    if created:
        log.info("simulated fleet created", extra={"event": "sim_fleet_created", "count": created})
    return created


async def _position(agent: DeliveryAgent) -> Tuple[float, float]:
    live = vehicle_locations.get(str(agent.id))
    if live and live.get("lat") is not None:
        return live["lat"], live["lng"]
    entry = await TrackingLog.find_one(TrackingLog.driverId == agent.id, TrackingLog.date == today_string())
    if entry and entry.lat is not None:
        return entry.lat, entry.lng
    home = next((a for a in AREAS if a[0] == agent.assignedArea), None)
    return (home[1], home[2]) if home else geo.CENTER


async def _publish(agent: DeliveryAgent, lat: float, lng: float, remaining_km: Optional[float] = None, target: Optional[str] = None) -> None:
    did = str(agent.id)
    area = nearest_area(lat, lng)
    passed = _passed.setdefault(did, [])
    if area not in passed:
        passed.append(area)
    eta, minutes = ("Idle", None) if remaining_km is None else eta_text(remaining_km)
    await publish_vehicle_location(did, agent.name, agent.vehicleNo, lat, lng, current_area=area, eta=eta, eta_minutes=minutes,
                                   distance_km=None if remaining_km is None else round(remaining_km, 2), target=target, areas=list(passed))


async def _drive(agent: DeliveryAgent, shipments: List[Shipment]) -> None:
    did = str(agent.id)
    lat, lng = await _position(agent)
    todo = [s for s in shipments if s.status in DRIVABLE]
    if not todo:
        await _publish(agent, lat, lng)                                   # heartbeat: an idle agent stays "live"
        if agent.availability != "available":
            await DeliveryAgent.get_motor_collection().update_one({"_id": agent.id}, {"$set": {"availability": "available"}})
        return
    if _dwell.get(did, 0) > 0:
        _dwell[did] -= 1
        await _publish(agent, lat, lng, 0.0, "pickup" if todo[0].status == "PICKUP_SCHEDULED" else "drop")
        return

    shipment = todo[0]
    heading_to_pickup = shipment.status == "PICKUP_SCHEDULED"
    target = (shipment.sender if heading_to_pickup else shipment.recipient).location
    if target is None:                                                    # cannot happen for a booked shipment; never crash the loop
        return
    lat, lng, remaining = move_toward(lat, lng, target.lat, target.lng, step_km())
    await _publish(agent, lat, lng, remaining, "pickup" if heading_to_pickup else "drop")

    actor = {"role": "driver", "id": did, "name": agent.name}
    arrived = remaining <= ARRIVE_KM
    try:
        if shipment.status == "PICKUP_SCHEDULED" and arrived:
            await change_status(shipment, "PICKED_UP", actor, "Picked up")
            _dwell[did] = DWELL_TICKS
        elif shipment.status == "PICKED_UP":
            await change_status(shipment, "IN_TRANSIT", actor, "On the way")
        elif shipment.status == "IN_TRANSIT" and remaining <= OUT_FOR_DELIVERY_KM:
            await change_status(shipment, "OUT_FOR_DELIVERY", actor, "Nearby, out for delivery")
        elif shipment.status == "OUT_FOR_DELIVERY" and arrived:
            await change_status(shipment, "DELIVERED", actor, "Delivered")
            _dwell[did] = DWELL_TICKS
    except ShipmentError as err:                                          # cancelled or changed by someone else meanwhile: just move on
        log.info("simulated status change skipped", extra={"event": "sim_status_skipped", "tracking": shipment.trackingNumber, "reason": err.message})


async def tick() -> None:
    agents = await DeliveryAgent.find(DeliveryAgent.isSimulated == True).to_list()  # noqa: E712
    if not agents:
        return
    rows = await Shipment.find({"assignedAgentId": {"$in": [a.id for a in agents]}, "status": {"$in": list(DRIVABLE)}}).sort("createdAt").to_list()
    by_agent: Dict = {}
    for s in rows:
        by_agent.setdefault(s.assignedAgentId, []).append(s)
    for agent in agents:
        try:
            await _drive(agent, by_agent.get(agent.id, []))
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("simulated agent step failed", extra={"event": "sim_step_failed", "agent_id": str(agent.id)})


async def run_forever() -> None:
    try:
        await seed_fleet()
    except Exception:
        log.exception("could not create the simulated fleet", extra={"event": "sim_seed_failed"})
    while True:
        try:
            await tick()
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("simulator tick failed", extra={"event": "sim_tick_failed"})
        await asyncio.sleep(config.sim_tick_seconds())
