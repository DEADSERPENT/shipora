import pytest

from models.shipment import allowed_next_statuses
from tests.conftest import RECIPIENT, register

pytestmark = pytest.mark.anyio


async def _setup(client):
    cust, ch = await register(client, "user", "c@t.test")
    agent, ah = await register(client, "driver", "a@t.test")
    _, adm = await register(client, "admin", "boss@t.test")
    return cust, ch, agent, ah, adm


async def _new_shipment(client, ch, **extra):
    r = await client.post("/api/shipments", json={"recipient": RECIPIENT, "parcel": {"weightKg": 2, "category": "electronics"}, **extra}, headers=ch)
    assert r.status_code == 201, r.text
    return r.json()


async def _status(client, headers, sid, status, expect=200):
    r = await client.post(f"/api/shipments/{sid}/status", json={"status": status}, headers=headers)
    assert r.status_code == expect, f"{status}: {r.status_code} {r.text}"
    return r.json()


# ─── Auth ──────────────────────────────────────────────────────────────────
async def test_auth_roles_login_and_profile(client):
    cust, ch, agent, ah, adm = await _setup(client)
    assert cust["customerType"] == "individual"
    assert agent["vehicleNo"] == "KA09ZZ0001" and agent["vehicleType"] == "bike"

    r = await client.post("/api/auth/login", json={"email": "C@T.test", "password": "secret123", "role": "user"})
    assert r.status_code == 200 and r.json()["user"]["role"] == "user"
    r = await client.post("/api/auth/login", json={"email": "c@t.test", "password": "wrong", "role": "user"})
    assert r.status_code == 400 and r.json()["message"] == "Invalid credentials"
    # a customer account must not log in through the agent role
    r = await client.post("/api/auth/login", json={"email": "c@t.test", "password": "secret123", "role": "driver"})
    assert r.status_code == 400

    r = await client.put("/api/auth/profile", json={"deliveryInstructions": "Leave at door", "customerType": "business"}, headers=ch)
    assert r.json()["deliveryInstructions"] == "Leave at door" and r.json()["customerType"] == "business"
    assert (await client.get("/api/auth/profile")).status_code == 401


# ─── Shipment create / retrieve ────────────────────────────────────────────
async def test_create_and_retrieve_shipment(client):
    cust, ch, agent, ah, adm = await _setup(client)
    s = await _new_shipment(client, ch, serviceType="same_day")
    assert s["status"] == "CREATED" and s["trackingNumber"].startswith("SHP")
    assert s["sender"]["address"] == "1 Test St"  # defaulted from the customer profile
    assert [e["status"] for e in s["statusHistory"]] == ["CREATED"]

    # retrieve by id and by tracking number, with allowed next statuses
    r = await client.get(f"/api/shipments/{s['trackingNumber']}", headers=ch)
    assert r.status_code == 200 and r.json()["_id"] == s["_id"]
    assert r.json()["allowedNextStatuses"] == ["CANCELLED"]  # customer: cancel only
    admin_view = (await client.get(f"/api/shipments/{s['_id']}", headers=adm)).json()
    assert admin_view["allowedNextStatuses"] == ["CANCELLED", "PICKUP_SCHEDULED"]

    # role scoping
    assert len((await client.get("/api/shipments", headers=ch)).json()) == 1
    assert len((await client.get("/api/shipments", headers=adm)).json()) == 1
    assert (await client.get("/api/shipments", headers=ah)).json() == []  # not assigned yet
    _, other = await register(client, "user", "other@t.test")
    assert (await client.get(f"/api/shipments/{s['_id']}", headers=other)).status_code == 403
    assert (await client.get(f"/api/shipments/{s['_id']}", headers=ah)).status_code == 403

    # validation + permissions
    assert (await client.post("/api/shipments", json={"recipient": RECIPIENT, "parcel": {"weightKg": 0}}, headers=ch)).status_code == 422
    assert (await client.post("/api/shipments", json={"recipient": RECIPIENT, "serviceType": "teleport"}, headers=ch)).status_code == 422
    assert (await client.post("/api/shipments", json={"recipient": RECIPIENT}, headers=ah)).status_code == 403
    assert (await client.post("/api/shipments", json={"recipient": RECIPIENT})).status_code == 401
    assert (await client.get("/api/shipments/SHPDOESNOTEXIST", headers=ch)).status_code == 404


async def test_public_tracking_hides_pii(client):
    cust, ch, *_ = await _setup(client)
    s = await _new_shipment(client, ch)
    r = await client.get(f"/api/shipments/track/{s['trackingNumber'].lower()}")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "CREATED" and body["timeline"][0]["status"] == "CREATED"
    assert "sender" not in body and "recipient" not in body and "customerId" not in body
    assert all(set(e) == {"status", "at"} for e in body["timeline"])  # no notes (can name the agent)
    assert (await client.get("/api/shipments/track/SHPNOPE")).status_code == 404


# ─── Lifecycle ─────────────────────────────────────────────────────────────
async def test_full_lifecycle_happy_path(client):
    cust, ch, agent, ah, adm = await _setup(client)
    s = await _new_shipment(client, ch)

    # can't skip ahead, and can't move forward with no agent
    await _status(client, adm, s["_id"], "IN_TRANSIT", expect=409)
    await _status(client, adm, s["_id"], "PICKUP_SCHEDULED")  # admin may schedule manually...
    await _status(client, adm, s["_id"], "PICKED_UP", expect=409)  # ...but no agent yet

    r = await client.put(f"/api/shipments/{s['_id']}/assign", json={"agentId": agent["id"]}, headers=adm)
    assert r.status_code == 200 and r.json()["assignedAgent"]["vehicleNo"] == "KA09ZZ0001"

    for st in ["PICKED_UP", "IN_TRANSIT", "OUT_FOR_DELIVERY", "DELIVERED"]:
        out = await _status(client, ah, s["_id"], st)
    assert out["status"] == "DELIVERED" and out["deliveredAt"] and out["deliveryAttempts"] == 1
    assert [e["status"] for e in out["statusHistory"]] == [
        "CREATED", "PICKUP_SCHEDULED", "PICKED_UP", "IN_TRANSIT", "OUT_FOR_DELIVERY", "DELIVERED"]

    # terminal: nothing further, for anyone
    await _status(client, adm, s["_id"], "OUT_FOR_DELIVERY", expect=409)
    await _status(client, ch, s["_id"], "CANCELLED", expect=409)

    # agent's tracking log reflects the delivery
    hist = (await client.get("/api/vehicles/history", headers=ah)).json()
    assert hist and hist[0]["deliveredCount"] == 1 and hist[0]["activeShipmentIds"] == []


async def test_assign_schedules_pickup_and_agent_scoping(client):
    cust, ch, agent, ah, adm = await _setup(client)
    other_agent, oh = await register(client, "driver", "a2@t.test", vehicleNo="KA09ZZ0002", licenseNo="dl456")
    s = await _new_shipment(client, ch)

    assert (await client.put(f"/api/shipments/{s['_id']}/assign", json={"agentId": agent["id"]}, headers=ch)).status_code == 403
    assert (await client.put(f"/api/shipments/{s['_id']}/assign", json={"agentId": "x"}, headers=adm)).status_code == 400
    assert (await client.put(f"/api/shipments/{s['_id']}/assign", json={"agentId": "0" * 24}, headers=adm)).status_code == 404

    r = await client.put(f"/api/shipments/{s['_id']}/assign", json={"agentId": agent["id"]}, headers=adm)
    assert r.json()["status"] == "PICKUP_SCHEDULED" and r.json()["pickupScheduledAt"]

    assert len((await client.get("/api/shipments", headers=ah)).json()) == 1
    assert (await client.get("/api/shipments", headers=oh)).json() == []
    await _status(client, oh, s["_id"], "PICKED_UP", expect=403)  # someone else's shipment
    await _status(client, ah, s["_id"], "RETURN_TO_ORIGIN", expect=403)  # admin-only status
    await _status(client, ah, s["_id"], "CANCELLED", expect=403)
    await _status(client, ah, s["_id"], "PICKED_UP")


async def test_exception_states_and_retry_limit(client):
    cust, ch, agent, ah, adm = await _setup(client)
    s = await _new_shipment(client, ch)
    await client.put(f"/api/shipments/{s['_id']}/assign", json={"agentId": agent["id"]}, headers=adm)
    for st in ["PICKED_UP", "IN_TRANSIT"]:
        await _status(client, ah, s["_id"], st)

    # three failed attempts, then OUT_FOR_DELIVERY is refused
    for attempt in range(3):
        await _status(client, ah, s["_id"], "OUT_FOR_DELIVERY")
        await _status(client, ah, s["_id"], "CUSTOMER_UNAVAILABLE" if attempt == 0 else "DELIVERY_FAILED")
        mid = (await client.get(f"/api/shipments/{s['_id']}", headers=ah)).json()
        assert mid["allowedNextStatuses"] == ([] if attempt == 2 else ["OUT_FOR_DELIVERY"])  # agent view; RTO is admin-only, retries capped at 3
        adm_mid = (await client.get(f"/api/shipments/{s['_id']}", headers=adm)).json()
        assert adm_mid["allowedNextStatuses"] == (["RETURN_TO_ORIGIN"] if attempt == 2 else ["OUT_FOR_DELIVERY", "RETURN_TO_ORIGIN"])
    await _status(client, ah, s["_id"], "OUT_FOR_DELIVERY", expect=409)
    out = await _status(client, adm, s["_id"], "RETURN_TO_ORIGIN")
    assert out["deliveryAttempts"] == 3 and out["status"] == "RETURN_TO_ORIGIN"
    await _status(client, adm, s["_id"], "OUT_FOR_DELIVERY", expect=409)


async def test_failed_pickup_resumes_at_pickup_leg(client):
    cust, ch, agent, ah, adm = await _setup(client)
    s = await _new_shipment(client, ch)
    await client.put(f"/api/shipments/{s['_id']}/assign", json={"agentId": agent["id"]}, headers=adm)
    await _status(client, ah, s["_id"], "ADDRESS_ISSUE")  # at pickup
    await _status(client, adm, s["_id"], "OUT_FOR_DELIVERY", expect=409)  # wrong leg
    await _status(client, adm, s["_id"], "PICKUP_SCHEDULED")  # reschedule
    await _status(client, ah, s["_id"], "PICKED_UP")


async def test_damaged_and_customer_cancellation(client):
    cust, ch, agent, ah, adm = await _setup(client)
    s1, s2 = await _new_shipment(client, ch), await _new_shipment(client, ch)

    assert (await _status(client, ch, s1["_id"], "CANCELLED"))["status"] == "CANCELLED"
    await _status(client, ch, s2["_id"], "PICKUP_SCHEDULED", expect=403)  # customers can only cancel
    _, other = await register(client, "user", "o@t.test")
    await _status(client, other, s2["_id"], "CANCELLED", expect=403)

    await client.put(f"/api/shipments/{s2['_id']}/assign", json={"agentId": agent["id"]}, headers=adm)
    await _status(client, ah, s2["_id"], "PICKED_UP")
    await _status(client, ch, s2["_id"], "CANCELLED", expect=409)  # too late for the customer
    await _status(client, ah, s2["_id"], "DAMAGED")
    assert (await _status(client, adm, s2["_id"], "CANCELLED"))["status"] == "CANCELLED"


def test_transition_table_shape():
    assert allowed_next_statuses("DELIVERED", []) == set()
    assert allowed_next_statuses("CANCELLED", []) == set()
    assert allowed_next_statuses("RETURN_TO_ORIGIN", []) == set()
    assert allowed_next_statuses("IN_TRANSIT", []) == {"OUT_FOR_DELIVERY", "DAMAGED", "RETURN_TO_ORIGIN"}


# ─── Delivery issues ───────────────────────────────────────────────────────
async def test_delivery_issues_linked_to_shipment(client):
    cust, ch, agent, ah, adm = await _setup(client)
    s = await _new_shipment(client, ch)
    body = {"subject": "Box crushed", "category": "damaged_parcel", "description": "Arrived damaged", "trackingNumber": s["trackingNumber"]}

    r = await client.post("/api/complaints", json=body, headers=ch)
    assert r.status_code == 201 and r.json()["shipmentId"] == s["_id"] and r.json()["customerName"] == "Cust"
    assert (await client.post("/api/complaints", json={**body, "category": "missed_pickup"}, headers=ch)).status_code == 422  # not a Shipora category
    assert (await client.post("/api/complaints", json=body, headers=ah)).status_code == 403
    _, other = await register(client, "user", "o2@t.test")
    assert (await client.post("/api/complaints", json=body, headers=other)).status_code == 404  # not their shipment

    r = await client.post("/api/complaints", json={**body, "isAnonymous": True, "trackingNumber": None}, headers=ch)
    assert r.status_code == 201 and r.json()["customerId"] is None
    admin_view = (await client.get("/api/complaints", headers=adm)).json()
    assert len(admin_view) == 2 and any(i["customerName"] == "Anonymous" for i in admin_view)
    assert len((await client.get("/api/complaints", headers=ch)).json()) == 1

    r = await client.put(f"/api/complaints/{admin_view[0]['_id']}", json={"status": "resolved", "adminReply": "Refunded"}, headers=adm)
    assert r.json()["status"] == "resolved" and r.json()["resolvedAt"]


# ─── Delivery agent / vehicle tracking / admin ─────────────────────────────
async def test_delivery_agent_tracking_and_admin_views(client):
    cust, ch, agent, ah, adm = await _setup(client)
    assert (await client.post("/api/vehicles/status", json={"currentArea": "X"}, headers=ch)).status_code == 403
    r = await client.post("/api/vehicles/status", json={"currentArea": "Koramangala", "eta": "10 mins", "areasCompleted": ["4th Block"]}, headers=ah)
    assert r.status_code == 200 and r.json()["areasCompleted"] == ["4th Block"] and r.json()["deliveredCount"] == 0
    assert (await client.post("/api/vehicles/area-complete", json={"area": "5th Block"}, headers=ah)).json()["areasCompleted"] == ["4th Block", "5th Block"]

    assert (await client.get("/api/vehicles/today", headers=ch)).status_code == 403  # route logs are operations-only
    today = (await client.get("/api/vehicles/today", headers=adm)).json()
    assert today[0]["driverId"]["vehicleNo"] == "KA09ZZ0001"

    s = await _new_shipment(client, ch)
    await client.put(f"/api/shipments/{s['_id']}/assign", json={"agentId": agent["id"]}, headers=adm)
    for st in ["PICKED_UP", "IN_TRANSIT", "OUT_FOR_DELIVERY"]:
        await _status(client, ah, s["_id"], st)
    log = (await client.get("/api/vehicles/history", headers=ah)).json()[0]
    assert log["activeShipmentIds"] == [s["_id"]]

    stats = (await client.get("/api/admin/stats", headers=adm)).json()
    assert stats["totalDrivers"] == 1 and stats["totalCustomers"] == 1 and stats["totalShipments"] == 1 and stats["activeShipments"] == 1
    assert (await client.get("/api/admin/stats", headers=ch)).status_code == 403
    agents = (await client.get("/api/admin/drivers", headers=adm)).json()
    assert agents[0]["availability"] == "available" and agents[0]["todayLog"]["activeShipmentIds"] == [s["_id"]]
    summary = (await client.get("/api/shipments/stats/summary", headers=adm)).json()
    assert summary["byStatus"] == {"OUT_FOR_DELIVERY": 1}


async def test_ai_tools_use_new_models(client):
    from tools.analytics import execute_get_operations_summary
    from tools.complaint_tools import execute_create_complaint, execute_get_complaint_status
    from tools.schedule_tools import execute_get_my_shipments
    from tools.shipment_tools import execute_get_shipment_status
    from tools.tracking_tools import execute_get_vehicle_status

    cust, ch, agent, ah, adm = await _setup(client)
    s = await _new_shipment(client, ch)
    await client.post("/api/vehicles/status", json={"currentArea": "Koramangala", "eta": "5 mins"}, headers=ah)

    r = await execute_get_shipment_status(s["trackingNumber"])
    assert r["found"] and r["status"] == "CREATED" and "recipient" not in r
    assert (await execute_get_shipment_status("SHPNOPE"))["found"] is False
    assert (await execute_get_my_shipments(cust | {"role": "user"}))["shipments"][0]["trackingNumber"] == s["trackingNumber"]
    assert (await execute_get_my_shipments(None))["note"]
    assert (await execute_get_vehicle_status(area="Koramangala", current_user={"id": "0" * 24, "role": "admin"}))["vehicles"][0]["vehicleNo"] == "KA09ZZ0001"
    created = await execute_create_complaint("Late", "delayed_delivery", "Very late", trackingNumber=s["trackingNumber"], current_user=cust | {"role": "user"})
    assert created["created"]
    bad = await execute_create_complaint("Late", "delayed_delivery", "Very late", trackingNumber="SHPNOPE", current_user=cust | {"role": "user"})
    assert bad["created"] is False
    assert (await execute_get_complaint_status(cust | {"role": "user"}))["complaints"][0]["status"] == "open"
    summ = await execute_get_operations_summary(current_user={"id": "0" * 24, "role": "admin"})
    assert summ["shipments"]["total"] == 1 and summ["complaints"]["total"] == 1 and summ["todayVehicles"]["activeVehicles"] == 1
