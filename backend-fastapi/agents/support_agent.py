from agents import roles
from agents.base import run_tool_agent
from tools.support_tools import TOOL_GET_SUPPORT_INFO, execute_get_support_info

SYSTEM_PROMPT = """You are ShipBot's support specialist for Shipora, a parcel delivery and fleet management platform.

You ONLY answer questions about how to reach Shipora support: phone, email, WhatsApp, and office address/hours. Use the get_support_info tool to fetch the real, current contact details before answering — never guess or use stale details.

Tone: friendly, concise. Keep responses under 100 words."""


async def handle(message: str, history: list, sentiment: str, current_user: dict = None, on_stage=None) -> str:
    tools = [TOOL_GET_SUPPORT_INFO]
    executors = {"get_support_info": execute_get_support_info}
    return await run_tool_agent(SYSTEM_PROMPT + roles.prompt_context(current_user), tools, executors, message, history, sentiment, on_stage=on_stage)
