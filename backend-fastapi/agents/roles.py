"""Role profiles for ShipBot. One place decides, per signed-in role (customer / delivery agent / operations / visitor):
what the assistant says when it opens, which suggestions it offers, which specialists and tools it may use, and the
role context added to every specialist prompt. The frontend renders GET /api/chat/profile; it carries no role logic."""

import re
from typing import Optional

ANON, USER, DRIVER, ADMIN = "anonymous", "user", "driver", "admin"

PROFILES = {
    ANON: {
        "label": "Visitor",
        "badge": "Same-day · Bengaluru",
        "title": "Hi, I'm ShipBot",
        "subtitle": "Track a parcel with its tracking number or ask how Shipora works. Sign in to book and manage deliveries.",
        "placeholder": "Ask about tracking or pricing…",
        "greeting": "Hi! I'm ShipBot. I can track a parcel from its tracking number and answer questions about Shipora. Sign in to book and manage your deliveries.",
        "suggestions": [
            {"text": "How do I track a parcel?", "icon": "map-pin"},
            {"text": "How much does delivery cost?", "icon": "wallet"},
            {"text": "How do I create an account?", "icon": "user"},
            {"text": "What are the support hours?", "icon": "headset"},
        ],
        "agents": {"tracking", "complaints", "schedule", "support", "general"},
        "context": "The user is NOT signed in. You can look up a parcel only when they give its tracking number, and answer general questions about Shipora. You cannot see anyone's account, shipments or issues, and you have no access to company-wide figures, the fleet or operations data — if asked, say that needs signing in with the right account; never say you will 'pull up' or 'check' data you have no tool for.",
    },
    USER: {
        "label": "Customer",
        "badge": "Same-day · Bengaluru",
        "title": "Hi, I'm ShipBot",
        "subtitle": "Track a parcel, book a delivery or report an issue — ask me anything.",
        "placeholder": "Ask about your parcels…",
        "greeting": "Hi! I'm ShipBot. I can help you track your parcels, book a delivery, check pickup and delivery times, and report an issue.",
        "suggestions": [
            {"text": "Where is my parcel?", "icon": "map-pin"},
            {"text": "How do I create a shipment?", "icon": "package"},
            {"text": "When will my parcel arrive?", "icon": "clock"},
            {"text": "How do I report a damaged parcel?", "icon": "alert"},
        ],
        "agents": {"tracking", "complaints", "schedule", "support", "general"},
        "context": "The user is a signed-in CUSTOMER. They can only see their own shipments and issues. You cannot list the live fleet or give company-wide figures to customers, so never offer to fetch them — say Operations handles that. Help them track parcels, understand pickup and delivery times, book shipments and report problems.",
    },
    DRIVER: {
        "label": "Delivery agent",
        "badge": "Delivery agent",
        "title": "Hi, I'm ShipBot",
        "subtitle": "Your assigned deliveries, status updates and live-location help.",
        "placeholder": "Ask about your route…",
        "greeting": "Hi! I'm ShipBot. I can show your assigned deliveries, tell you which one is next, and explain how to update a delivery or handle a problem at the door.",
        "suggestions": [
            {"text": "What's on my route today?", "icon": "route"},
            {"text": "Which delivery is next?", "icon": "navigation"},
            {"text": "How do I update a delivery status?", "icon": "list"},
            {"text": "What if the receiver isn't available?", "icon": "alert"},
        ],
        # Delivery agents don't file customer issues (they flag a failed delivery on the route screen),
        # and "my schedule" for a rider is their route, handled by the tracking specialist.
        "agents": {"tracking", "support", "general"},
        "context": "The user is a signed-in DELIVERY AGENT (rider). Only discuss the deliveries assigned to them (use get_my_assignments), how to update statuses (picked up, in transit, out for delivery, delivered, or an exception), live location sharing and handling problems at pickup or drop. They cannot see other riders' vehicles, the live fleet, other riders' or customers' data, and they cannot assign shipments — Operations does that. If asked for the fleet or company-wide figures, say that is visible to Operations only; do not substitute their own deliveries for it.",
    },
    ADMIN: {
        "label": "Operations",
        "badge": "Operations",
        "title": "Hi, I'm ShipBot",
        "subtitle": "Fleet, shipments and delivery issues — ask for numbers, not guesses.",
        "placeholder": "Ask about operations…",
        "greeting": "Hi! I'm ShipBot. I can summarise operations, look up any shipment, list delivery issues and show which vehicles are live.",
        "suggestions": [
            {"text": "Summarize today's operations", "icon": "chart"},
            {"text": "How many delivery issues are open?", "icon": "alert"},
            {"text": "Which vehicles are live right now?", "icon": "truck"},
            {"text": "How do I assign an agent to a shipment?", "icon": "users"},
        ],
        "agents": {"tracking", "complaints", "support", "general"},
        "context": "The user is a signed-in OPERATIONS admin. They can look up any shipment, the live fleet, delivery issues across customers and operational summaries. Answer with real numbers from the tools. They do not have personal shipments or personal issues.",
    },
}

DENIED = {
    (DRIVER, "complaints"): "Delivery issues are filed by customers and handled by Operations. If a delivery goes wrong, mark it as failed, receiver unavailable, address issue or damaged from your route screen and Operations will follow up.",
}


_FLEET_RE = re.compile(r"\b(fleet|(?:which|what|show|list|all|other)\b.*\b(?:vehicles?|riders?|drivers?|agents?))\b", re.I)
_FILE_ISSUE_RE = re.compile(r"\b(?:complain\w*|(?:file|raise|log|submit|report|open)\b.{0,25}\b(?:issue|complaint|problem))\b", re.I)
_OPS_NUMBERS_RE = re.compile(r"\b(?:summar\w*|overview|report)\b.*\b(?:operations?|performance)\b|\btoday'?s? operations\b", re.I)


def intent_denial(user: Optional[dict], message: str) -> Optional[str]:
    """Questions a role must never be answered with data for, caught before any model runs. Small local models tend to
    announce 'let me fetch that' or to answer with whatever data they do have, so these are refused deterministically."""
    role = role_of(user)
    message = user_text(message)
    if role == ADMIN:
        return None
    if _OPS_NUMBERS_RE.search(message):
        return "Company-wide operations figures are available to Operations accounts only."
    if role == DRIVER and _FILE_ISSUE_RE.search(message):
        return DENIED[(DRIVER, "complaints")]
    if _FLEET_RE.search(message):
        if role == DRIVER:
            return "The live fleet view is for Operations only. I can show your own deliveries — just ask what's on your route."
        return "The live fleet view is for Operations only. To follow your own parcel, give me its tracking number."
    return None


_WRAPPER_MARKER = "User's message:"


def user_text(message: str) -> str:
    """The person's own words. The chat widget prefixes each message with a language/style instruction that ends in
    "User's message: <text>"; strict checks (is this a clean yes?) and stored transcripts must look at <text> only."""
    i = (message or "").rfind(_WRAPPER_MARKER)
    return message[i + len(_WRAPPER_MARKER):].strip() if i != -1 else (message or "").strip()


def role_of(user: Optional[dict]) -> str:
    r = (user or {}).get("role")
    return r if r in PROFILES else ANON


def profile_for(user: Optional[dict]) -> dict:
    p = PROFILES[role_of(user)]
    out = {k: p[k] for k in ("label", "badge", "title", "subtitle", "placeholder", "greeting", "suggestions")}
    out["role"] = role_of(user)
    return out


def prompt_context(user: Optional[dict]) -> str:
    ctx = PROFILES[role_of(user)].get("context")
    return f"\n\nWho you are talking to: {ctx}" if ctx else ""


def route_for(user: Optional[dict], agent: str):
    """Returns (agent_to_use, denial_message_or_None) for the classified agent."""
    role = role_of(user)
    if (role, agent) in DENIED:
        return agent, DENIED[(role, agent)]
    if role in (DRIVER, ADMIN) and agent == "schedule":
        return "tracking", None     # a rider's or admin's "schedule" question is a lookup on the tracking specialist's role-specific tools
    if agent not in PROFILES[role]["agents"]:
        return "general", None
    return agent, None
