"""Phase 5 / item 7 — structured logging, request correlation and secret hygiene."""
import io
import json
import logging
import re
from pathlib import Path

import httpx
import pytest

import logging_config
from tests.conftest import RECIPIENT, register

pytestmark = pytest.mark.anyio

BACKEND = Path(__file__).resolve().parent.parent


@pytest.fixture
def logs():
    """Captures everything the app logs, rendered exactly as production would (JSON lines)."""
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(logging_config.JsonFormatter())
    handler.addFilter(logging_config.RequestContextFilter())
    root = logging.getLogger()
    old_level = root.level
    root.addHandler(handler)
    root.setLevel(logging.DEBUG)

    class Cap:
        def lines(self):
            return [json.loads(l) for l in stream.getvalue().splitlines() if l.strip()]

        def raw(self):
            return stream.getvalue()

        def events(self, name):
            return [l for l in self.lines() if l.get("event") == name]
    yield Cap()
    root.removeHandler(handler)
    root.setLevel(old_level)


# ─── formatter ─────────────────────────────────────────────────────────────
def test_json_formatter_emits_the_documented_fields():
    rec = logging.LogRecord("shipora.test", logging.WARNING, __file__, 1, "hello %s", ("world",), None)
    rec.event, rec.tracking, rec.user_id = "demo", "SHP0123456789", "u1"
    out = json.loads(logging_config.JsonFormatter().format(rec))
    assert out["level"] == "WARNING" and out["logger"] == "shipora.test" and out["message"] == "hello world"
    assert out["event"] == "demo" and out["tracking"] == "SHP0123456789" and out["user_id"] == "u1"
    assert re.match(r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(\.\d+)?Z$", out["timestamp"])


def test_exceptions_are_logged_with_type_and_traceback_but_redacted():
    scheme, creds = "mongodb+srv://", "bob:topsecret"
    msg = f"db said password=hunter2 for {scheme}{creds}@cluster.example.net/x"
    try:
        raise RuntimeError(msg)
    except RuntimeError:
        rec = logging.LogRecord("t", logging.ERROR, __file__, 1, "boom", (), __import__("sys").exc_info())
    out = json.loads(logging_config.JsonFormatter().format(rec))
    assert out["error_type"] == "RuntimeError" and "Traceback" in out["exception"]
    blob = json.dumps(out)
    assert "hunter2" not in blob and "topsecret" not in blob and "bob:" not in blob


@pytest.mark.parametrize("secret,text", [
    ("eyJhbGciOiJIUzI1NiJ9.eyJpZCI6IjEifQ.c2lnbmF0dXJlLXZhbHVl", "token was eyJhbGciOiJIUzI1NiJ9.eyJpZCI6IjEifQ.c2lnbmF0dXJlLXZhbHVl ok"),
    ("abc123tokenvalue", "Authorization: Bearer abc123tokenvalue"),
    ("p@ssw0rd!", "login password=p@ssw0rd! failed"),
    ("p@ssw0rd!", '{"password": "p@ssw0rd!", "email": "a@b.co"}'),
    ("sk-proj-abcdefghijklmnop12345", "openai sk-proj-abcdefghijklmnop12345 rejected"),
    ("S3cr3tPw", "connecting to mongodb+srv://" "shipora:S3cr3tPw@cluster0.mongodb.net/shipora"),
    ("my-api-key-value", "api_key=my-api-key-value"),
])
def test_redaction(secret, text):
    cleaned = logging_config.redact(text)
    assert secret not in cleaned and "REDACTED" in cleaned


def test_redaction_leaves_ordinary_text_alone():
    s = "shipment SHP0123456789 moved to OUT_FOR_DELIVERY for user 6ac600000000000000000001"
    assert logging_config.redact(s) == s


def test_no_bare_print_statements_left_in_the_backend():
    offenders = []
    for p in BACKEND.rglob("*.py"):
        rel = p.relative_to(BACKEND).parts
        if rel[0] in (".venv", "tests", "__pycache__"):
            continue
        for i, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1):
            if re.match(r"\s*print\(", line):
                offenders.append(f"{'/'.join(rel)}:{i}")
    assert offenders == []


# ─── per-request logging ───────────────────────────────────────────────────
async def test_every_request_is_logged_with_latency_status_and_request_id(client, logs):
    r = await client.get("/api/health")
    rid = r.headers["x-request-id"]
    assert re.match(r"^[A-Za-z0-9\-]{8,64}$", rid)
    ev = [e for e in logs.events("http_request") if e.get("request_id") == rid]
    assert len(ev) == 1
    e = ev[0]
    assert e["method"] == "GET" and e["path"] == "/api/health" and e["status"] == 200
    assert isinstance(e["latency_ms"], (int, float)) and e["latency_ms"] >= 0 and e["level"] in ("DEBUG", "INFO")


async def test_incoming_request_id_is_honoured_if_sane_and_replaced_if_not(client, logs):
    r = await client.get("/api/health", headers={"X-Request-ID": "trace-abc-12345"})
    assert r.headers["x-request-id"] == "trace-abc-12345"
    for bad in ("x" * 500, "has spaces and\ttabs", "../../etc"):
        r = await client.get("/api/health", headers={"X-Request-ID": bad})
        assert r.headers["x-request-id"] != bad and re.match(r"^[A-Za-z0-9\-]{8,64}$", r.headers["x-request-id"])


async def test_authenticated_requests_carry_user_and_role_never_the_token(client, logs):
    user, h = await register(client, "user", "c@t.test")
    token = h["Authorization"].split()[1]
    await client.get("/api/shipments", headers=h)
    ev = [e for e in logs.events("http_request") if e["path"] == "/api/shipments"][0]
    assert ev["user_id"] == user["id"] and ev["role"] == "user"
    assert token not in logs.raw() and "Bearer" not in logs.raw()


async def test_status_levels_follow_outcome(client, logs):
    await client.get("/api/shipments")                    # 401
    ev = [e for e in logs.events("http_request") if e["path"] == "/api/shipments"][0]
    assert ev["status"] == 401 and ev["level"] == "WARNING"


async def test_shipment_events_include_tracking_id_and_request_correlation(client, logs):
    _, ch = await register(client, "user", "c@t.test")
    _, adm = await register(client, "admin", "boss@t.test")
    agent, ah = await register(client, "driver", "a@t.test")
    s = (await client.post("/api/shipments", json={"recipient": RECIPIENT}, headers=ch)).json()
    r = await client.put(f"/api/shipments/{s['_id']}/assign", json={"agentId": agent["id"]}, headers=adm)
    ev = [e for e in logs.events("shipment_assigned") if e["tracking"] == s["trackingNumber"]]
    assert ev and ev[0]["agent_id"] == agent["id"]
    assert ev[0]["request_id"] == r.headers["x-request-id"]            # business log lines share the request's id
    r2 = await client.post(f"/api/shipments/{s['_id']}/status", json={"status": "PICKED_UP"}, headers=ah)
    st = [e for e in logs.events("shipment_status") if e["status"] == "PICKED_UP"][0]
    assert st["tracking"] == s["trackingNumber"] and st["role"] == "driver" and st["request_id"] == r2.headers["x-request-id"]


async def test_unhandled_errors_return_a_safe_body_and_are_logged_in_full(logs):
    from main import api

    @api.get("/__boom_test")
    async def boom():
        raise RuntimeError("internal detail: password=hunter2")
    transport = httpx.ASGITransport(app=api, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.get("/__boom_test")
    assert r.status_code == 500
    body = r.json()
    assert body["message"] == "Internal server error" and body["requestId"] == r.headers["x-request-id"]
    assert "hunter2" not in r.text and "RuntimeError" not in r.text and "Traceback" not in r.text
    err = [l for l in logs.lines() if l["level"] == "ERROR" and l.get("request_id") == body["requestId"]]
    assert err and err[0]["error_type"] == "RuntimeError" and "hunter2" not in logs.raw()


async def test_nothing_sensitive_reaches_the_logs_across_a_realistic_session(client, logs, monkeypatch):
    import config
    monkeypatch.setattr(config, "OPENAI_API_KEY", "sk-marker-openai-key-0123456789")
    pw, secret_chat = "My-Sup3r-Secret-Pass!", "MARKER-PRIVATE-CHAT-TEXT-98765"
    reg = await client.post("/api/auth/register/user", json={"name": "Priv Person", "email": "priv.person@t.test", "password": pw,
                                                             "phone": "9123456789", "address": "42 Private Road", "location": {"lat": 1, "lng": 2}})
    token = reg.json()["token"]
    h = {"Authorization": f"Bearer {token}"}
    await client.post("/api/auth/login", json={"email": "priv.person@t.test", "password": pw, "role": "user"})
    await client.post("/api/auth/login", json={"email": "priv.person@t.test", "password": "wrong-" + pw, "role": "user"})
    await client.post("/api/auth/change-password", json={"currentPassword": pw, "newPassword": "Another-Secret-1!"}, headers=h)
    await client.post("/api/auth/forgot-password", json={"email": "priv.person@t.test", "role": "user"})
    await client.post("/api/shipments", json={"recipient": RECIPIENT}, headers=h)
    await client.post("/api/chat", json={"message": secret_chat}, headers=h)
    raw = logs.raw()
    for forbidden in (pw, "wrong-" + pw, "Another-Secret-1!", token, "priv.person@t.test", "9123456789", "42 Private Road",
                      secret_chat, "sk-marker-openai", "Authorization", "eyJ"):
        assert forbidden not in raw, f"leaked into logs: {forbidden}"
    assert logs.events("login_ok") and logs.events("login_failed")     # ...while still being useful


def test_log_format_and_level_are_configurable(monkeypatch):
    monkeypatch.setenv("LOG_FORMAT", "text")
    assert logging_config.log_format() == "text"
    monkeypatch.setenv("LOG_FORMAT", "json")
    assert logging_config.log_format() == "json"
    monkeypatch.delenv("LOG_FORMAT")
    monkeypatch.setenv("APP_ENV", "production")
    assert logging_config.log_format() == "json"                        # structured by default where it matters
    monkeypatch.setenv("LOG_LEVEL", "debug")
    assert logging_config.log_level() == logging.DEBUG
    monkeypatch.setenv("LOG_LEVEL", "nonsense")
    assert logging_config.log_level() == logging.INFO
