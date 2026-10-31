"""Phase 5 / item 3 — concurrent updates must never leave a shipment inconsistent.

Real database latency is what makes races observable (every request reads, then later
writes). mongomock answers instantly, so the `slow_reads` fixture adds a small delay
after the shipment is loaded — exactly the stale-read window a request has against Atlas."""
import asyncio

import pytest

import routes.shipments as shipment_routes
from models.shipment import StatusEvent, allowed_next_statuses
from tests.conftest import RECIPIENT, register

pytestmark = pytest.mark.anyio

PATH = ["PICKED_UP", "IN_TRANSIT", "OUT_FOR_DELIVERY"]


@pytest.fixture
async def slow_reads(monkeypatch):
    original = shipment_routes._find

    async def delayed(ref):
        found = await original(ref)
        await asyncio.sleep(0.05)
        return found
    monkeypatch.setattr(shipment_routes, "_find", delayed)


class World: ...


@pytest.fixture
async def w(client):
    w = World()
    w.c = client
    w.cust, w.ch = await register(client, "user", "c@t.test")
    w.agent, w.ah = await register(client, "driver", "a@t.test", vehicleNo="KA09ZZ1111", licenseNo="DL1111")
    w.agent2, w.ah2 = await register(client, "driver", "a2@t.test", vehicleNo="KA09ZZ2222", licenseNo="DL2222")
    _, w.adm = await register(client, "admin", "boss@t.test")
    _, w.adm2 = await register(client, "admin", "boss2@t.test")
    return w


async def make(w, upto=None, assign=True):
    """Creates a shipment and walks it (sequentially, no races) up to `upto`."""
    r = await w.c.post("/api/shipments", json={"recipient": RECIPIENT, "parcel": {"weightKg": 1}}, headers=w.ch)
    s = r.json()
    if assign:
        a = await w.c.put(f"/api/shipments/{s['_id']}/assign", json={"agentId": w.agent["id"]}, headers=w.adm)
        assert a.status_code == 200, a.text
    if upto:
        for st in PATH[: PATH.index(upto) + 1]:
            assert (await w.c.post(f"/api/shipments/{s['_id']}/status", json={"status": st}, headers=w.ah)).status_code == 200
    return s["_id"]


async def get(w, sid):
    return (await w.c.get(f"/api/shipments/{sid}", headers=w.adm)).json()


def assert_consistent(s):
    """The stored shipment must be explainable: history is a legal path and ends at `status`."""
    events = [StatusEvent(**e) for e in s["statusHistory"]]
    assert events[-1].status == s["status"], "status does not match the last history event"
    for i in range(len(events) - 1):
        assert events[i + 1].status in allowed_next_statuses(events[i].status, events[: i + 1]), \
            f"illegal step {events[i].status} -> {events[i + 1].status}"
    assert s["deliveryAttempts"] == sum(1 for e in events if e.status == "OUT_FOR_DELIVERY")
    assert s["deliveryAttempts"] <= 3


def post_status(w, sid, status, headers):
    return w.c.post(f"/api/shipments/{sid}/status", json={"status": status}, headers=headers)


async def test_two_valid_transitions_race_exactly_one_wins(w, slow_reads):
    sid = await make(w, "PICKED_UP")
    before = len((await get(w, sid))["statusHistory"])
    r1, r2 = await asyncio.gather(post_status(w, sid, "IN_TRANSIT", w.ah), post_status(w, sid, "DAMAGED", w.ah))
    assert sorted([r1.status_code, r2.status_code]) == [200, 409], (r1.text, r2.text)
    final = await get(w, sid)
    assert len(final["statusHistory"]) == before + 1                      # exactly one new event, none lost or doubled
    winner = "IN_TRANSIT" if r1.status_code == 200 else "DAMAGED"
    assert final["status"] == winner
    assert_consistent(final)


async def test_cancel_races_pickup_exactly_one_wins(w, slow_reads):
    sid = await make(w)                                                    # PICKUP_SCHEDULED
    cancel, pickup = await asyncio.gather(post_status(w, sid, "CANCELLED", w.ch), post_status(w, sid, "PICKED_UP", w.ah))
    assert sorted([cancel.status_code, pickup.status_code]) == [200, 409], (cancel.text, pickup.text)
    final = await get(w, sid)
    assert final["status"] == ("CANCELLED" if cancel.status_code == 200 else "PICKED_UP")
    assert_consistent(final)
    # a cancelled shipment can never be revived by the loser retrying
    if final["status"] == "CANCELLED":
        assert (await post_status(w, sid, "PICKED_UP", w.ah)).status_code in (403, 409)


async def test_simultaneous_delivery_attempts_count_once(w, slow_reads):
    sid = await make(w, "IN_TRANSIT")
    rs = await asyncio.gather(*[post_status(w, sid, "OUT_FOR_DELIVERY", w.ah) for _ in range(8)])
    assert sorted(r.status_code for r in rs) == [200] + [409] * 7
    final = await get(w, sid)
    assert final["deliveryAttempts"] == 1
    assert sum(1 for e in final["statusHistory"] if e["status"] == "OUT_FOR_DELIVERY") == 1
    assert_consistent(final)


async def test_attempt_cap_cannot_be_exceeded_by_a_race(w, slow_reads):
    sid = await make(w, "OUT_FOR_DELIVERY")                                # attempt 1
    for _ in range(1):
        await post_status(w, sid, "DELIVERY_FAILED", w.ah)
        await post_status(w, sid, "OUT_FOR_DELIVERY", w.ah)                # attempt 2
    await post_status(w, sid, "DELIVERY_FAILED", w.ah)
    assert (await get(w, sid))["deliveryAttempts"] == 2
    a, b = await asyncio.gather(post_status(w, sid, "OUT_FOR_DELIVERY", w.ah), post_status(w, sid, "OUT_FOR_DELIVERY", w.adm))
    assert sorted([a.status_code, b.status_code]) == [200, 409]
    final = await get(w, sid)
    assert final["deliveryAttempts"] == 3                                  # not 4
    assert_consistent(final)


async def test_double_delivery_counts_the_parcel_once(w, slow_reads):
    sid = await make(w, "OUT_FOR_DELIVERY")
    rs = await asyncio.gather(*[post_status(w, sid, "DELIVERED", w.ah) for _ in range(5)])
    assert sorted(r.status_code for r in rs) == [200] + [409] * 4
    log = (await w.c.get("/api/vehicles/history", headers=w.ah)).json()[0]
    assert log["deliveredCount"] == 1 and log["activeShipmentIds"] == []
    final = await get(w, sid)
    assert final["deliveredAt"] and sum(1 for e in final["statusHistory"] if e["status"] == "DELIVERED") == 1
    assert_consistent(final)


async def test_simultaneous_assignment_schedules_pickup_once(w, slow_reads):
    sid = await make(w, assign=False)                                      # CREATED, unassigned
    a, b = await asyncio.gather(
        w.c.put(f"/api/shipments/{sid}/assign", json={"agentId": w.agent["id"]}, headers=w.adm),
        w.c.put(f"/api/shipments/{sid}/assign", json={"agentId": w.agent2["id"]}, headers=w.adm2))
    assert a.status_code == 200 and b.status_code == 200, (a.text, b.text)  # both are legal; last writer wins the agent
    final = await get(w, sid)
    assert final["assignedAgentId"] in (w.agent["id"], w.agent2["id"])
    assert [e["status"] for e in final["statusHistory"]].count("PICKUP_SCHEDULED") == 1   # not twice
    assert final["status"] == "PICKUP_SCHEDULED"
    assert_consistent(final)


async def test_assign_races_cancel(w, slow_reads):
    sid = await make(w, assign=False)
    cancel, assign = await asyncio.gather(
        post_status(w, sid, "CANCELLED", w.ch),
        w.c.put(f"/api/shipments/{sid}/assign", json={"agentId": w.agent["id"]}, headers=w.adm))
    assert cancel.status_code == 200
    final = await get(w, sid)
    assert final["status"] == "CANCELLED"                                  # cancel always sticks, whichever order
    assert_consistent(final)
    assert (await w.c.put(f"/api/shipments/{sid}/assign", json={"agentId": w.agent2["id"]}, headers=w.adm)).status_code == 409


async def test_status_update_and_reassignment_do_not_overwrite_each_other(w, slow_reads):
    sid = await make(w)                                                    # PICKUP_SCHEDULED, agent A
    status, assign = await asyncio.gather(
        post_status(w, sid, "PICKED_UP", w.ah),
        w.c.put(f"/api/shipments/{sid}/assign", json={"agentId": w.agent2["id"]}, headers=w.adm))
    final = await get(w, sid)
    if status.status_code == 200:
        assert "PICKED_UP" in [e["status"] for e in final["statusHistory"]], "status update was lost"
    if assign.status_code == 200:
        assert final["assignedAgentId"] == w.agent2["id"], "reassignment was lost"
    assert status.status_code in (200, 403, 409) and assign.status_code in (200, 409)
    assert_consistent(final)


async def test_history_never_loses_events_under_a_burst(w, slow_reads):
    """A burst of mixed operations from several actors: whatever order they land in, the
    stored history must remain a legal, gap-free path."""
    sid = await make(w, "IN_TRANSIT")
    ops = [post_status(w, sid, "OUT_FOR_DELIVERY", w.ah), post_status(w, sid, "DAMAGED", w.ah), post_status(w, sid, "OUT_FOR_DELIVERY", w.adm),
           post_status(w, sid, "RETURN_TO_ORIGIN", w.adm), post_status(w, sid, "DELIVERED", w.ah), post_status(w, sid, "CANCELLED", w.ch)]
    rs = await asyncio.gather(*ops)
    final = await get(w, sid)
    assert_consistent(final)
    applied = [r for r in rs if r.status_code == 200]
    assert len(final["statusHistory"]) == 4 + len(applied)                 # initial path (4 events) + exactly the successful ops
