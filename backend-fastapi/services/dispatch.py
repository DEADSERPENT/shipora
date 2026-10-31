"""Automatic delivery-agent assignment ("dispatch").

A new shipment is matched to the best available delivery agent without anyone in Operations touching it: the agent closest to the
pickup address wins, with a penalty for every parcel they are already carrying, and nobody is given more than MAX_ACTIVE_PER_AGENT
at once. The assignment itself goes through services/shipments.assign_agent(), the same function an admin's manual assignment uses,
so the pickup gets scheduled, the history records who/why, and the customer is notified exactly as before. Operations can still
reassign by hand at any time.

If no agent is free the shipment simply stays CREATED and sweep_forever() retries it, so it is picked up as soon as an agent comes
online or finishes a delivery."""

import asyncio
import logging
from collections import Counter
from datetime import datetime
from typing import Dict, Optional, Tuple

import config
from models.delivery_agent import DeliveryAgent
from models.shipment import TERMINAL_STATUSES, Shipment
from models.tracking_log import TrackingLog
from services import geo
from services.shipments import ShipmentError, assign_agent
from sockets import vehicle_locations
from utils.dates import today_string

log = logging.getLogger("shipora.dispatch")

MAX_ACTIVE_PER_AGENT = 4
LOAD_PENALTY_KM = 3.0          # each parcel already on an agent counts as this many extra kilometres of distance
UNKNOWN_POSITION_KM = 6.0      # an agent with no known position ranks below one that is close, above one that is far away
SWEEP_SECONDS = 15.0

SYSTEM_ACTOR = {"role": "admin", "id": "system:dispatch", "name": "Auto-dispatch"}

_background: set = set()       # strong references so a fire-and-forget assignment is not garbage-collected mid-flight


async def agent_positions() -> Dict[str, Tuple[float, float]]:
    """Last known position of every agent: today's tracking log, overridden by the live GPS store."""
    positions: Dict[str, Tuple[float, float]] = {}
    for entry in await TrackingLog.find(TrackingLog.date == today_string()).to_list():
        if entry.lat is not None and entry.lng is not None:
            positions[str(entry.driverId)] = (entry.lat, entry.lng)
    for agent_id, live in vehicle_locations.items():
        if live.get("lat") is not None and live.get("lng") is not None:
            positions[agent_id] = (live["lat"], live["lng"])
    return positions


async def active_load() -> Counter:
    rows = await Shipment.find({"assignedAgentId": {"$ne": None}, "status": {"$nin": list(TERMINAL_STATUSES)}}).to_list()
    return Counter(str(s.assignedAgentId) for s in rows)


async def pick_agent(shipment: Shipment) -> Optional[DeliveryAgent]:
    """The best agent for this shipment's pickup, or None when nobody can take it."""
    agents = await DeliveryAgent.find(DeliveryAgent.availability != "off_duty").to_list()
    if not agents:
        return None
    positions, load = await agent_positions(), await active_load()
    pickup = shipment.sender.location
    best, best_score = None, float("inf")
    for agent in sorted(agents, key=lambda a: a.name):
        key = str(agent.id)
        if load[key] >= MAX_ACTIVE_PER_AGENT:
            continue
        where = positions.get(key)
        if pickup is not None and where is not None:
            distance = geo.distance_km(where[0], where[1], pickup.lat, pickup.lng)
        else:
            distance = UNKNOWN_POSITION_KM
        score = distance + LOAD_PENALTY_KM * load[key]
        if score < best_score:
            best, best_score = agent, score
    return best


async def auto_assign(shipment_id) -> Optional[Shipment]:
    """Assigns an agent to a still-unassigned CREATED shipment. Returns the updated shipment, or None if nothing was done."""
    shipment = await Shipment.get(shipment_id)
    if shipment is None or shipment.assignedAgentId is not None or shipment.status != "CREATED":
        return None
    agent = await pick_agent(shipment)
    if agent is None:
        log.info("no delivery agent available yet", extra={"event": "dispatch_no_agent", "tracking": shipment.trackingNumber})
        return None
    try:
        updated = await assign_agent(shipment, agent.id, SYSTEM_ACTOR, note=f"Auto-assigned to {agent.name}")
    except ShipmentError as err:
        log.info("auto-assignment skipped", extra={"event": "dispatch_skipped", "tracking": shipment.trackingNumber, "reason": err.message})
        return None
    await DeliveryAgent.get_motor_collection().update_one({"_id": agent.id}, {"$set": {"availability": "on_delivery", "updatedAt": datetime.utcnow()}})
    log.info("shipment auto-assigned", extra={"event": "dispatch_assigned", "tracking": updated.trackingNumber, "agent_id": str(agent.id)})
    return updated


async def assign_soon(shipment_id) -> None:
    """Background job started right after booking: a short pause, then the match."""
    try:
        await asyncio.sleep(config.auto_assign_delay_seconds())
        await auto_assign(shipment_id)
    except asyncio.CancelledError:
        raise
    except Exception:
        log.exception("auto-assignment failed", extra={"event": "dispatch_failed"})


def schedule(shipment_id) -> None:
    """Fire-and-forget auto-assignment for a new shipment (no-op when AUTO_ASSIGN_ENABLED=false)."""
    if not config.auto_assign_enabled():
        return
    task = asyncio.create_task(assign_soon(shipment_id))
    _background.add(task)
    task.add_done_callback(_background.discard)


async def sweep_once() -> int:
    """Retries every shipment that is still waiting for an agent. Returns how many were assigned."""
    waiting = await Shipment.find({"status": "CREATED", "assignedAgentId": None}).sort("createdAt").limit(50).to_list()
    assigned = 0
    for shipment in waiting:
        if await auto_assign(shipment.id) is not None:
            assigned += 1
    return assigned


async def sweep_forever() -> None:
    while True:
        try:
            await sweep_once()
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("dispatch sweep failed", extra={"event": "dispatch_sweep_failed"})
        await asyncio.sleep(SWEEP_SECONDS)
