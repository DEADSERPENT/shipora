"""Test harness: every test gets a fresh in-memory Mongo (mongomock_motor) with
Beanie initialised against the real document models, and an httpx client wired
straight to the FastAPI app. Never touches Atlas, regardless of .env."""

import os
import sys
from pathlib import Path

# Must be set before `config` is imported (python-dotenv does not override
# variables that already exist in the environment).
os.environ["MONGO_URI"] = "mongodb://127.0.0.1:1/shipora-test"
os.environ["GEMINI_API_KEY"] = ""
os.environ["VOICE_WARMUP"] = "false"
os.environ["BCRYPT_ROUNDS"] = "4"  # fast hashing in tests only
os.environ["GPS_MIN_INTERVAL_SECONDS"] = "0"  # the flood throttle is exercised by its own test
os.environ["RATE_LIMIT_ENABLED"] = "false"  # rate-limit tests switch it on explicitly
os.environ["DUPLICATE_WINDOW_SECONDS"] = "0"  # key-less duplicate suppression is off unless a test enables it
os.environ["JWT_SECRET"] = "Vq3-ZTest-Only-Secret-0f9aKd7LmXc2RhE8yBw5NpJs"  # test-only value; real secrets live in .env

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import httpx
import pytest
from beanie import init_beanie
from mongomock_motor import AsyncMongoMockClient

import sockets
from database import DOCUMENT_MODELS
from main import api


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture
async def client():
    db = AsyncMongoMockClient()["shipora-test"]
    await init_beanie(database=db, document_models=DOCUMENT_MODELS)
    sockets.vehicle_locations.clear()
    sockets.reset_state()
    transport = httpx.ASGITransport(app=api)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


async def register(client, kind: str, email: str, **extra):
    bodies = {
        "user": dict(name="Cust", phone="9880000099", address="1 Test St", location={"lat": 12.9, "lng": 77.6}),
        "driver": dict(name="Agent", phone="9880000098", vehicleNo="ka09zz0001", licenseNo="dl123", assignedArea="Koramangala", vehicleType="bike"),
        "admin": dict(name="Boss", organization="Shipora"),
    }
    body = {**bodies[kind], "email": email, "password": "secret123", **extra}
    r = await client.post(f"/api/auth/register/{kind}", json=body)
    assert r.status_code == 201, r.text
    data = r.json()
    return data["user"], {"Authorization": f"Bearer {data['token']}"}


RECIPIENT = {"name": "Rec", "phone": "9880000077", "address": "9 Dest Rd", "location": {"lat": 12.97, "lng": 77.64}}
