"""Phase 5 / item 4 — duplicate shipment creation (retries, double-clicks, network retries)."""
import asyncio

import pytest

from models.shipment import Shipment
from tests.conftest import RECIPIENT, register

pytestmark = pytest.mark.anyio

BODY = {"recipient": RECIPIENT, "parcel": {"weightKg": 2, "category": "electronics"}, "serviceType": "same_day"}


@pytest.fixture
async def w(client):
    class W: ...
    w = W()
    w.c = client
    _, w.ch = await register(client, "user", "c@t.test")
    _, w.ch2 = await register(client, "user", "c2@t.test")
    return w


async def count(w, headers=None):
    return len((await w.c.get("/api/shipments", headers=headers or w.ch)).json())


def post(w, body=None, key=None, headers=None):
    h = dict(headers or w.ch)
    if key is not None:
        h["Idempotency-Key"] = key
    return w.c.post("/api/shipments", json=body or BODY, headers=h)


@pytest.fixture
def slow_insert(monkeypatch):
    original = Shipment.insert

    async def slow(self, *a, **k):
        await asyncio.sleep(0.05)
        return await original(self, *a, **k)
    monkeypatch.setattr(Shipment, "insert", slow)


async def test_repeated_request_with_same_key_creates_one_shipment(w):
    first = await post(w, key="form-0001-abcdef")
    again = await post(w, key="form-0001-abcdef")
    assert first.status_code == 201 and again.status_code == 200
    assert again.headers.get("idempotent-replay") == "true" and "idempotent-replay" not in first.headers
    assert again.json()["_id"] == first.json()["_id"] and again.json()["trackingNumber"] == first.json()["trackingNumber"]
    assert await count(w) == 1


async def test_concurrent_identical_requests_create_exactly_one(w, slow_insert):
    rs = await asyncio.gather(*[post(w, key="double-click-key-1") for _ in range(6)])
    assert sorted(r.status_code for r in rs).count(201) == 1 and all(r.status_code in (200, 201) for r in rs), [r.status_code for r in rs]
    assert len({r.json()["trackingNumber"] for r in rs}) == 1
    assert await count(w) == 1


async def test_same_key_with_different_payload_is_rejected(w):
    ok = await post(w, key="reused-key-12345")
    changed = {**BODY, "parcel": {"weightKg": 3}}
    r = await post(w, body=changed, key="reused-key-12345")
    assert ok.status_code == 201 and r.status_code == 422
    assert "idempotency" in r.json()["message"].lower()
    assert await count(w) == 1


async def test_keys_are_scoped_per_customer(w):
    a = await post(w, key="shared-key-123456", headers=w.ch)
    b = await post(w, key="shared-key-123456", headers=w.ch2)
    assert a.status_code == 201 and b.status_code == 201
    assert a.json()["_id"] != b.json()["_id"]
    assert await count(w, w.ch) == 1 and await count(w, w.ch2) == 1


async def test_different_keys_are_distinct_intents(w):
    a, b = await post(w, key="intent-aaaaaaaa"), await post(w, key="intent-bbbbbbbb")
    assert a.status_code == 201 and b.status_code == 201 and await count(w) == 2


async def test_retry_after_state_change_still_returns_the_original(w):
    first = await post(w, key="retry-key-9999999")
    cancel = await w.c.post(f"/api/shipments/{first.json()['_id']}/status", json={"status": "CANCELLED"}, headers=w.ch)
    assert cancel.status_code == 200
    again = await post(w, key="retry-key-9999999")
    assert again.status_code == 200 and again.json()["_id"] == first.json()["_id"] and again.json()["status"] == "CANCELLED"
    assert await count(w) == 1


@pytest.mark.parametrize("key", ["short", "x" * 200, "has space in it 123", "bad/chars/12345678"])
async def test_malformed_idempotency_keys_are_rejected(w, key):
    r = await post(w, key=key)
    assert r.status_code == 422 and await count(w) == 0


async def test_double_click_without_a_key_is_suppressed_within_the_window(w, monkeypatch):
    monkeypatch.setenv("DUPLICATE_WINDOW_SECONDS", "5")
    a = await post(w)
    b = await post(w)                                                    # identical request moments later
    assert a.status_code == 201 and b.status_code == 200 and b.headers.get("idempotent-replay") == "true"
    assert a.json()["_id"] == b.json()["_id"] and await count(w) == 1
    # a genuinely different parcel is never treated as a duplicate
    c = await post(w, body={**BODY, "parcel": {"weightKg": 3}})
    assert c.status_code == 201 and await count(w) == 2


async def test_concurrent_double_click_without_a_key_creates_one(w, slow_insert, monkeypatch):
    monkeypatch.setenv("DUPLICATE_WINDOW_SECONDS", "5")
    rs = await asyncio.gather(*[post(w) for _ in range(5)])
    assert sorted(r.status_code for r in rs).count(201) == 1
    assert await count(w) == 1


async def test_identical_shipment_after_the_window_is_allowed(w, monkeypatch):
    monkeypatch.setenv("DUPLICATE_WINDOW_SECONDS", "0")                  # window disabled/expired
    a, b = await post(w), await post(w)
    assert a.status_code == 201 and b.status_code == 201 and await count(w) == 2


async def test_a_failed_creation_does_not_poison_the_key(w, monkeypatch):
    original = Shipment.insert
    calls = {"n": 0}

    async def flaky(self, *a, **k):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("database hiccup")
        return await original(self, *a, **k)
    monkeypatch.setattr(Shipment, "insert", flaky)
    import httpx
    from main import api
    # the first attempt fails with a server error (surface it as a response rather than raising into the test)
    transport = httpx.ASGITransport(app=api, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c2:
        r1 = await c2.post("/api/shipments", json=BODY, headers={**w.ch, "Idempotency-Key": "flaky-key-1234567"})
        assert r1.status_code == 500
    r2 = await post(w, key="flaky-key-1234567")                          # the client's retry must be able to succeed
    assert r2.status_code == 201 and await count(w) == 1
