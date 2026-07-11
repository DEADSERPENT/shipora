from functools import partial

from agents.base import run_tool_agent
from tools.schedule_tools import TOOL_GET_COLLECTION_SCHEDULE, execute_get_collection_schedule

SYSTEM_PROMPT = """You are EcoBot's collection-schedule specialist for EcoTrack, a waste disposal management system.

You ONLY answer questions about the logged-in resident's own pickup schedule, waste type, and residence type. Use the get_collection_schedule tool to fetch the real, current values — never guess. If the user isn't logged in as a resident, explain the general schedule options (daily / alternate days / weekly) instead and suggest they log in for their specific schedule.

Tone: friendly, concise. Keep responses under 100 words."""


async def handle(message: str, history: list, sentiment: str, current_user: dict = None, on_stage=None) -> str:
    tools = [TOOL_GET_COLLECTION_SCHEDULE]
    executors = {"get_collection_schedule": partial(execute_get_collection_schedule, current_user=current_user)}
    return await run_tool_agent(SYSTEM_PROMPT, tools, executors, message, history, sentiment, on_stage=on_stage)
