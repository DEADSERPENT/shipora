"""Upfront fare / distance / ETA estimate, the 20 kg two-wheeler limit, and fare + payment method stored on bookings."""
import pytest

import config
from models.shipment import Shipment
from services import pricing
from tests.conftest import RECIPIENT, register

pytestmark = pytest.mark.anyio

KORAMANGALA = {"lat": 12.9352, "lng": 77.6245}
INDIRANAGAR = {"lat": 12.9719, "lng": 77.6412}


class P:  # tiny stand-in for a Location
    def __init__(self, lat, lng): self.lat, self.lng = lat, lng


def test_haversine_and_fare_formula():
    km = pricing.haversine_km(12.9352, 77.6245, 12.9719, 77.6412)
    assert 4.0 < km < 5.0  # Koramangala -> Indiranagar is ~4.4 km as the crow flies
    q = pricing.estimate(P(12.9352, 77.6245), P(12.9719, 77.6412), 2)
    assert q["distanceKm"] == round(km * pricing.ROAD_FACTOR, 1)
    assert q["fare"] == round(config.FARE_BASE_INR + (q["distanceKm"] - config.FARE_INCLUDED_KM) * config.FARE_PER_KM_INR)
    assert q["etaMinutes"] == round(config.ETA_BASE_MINUTES + q["distanceKm"] * config.ETA_MINUTES_PER_KM)


def test_short_hop_costs_the_base_fare_only():
    q = pricing.estimate(P(12.9716, 77.5946), P(12.9720, 77.5950))  # well inside the included km
    assert q["fare"] == round(config.FARE_BASE_INR)


def test_overweight_parcel_is_refused():
    with pytest.raises(pricing.EstimateError):
        pricing.estimate(P(12.97, 77.59), P(12.98, 77.60), config.MAX_PARCEL_KG + 0.1)


async def test_public_estimate_endpoint(client):
    r = await client.post("/api/shipments/estimate", json={"pickup": KORAMANGALA, "drop": INDIRANAGAR, "weightKg": 3})  # no auth: public
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["currency"] == "INR" and body["fare"] >= config.FARE_BASE_INR and body["distanceKm"] > 0 and body["etaMinutes"] > 0
    assert body["maxWeightKg"] == config.MAX_PARCEL_KG


async def test_estimate_rejects_outside_bengaluru_and_overweight(client):
    delhi = {"lat": 28.61, "lng": 77.21}
    r = await client.post("/api/shipments/estimate", json={"pickup": KORAMANGALA, "drop": delhi})
    assert r.status_code == 422 and "Bengaluru" in r.json()["message"]
    r = await client.post("/api/shipments/estimate", json={"pickup": KORAMANGALA, "drop": INDIRANAGAR, "weightKg": 50})
    assert r.status_code == 422 and "kg" in r.json()["message"]


async def test_booking_stores_fare_distance_payment_and_distance_based_eta(client):
    user, headers = await register(client, "user", "fare1@t.test")
    r = await client.post("/api/shipments", json={"recipient": RECIPIENT, "parcel": {"weightKg": 2}, "paymentMethod": "upi"}, headers=headers)
    assert r.status_code == 201, r.text
    s = r.json().get("shipment") or r.json()
    assert s["paymentMethod"] == "upi" and s["fare"] >= config.FARE_BASE_INR and s["distanceKm"] > 0
    doc = await Shipment.find_one(Shipment.trackingNumber == s["trackingNumber"])
    minutes = (doc.estimatedDelivery - doc.createdAt).total_seconds() / 60
    assert abs(minutes - (config.ETA_BASE_MINUTES + s["distanceKm"] * config.ETA_MINUTES_PER_KM)) < 2


async def test_booking_over_the_weight_limit_is_rejected(client):
    user, headers = await register(client, "user", "fare2@t.test")
    r = await client.post("/api/shipments", json={"recipient": RECIPIENT, "parcel": {"weightKg": config.MAX_PARCEL_KG + 1}}, headers=headers)
    assert r.status_code == 422 and "kg" in r.json()["message"]


async def test_public_tracking_never_exposes_the_fare(client):
    user, headers = await register(client, "user", "fare3@t.test")
    s = (await client.post("/api/shipments", json={"recipient": RECIPIENT}, headers=headers)).json()
    tn = (s.get("shipment") or s)["trackingNumber"]
    pub = (await client.get(f"/api/shipments/track/{tn}")).json()
    assert "fare" not in pub and "paymentMethod" not in pub and "distanceKm" not in pub


def test_weight_changes_the_fare_but_distance_does_not_depend_on_it():
    a, b = P(12.9352, 77.6245), P(12.9719, 77.6412)
    light, at_free, heavy, max_kg = (pricing.estimate(a, b, kg) for kg in (1, config.FARE_FREE_WEIGHT_KG, 10, config.MAX_PARCEL_KG))
    assert light["fare"] == at_free["fare"] and light["weightSurcharge"] == 0 and at_free["weightSurcharge"] == 0  # up to the free weight: no surcharge
    assert heavy["weightSurcharge"] == round((10 - config.FARE_FREE_WEIGHT_KG) * config.FARE_PER_EXTRA_KG_INR)
    assert heavy["fare"] == light["fare"] + heavy["weightSurcharge"] > light["fare"]
    assert max_kg["fare"] > heavy["fare"]
    assert light["distanceKm"] == heavy["distanceKm"] == max_kg["distanceKm"]  # weight never changes the distance
    assert pricing.estimate(a, b)["fare"] == light["fare"]  # no weight given -> no surcharge


def test_fare_grows_with_distance_and_matches_the_published_formula():
    near, far = P(12.9716, 77.5946), P(12.9720, 77.5950)
    mid, long_ = P(12.9719, 77.6412), P(12.9698, 77.7500)  # ~3 km / ~15 km from the MG Road area
    start = P(12.9716, 77.5946)
    q = [pricing.estimate(start, p, 2) for p in (far, mid, long_)]
    assert q[0]["fare"] < q[1]["fare"] < q[2]["fare"]
    for r in q:  # every quote reproduces base + per-km beyond the included km (2 kg: no weight surcharge)
        assert r["fare"] == round(config.FARE_BASE_INR + max(0, r["distanceKm"] - config.FARE_INCLUDED_KM) * config.FARE_PER_KM_INR)
