import pytest

pytestmark = pytest.mark.anyio


async def test_readiness_endpoint(client):
    r = await client.get("/api/health/ready")
    assert r.status_code == 200 and r.json()["status"] == "READY"
