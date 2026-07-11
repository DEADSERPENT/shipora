"""General-purpose EcoBot agent — the orchestrator's fallback branch for
anything that isn't tracking/complaints/support, and for when a specialist
agent can't run (no Anthropic key, tool-call failure, etc).

Owns the system prompt, rule-based knowledge base, and LLM call that used to
live in routes/chat.py. Relocated (not duplicated) here so agents/orchestrator.py
can use it without routes/chat.py and agents/ importing each other in a cycle —
the dependency direction is strictly routes -> agents -> services/models.
"""

import re
from typing import Optional

from agents.base import run_tool_agent
from services.llm import get_llm_reply
from tools.knowledge_base_tools import TOOL_SEARCH_KNOWLEDGE_BASE, execute_search_knowledge_base

GENERAL_SYSTEM_PROMPT = """You are EcoBot, the friendly AI assistant for EcoTrack — a smart waste disposal management system. You help residents, drivers, and admins use the platform effectively.

You ONLY answer questions related to:
- EcoTrack features: live GPS vehicle tracking, collection schedules, proximity alerts
- Waste disposal: types of waste (household, recyclable, organic, mixed), separation, best practices
- Account management: profile updates, password changes, location settings, pickup schedule
- Resident features: viewing live vehicle tracking, collection logs, filing complaints, anonymous complaints
- Driver features: sharing GPS location, marking areas as completed, updating status and ETA
- Admin features: monitoring drivers, viewing collection logs, managing complaints, editing support contact details
- Complaints: how to submit, track status, anonymous submissions
- Support: contact details, working hours, FAQs
- Waste collection schedules: daily, alternate days, weekly options
- Resident types: independent house vs flat/apartment

Respond as if you're speaking to someone out loud, not writing a document:
- Use short sentences and contractions ("you'll", "it's", "don't").
- Never use markdown — no bold (**), no bullet points, no numbered lists, no headers.
- Turn lists into natural spoken sentences instead. For multi-step instructions, walk through the steps conversationally ("First, open your dashboard. Then tap Live Tracking — you'll see the truck right there.") rather than itemizing them.
- Add natural conversational phrases where they fit ("Sure!", "Good question,", "Here's the thing —").

For example, instead of:
"Waste should be segregated into biodegradable and non-biodegradable categories."
Say:
"Sure! You'll want to separate your waste into two groups — biodegradable, like food scraps, and non-biodegradable, like plastic bottles."

If a question is completely unrelated to waste management or EcoTrack, say something like:
"I'm EcoBot, and I can only help with EcoTrack and waste disposal stuff. For anything else, a general search engine's your best bet. Is there something about EcoTrack I can help with?"

Keep responses under 120 words unless the question genuinely needs more — this is spoken aloud, so shorter is better."""

# ─── Built-in rule-based knowledge base ─────────────────────────────────────
KB = [
    {
        "keys": ["track", "truck", "vehicle", "where", "location", "map", "live", "gps"],
        "reply": "**How to track the waste truck:**\n"
        "• Open your **Resident Dashboard** — the map shows all active vehicles in real time.\n"
        "• When a truck comes within **3 km** of your home, a proximity alert appears and a route line is drawn to your door.\n"
        "• The sidebar shows each vehicle's current area and ETA.",
    },
    {
        "keys": ["complaint", "complain", "report", "issue", "problem", "raise"],
        "reply": "**Filing a complaint:**\n"
        "• Go to **Complaints** from your dashboard or the quick-actions panel.\n"
        "• Click **+ New Complaint**, choose a category, add a subject and description (min 20 chars), then submit.\n"
        "• Want privacy? Tick **Submit Anonymously** — your name won't be shared with admin.\n"
        "• Track status (Open → In Progress → Resolved) in your complaint list.",
    },
    {
        "keys": ["anonymous", "privacy", "identity", "hide", "secret"],
        "reply": "**Anonymous complaints:**\n"
        "You can submit a complaint without revealing your identity.\n"
        "• In the New Complaint form, tick **Submit Anonymously**.\n"
        "• Your name and contact details are hidden from admin.\n"
        "• Note: anonymous complaints cannot be tracked after submission — they won't appear in your list.",
    },
    {
        "keys": ["schedule", "pickup", "daily", "alternate", "weekly", "frequency", "change schedule"],
        "reply": "**Pickup schedules available:**\n"
        "• **Daily** — collected every day\n"
        "• **Alternate Days** — every other day\n"
        "• **Weekly** — once a week\n\n"
        "To change your schedule: go to **Profile → Collection Preferences** and select a new schedule. Changes take effect from the next cycle.",
    },
    {
        "keys": ["waste type", "household", "recyclable", "organic", "mixed", "separate", "bin", "which waste"],
        "reply": "**Waste types accepted:**\n"
        "• **Mixed** — general waste\n"
        "• **Household** — kitchen & home waste\n"
        "• **Recyclable** — paper, plastic, glass, metal\n"
        "• **Organic** — food scraps, garden waste\n\n"
        "**Separation tip:** Green bin = organic, Blue = dry recyclables, Black = non-recyclable. Hazardous items (batteries, chemicals) are NOT accepted.",
    },
    {
        "keys": ["log", "history", "collection log", "past", "previous", "record"],
        "reply": "**Viewing collection logs:**\n"
        "• **Residents** — go to **Collection Log** from your dashboard to see up to 30 days of collection records grouped by date.\n"
        "• **Drivers** — go to **Collection History** to see your own 30-day log with areas covered and stats.\n"
        "• **Admins** — the Collection Logs tab lets you filter by any date.",
    },
    {
        "keys": ["profile", "edit", "update", "change name", "change phone", "change address"],
        "reply": "**Updating your profile:**\n"
        "• Click **Profile** in the top navbar.\n"
        "• Residents can edit: name, phone, address, waste type, pickup schedule, residence type, and home location.\n"
        "• Drivers can edit: name, phone, and assigned area.\n"
        "• Email, vehicle number, and licence are locked (contact admin to change).\n"
        "• Scroll down to change your **password** anytime.",
    },
    {
        "keys": ["password", "forgot", "reset", "change password"],
        "reply": "**Password help:**\n"
        "• **Forgot password?** On the login page click **Forgot password?** — enter your email, select your role, then set a new password.\n"
        "• **Change password** while logged in: go to **Profile** → scroll to the **Change Password** section → enter your current password and new password.",
    },
    {
        "keys": ["driver", "driver dashboard", "start sharing", "gps", "broadcast", "area complete"],
        "reply": "**Driver features:**\n"
        "• Click **Start Sharing Location** to broadcast your GPS position live to all residents.\n"
        "• Update **Current Area** and **ETA** in the status panel — residents see this in real time.\n"
        "• Use **Areas Completed** to log zones you have finished — tap Add after typing the area name.\n"
        "• Click **Save Status** to persist your status to the database.",
    },
    {
        "keys": ["admin", "admin dashboard", "monitor", "overview"],
        "reply": "**Admin dashboard tabs:**\n"
        "• **Overview** — live driver feed, stats (active drivers, areas done, total residents).\n"
        "• **Collection Logs** — filter by date, see all driver activity.\n"
        "• **Complaints** — read and respond to resident complaints, update status.\n"
        "• **Settings** — edit the support contact details (phone, email, WhatsApp, office address).",
    },
    {
        "keys": ["support", "contact", "help", "phone", "email", "whatsapp", "helpline", "call"],
        "reply": "**Getting support:**\n"
        "Visit the **Support** page (Navbar → Support) for:\n"
        "• Helpline number (24/7 toll-free)\n"
        "• Email support (reply within 24 hrs)\n"
        "• WhatsApp (Mon–Sat, 8 AM–8 PM)\n"
        "• Municipal office address & hours\n\n"
        "Admins can update these details in **Admin Dashboard → Settings**.",
    },
    {
        "keys": ["residence", "flat", "apartment", "house", "independent", "resident type"],
        "reply": "**Residence type:**\n"
        "During registration (or in your Profile), you can set whether you live in an **Independent House** or a **Flat/Apartment**. This helps the waste management team optimise pickup routes for your area.",
    },
    {
        "keys": ["proximity", "alert", "nearby", "near me", "3 km", "notification"],
        "reply": "**Proximity alerts:**\n"
        "When a waste truck comes within **3 km** of your registered home location:\n"
        "• A green alert banner appears at the top of your dashboard.\n"
        "• A route line is drawn on the map showing the road path to your home.\n"
        "• The sidebar shows the driver name, vehicle number, and ETA.",
    },
    {
        "keys": ["register", "sign up", "create account", "new account"],
        "reply": "**Creating an account:**\n"
        "• Go to **Register** and pick your role: Resident, Driver, or Admin.\n"
        "• Residents: fill in name, phone (10-digit Indian), email, waste type, schedule, residence type, and pin your home on the map.\n"
        "• Drivers: add vehicle number (e.g. KA01AB1234) and driving licence number.\n"
        "• Admins: add organisation name.",
    },
    {
        "keys": ["login", "sign in", "cant login", "cannot login", "access"],
        "reply": "**Logging in:**\n"
        "• Go to **Login**, select your role (Resident / Driver / Admin), enter email and password.\n"
        "• If you forgot your password, click **Forgot password?** below the form.\n"
        "• Make sure you select the correct role — a resident login will not work with a driver account.",
    },
]

_GREETING_RE = re.compile(r"^(hi|hello|hey|good\s*(morning|afternoon|evening)|howdy)", re.IGNORECASE)


def _best_kb_match(query: str) -> Optional[dict]:
    """Shared by rule_based_reply() (zero-key fallback) and
    tools/knowledge_base_tools.py (the tool-calling tier) — one scoring
    implementation, not two."""
    lower = query.lower()
    best, best_score = None, 0
    for entry in KB:
        score = sum(1 for k in entry["keys"] if k in lower)
        if score > best_score:
            best_score, best = score, entry
    return best


def rule_based_reply(msg: str) -> str:
    lower = msg.lower()
    best = _best_kb_match(msg)
    if best:
        return best["reply"]
    if _GREETING_RE.match(lower):
        return (
            "Hello! I am **EcoBot** 🌿, your EcoTrack assistant.\n\n"
            "I can help you with:\n"
            "• Tracking waste collection vehicles\n"
            "• Managing complaints\n"
            "• Pickup schedules & waste types\n"
            "• Profile & account settings\n"
            "• Driver and admin features\n\n"
            "What would you like to know?"
        )
    return (
        "I am EcoBot and I can only help with EcoTrack and waste disposal topics. Try asking about:\n"
        '• **Vehicle tracking** — "How do I track the truck?"\n'
        '• **Complaints** — "How do I file a complaint?"\n'
        '• **Schedule** — "How do I change my pickup schedule?"\n'
        '• **Waste types** — "What waste types are accepted?"'
    )


async def handle(message: str, history: list, sentiment: str = "neutral", current_user: dict = None, on_stage=None) -> dict:
    """Three-tier fallback, each tier completely independent of the ones
    below it: (1) Anthropic tool-calling KB search — grounds informational
    answers in the same KB data rather than freeform recall; (2) the
    existing provider-agnostic get_llm_reply (LLM_PROVIDER); (3) the
    existing rule_based_reply() keyword match, EcoTrack's original
    zero-API-key safety net, completely unchanged."""
    tools = [TOOL_SEARCH_KNOWLEDGE_BASE]
    executors = {"search_knowledge_base": execute_search_knowledge_base}
    tool_reply = await run_tool_agent(GENERAL_SYSTEM_PROMPT, tools, executors, message, history, sentiment, on_stage=on_stage)
    if tool_reply is not None:
        return {"reply": tool_reply, "source": "ai"}

    reply = await get_llm_reply(message, history, GENERAL_SYSTEM_PROMPT)
    if reply is None:
        return {"reply": rule_based_reply(message), "source": "builtin"}
    return {"reply": reply, "source": "ai"}
