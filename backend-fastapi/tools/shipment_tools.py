"""Tool schema + executor for looking up a shipment's live status by
tracking number. Exposes the same public view as GET /api/shipments/track —
status, ETA and timeline only, never names/addresses/phones — because the
tracking number itself is the access token."""

import re
from typing import Optional

from beanie import PydanticObjectId

from models.shipment import Shipment, tracking_checksum_ok
from serializers import shipment_public_json
from utils.dates import friendly_date

TOOL_GET_SHIPMENT_STATUS = {
    "name": "get_shipment_status",
    "description": "Look up the current status, estimated delivery and status timeline of a parcel by its tracking number (e.g. 'SHP1A2B3C4D5E'). Call this whenever the user asks where their parcel/shipment/package is or what its status is.",
    "input_schema": {
        "type": "object",
        "properties": {"trackingNumber": {"type": "string", "description": "The shipment tracking number, starting with SHP."}},
        "required": ["trackingNumber"],
    },
}


def extract_tracking_number(text: str) -> Optional[str]:
    """Finds a tracking number in free text or a transcript: "SHP48217390", "S H P 4 8 2 1 7 3 9 0", "shp-4821-7390" and the
    legacy SHP + 10 hex form, including mis-heard lookalike characters. See voice/transcript_fix.py."""
    from voice.transcript_fix import extract_id
    return extract_id(text)


def _edit_distance(a: str, b: str) -> int:
    """Levenshtein distance: speech recognition substitutes, drops AND inserts characters."""
    prev = list(range(len(b) + 1))
    for i, x in enumerate(a, 1):
        cur = [i]
        for j, y in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (x != y)))
        prev = cur
    return prev[-1]


async def _did_you_mean(ref: str, current_user: Optional[dict]) -> Optional[str]:
    """A mis-heard ID (speech-to-text swaps '1A2' for '182') is repaired ONLY against the signed-in customer's own
    shipments. Fuzzy-matching against everyone's would let anyone enumerate real tracking numbers."""
    if not current_user or current_user.get("role") != "user":
        return None
    mine = await Shipment.find(Shipment.customerId == PydanticObjectId(current_user["id"])).limit(50).to_list()
    close = sorted((_edit_distance(ref, s.trackingNumber), s.trackingNumber) for s in mine)
    if close and close[0][0] <= 2 and (len(close) == 1 or close[1][0] > close[0][0]):
        return close[0][1]
    return None


NOT_ASSIGNED_NOTE = "That shipment is not assigned to you, so I can't share it. Operations assigns deliveries."


async def execute_get_shipment_status(trackingNumber: str, current_user: Optional[dict] = None) -> dict:
    ref = extract_tracking_number(trackingNumber) or trackingNumber.strip().upper()
    if not tracking_checksum_ok(ref):
        # A number whose check digit fails was mis-heard or mistyped. Say so without querying the database: an invalid
        # number can never be a real one, and probing real ones is exactly what check digits make impossible to guess.
        suggestion = await _did_you_mean(ref, current_user)
        if suggestion:
            return {"found": False, "didYouMean": suggestion,
                    "note": f"That number's check digit does not match, but the customer has {suggestion}, which is very close. Ask them to confirm it."}
        return {"found": False, "badChecksum": True,
                "note": "That tracking number does not look right (check digit mismatch) — it was probably misheard. Ask the user to say it again, one digit at a time."}
    shipment = await Shipment.find_one(Shipment.trackingNumber == ref)
    if (current_user or {}).get("role") == "driver":
        # A rider sees only what is assigned to them. A number that does not exist gets the same answer as someone else's,
        # so a rider cannot probe which tracking numbers are real.
        if shipment is None or shipment.assignedAgentId is None or str(shipment.assignedAgentId) != current_user.get("id"):
            return {"found": False, "note": NOT_ASSIGNED_NOTE}
    if not shipment:
        suggestion = await _did_you_mean(ref, current_user)
        if suggestion:
            return {"found": False, "didYouMean": suggestion,
                    "note": f"No shipment {ref}, but the customer has {suggestion}, which is very close. Ask them to confirm it is the one they mean."}
        return {"found": False, "note": "No shipment found with that tracking number. Ask the user to double-check it."}
    public = shipment_public_json(shipment)
    # The model gets dates as ready-made text and NO raw timestamps: they are UTC, and a small model will happily read
    # "08:44" out as the customer's local time.
    public.pop("estimatedDelivery", None)
    public.pop("deliveredAt", None)
    public["timeline"] = [{"status": e.status, "onText": friendly_date(e.at)} for e in shipment.statusHistory]
    return {
        "found": True,
        **public,
        # Ready-made customer-facing dates: quote these exactly (never "today"/"tomorrow"/"in N days").
        "estimatedDeliveryText": friendly_date(shipment.estimatedDelivery),
        "deliveredOnText": friendly_date(shipment.deliveredAt),
    }
