"""Tool schema + executor wrapping EcoTrack's rule-based knowledge base, so
general/informational answers are tool-grounded too rather than freeform.
Reuses agents/general_agent.py's KB matching (_best_kb_match) rather than
duplicating the KB data or its scoring logic — that stays the single source
of truth, also used by the zero-key rule_based_reply() fallback."""

TOOL_SEARCH_KNOWLEDGE_BASE = {
    "name": "search_knowledge_base",
    "description": (
        "Search EcoTrack's knowledge base for how-to information: collection schedule formats, "
        "waste types, profile/password help, registration/login, admin features, driver features, "
        "proximity alerts, anonymous complaints, and similar informational questions. Call this "
        "before answering any how-to/informational question rather than answering from memory."
    ),
    "input_schema": {
        "type": "object",
        "properties": {"query": {"type": "string", "description": "The user's question, or a short paraphrase of it."}},
        "required": ["query"],
    },
}


async def execute_search_knowledge_base(query: str) -> dict:
    from agents.general_agent import _best_kb_match

    match = _best_kb_match(query)
    if not match:
        return {"found": False, "note": "No matching knowledge base entry. Answer only if you're confident it's an EcoTrack topic; otherwise say you can only help with EcoTrack and waste disposal."}
    return {"found": True, "answer": match["reply"]}
