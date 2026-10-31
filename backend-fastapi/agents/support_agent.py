import re

from agents import roles
from agents.base import run_tool_agent
from tools.support_tools import TOOL_GET_SUPPORT_INFO, execute_get_support_info

SYSTEM_PROMPT = """You are ShipBot's support specialist for Shipora, a parcel delivery and fleet management platform.

You ONLY answer questions about how to reach Shipora support: phone, email, WhatsApp, and office address/hours. Use the get_support_info tool to fetch the real, current contact details before answering — never guess or use stale details.

Tone: friendly, concise. Keep responses under 100 words."""


_EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
_PHONE = re.compile(r"\+?\d[\d\s().-]{5,}\d")


def contact_text(cfg: dict) -> str:
    return (f"You can reach Shipora support by phone at {cfg['phone']}, by email at {cfg['email']} or on WhatsApp at {cfg['whatsapp']}. "
            f"Office hours: {cfg['officeHours']}. Address: {cfg['officeAddress']}.")


def invents_contact_details(reply: str, cfg: dict) -> bool:
    """True when the reply states an email address or phone number that is not Shipora's real one. A small model that skips the lookup
    makes plausible ones up ("123-456-7890"), and a customer will dial them."""
    real_digits = {re.sub(r"\D", "", cfg.get("phone", "")), re.sub(r"\D", "", cfg.get("whatsapp", ""))} - {""}
    for email in _EMAIL.findall(reply):
        if email.lower() != str(cfg.get("email", "")).lower():
            return True
    for phone in _PHONE.findall(reply):
        digits = re.sub(r"\D", "", phone)
        if len(digits) >= 7 and not any(real.endswith(digits) or digits.endswith(real) for real in real_digits):
            return True
    return False


async def handle(message: str, history: list, sentiment: str, current_user: dict = None, on_stage=None, meta: dict = None) -> str:
    tools = [TOOL_GET_SUPPORT_INFO]
    executors = {"get_support_info": execute_get_support_info}
    reply = await run_tool_agent(SYSTEM_PROMPT + roles.prompt_context(current_user), tools, executors, message, history, sentiment, on_stage=on_stage)
    if reply is None:
        return None
    cfg = await execute_get_support_info()
    if invents_contact_details(reply, cfg):
        if meta is not None:
            meta["source"] = "builtin"
        return contact_text(cfg)
    return reply
