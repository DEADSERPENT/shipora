"""Tool schema + executor for Shipora support contact info."""

from models.support_config import SupportConfig
from serializers import support_config_json

TOOL_GET_SUPPORT_INFO = {
    "name": "get_support_info",
    "description": "Fetch current Shipora support contact details (phone, email, WhatsApp, office hours/address).",
    "input_schema": {"type": "object", "properties": {}, "required": []},
}


async def execute_get_support_info() -> dict:
    doc = await SupportConfig.find_one({})
    return support_config_json(doc)
