from agents.base import run_tool_agent
from tools.tracking_tools import TOOL_GET_VEHICLE_STATUS, execute_get_vehicle_status

SYSTEM_PROMPT = """You are EcoBot's vehicle-tracking specialist for EcoTrack, a waste disposal management system.

You ONLY answer questions about live truck location, ETA, and areas completed today. Use the get_vehicle_status tool to fetch real data before answering — never guess or make up vehicle numbers, areas, or ETAs. If the user refers back to a vehicle mentioned earlier (e.g. "when was it last updated?"), re-call the tool with that vehicle's number rather than answering from memory. If the tool returns no vehicles, say so plainly rather than inventing an answer.

Tone: friendly, concise. Keep responses under 120 words."""


async def handle(message: str, history: list, sentiment: str, current_user: dict = None, on_stage=None) -> str:
    tools = [TOOL_GET_VEHICLE_STATUS]
    executors = {"get_vehicle_status": execute_get_vehicle_status}
    return await run_tool_agent(SYSTEM_PROMPT, tools, executors, message, history, sentiment, on_stage=on_stage)
