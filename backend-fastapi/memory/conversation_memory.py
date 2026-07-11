"""MongoDB-backed conversation memory, keyed by sessionId. Durable across
backend restarts and multiple workers (unlike an in-process dict), so a
follow-up question ("KA01AB1234" after "track my truck, which one?") still
resolves correctly even if the request lands on a different worker."""

from typing import List, Optional

from models.conversation_turn import ConversationTurn

DEFAULT_LIMIT = 20


async def get_history(session_id: Optional[str], limit: int = DEFAULT_LIMIT) -> List[dict]:
    """Returns the last `limit` turns for a session, oldest first, shaped as
    {"role": ..., "content": ...} ready to feed into agents. Returns an
    empty list (stateless turn) when no session_id is given."""
    if not session_id:
        return []
    turns = (
        await ConversationTurn.find(ConversationTurn.sessionId == session_id)
        .sort(-ConversationTurn.createdAt)
        .limit(limit)
        .to_list()
    )
    turns.reverse()
    return [{"role": t.role, "content": t.content} for t in turns]


async def append_turn(session_id: Optional[str], role: str, content: str, agent: Optional[str] = None) -> None:
    """No-ops when session_id is absent — matches get_history's stateless
    fallback rather than persisting turns nothing can retrieve them by."""
    if not session_id:
        return
    await ConversationTurn(sessionId=session_id, role=role, content=content, agent=agent).insert()
