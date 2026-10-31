"""Phase 5 / item 6 — rate limiting on security-sensitive and high-cost endpoints."""
import pytest

import ratelimit
from tests.conftest import RECIPIENT, register

pytestmark = pytest.mark.anyio

LOGIN = {"email": "nobody@t.test", "password": "wrong-password", "role": "user"}


@pytest.fixture(autouse=True)
def limits_on(monkeypatch):
    """Rate limiting is off for the rest of the suite (conftest); these tests turn it on with a controllable clock."""
    monkeypatch.setenv("RATE_LIMIT_ENABLED", "true")
    clock = {"t": 1000.0}
    monkeypatch.setattr(ratelimit.limiter, "clock", lambda: clock["t"])
    ratelimit.limiter.reset()
    return clock


@pytest.fixture
def clock(limits_on):
    return limits_on


# ─── spec parsing / configuration ──────────────────────────────────────────
def test_limit_spec_parsing(monkeypatch):
    assert ratelimit.parse_spec("10/60") == (10, 60.0)
    assert ratelimit.parse_spec(" 5 / 2.5 ") == (5, 2.5)
    for bad in ("", "x", "10", "0/60", "-1/60", "10/0", "10/-3", "a/b"):
        assert ratelimit.parse_spec(bad) is None, bad
    monkeypatch.setenv("RATE_LIMIT_LOGIN", "3/30")
    assert ratelimit.limit_for("login") == (3, 30.0)
    monkeypatch.setenv("RATE_LIMIT_LOGIN", "garbage")
    assert ratelimit.limit_for("login") == ratelimit.DEFAULT_LIMITS["login"]   # a typo never disables protection


def test_sliding_window_unit(clock):
    lim = ratelimit.limiter
    for _ in range(3):
        assert lim.hit("t", "k", 3, 10)[0] is True
    ok, retry = lim.hit("t", "k", 3, 10)
    assert ok is False and 0 < retry <= 10
    clock["t"] += 10.1
    assert lim.hit("t", "k", 3, 10)[0] is True                       # window slid
    assert lim.hit("t", "other", 3, 10)[0] is True                   # keys are independent


def test_idle_keys_are_purged(clock):
    lim = ratelimit.limiter
    for i in range(50):
        lim.hit("t", f"k{i}", 5, 10)
    assert lim.size() == 50
    clock["t"] += 11
    lim.purge()
    assert lim.size() == 0


# ─── endpoints ─────────────────────────────────────────────────────────────
async def test_login_is_limited_per_client_and_recovers(client, monkeypatch, clock):
    monkeypatch.setenv("RATE_LIMIT_LOGIN", "5/60")
    codes = [(await client.post("/api/auth/login", json={**LOGIN, "email": f"u{i}@t.test"})).status_code for i in range(7)]
    assert codes[:5] == [400] * 5 and codes[5:] == [429, 429]
    r = await client.post("/api/auth/login", json=LOGIN)
    assert r.status_code == 429
    assert int(r.headers["retry-after"]) >= 1
    assert isinstance(r.json()["message"], str) and "too many" in r.json()["message"].lower()
    clock["t"] += 61
    assert (await client.post("/api/auth/login", json=LOGIN)).status_code == 400   # allowed again (just wrong credentials)


async def test_one_account_cannot_be_hammered_from_many_addresses(client, monkeypatch):
    monkeypatch.setenv("TRUST_PROXY_HEADERS", "true")
    monkeypatch.setenv("RATE_LIMIT_LOGIN", "1000/60")
    monkeypatch.setenv("RATE_LIMIT_LOGIN_ACCOUNT", "4/60")
    await register(client, "user", "victim@t.test")
    codes = []
    for i in range(7):
        r = await client.post("/api/auth/login", json={"email": "victim@t.test", "password": f"guess-{i}", "role": "user"},
                              headers={"X-Forwarded-For": f"203.0.113.{i}"})            # a different "IP" every time
        codes.append(r.status_code)
    assert codes[:4] == [400] * 4 and codes[4:] == [429] * 3
    # the real owner is locked out too for the window — and other accounts are untouched
    other = await client.post("/api/auth/login", json={**LOGIN, "email": "someone-else@t.test"}, headers={"X-Forwarded-For": "198.51.100.9"})
    assert other.status_code == 400


async def test_successful_logins_do_not_burn_the_account_limit(client, monkeypatch):
    monkeypatch.setenv("RATE_LIMIT_LOGIN_ACCOUNT", "3/60")
    await register(client, "user", "real@t.test")
    for _ in range(6):
        assert (await client.post("/api/auth/login", json={"email": "real@t.test", "password": "secret123", "role": "user"})).status_code == 200


async def test_proxy_headers_are_ignored_unless_trusted(client, monkeypatch):
    monkeypatch.delenv("TRUST_PROXY_HEADERS", raising=False)
    monkeypatch.setenv("RATE_LIMIT_LOGIN", "3/60")
    codes = [(await client.post("/api/auth/login", json={**LOGIN, "email": f"p{i}@t.test"}, headers={"X-Forwarded-For": f"203.0.113.{i}"})).status_code for i in range(5)]
    assert codes == [400, 400, 400, 429, 429]                         # spoofing X-Forwarded-For doesn't dodge the limit


async def test_registration_and_password_reset_are_limited(client, monkeypatch):
    monkeypatch.setenv("RATE_LIMIT_REGISTER", "3/3600")
    monkeypatch.setenv("RATE_LIMIT_PASSWORD_RESET", "2/900")
    base = dict(name="N", password="secret123", phone="9000000001", address="1 Test Lane", location={"lat": 1, "lng": 2})
    codes = [(await client.post("/api/auth/register/user", json={**base, "email": f"r{i}@t.test"})).status_code for i in range(5)]
    assert codes == [201, 201, 201, 429, 429]
    f = [(await client.post("/api/auth/forgot-password", json={"email": "r0@t.test", "role": "user"})).status_code for _ in range(4)]
    assert f == [200, 200, 429, 429]
    assert (await client.post("/api/auth/reset-password", json={"email": "r0@t.test", "newPassword": "newpass99", "resetToken": "x"})).status_code == 429


async def test_public_tracking_is_limited_but_generous(client, monkeypatch):
    for _ in range(30):                                               # default allows ordinary polling
        assert (await client.get("/api/shipments/track/SHP0000000000")).status_code == 404
    monkeypatch.setenv("RATE_LIMIT_TRACK", "3/60")
    ratelimit.limiter.reset()
    codes = [(await client.get("/api/shipments/track/SHP0000000000")).status_code for _ in range(5)]
    assert codes == [404, 404, 404, 429, 429]


async def test_chat_is_limited_per_user_not_globally(client, monkeypatch):
    monkeypatch.setenv("RATE_LIMIT_CHAT", "2/60")
    _, a = await register(client, "user", "a@t.test")
    _, b = await register(client, "user", "b@t.test")
    send = lambda h: client.post("/api/chat", json={"message": "hello"}, headers=h)
    assert [(await send(a)).status_code for _ in range(3)] == [200, 200, 429]
    assert (await send(b)).status_code == 200                         # a different customer is unaffected
    assert (await client.post("/api/chat", json={"message": "hi"})).status_code == 200   # so is an anonymous visitor (own bucket)


async def test_voice_is_limited_and_oversize_uploads_are_refused(client, monkeypatch):
    import config
    monkeypatch.setenv("RATE_LIMIT_VOICE", "2/60")
    files = lambda n=10: {"audio": ("a.webm", b"x" * n, "audio/webm")}
    r = [(await client.post("/api/voice/chat", files=files(), data={"speak": "false"})).status_code for _ in range(3)]
    assert r[2] == 429 and 429 not in r[:2]
    ratelimit.limiter.reset()
    monkeypatch.setattr(config, "VOICE_MAX_UPLOAD_BYTES", 100)
    assert (await client.post("/api/voice/chat", files=files(500), data={"speak": "false"})).status_code == 413


async def test_shipment_creation_is_limited_per_customer(client, monkeypatch):
    monkeypatch.setenv("RATE_LIMIT_SHIPMENT_CREATE", "3/60")
    _, a = await register(client, "user", "a@t.test")
    _, b = await register(client, "user", "b@t.test")
    mk = lambda h, i: client.post("/api/shipments", json={"recipient": RECIPIENT, "parcel": {"weightKg": i + 1}}, headers=h)
    assert [(await mk(a, i)).status_code for i in range(5)] == [201, 201, 201, 429, 429]
    assert (await mk(b, 0)).status_code == 201


async def test_normal_traffic_is_not_throttled(client):
    """Tracking/status traffic is deliberately NOT rate limited: dashboards poll and agents tap through states."""
    _, ch = await register(client, "user", "c@t.test")
    agent, ah = await register(client, "driver", "a@t.test")
    _, adm = await register(client, "admin", "boss@t.test")
    s = (await client.post("/api/shipments", json={"recipient": RECIPIENT}, headers=ch)).json()
    await client.put(f"/api/shipments/{s['_id']}/assign", json={"agentId": agent["id"]}, headers=adm)
    for _ in range(150):
        assert (await client.get(f"/api/shipments/{s['_id']}", headers=ch)).status_code == 200
        assert (await client.get("/api/shipments", headers=ch)).status_code == 200
    for _ in range(40):
        assert (await client.post("/api/vehicles/status", json={"currentArea": "X"}, headers=ah)).status_code == 200


async def test_limiter_can_be_disabled(client, monkeypatch):
    monkeypatch.setenv("RATE_LIMIT_ENABLED", "false")
    monkeypatch.setenv("RATE_LIMIT_LOGIN", "1/60")
    assert [(await client.post("/api/auth/login", json=LOGIN)).status_code for _ in range(4)] == [400] * 4


async def test_throttle_events_are_logged_without_sensitive_data(client, monkeypatch, caplog):
    import logging
    monkeypatch.setenv("RATE_LIMIT_LOGIN", "1/60")
    with caplog.at_level(logging.WARNING):
        await client.post("/api/auth/login", json={**LOGIN, "email": "private.person@t.test"})
        await client.post("/api/auth/login", json={**LOGIN, "email": "private.person@t.test"})
    text = caplog.text
    assert "rate limit" in text.lower()
    assert "private.person@t.test" not in text and "wrong-password" not in text
