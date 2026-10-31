"""Upfront fare / distance / ETA estimate for a same-day parcel (the "Get an estimate" step on Porter-style apps).

Fare = a base fare that already covers the first FARE_INCLUDED_KM, plus FARE_PER_KM_INR for every further km,
plus FARE_PER_EXTRA_KG_INR for every kg above FARE_FREE_WEIGHT_KG (so a heavy parcel costs more than a light one).
All numbers come from config (env-overridable) so operations can tune them without a code change. Distance is the
straight-line (haversine) distance between the two pins stretched by ROAD_FACTOR to approximate road distance."""

import math
from typing import Optional

import config

ROAD_FACTOR = 1.25  # straight line -> typical Bengaluru road distance
EARTH_RADIUS_KM = 6371.0088


class EstimateError(ValueError):
    """The request cannot be priced (e.g. parcel too heavy)."""


def haversine_km(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi, dlmb = p2 - p1, math.radians(lng2 - lng1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlmb / 2) ** 2
    return 2 * EARTH_RADIUS_KM * math.asin(math.sqrt(a))


def estimate(pickup, drop, weight_kg: Optional[float] = None) -> dict:
    """`pickup` / `drop` need .lat and .lng. Returns distance (km), fare (whole rupees) and ETA (minutes)."""
    if weight_kg is not None and weight_kg > config.MAX_PARCEL_KG:
        raise EstimateError(f"Parcels can weigh at most {config.MAX_PARCEL_KG:g} kg for same-day bike delivery.")
    km = round(haversine_km(pickup.lat, pickup.lng, drop.lat, drop.lng) * ROAD_FACTOR, 1)
    extra_km = max(0.0, km - config.FARE_INCLUDED_KM)
    weight_surcharge = max(0.0, (weight_kg or 0) - config.FARE_FREE_WEIGHT_KG) * config.FARE_PER_EXTRA_KG_INR
    fare = int(round(config.FARE_BASE_INR + extra_km * config.FARE_PER_KM_INR + weight_surcharge))
    eta = int(round(config.ETA_BASE_MINUTES + km * config.ETA_MINUTES_PER_KM))
    return {
        "distanceKm": km,
        "fare": fare,
        "currency": "INR",
        "etaMinutes": eta,
        "baseFare": config.FARE_BASE_INR,
        "includedKm": config.FARE_INCLUDED_KM,
        "perKm": config.FARE_PER_KM_INR,
        "weightSurcharge": int(round(weight_surcharge)),
        "freeWeightKg": config.FARE_FREE_WEIGHT_KG,
        "perExtraKg": config.FARE_PER_EXTRA_KG_INR,
        "maxWeightKg": config.MAX_PARCEL_KG,
    }
