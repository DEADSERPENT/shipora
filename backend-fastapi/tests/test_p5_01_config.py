"""Phase 5 / item 1 — secrets and startup validation."""
import asyncio
import logging
import os
import socket
import subprocess
import sys
from pathlib import Path

import httpx
import pytest

import config

BACKEND_DIR = Path(__file__).resolve().parent.parent
STRONG = "q7Gx-2LpZr9VbN4sTe8YwKc1HdMf6JaU0oXiB3RnSyEtPz5W"  # 48 chars, high entropy (test value only)


# ─── JWT secret ────────────────────────────────────────────────────────────
def test_jwt_secret_has_no_default_in_source():
    src = (BACKEND_DIR / "config.py").read_text(encoding="utf-8")
    assert 'os.getenv("JWT_SECRET")' in src
    assert 'getenv("JWT_SECRET",' not in src and "environ.get(\"JWT_SECRET\"," not in src


@pytest.mark.parametrize("bad", [
    None, "", "shipora_secret", "your_jwt_secret_here", "change-me", "secret", "test-secret",
    "short-but-random-9aZ", "a" * 64, "ababababababababababababababababab",
])
def test_insecure_jwt_secrets_are_rejected(bad):
    env = {"JWT_SECRET": bad} if bad is not None else {}
    problems = config.check_environment(env)
    assert any("JWT_SECRET" in p for p in problems), problems
    assert all((bad or "x") not in p or not bad for p in problems)  # a problem message never echoes the secret


def test_strong_jwt_secret_is_accepted():
    assert [p for p in config.check_environment({"JWT_SECRET": STRONG}) if "JWT_SECRET" in p] == []


def test_validate_raises_without_leaking_the_secret(monkeypatch):
    monkeypatch.setenv("JWT_SECRET", "shipora_secret")
    with pytest.raises(config.ConfigError) as exc:
        config.validate()
    assert "JWT_SECRET" in str(exc.value)
    assert "shipora_secret" not in str(exc.value)


def test_sign_token_refuses_when_secret_missing(monkeypatch):
    import auth_utils
    monkeypatch.setattr(config, "JWT_SECRET", None)
    with pytest.raises(config.ConfigError):
        auth_utils.sign_token({"id": "1", "role": "user"})


def test_app_lifespan_refuses_to_start_with_bad_secret(monkeypatch):
    from main import api
    monkeypatch.setenv("JWT_SECRET", "shipora_secret")

    async def go():
        async with api.router.lifespan_context(api):
            pass
    with pytest.raises(config.ConfigError):
        asyncio.run(go())


def test_real_server_process_exits_when_secret_is_insecure():
    """End to end: `uvicorn main:app` must exit non-zero instead of serving."""
    s = socket.socket(); s.bind(("127.0.0.1", 0)); port = s.getsockname()[1]; s.close()
    env = {**os.environ, "JWT_SECRET": "shipora_secret", "MONGO_URI": "mongodb://user:hunter2pw@127.0.0.1:1/x"}
    p = subprocess.run([sys.executable, "-m", "uvicorn", "main:app", "--port", str(port)], cwd=BACKEND_DIR, env=env,
                       capture_output=True, text=True, timeout=60)
    out = p.stdout + p.stderr
    assert p.returncode != 0
    assert "JWT_SECRET" in out
    assert "shipora_secret" not in out and "hunter2pw" not in out


# ─── Environment / CORS ────────────────────────────────────────────────────
def test_unknown_app_env_is_rejected():
    assert any("APP_ENV" in p for p in config.check_environment({"JWT_SECRET": STRONG, "APP_ENV": "prod-ish"}))


@pytest.mark.parametrize("origin", ["*", "http://*.example.com", "localhost:3000", "https://shipora.example.com/app", "ftp://x.io"])
def test_malformed_or_wildcard_cors_origins_rejected(origin):
    problems = config.check_environment({"JWT_SECRET": STRONG, "CLIENT_URL": origin})
    assert any("CLIENT_URL" in p or "CORS_ORIGINS" in p for p in problems), problems


def test_production_rejects_http_and_localhost_origins():
    base = {"JWT_SECRET": STRONG, "APP_ENV": "production"}
    assert config.check_environment({**base, "CLIENT_URL": "https://shipora.example.com"}) == []
    for o in ("http://shipora.example.com", "https://localhost:3000", "https://127.0.0.1"):
        assert any("production" in p for p in config.check_environment({**base, "CLIENT_URL": o})), o
    assert any("CLIENT_URL" in p for p in config.check_environment(base))  # production must set it explicitly


def test_development_defaults_are_allowed():
    assert config.check_environment({"JWT_SECRET": STRONG}) == []


def test_cors_origins_parsing(monkeypatch):
    monkeypatch.setenv("CORS_ORIGINS", "https://a.example.com, https://b.example.com/")
    assert config.cors_origins() == ["https://a.example.com", "https://b.example.com"]
    monkeypatch.delenv("CORS_ORIGINS")
    monkeypatch.setenv("CLIENT_URL", "http://localhost:3000")
    assert config.cors_origins() == ["http://localhost:3000"]


@pytest.mark.anyio
async def test_cors_only_allows_configured_origin(client):
    ok = await client.options("/api/health", headers={"Origin": "http://localhost:3000", "Access-Control-Request-Method": "GET"})
    assert ok.headers.get("access-control-allow-origin") == "http://localhost:3000"
    assert ok.headers.get("access-control-allow-credentials") == "true"
    bad = await client.options("/api/health", headers={"Origin": "https://evil.example", "Access-Control-Request-Method": "GET"})
    assert "access-control-allow-origin" not in bad.headers


# ─── Secrets never reach logs ──────────────────────────────────────────────
def test_redact_uri_hides_credentials():
    r = config.redact_uri("mongodb+srv://" "shipora_user:S3cr3tPw@shipora-cluster.abc.mongodb.net/shipora?retryWrites=true")
    assert "S3cr3tPw" not in r and "shipora_user" not in r
    assert "shipora-cluster.abc.mongodb.net" in r and "shipora" in r
    assert config.redact_uri("mongodb://localhost:27017/x") == "mongodb://localhost:27017/x"
    assert "pw" not in config.redact_uri("mongodb://u:pw@h/db")


@pytest.mark.anyio
async def test_connect_db_does_not_log_credentials(monkeypatch, capsys, caplog):
    import motor.motor_asyncio as motor
    from mongomock_motor import AsyncMongoMockClient
    import database

    class FakeClient:
        def __init__(self, *a, **k):
            self._c = AsyncMongoMockClient()
            self.admin = type("A", (), {"command": staticmethod(lambda *a, **k: asyncio.sleep(0))})()
        def get_default_database(self):
            return self._c["fake"]

    monkeypatch.setattr(motor, "AsyncIOMotorClient", FakeClient)
    monkeypatch.setattr(config, "MONGO_URI", "mongodb+srv://" "shipora_user:S3cr3tPw@cluster.example.net/shipora")
    with caplog.at_level(logging.DEBUG):
        await database.connect_db()
    seen = capsys.readouterr().out + capsys.readouterr().err + caplog.text
    assert "S3cr3tPw" not in seen and "shipora_user" not in seen


@pytest.mark.anyio
async def test_production_never_falls_back_to_in_memory_db(monkeypatch):
    import motor.motor_asyncio as motor
    import database

    class Unreachable:
        def __init__(self, *a, **k):
            async def boom(*a, **k): raise ConnectionError("down")
            self.admin = type("A", (), {"command": staticmethod(boom)})()

    monkeypatch.setattr(motor, "AsyncIOMotorClient", Unreachable)
    monkeypatch.setenv("APP_ENV", "production")
    with pytest.raises(Exception):
        await database.connect_db()


# ─── .env hygiene ──────────────────────────────────────────────────────────
def test_dotenv_is_git_ignored_and_never_committed():
    repo = BACKEND_DIR.parent
    ignored = subprocess.run(["git", "check-ignore", "-q", "backend-fastapi/.env"], cwd=repo)
    assert ignored.returncode == 0
    tracked = subprocess.run(["git", "ls-files"], cwd=repo, capture_output=True, text=True).stdout.splitlines()
    assert not [f for f in tracked if f.endswith("/.env") or f == ".env"]
    example = (BACKEND_DIR / ".env.example").read_text(encoding="utf-8")
    assert "shipora_secret" not in example
