"""Phase 5 / item 2 — authorization boundaries and input validation."""
from datetime import datetime, timedelta, timezone

import jwt
import pytest

import config
from tests.conftest import RECIPIENT, register

pytestmark = pytest.mark.anyio

ADMIN_BODY = dict(name="Boss", organization="Shipora")


class World:
    """Two customers, two agents, an admin and one shipment (owned by customer A, assigned to agent A)."""


@pytest.fixture
async def w(client):
    w = World()
    w.c = client
    w.custA, w.hA = await register(client, "user", "ca@t.test")
    w.custB, w.hB = await register(client, "user", "cb@t.test")
    w.agentA, w.aA = await register(client, "driver", "aa@t.test", vehicleNo="KA09ZZ1111", licenseNo="DL1111")
    w.agentB, w.aB = await register(client, "driver", "ab@t.test", vehicleNo="KA09ZZ2222", licenseNo="DL2222")
    w.admin, w.adm = await register(client, "admin", "boss@t.test")
    r = await client.post("/api/shipments", json={"recipient": RECIPIENT, "parcel": {"weightKg": 2}}, headers=w.hA)
    w.sid, w.tn = r.json()["_id"], r.json()["trackingNumber"]
    await client.put(f"/api/shipments/{w.sid}/assign", json={"agentId": w.agentA["id"]}, headers=w.adm)
    r = await client.post("/api/complaints", json={"subject": "s", "category": "other", "description": "x" * 25}, headers=w.hA)
    w.iid = r.json()["_id"]
    return w


# ─── role × endpoint matrix ────────────────────────────────────────────────
async def test_shipment_visibility_matrix(w):
    url = f"/api/shipments/{w.sid}"
    for headers, expected in [(w.hA, 200), (w.aA, 200), (w.adm, 200), (w.hB, 403), (w.aB, 403), (None, 401)]:
        r = await w.c.get(url, headers=headers or {})
        assert r.status_code == expected, (headers, r.status_code)
    lists = {name: (await w.c.get("/api/shipments", headers=h)).json() for name, h in
             dict(custA=w.hA, custB=w.hB, agentA=w.aA, agentB=w.aB, admin=w.adm).items()}
    assert [len(lists[k]) for k in ("custA", "custB", "agentA", "agentB", "admin")] == [1, 0, 1, 0, 1]


async def test_status_change_boundaries(w):
    s = f"/api/shipments/{w.sid}/status"
    post = lambda h, st: w.c.post(s, json={"status": st}, headers=h or {})
    assert (await post(None, "PICKED_UP")).status_code == 401
    assert (await post(w.hB, "CANCELLED")).status_code == 403           # someone else's shipment
    assert (await post(w.hA, "PICKED_UP")).status_code == 403           # customers can only cancel
    assert (await post(w.aB, "PICKED_UP")).status_code == 403           # agent B, not assigned
    assert (await post(w.aA, "CANCELLED")).status_code == 403           # agent cannot cancel
    assert (await post(w.aA, "RETURN_TO_ORIGIN")).status_code == 403    # admin-only status
    assert (await post(w.aA, "PICKUP_SCHEDULED")).status_code == 403
    assert (await post(w.aA, "NOT_A_STATUS")).status_code == 422        # invalid enum
    assert (await post(w.aA, "PICKED_UP")).status_code == 200


async def test_assignment_is_admin_only_no_self_assign(w):
    a = f"/api/shipments/{w.sid}/assign"
    for headers in (w.hA, w.hB, w.aA, w.aB):
        assert (await w.c.put(a, json={"agentId": w.agentB["id"]}, headers=headers)).status_code == 403
    assert (await w.c.put(a, json={"agentId": w.agentB["id"]})).status_code == 401
    # agent B tries to grab a shipment for themselves
    assert (await w.c.put(a, json={"agentId": w.agentB["id"]}, headers=w.aB)).status_code == 403
    cur = (await w.c.get(f"/api/shipments/{w.sid}", headers=w.adm)).json()
    assert cur["assignedAgentId"] == w.agentA["id"]
    # assigning a non-agent id (a customer id) is rejected
    r = await w.c.put(a, json={"agentId": w.custB["id"]}, headers=w.adm)
    assert r.status_code == 404


async def test_creation_and_admin_surfaces_are_role_gated(w):
    body = {"recipient": RECIPIENT, "parcel": {"weightKg": 1}}
    assert (await w.c.post("/api/shipments", json=body, headers=w.aA)).status_code == 403
    assert (await w.c.post("/api/shipments", json=body, headers=w.adm)).status_code == 403
    assert (await w.c.post("/api/shipments", json=body)).status_code == 401
    admin_only = [("get", "/api/admin/stats"), ("get", "/api/admin/drivers"), ("get", "/api/admin/logs"),
                  ("get", "/api/shipments/stats/summary"), ("get", "/api/analytics/overview"), ("get", "/api/analytics/timeseries")]
    for method, path in admin_only:
        for headers in (w.hA, w.aA):
            assert (await getattr(w.c, method)(path, headers=headers)).status_code == 403, (path, headers)
        assert (await getattr(w.c, method)(path)).status_code == 401, path
        assert (await getattr(w.c, method)(path, headers=w.adm)).status_code == 200, path
    for headers in (w.hA, w.aA):
        assert (await w.c.put("/api/support/config", json={"phone": "1"}, headers=headers)).status_code == 403
        assert (await w.c.put(f"/api/complaints/{w.iid}", json={"status": "closed"}, headers=headers)).status_code == 403


async def test_vehicle_endpoints_are_agent_only_and_live_feed_needs_auth(w):
    for path, body in [("/api/vehicles/status", {"currentArea": "x"}), ("/api/vehicles/area-complete", {"area": "x"})]:
        for headers in (w.hA, w.adm):
            assert (await w.c.post(path, json=body, headers=headers)).status_code == 403
        assert (await w.c.post(path, json=body)).status_code == 401
        assert (await w.c.post(path, json=body, headers=w.aA)).status_code == 200
    # the live fleet position feed (agent names, plates, GPS) is not public
    assert (await w.c.get("/api/vehicles/locations")).status_code == 401
    assert (await w.c.get("/api/vehicles/locations", headers=w.hA)).status_code == 200
    # customers cannot read other agents' route logs / contact details
    assert (await w.c.get("/api/vehicles/today", headers=w.hA)).status_code == 403
    assert (await w.c.get("/api/vehicles/history", headers=w.hA)).status_code == 403
    assert (await w.c.get("/api/vehicles/today", headers=w.adm)).status_code == 200
    assert (await w.c.get("/api/vehicles/history", headers=w.aA)).status_code == 200


async def test_delivery_issue_boundaries(w):
    body = {"subject": "s", "category": "other", "description": "y" * 25}
    assert (await w.c.post("/api/complaints", json=body, headers=w.aA)).status_code == 403
    assert (await w.c.post("/api/complaints", json=body, headers=w.adm)).status_code == 403
    assert (await w.c.post("/api/complaints", json=body)).status_code == 401
    mine, theirs, agent = [(await w.c.get("/api/complaints", headers=h)).json() for h in (w.hA, w.hB, w.aA)]
    assert len(mine) == 1 and theirs == [] and agent == []
    # a customer cannot attach an issue to someone else's shipment
    assert (await w.c.post("/api/complaints", json={**body, "trackingNumber": w.tn}, headers=w.hB)).status_code == 404
    # malformed ids never 500
    for bad in ("not-an-id", "123", "x" * 300):
        r = await w.c.put(f"/api/complaints/{bad}", json={"status": "closed"}, headers=w.adm)
        assert r.status_code in (400, 404, 422), (bad, r.status_code)
    assert (await w.c.put("/api/complaints/" + "0" * 24, json={"status": "closed"}, headers=w.adm)).status_code == 404


# ─── tokens ────────────────────────────────────────────────────────────────
async def test_forged_expired_and_tampered_tokens_are_rejected(w):
    ok = w.hA["Authorization"].split()[1]
    payload = jwt.decode(ok, options={"verify_signature": False})
    expired = jwt.encode({**payload, "exp": datetime.now(timezone.utc) - timedelta(minutes=1)}, config.JWT_SECRET, algorithm="HS256")
    wrong_key = jwt.encode(payload, "another-secret-that-is-long-enough-0123456789", algorithm="HS256")
    escalated = jwt.encode({**payload, "role": "admin"}, "guess-shipora_secret-0000000000000000", algorithm="HS256")
    none_alg = jwt.encode({**payload, "role": "admin"}, key=None, algorithm="none")
    h, p, s = ok.split(".")
    tampered_sig = f"{h}.{p}.{s[:-3]}abc"
    for token in (expired, wrong_key, escalated, none_alg, tampered_sig, "garbage", ""):
        r = await w.c.get("/api/admin/stats", headers={"Authorization": f"Bearer {token}"})
        assert r.status_code == 401, token[:20]
    # the old built-in default secret must not mint admin tokens any more
    legacy = jwt.encode({**payload, "role": "admin", "exp": datetime.now(timezone.utc) + timedelta(days=1)}, "shipora_secret", algorithm="HS256")
    assert (await w.c.get("/api/admin/stats", headers={"Authorization": f"Bearer {legacy}"})).status_code == 401


# ─── registration / profile / password reset ───────────────────────────────
async def test_registration_cannot_escalate_role(client):
    r = await client.post("/api/auth/register/user", json={
        "name": "X", "email": "x@t.test", "password": "secret123", "phone": "9000000001", "address": "1 Test Lane",
        "location": {"lat": 1, "lng": 2}, "role": "admin"})
    assert r.status_code == 201 and r.json()["user"]["role"] == "user"
    h = {"Authorization": "Bearer " + r.json()["token"]}
    assert (await client.get("/api/admin/stats", headers=h)).status_code == 403


async def test_admin_signup_is_gated_in_production(client, monkeypatch):
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.delenv("ADMIN_SIGNUP_CODE", raising=False)
    r = await client.post("/api/auth/register/admin", json={**ADMIN_BODY, "email": "p1@t.test", "password": "secret123"})
    assert r.status_code == 403                                          # no invite code configured => disabled
    monkeypatch.setenv("ADMIN_SIGNUP_CODE", "invite-9X7-correct-horse")
    for code in (None, "", "wrong"):
        body = {**ADMIN_BODY, "email": "p2@t.test", "password": "secret123", **({"inviteCode": code} if code is not None else {})}
        assert (await client.post("/api/auth/register/admin", json=body)).status_code == 403
    ok = await client.post("/api/auth/register/admin", json={**ADMIN_BODY, "email": "p3@t.test", "password": "secret123", "inviteCode": "invite-9X7-correct-horse"})
    assert ok.status_code == 201 and ok.json()["user"]["role"] == "admin"
    # other roles are unaffected
    assert (await client.post("/api/auth/register/driver", json=dict(name="A", email="pa@t.test", password="secret123", phone="9000000002",
                                                                        vehicleNo="KA01AB1234", licenseNo="DL9", assignedArea="z"))).status_code == 201


async def test_admin_signup_open_in_development_for_local_work(client, monkeypatch):
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.delenv("ADMIN_SIGNUP_CODE", raising=False)
    assert (await client.post("/api/auth/register/admin", json={**ADMIN_BODY, "email": "d@t.test", "password": "secret123"})).status_code == 201


async def test_password_reset_requires_a_reset_token(client):
    user, _ = await register(client, "user", "victim@t.test")
    # (1) knowing only the victim's email must NOT be enough to take the account over
    r = await client.post("/api/auth/reset-password", json={"email": "victim@t.test", "role": "user", "newPassword": "hacked-pass-1"})
    assert r.status_code in (400, 401, 403, 422)
    assert (await client.post("/api/auth/login", json={"email": "victim@t.test", "password": "hacked-pass-1", "role": "user"})).status_code == 400
    assert (await client.post("/api/auth/login", json={"email": "victim@t.test", "password": "secret123", "role": "user"})).status_code == 200
    bad = await client.post("/api/auth/reset-password", json={"email": "victim@t.test", "role": "user", "newPassword": "hacked-pass-2", "resetToken": "nope"})
    assert bad.status_code in (400, 401, 403)
    # (2) the legitimate flow: token comes from /forgot-password
    f = await client.post("/api/auth/forgot-password", json={"email": "victim@t.test", "role": "user"})
    token = f.json()["resetToken"]  # development only — in production it would be emailed
    other, _ = await register(client, "user", "other@t.test")
    wrong_acct = await client.post("/api/auth/reset-password", json={"email": "other@t.test", "role": "user", "newPassword": "hacked-pass-3", "resetToken": token})
    assert wrong_acct.status_code in (400, 401, 403)                      # token is bound to its own account
    ok = await client.post("/api/auth/reset-password", json={"email": "victim@t.test", "role": "user", "newPassword": "brand-new-pass", "resetToken": token})
    assert ok.status_code == 200
    assert (await client.post("/api/auth/login", json={"email": "victim@t.test", "password": "brand-new-pass", "role": "user"})).status_code == 200
    again = await client.post("/api/auth/reset-password", json={"email": "victim@t.test", "role": "user", "newPassword": "another-pass-9", "resetToken": token})
    assert again.status_code in (400, 401, 403)                           # single use


async def test_forgot_password_does_not_enumerate_or_leak_tokens_in_production(client, monkeypatch):
    await register(client, "user", "real@t.test")
    monkeypatch.setenv("APP_ENV", "production")
    a = await client.post("/api/auth/forgot-password", json={"email": "real@t.test", "role": "user"})
    b = await client.post("/api/auth/forgot-password", json={"email": "ghost@t.test", "role": "user"})
    assert a.status_code == b.status_code == 200
    assert a.json() == b.json() and "resetToken" not in a.json()


async def test_profile_update_is_validated_and_cannot_change_privileged_fields(w):
    r = await w.c.put("/api/auth/profile", json={"role": "admin", "email": "evil@t.test", "password": "x", "name": "New Name"}, headers=w.hA)
    assert r.status_code == 200 and r.json()["role"] == "user" and r.json()["email"] == "ca@t.test" and r.json()["name"] == "New Name"
    assert (await w.c.post("/api/auth/login", json={"email": "ca@t.test", "password": "secret123", "role": "user"})).status_code == 200
    for body in ({"location": {"lat": "x"}}, {"location": {"lat": 120, "lng": 0}}, {"location": "nope"}, {"customerType": "alien"}, {"name": ""}, {"name": "n" * 500}):
        assert (await w.c.put("/api/auth/profile", json=body, headers=w.hA)).status_code == 422, body
    # an invalid agent value used to be stored and then broke the account on next read
    for body in ({"vehicleType": "rocket"}, {"availability": "sleeping"}):
        assert (await w.c.put("/api/auth/profile", json=body, headers=w.aA)).status_code == 422, body
    assert (await w.c.get("/api/auth/profile", headers=w.aA)).status_code == 200
    assert (await w.c.post("/api/auth/login", json={"email": "aa@t.test", "password": "secret123", "role": "driver"})).status_code == 200


# ─── input validation ──────────────────────────────────────────────────────
def _body(**over):
    b = {"recipient": dict(RECIPIENT), "parcel": {"weightKg": 2}, "serviceType": "same_day"}
    for k, v in over.items():
        if k.startswith("recipient_"):
            b["recipient"][k[10:]] = v
        elif k.startswith("parcel_"):
            b["parcel"][k[7:]] = v
        else:
            b[k] = v
    return b


@pytest.mark.parametrize("field,value", [
    ("recipient_address", ""), ("recipient_address", "   "), ("recipient_address", "a" * 1000),
    ("recipient_name", ""), ("recipient_name", "n" * 500), ("recipient_phone", "abc"), ("recipient_phone", ""),
    ("recipient_location", {"lat": 91, "lng": 10}), ("recipient_location", {"lat": 10, "lng": 181}),
    ("recipient_location", {"lat": -91, "lng": 10}), ("recipient_location", {"lat": "x", "lng": 10}),
    ("parcel_weightKg", 0), ("parcel_weightKg", -3), ("parcel_weightKg", 1e9), ("parcel_weightKg", "heavy"),
    ("parcel_declaredValue", -1), ("parcel_declaredValue", 1e12),
    ("parcel_lengthCm", 0), ("parcel_description", "d" * 5000), ("parcel_category", "weapons"),
    ("serviceType", "teleport"),
])
async def test_shipment_creation_rejects_invalid_input(w, field, value):
    before = len((await w.c.get("/api/shipments", headers=w.hA)).json())
    r = await w.c.post("/api/shipments", json=_body(**{field: value}), headers=w.hA)
    assert r.status_code == 422, (field, value, r.status_code, r.text[:120])
    assert isinstance(r.json().get("message"), str) and r.json()["message"]  # readable for the UI, not Pydantic internals
    assert len((await w.c.get("/api/shipments", headers=w.hA)).json()) == before


async def test_valid_boundary_values_are_accepted(w):
    from services import geo
    r = await w.c.post("/api/shipments", json=_body(recipient_location={"lat": geo.SOUTH, "lng": geo.EAST}, parcel_weightKg=0.1, parcel_declaredValue=0), headers=w.hA)
    assert r.status_code == 201, r.text


async def test_shipments_outside_bengaluru_are_rejected(w):
    for loc in ({"lat": 28.61, "lng": 77.21}, {"lat": 13.30, "lng": 77.59}, {"lat": 12.97, "lng": 77.90}, {"lat": -90, "lng": 180}):  # Delhi, just N / E of the box, antipode
        r = await w.c.post("/api/shipments", json=_body(recipient_location=loc), headers=w.hA)
        assert r.status_code == 422 and "Bengaluru" in r.json()["message"], (loc, r.text)
    body = _body()
    body["sender"] = {"name": "S", "phone": "9880000055", "address": "1 Far Away Rd", "location": {"lat": 19.07, "lng": 72.87}}  # Mumbai pickup
    r = await w.c.post("/api/shipments", json=body, headers=w.hA)
    assert r.status_code == 422 and "pickup" in r.json()["message"], r.text


async def test_delivery_location_is_required(w):
    body = _body()
    body["recipient"].pop("location")
    r = await w.c.post("/api/shipments", json=body, headers=w.hA)
    assert r.status_code == 422 and "Bengaluru" in r.json()["message"], r.text


async def test_only_same_day_service_is_offered(w):
    for service in ("standard", "express"):
        assert (await w.c.post("/api/shipments", json=_body(serviceType=service), headers=w.hA)).status_code == 422, service
    r = await w.c.post("/api/shipments", json=_body(), headers=w.hA)
    created = r.json().get("shipment") or r.json()
    assert r.status_code == 201 and created["serviceType"] == "same_day"


async def test_registration_rejects_bad_coordinates_and_phone(client):
    base = dict(name="N", email="n@t.test", password="secret123", phone="9000000009", address="1 Test Lane", location={"lat": 1, "lng": 2})
    for patch in ({"location": {"lat": 200, "lng": 0}}, {"location": {"lat": 0, "lng": -999}}, {"phone": "x"}, {"name": ""}, {"password": "123"}):
        assert (await client.post("/api/auth/register/user", json={**base, **patch})).status_code == 422, patch


async def test_identifiers_are_validated(w):
    for bad in ("../../etc/passwd", "SHP", "x" * 500, "%00", "{\"$ne\":1}", "SHP-ZZZ"):
        assert (await w.c.get(f"/api/shipments/track/{bad}")).status_code in (404, 422), bad
        r = await w.c.get(f"/api/shipments/{bad}", headers=w.hA)
        assert r.status_code in (404, 422), (bad, r.status_code)
    assert (await w.c.put(f"/api/shipments/{w.sid}/assign", json={"agentId": "zz"}, headers=w.adm)).status_code == 400
    assert (await w.c.get("/api/shipments?status=BOGUS", headers=w.hA)).status_code == 422


async def test_public_tracking_leaks_nothing_personal(w):
    r = await w.c.get(f"/api/shipments/track/{w.tn}")
    assert r.status_code == 200
    text = r.text.lower()
    for secret in ("cust", "agent", "9880000077", "9 dest rd", "1 test st", w.custA["id"], w.agentA["id"], "ca@t.test", "ka09zz1111"):
        assert secret.lower() not in text, secret
    assert set(r.json()) == {"trackingNumber", "status", "serviceType", "estimatedDelivery", "deliveredAt", "timeline"}


async def test_chat_inputs_are_bounded(client):
    assert (await client.post("/api/chat", json={"message": "x" * 100000})).status_code == 422
    assert (await client.post("/api/chat", json={"message": "   "})).status_code == 400
    assert (await client.post("/api/chat", json={"message": "hi", "sessionId": "s" * 500})).status_code == 422


# ─── lifecycle rules cannot be bypassed ────────────────────────────────────
async def test_attempt_limit_and_terminal_states_cannot_be_bypassed(w):
    st = lambda h, s: w.c.post(f"/api/shipments/{w.sid}/status", json={"status": s}, headers=h)
    for s in ("PICKED_UP", "IN_TRANSIT"):
        assert (await st(w.aA, s)).status_code == 200
    for i in range(3):
        assert (await st(w.aA, "OUT_FOR_DELIVERY")).status_code == 200
        assert (await st(w.aA, "DELIVERY_FAILED")).status_code == 200
    assert (await st(w.aA, "OUT_FOR_DELIVERY")).status_code == 409
    assert (await st(w.adm, "OUT_FOR_DELIVERY")).status_code == 409       # not even admin
    assert (await st(w.adm, "RETURN_TO_ORIGIN")).status_code == 200
    for who in (w.adm, w.aA, w.hA):
        for target in ("DELIVERED", "OUT_FOR_DELIVERY", "CANCELLED", "PICKUP_SCHEDULED", "CREATED"):
            assert (await st(who, target)).status_code in (403, 409), (who, target)
    assert (await w.c.put(f"/api/shipments/{w.sid}/assign", json={"agentId": w.agentB["id"]}, headers=w.adm)).status_code == 409
    final = (await w.c.get(f"/api/shipments/{w.sid}", headers=w.adm)).json()
    assert final["status"] == "RETURN_TO_ORIGIN" and final["deliveryAttempts"] == 3


async def test_status_note_is_bounded(w):
    r = await w.c.post(f"/api/shipments/{w.sid}/status", json={"status": "PICKED_UP", "note": "n" * 5000}, headers=w.aA)
    assert r.status_code == 422


# ─── account uniqueness + admin sign-up policy ─────────────────────────────
async def test_each_account_collection_has_a_unique_email_index(client):
    from models.admin import Admin
    from models.customer import Customer
    from models.delivery_agent import DeliveryAgent

    for model in (Customer, DeliveryAgent, Admin):
        info = await model.get_motor_collection().index_information()
        assert any(v.get("unique") and [k for k, _ in v["key"]] == ["email"] for v in info.values()), model.__name__


async def test_duplicate_email_is_rejected_even_when_the_pre_check_is_raced(client, monkeypatch):
    from models.customer import Customer

    body = dict(name="Dup", email="dup@t.test", password="secret123", phone="9000000011", address="1 Test Lane", location={"lat": 12.97, "lng": 77.59})
    assert (await client.post("/api/auth/register/user", json=body)).status_code == 201
    real_find = Customer.find_one

    async def blind(*a, **k):  # simulate the second request passing the "already registered?" check at the same instant
        return None
    monkeypatch.setattr(Customer, "find_one", blind)
    r = await client.post("/api/auth/register/user", json=body)
    monkeypatch.setattr(Customer, "find_one", real_find)
    assert r.status_code == 400 and "already registered" in r.json()["message"].lower()


async def test_admin_signup_is_closed_on_a_real_database_without_an_invite_code(client, monkeypatch):
    import database
    body = {"name": "Ad", "email": "ad@t.test", "password": "secret123", "organization": "x"}
    monkeypatch.delenv("ADMIN_SIGNUP_CODE", raising=False)
    monkeypatch.setattr(database, "REAL_DB", True)
    assert (await client.post("/api/auth/register/admin", json=body)).status_code == 403          # real DB, no code: closed
    monkeypatch.setenv("ADMIN_SIGNUP_CODE", "let-me-in-1234")
    assert (await client.post("/api/auth/register/admin", json=body)).status_code == 403          # wrong / missing code
    assert (await client.post("/api/auth/register/admin", json={**body, "inviteCode": "let-me-in-1234"})).status_code == 201
    monkeypatch.delenv("ADMIN_SIGNUP_CODE", raising=False)
    monkeypatch.setattr(database, "REAL_DB", False)
    assert (await client.post("/api/auth/register/admin", json={**body, "email": "ad2@t.test"})).status_code == 201  # throw-away dev DB: open
