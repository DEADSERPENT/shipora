"""The mock-data seed runs whenever the app starts on an empty database — notably the in-memory fallback used when
Atlas is unreachable. A loop variable once shadowed the module logger and crashed startup on exactly that path."""
import pytest

from models.delivery_agent import DeliveryAgent
from models.shipment import Shipment
from seed import seed_mock_data

pytestmark = pytest.mark.anyio


async def test_seed_runs_on_an_empty_database_and_is_idempotent(client):
    await seed_mock_data()                                   # used to raise AttributeError: 'TrackingLog' object has no attribute 'info'
    agents, shipments = await DeliveryAgent.find_all().count(), await Shipment.find_all().count()
    assert agents >= 1 and shipments >= 1
    await seed_mock_data()                                   # second run is a no-op
    assert await DeliveryAgent.find_all().count() == agents and await Shipment.find_all().count() == shipments
