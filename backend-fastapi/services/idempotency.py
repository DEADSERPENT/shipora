"""Duplicate-request protection for shipment creation.

A client retry, a double-click or a network retry must not create a second parcel.
Two mechanisms share one atomic primitive — a *claim* record whose unique `_id` is
(customer, scope). Whoever inserts the record first owns the request; everyone else
(including requests that arrive while the owner is still working) is handed the
owner's shipment:

  * explicit  `Idempotency-Key` header  -> scope = key, kept 24 h (config: IDEMPOTENCY_TTL_HOURS).
    The same key with a *different* payload is a client bug and is rejected (422).
  * no key                              -> scope = fingerprint of the payload, kept for a short
    window (config: DUPLICATE_WINDOW_SECONDS, 0 disables). Catches double-clicks from clients that
    don't send a key. Genuinely different parcels have different fingerprints and are unaffected.

The collection is created on first use; `ensure_indexes` adds a TTL index so old claims vanish."""

import asyncio
import hashlib
import json
import logging
import re
from datetime import datetime, timedelta
from typing import Optional, Tuple

from pymongo.errors import DuplicateKeyError

from models.shipment import Shipment

log = logging.getLogger("shipora.idempotency")

KEY_RE = re.compile(r"^[A-Za-z0-9_\-:.]{8,128}$")
WAIT_FOR_OWNER_SECONDS = 3.0


def _col():
    return Shipment.get_motor_collection().database["idempotency_keys"]


async def ensure_indexes(db) -> None:
    try:
        await db["idempotency_keys"].create_index("expiresAt", expireAfterSeconds=0)
    except Exception as err:  # never block startup on a housekeeping index
        log.warning("could not create idempotency TTL index", extra={"event": "index_failed", "error_type": type(err).__name__})


def fingerprint(customer_id: str, payload: dict) -> str:
    canonical = json.dumps({"customer": customer_id, "request": payload}, sort_keys=True, default=str, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()


async def claim(scope: str, fp: str, ttl: timedelta) -> Tuple[bool, dict]:
    """Returns (owned, record). owned=True means the caller must create the shipment."""
    for _ in range(3):
        now = datetime.utcnow()
        doc = {"_id": scope, "fingerprint": fp, "shipmentId": None, "createdAt": now, "expiresAt": now + ttl}
        try:
            await _col().insert_one(doc)
            return True, doc
        except DuplicateKeyError:
            existing = await _col().find_one({"_id": scope})
            if existing is None:
                continue                                   # released between our insert and read — try again
            if existing["expiresAt"] < now:                # expired but not yet purged by the TTL monitor
                if await _col().find_one_and_replace({"_id": scope, "expiresAt": {"$lt": now}}, doc) is not None:
                    return True, doc
                existing = await _col().find_one({"_id": scope})
                if existing is None:
                    continue
            return False, existing
    raise RuntimeError("could not claim idempotency scope")


async def complete(scope: str, shipment_id) -> None:
    await _col().update_one({"_id": scope}, {"$set": {"shipmentId": shipment_id}})


async def release(scope: str) -> None:
    """Creation failed — drop the claim so the client's retry can succeed."""
    await _col().delete_one({"_id": scope, "shipmentId": None})


async def wait_for_owner(scope: str) -> Optional[object]:
    """A concurrent duplicate waits (briefly) for the request that owns the claim to finish."""
    deadline = asyncio.get_event_loop().time() + WAIT_FOR_OWNER_SECONDS
    while asyncio.get_event_loop().time() < deadline:
        rec = await _col().find_one({"_id": scope})
        if rec is None:
            return None
        if rec.get("shipmentId") is not None:
            return rec["shipmentId"]
        await asyncio.sleep(0.02)
    return None
