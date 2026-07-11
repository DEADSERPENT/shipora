from collections import Counter, defaultdict
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, Query

from auth_utils import require_role
from models.chat_analytics import ChatAnalytics
from serializers import iso

router = APIRouter(prefix="/api/analytics", tags=["Analytics"])

admin_only = require_role("admin", "Admin access required")

_AGENTS = ["tracking", "complaints", "schedule", "support", "general"]
_SENTIMENTS = ["positive", "neutral", "negative"]


@router.get("/overview", summary="Chat/voice analytics summary")
async def overview(_admin: dict = Depends(admin_only)):
    # Demo-scale collection — plain Python aggregation over .find_all() is
    # simpler and fine here; a $group pipeline would only be worth it at
    # much higher row counts.
    records = await ChatAnalytics.find_all().to_list()
    total = len(records)

    channel_counts = Counter(r.channel for r in records)
    agent_counts = Counter(r.agent for r in records)
    sentiment_counts = Counter(r.sentiment for r in records)
    source_counts = Counter(r.source for r in records)

    def avg(field: str):
        vals = [r.latencyMs.get(field) for r in records if r.latencyMs.get(field) is not None]
        return round(sum(vals) / len(vals)) if vals else None

    recent = await ChatAnalytics.find_all().sort(-ChatAnalytics.createdAt).limit(20).to_list()

    return {
        "totalConversations": total,
        "channelBreakdown": {"text": channel_counts.get("text", 0), "voice": channel_counts.get("voice", 0)},
        "agentDistribution": [{"agent": a, "count": agent_counts.get(a, 0)} for a in _AGENTS],
        "sentimentDistribution": [{"sentiment": s, "count": sentiment_counts.get(s, 0)} for s in _SENTIMENTS],
        "sourceBreakdown": {"ai": source_counts.get("ai", 0), "builtin": source_counts.get("builtin", 0)},
        "avgLatencyMs": {"stt": avg("stt"), "llm": avg("llm"), "tts": avg("tts"), "total": avg("total")},
        "recentConversations": [
            {
                "sessionId": r.sessionId,
                "channel": r.channel,
                "agent": r.agent,
                "sentiment": r.sentiment,
                "source": r.source,
                "transcript": r.transcript,
                "reply": r.reply,
                "createdAt": iso(r.createdAt),
            }
            for r in recent
        ],
    }


@router.get("/timeseries", summary="Daily conversation counts")
async def timeseries(days: int = Query(7, ge=1, le=90), _admin: dict = Depends(admin_only)):
    cutoff = datetime.utcnow() - timedelta(days=days)
    records = await ChatAnalytics.find(ChatAnalytics.createdAt >= cutoff).to_list()
    by_day = defaultdict(int)
    for r in records:
        by_day[r.createdAt.strftime("%Y-%m-%d")] += 1
    return [{"date": d, "count": c} for d, c in sorted(by_day.items())]
