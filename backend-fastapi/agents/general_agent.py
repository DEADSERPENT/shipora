"""General-purpose ShipBot agent — the orchestrator's fallback branch for
anything that isn't tracking/issues/support, and for when a specialist
agent can't run (no Gemini key, tool-call failure, etc).

Owns the system prompt, rule-based knowledge base, and LLM call that used to
live in routes/chat.py. Relocated (not duplicated) here so agents/orchestrator.py
can use it without routes/chat.py and agents/ importing each other in a cycle —
the dependency direction is strictly routes -> agents -> services/models.
"""

import re
from typing import Optional

import json
from functools import partial

import config
from agents import roles
from agents.base import run_tool_agent
from services.llm import get_llm_reply
from agents.base import PROMISE_REPLACEMENT, is_empty_promise
from tools.analytics import TOOL_GET_OPERATIONS_SUMMARY, execute_get_operations_summary, format_ops_summary
from tools.knowledge_base_tools import TOOL_SEARCH_KNOWLEDGE_BASE, execute_search_knowledge_base

GENERAL_SYSTEM_PROMPT = """You are ShipBot, the friendly AI assistant for Shipora — a parcel delivery and fleet management platform. You help customers, delivery agents, and admins use the platform effectively.

You ONLY answer questions related to:
- Shipora features: creating shipments, live tracking by tracking number, delivery-vehicle tracking, status updates
- Shipment lifecycle: created, pickup scheduled, picked up, in transit, out for delivery, delivered — and exceptions: delivery failed, customer unavailable, address issue, damaged, cancelled, returned to origin
- Service: Shipora is a same-day delivery service that operates in Bengaluru only (pickup and drop must both be inside Bengaluru; no standard/express/multi-day options); parcel categories and packaging basics
- Pricing and limits: __PRICING__
- Account management: profile updates, password changes, saved address and delivery instructions
- Customer features: creating and tracking shipments, reporting delivery issues
- Delivery agent features: sharing live location, updating shipment status, updating area and ETA
- Admin features: assigning agents to shipments, monitoring the fleet, managing delivery issues, editing support contact details
- Support: contact details, working hours, FAQs
- Operational analytics (admin-facing): shipment counts by status, delivery-issue trends, today's deliveries, resolution times — use the get_operations_summary tool for these broad "how are things going" questions, never guess numbers. When you call it, report the shipment pipeline, the delivery-issue stats AND the vehicle activity it returns.

Respond as if you're speaking to someone out loud, not writing a document:
- Use short sentences and contractions ("you'll", "it's", "don't").
- Never use markdown — no bold (**), no bullet points, no numbered lists, no headers.
- Turn lists into natural spoken sentences instead. For multi-step instructions, walk through the steps conversationally rather than itemizing them.
- Add natural conversational phrases where they fit ("Sure!", "Good question,", "Here's the thing —").

If a question is completely unrelated to parcel delivery or Shipora, say something like:
"I'm ShipBot, and I can only help with Shipora and parcel delivery stuff. For anything else, a general search engine's your best bet. Is there something about Shipora I can help with?"

Keep responses under 120 words unless the question genuinely needs more — this is spoken aloud, so shorter is better."""

def _money(v: float) -> str:
    return f"₹{v:g}"


def _pricing_line() -> str:
    return (f"the fare starts at {_money(config.FARE_BASE_INR)} and covers the first {config.FARE_INCLUDED_KM:g} km, then {_money(config.FARE_PER_KM_INR)} per extra km, plus {_money(config.FARE_PER_EXTRA_KG_INR)} per kg above {config.FARE_FREE_WEIGHT_KG:g} kg; "
            f"parcels can weigh up to {config.MAX_PARCEL_KG:g} kg (bike delivery); payment is cash or UPI to the rider on delivery; "
            "the exact fare and ETA are shown before booking. Never quote a price other than these numbers.")


GENERAL_SYSTEM_PROMPT = GENERAL_SYSTEM_PROMPT.replace("__PRICING__", _pricing_line())

# ─── Built-in rule-based knowledge base ─────────────────────────────────────
KB = [
    {
        "keys": ["track", "where", "location", "map", "live", "gps", "tracking number"],
        "reply": "**Tracking a parcel:**\n"
        "• Every shipment gets a tracking number starting with **SHP**.\n"
        "• Enter it on the tracking page to see its current status and full timeline.\n"
        "• Once it's out for delivery, the delivery vehicle's live position and ETA are shown on the map.",
    },
    {
        "keys": ["status", "lifecycle", "stages", "in transit", "out for delivery", "delivered"],
        "reply": "**Shipment stages:**\n"
        "• Created → Pickup Scheduled → Picked Up → In Transit → Out for Delivery → Delivered.\n"
        "• Exceptions: Delivery Failed, Customer Unavailable, Address Issue, Damaged, Cancelled, Return to Origin.\n"
        "• A delivery is attempted up to 3 times before the parcel is returned to the sender.",
    },
    {
        "keys": ["create", "send", "book", "new shipment", "ship"],
        "reply": "**Creating a shipment:**\n"
        "• Log in as a customer and choose **New Shipment**.\n"
        "• Enter the recipient's name, phone and address, plus parcel weight, category and declared value.\n"
        "• Drop the pin for pickup and delivery on the map — both must be inside Bengaluru. Delivery is same-day, and you'll get a tracking number straight away.",
    },
    {
        "keys": ["cancel"],
        "reply": "**Cancelling a shipment:**\n"
        "You can cancel a shipment yourself until it has been picked up. After pickup, contact support and an admin can arrange a return to origin.",
    },
    {
        "keys": ["service", "express", "same day", "same-day", "standard", "delivery time", "how long", "bengaluru", "bangalore", "city", "area", "outside"],
        "reply": "**Same-day delivery, Bengaluru only:**\n"
        "• Every parcel is picked up and delivered the same day — there are no standard or express slots.\n"
        "• Both the pickup and the delivery address must be inside Bengaluru.\n\n"
        "The estimated delivery date is shown on every shipment.",
    },
    {
        "keys": ["price", "fare", "cost", "charge", "how much", "pay", "payment", "cash", "upi", "kg", "weight", "heavy", "limit", "prohibited", "not allowed", "banned", "allowed", "carry", "can't", "cannot"],
        "reply": "**Fare, limits and payment:**\n"
        f"• The fare starts at {_money(config.FARE_BASE_INR)} and covers the first {config.FARE_INCLUDED_KM:g} km, then {_money(config.FARE_PER_KM_INR)} for every extra km.\n"
        f"• Parcels above {config.FARE_FREE_WEIGHT_KG:g} kg add {_money(config.FARE_PER_EXTRA_KG_INR)} for every extra kg.\n"
        f"• Parcels can weigh up to {config.MAX_PARCEL_KG:g} kg (we deliver by bike).\n"
        "• You pay the rider on delivery, by cash or UPI.\n"
        "• We can't carry flammables, alcohol, medicines, cash, jewellery, live animals or anything illegal.\n\n"
        "You'll see the exact fare and ETA before you book.",
    },
    {
        "keys": ["issue", "problem", "complaint", "complain", "report", "damaged", "lost", "delay", "late", "wrong address"],
        "reply": "**Reporting a delivery issue:**\n"
        "• Open **Delivery Issues**, choose a category (delayed, lost, damaged, wrong address, agent behaviour, failed delivery, other).\n"
        "• Optionally link the shipment's tracking number, add a description, and submit.\n"
        "• You can track its status (Open → In Progress → Resolved) and read the admin's reply.",
    },
    {
        "keys": ["anonymous", "privacy", "identity", "hide", "secret"],
        "reply": "**Anonymous reports:**\n"
        "You can report a delivery issue without revealing your identity — your name and contact details are hidden from admin. Anonymous reports can't be tracked afterwards.",
    },
    {
        "keys": ["profile", "edit", "update", "change name", "change phone", "change address"],
        "reply": "**Updating your profile:**\n"
        "• Click **Profile** in the navbar.\n"
        "• Customers can edit: name, phone, address, account type and delivery instructions.\n"
        "• Delivery agents can edit: name, phone, delivery area and vehicle type.\n"
        "• Email, vehicle number and licence are locked — contact admin to change them.",
    },
    {
        "keys": ["password", "forgot", "reset", "change password"],
        "reply": "**Password help:**\n"
        "• **Forgot password?** On the login page click **Forgot password?** — enter your email, select your role, then set a new password.\n"
        "• **Change password** while logged in: go to **Profile** and use the **Change Password** section.",
    },
    {
        "keys": ["agent", "driver", "delivery agent", "start sharing", "broadcast", "area complete", "deliver"],
        "reply": "**Delivery agent features:**\n"
        "• Start sharing your live location so customers and admins can follow your vehicle.\n"
        "• See your assigned shipments and update each one: picked up, in transit, out for delivery, delivered, or an exception.\n"
        "• Keep your current area and ETA up to date.",
    },
    {
        "keys": ["admin", "admin dashboard", "monitor", "overview", "assign"],
        "reply": "**Admin features:**\n"
        "• Overview of shipments by status and the live fleet.\n"
        "• Assign a delivery agent to a shipment — this schedules the pickup.\n"
        "• Review tracking history, handle delivery issues, and edit the support contact details.",
    },
    {
        "keys": ["support", "contact", "help", "phone", "email", "whatsapp", "helpline", "call"],
        "reply": "**Getting support:**\n"
        "Visit the **Support** page for the helpline, email, WhatsApp, office address and hours. Admins can update these details in the admin settings.",
    },
    {
        "keys": ["register", "sign up", "create account", "new account"],
        "reply": "**Creating an account:**\n"
        "• Go to **Register** and pick your role: Customer, Delivery Agent, or Admin.\n"
        "• Customers: name, phone, email, address and a pin on the map.\n"
        "• Delivery agents: vehicle number and type, driving licence number and delivery area.\n"
        "• Admins: add organisation name.",
    },
    {
        "keys": ["login", "sign in", "cant login", "cannot login", "access"],
        "reply": "**Logging in:**\n"
        "• Go to **Login**, select your role (Customer / Delivery Agent / Admin), enter email and password.\n"
        "• If you forgot your password, click **Forgot password?** below the form.\n"
        "• Make sure you select the correct role — a customer login will not work with an agent account.",
    },
]

_GREETING_RE = re.compile(r"^(hi|hello|hey|good\s*(morning|afternoon|evening)|howdy)", re.IGNORECASE)


_OPS_INTENT_RE = re.compile(r"\b(summar\w*|operations?|performance|overview|how (?:are|is) (?:things|it|everything)|status report|today'?s? (?:numbers|stats|figures))\b", re.I)


def _best_kb_match(query: str) -> Optional[dict]:
    """Shared by rule_based_reply() (zero-key fallback) and
    tools/knowledge_base_tools.py (the tool-calling tier) — one scoring
    implementation, not two."""
    lower = query.lower()
    best, best_score = None, 0
    for entry in KB:
        # whole-word match ("live" must not fire inside "delivery"); multi-word keys are more specific, so they weigh more
        score = sum(len(k.split()) for k in entry["keys"] if re.search(rf"(?<![\w-]){re.escape(k)}s?(?![\w-])", lower))
        if score > best_score:
            best_score, best = score, entry
    return best


def rule_based_reply(msg: str, current_user: dict = None) -> str:
    lower = msg.lower()
    best = _best_kb_match(msg)
    if best:
        return best["reply"]
    if _GREETING_RE.match(lower) and roles.role_of(current_user) != roles.ANON:
        return roles.PROFILES[roles.role_of(current_user)]["greeting"]
    if _GREETING_RE.match(lower):
        return (
            "Hello! I am **ShipBot** 📦, your Shipora assistant.\n\n"
            "I can help you with:\n"
            "• Tracking parcels and delivery vehicles\n"
            "• Creating shipments\n"
            "• Reporting delivery issues\n"
            "• Profile & account settings\n"
            "• Delivery agent and admin features\n\n"
            "What would you like to know?"
        )
    return (
        "I am ShipBot and I can only help with Shipora and parcel delivery topics. Try asking about:\n"
        '• **Tracking** — "How do I track my parcel?"\n'
        '• **Shipments** — "How do I create a shipment?"\n'
        '• **Issues** — "How do I report a damaged parcel?"\n'
        '• **Delivery** — "How long does delivery take?"'
    )


async def handle(message: str, history: list, sentiment: str = "neutral", current_user: dict = None, on_stage=None) -> dict:
    """Three-tier fallback, each tier completely independent of the ones
    below it: (1) Gemini tool-calling KB search + operations-summary
    lookup — grounds informational/analytics answers in real data rather
    than freeform recall; (2) the existing get_llm_reply (Gemini plain
    text); (3) the existing rule_based_reply() keyword match, Shipora's
    original zero-API-key safety net, completely unchanged."""
    tools = [TOOL_SEARCH_KNOWLEDGE_BASE]
    executors = {"search_knowledge_base": execute_search_knowledge_base}
    if roles.role_of(current_user) == roles.ADMIN:   # company-wide numbers are for Operations only
        tools.append(TOOL_GET_OPERATIONS_SUMMARY)
        executors["get_operations_summary"] = partial(execute_get_operations_summary, current_user=current_user)
    system = GENERAL_SYSTEM_PROMPT + roles.prompt_context(current_user)
    ops_data = None
    if roles.role_of(current_user) == roles.ADMIN and _OPS_INTENT_RE.search(message):
        # Small local models often announce "let me check" and never call the tool, so for a plain ops-summary request
        # fetch the numbers first and hand them over as authoritative context; every provider then only has to phrase them.
        data = await execute_get_operations_summary(current_user=current_user)
        ops_data = data
        system += ("\n\nLive operations data, fetched just now (authoritative; answer only from it, and report the shipment "
                   "pipeline, the delivery-issue numbers and the vehicle activity). Name each figure's reporting period exactly as given "
                   "in the *PeriodText fields — shipment counts are all time, issue figures cover windowDays days, vehicles are today; "
                   "never call a figure 'today's' unless it is the vehicle activity: " + json.dumps(data))
    tool_reply = await run_tool_agent(system, tools, executors, message, history, sentiment, on_stage=on_stage)
    if ops_data is not None and (tool_reply is None or tool_reply == PROMISE_REPLACEMENT or is_empty_promise(tool_reply)):
        return {"reply": format_ops_summary(ops_data), "source": "builtin"}     # the numbers are in hand: state them, whatever the model did
    if tool_reply is not None:
        return {"reply": tool_reply, "source": "ai"}

    reply = await get_llm_reply(message, history, system)
    if reply is None:
        return {"reply": rule_based_reply(message, current_user), "source": "builtin"}
    return {"reply": reply, "source": "ai"}
