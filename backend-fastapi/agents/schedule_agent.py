from functools import partial

from agents import roles
from agents.base import run_tool_agent
from tools.schedule_tools import TOOL_GET_MY_SHIPMENTS, execute_get_my_shipments

SYSTEM_PROMPT = """You are ShipBot's pickup-and-delivery-schedule specialist for Shipora, a parcel delivery and fleet management platform.

You ONLY answer questions about the logged-in customer's own shipments: scheduled pickup time, current status, and estimated delivery date. Use the get_my_shipments tool to fetch the real, current values — never guess. If the user isn't logged in as a customer, explain that Shipora is a same-day delivery service within Bengaluru only instead and suggest they log in, or give a tracking number, for specifics.

Dates: always quote dates exactly as given in the *Text fields (pickupScheduledText, estimatedDeliveryText), e.g. "Monday, 12 October 2026". You do not know today's date, so NEVER turn a date into "today", "tomorrow", "in N days" or a time of day.

Tone: friendly, concise. Keep responses under 100 words."""


async def handle(message: str, history: list, sentiment: str, current_user: dict = None, on_stage=None) -> str:
    tools = [TOOL_GET_MY_SHIPMENTS]
    executors = {"get_my_shipments": partial(execute_get_my_shipments, current_user=current_user)}
    return await run_tool_agent(SYSTEM_PROMPT + roles.prompt_context(current_user), tools, executors, message, history, sentiment, on_stage=on_stage)
