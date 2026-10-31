"""Customer-facing dates come from the backend, not from the model's date arithmetic.

Regression: with an estimated delivery of 12 October, ShipBot once said "delivered by today at 3:01 PM" — the model
does not know today's date and invented a relative one. The tools now return ready-made date text and the prompts
forbid relative wording."""
from datetime import datetime

import pytest

from agents import schedule_agent, tracking_agent
from models.shipment import Shipment
from tests.conftest import RECIPIENT, register
from tools.schedule_tools import execute_get_my_shipments
from tools.shipment_tools import execute_get_shipment_status
from utils.dates import friendly_date

pytestmark = pytest.mark.anyio


def test_friendly_date_is_exact_locale_independent_and_date_only():
    assert friendly_date(datetime(2026, 10, 12, 15, 1, 7)) == "Monday, 12 October 2026"
    assert friendly_date(datetime(2026, 1, 1, 0, 0)) == "Thursday, 1 January 2026"
    assert friendly_date(datetime(2028, 2, 29, 23, 59)) == "Tuesday, 29 February 2028"
    assert "PM" not in friendly_date(datetime(2026, 10, 12, 15, 1)) and ":" not in friendly_date(datetime(2026, 10, 12, 15, 1))
    assert friendly_date(None) is None


async def _shipment(client, headers):
    r = await client.post("/api/shipments", json={"recipient": RECIPIENT, "serviceType": "same_day"}, headers=headers)
    assert r.status_code == 201, r.text
    body = r.json()
    return (body.get("shipment") or body)["trackingNumber"]


async def test_get_shipment_status_returns_ready_made_dates(client):
    user, headers = await register(client, "user", "eta1@t.test")
    tn = await _shipment(client, headers)
    s = await Shipment.find_one(Shipment.trackingNumber == tn)
    s.estimatedDelivery = datetime(2026, 10, 12, 15, 1)
    s.deliveredAt = datetime(2026, 10, 11, 9, 30)
    await s.save()

    out = await execute_get_shipment_status(tn)
    assert out["estimatedDeliveryText"] == "Monday, 12 October 2026"
    assert out["deliveredOnText"] == "Sunday, 11 October 2026"
    # the LLM is given dates as text only: raw UTC timestamps made a small model announce "last updated at 08:44 AM"
    assert "estimatedDelivery" not in out and "deliveredAt" not in out
    assert all(set(e) == {"status", "onText"} for e in out["timeline"])


async def test_undelivered_shipment_has_no_delivered_text(client):
    user, headers = await register(client, "user", "eta2@t.test")
    tn = await _shipment(client, headers)
    out = await execute_get_shipment_status(tn)
    assert out["deliveredOnText"] is None and out["estimatedDeliveryText"]


async def test_get_my_shipments_returns_ready_made_dates(client):
    user, headers = await register(client, "user", "eta3@t.test")
    tn = await _shipment(client, headers)
    s = await Shipment.find_one(Shipment.trackingNumber == tn)
    s.estimatedDelivery = datetime(2026, 10, 12, 15, 1)
    s.pickupScheduledAt = datetime(2026, 10, 8, 10, 0)
    await s.save()

    out = await execute_get_my_shipments(current_user={"id": user["id"], "role": "user"})
    item = out["shipments"][0]
    assert item["estimatedDeliveryText"] == "Monday, 12 October 2026"
    assert item["pickupScheduledText"] == "Thursday, 8 October 2026"


async def test_missing_dates_are_none_not_a_made_up_value(client):
    user, headers = await register(client, "user", "eta4@t.test")
    tn = await _shipment(client, headers)
    s = await Shipment.find_one(Shipment.trackingNumber == tn)
    s.estimatedDelivery, s.pickupScheduledAt = None, None
    await s.save()
    item = (await execute_get_my_shipments(current_user={"id": user["id"], "role": "user"}))["shipments"][0]
    assert item["estimatedDeliveryText"] is None and item["pickupScheduledText"] is None


@pytest.mark.parametrize("prompt", [tracking_agent.SYSTEM_PROMPT, schedule_agent.SYSTEM_PROMPT], ids=["tracking", "schedule"])
def test_prompts_forbid_relative_dates_and_point_at_the_text_fields(prompt):
    assert "estimatedDeliveryText" in prompt and "pickupScheduledText" in prompt
    assert "NEVER turn a date into" in prompt and '"today"' in prompt and '"tomorrow"' in prompt
    assert "do not know today's date" in prompt
