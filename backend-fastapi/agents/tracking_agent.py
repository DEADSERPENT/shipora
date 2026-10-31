import re
from functools import partial

from agents import roles
from agents.base import run_tool_agent
from tools.agent_tools import TOOL_GET_MY_ASSIGNMENTS, execute_get_my_assignments
from tools.schedule_tools import TOOL_GET_MY_SHIPMENTS, execute_get_my_shipments
from tools.shipment_tools import NOT_ASSIGNED_NOTE, TOOL_GET_SHIPMENT_STATUS, execute_get_shipment_status, extract_tracking_number
from tools.tracking_tools import TOOL_GET_VEHICLE_STATUS, execute_get_vehicle_status

SYSTEM_PROMPT = """You are ShipBot's tracking specialist for Shipora, a parcel delivery and fleet management platform.

You ONLY answer questions about where a parcel is and about live delivery-vehicle location, ETA and areas covered today (use get_vehicle_status). Fetch real data before answering — never guess or make up tracking statuses, vehicle numbers, areas, or ETAs.

For a parcel: if the user gives a tracking number, use get_shipment_status with it. If they ask about "my parcel" / "my shipment" without a number, use get_my_shipments to find their own shipments (it only works for a logged-in customer; if it says they aren't logged in, ask for the tracking number instead). Then: if exactly one of their shipments has isActive true, answer with that shipment's status and estimated delivery straight away — don't ask for a tracking number you can already see. If several are active, list them briefly (tracking number and status) and ask which one they mean. If none are active, say so and mention their most recent one.

Dates: always quote dates exactly as given in the *Text fields (estimatedDeliveryText, pickupScheduledText, deliveredOnText), e.g. "Monday, 12 October 2026". You do not know today's date, so NEVER turn a date into "today", "tomorrow", "in N days" or a time of day. If the user refers back to a vehicle mentioned earlier (e.g. "when was it last updated?"), re-call the tool with that vehicle's number rather than answering from memory. If the tool returns no vehicles, say so plainly rather than inventing an answer.

Tone: friendly, concise. Keep responses under 120 words."""


# "Where is my parcel?" in the three languages the chat widget offers (English, Hindi, Kannada).
_MY_PARCEL = re.compile(r"\b(?:my|where)\b.*\b(?:parcel|package|shipment|order)s?\b|(?:पार्सल|पैकेज|शिपमेंट|ऑर्डर)|(?:ಪಾರ್ಸೆಲ್|ಪಾರ್ಸಲ್|ಪ್ಯಾಕೇಜ್|ಶಿಪ್‌ಮೆಂಟ್)", re.I)
_ROUTE = re.compile(r"\b(?:my route|my deliver\w*|what'?s next|next deliver\w*|which delivery|(?:what|which) .{0,20}(?:pending|assigned)|assigned to me|on my route)\b", re.I)


async def direct(message: str, current_user: dict = None) -> str:
    """Questions whose whole answer is the caller's own database rows need no model: a rider asking for their route gets the exact list
    (tracking numbers included), instantly. Returns None for everything else."""
    if roles.role_of(current_user) == roles.DRIVER and not extract_tracking_number(message) and _ROUTE.search(message):
        return await _rider_route_summary(current_user)
    return None


_HOWTO = re.compile(r"^\W*(?:how|can i|could i|do i|does|is it possible|what (?:is|are|if))\b", re.I)
def is_howto(message: str) -> bool:
    """"How do I…", "Can I cancel my shipment?", "What if…": a question about the service, not a lookup of the caller's own parcels."""
    return bool(_HOWTO.search(message))


_RAW_STATUS = re.compile(r"\b[A-Z]{2,}_[A-Z_]{2,}\b")          # OUT_FOR_DELIVERY, IN_TRANSIT...: a database enum, not a sentence


async def handle(message: str, history: list, sentiment: str, current_user: dict = None, on_stage=None, meta: dict = None) -> str:
    ran = []
    reply = await _handle(message, history, sentiment, current_user, on_stage, ran)
    if reply is None:
        return None
    ref = extract_tracking_number(message)
    grounded = None
    if not ran and not ref and not _HOWTO.search(message) and roles.role_of(current_user) != roles.DRIVER:
        # "Where is my parcel?" answered without looking anything up is a guess: answer from the caller's own database rows instead.
        grounded = await fallback(message, current_user)
    elif ref and "get_shipment_status" in ran and (ref not in re.sub(r"\W", "", reply.upper()) or _RAW_STATUS.search(reply)):
        # A lookup by number whose answer never names the parcel, or shows a raw status code, is not fit to read out: state the facts.
        grounded = await fallback(message, current_user)
    if grounded:
        if meta is not None:
            meta["source"] = "builtin"
        return grounded
    return reply


async def _handle(message, history, sentiment, current_user, on_stage, ran) -> str:
    tools = [TOOL_GET_VEHICLE_STATUS, TOOL_GET_SHIPMENT_STATUS, TOOL_GET_MY_SHIPMENTS]
    executors = {
        "get_vehicle_status": partial(execute_get_vehicle_status, current_user=current_user),
        "get_shipment_status": partial(execute_get_shipment_status, current_user=current_user),
        # bound to the caller: the tool takes no customer id, so a customer can only ever see their own shipments
        "get_my_shipments": partial(execute_get_my_shipments, current_user=current_user),
    }
    role = roles.role_of(current_user)
    if role == roles.DRIVER:
        # A rider works from their own assignments: no fleet-wide vehicle list, no other riders' parcels.
        tools = [TOOL_GET_MY_ASSIGNMENTS, TOOL_GET_SHIPMENT_STATUS]
        executors = {
            "get_my_shipments": executors["get_my_shipments"],   # self-gated to customers; kept so a stray call gets a note, not a crash
            "get_my_assignments": partial(execute_get_my_assignments, current_user=current_user),
            "get_shipment_status": partial(execute_get_shipment_status, current_user=current_user),
        }
    elif role == roles.ADMIN:
        tools = [TOOL_GET_VEHICLE_STATUS, TOOL_GET_SHIPMENT_STATUS]
    else:
        tools = [TOOL_GET_SHIPMENT_STATUS, TOOL_GET_MY_SHIPMENTS]   # customers and visitors never get the live fleet list
        executors.pop("get_vehicle_status")
    return await run_tool_agent(SYSTEM_PROMPT + roles.prompt_context(current_user), tools, executors, message, history, sentiment, on_stage=on_stage, ran_out=ran)


async def _rider_route_summary(current_user: dict) -> str:
    r = await execute_get_my_assignments(current_user=current_user)
    active = [s for s in r.get("shipments", []) if s["isActive"]]
    if not active:
        return "You have no active deliveries right now. Operations will assign the next one."
    lines = "; ".join(f"{s['trackingNumber']} ({s['status'].replace('_', ' ').lower()}) to {s['dropAddress']}" for s in active[:5])
    return f"You have {len(active)} active deliver{'y' if len(active) == 1 else 'ies'}: {lines}."


async def _customer_summary(current_user: dict) -> str:
    r = await execute_get_my_shipments(current_user=current_user)
    active = [s for s in r.get("shipments", []) if s["isActive"]]
    if not active:
        return "You have no active shipments right now."
    lines = "; ".join(f"{s['trackingNumber']} ({s['status'].replace('_', ' ').lower()}"
                      f"{', est. ' + s['estimatedDeliveryText'] if s.get('estimatedDeliveryText') else ''})" for s in active[:5])
    return f"You have {len(active)} active shipment{'' if len(active) == 1 else 's'}: {lines}."


async def fallback(message: str, current_user: dict = None) -> str:
    """LLM unavailable (outage, timeout, no key): answer a parcel-status question straight from the database instead of
    handing back generic help. Only fires when the message contains a tracking number; otherwise returns None."""
    is_rider = roles.role_of(current_user) == roles.DRIVER
    ref = extract_tracking_number(message)
    if not ref:
        if is_rider and re.search(r"\b(route|deliver\w*|next|pending|assign\w*|today)\b", message, re.I):
            return await _rider_route_summary(current_user)
        if roles.role_of(current_user) == roles.USER and _MY_PARCEL.search(message) and not _HOWTO.search(message):
            return await _customer_summary(current_user)      # their own, from the database, when no model is available
        return None
    # Same rule as the tool path: a rider only ever sees shipments assigned to them.
    r = await execute_get_shipment_status(ref, current_user=current_user)      # the executor itself enforces the rider rule
    if not r.get("found") and r.get("note") == NOT_ASSIGNED_NOTE:
        return "That shipment isn't assigned to you, so I can't share it. Operations assigns deliveries."
    if r.get("found"):
        status = r["status"].replace("_", " ").lower()
        eta = f" Estimated delivery: {r['estimatedDeliveryText']}." if r.get("estimatedDeliveryText") and r["status"] != "DELIVERED" else ""
        return f"Your parcel {r['trackingNumber']} is currently {status}.{eta}"
    if r.get("badChecksum"):
        return "I didn't catch that tracking number clearly. Please say it again, one digit at a time."
    if r.get("didYouMean"):
        return f"I couldn't find {ref}. Did you mean {r['didYouMean']}? Say yes and I'll check it."
    return f"I couldn't find a shipment with tracking number {ref}. Please check it and say it again, one letter or digit at a time."
