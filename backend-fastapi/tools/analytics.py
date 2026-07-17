"""Tool schema + executor for cross-cutting operational analytics — complaint
counts by status/category, today's active vehicle/collection activity. Bound
into general_agent (the catch-all specialist), since these queries span
multiple domains rather than belonging to one specialist.

Plain-Python aggregation over .find()/.find_all(), same demo-scale style
routes/analytics.py already uses and justifies — a $group pipeline would
only be worth it at much higher row counts."""

from collections import Counter
from datetime import datetime, timedelta

from models.complaint import Complaint
from models.vehicle_log import VehicleLog
from utils.dates import today_string

TOOL_GET_OPERATIONS_SUMMARY = {
    "name": "get_operations_summary",
    "description": (
        "Get a cross-cutting summary of municipal waste operations: complaint counts by status "
        "and category over a time window (default last 7 days, NOT just today), average complaint "
        "resolution time, and today's active vehicle/collection activity. When summarizing, report "
        "BOTH the complaint numbers (total, by status, by category) AND the vehicle/collection "
        "activity — do not omit either half. Use this for broad questions like 'summarize today's "
        "operations', 'what's today's performance', 'how many complaints were solved', or "
        "'what's the collection efficiency today' — not for single-entity lookups (use the "
        "tracking/complaints tools for those)."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "days": {"type": "integer", "description": "Window for complaint stats, in days. Defaults to 7."},
        },
        "required": [],
    },
}


async def execute_get_operations_summary(days: int = 7) -> dict:
    cutoff = datetime.utcnow() - timedelta(days=days or 7)
    complaints = await Complaint.find(Complaint.createdAt >= cutoff).to_list()
    status_counts = Counter(c.status for c in complaints)
    category_counts = Counter(c.category for c in complaints)

    resolved = [c for c in complaints if c.status in ("resolved", "closed") and c.resolvedAt and c.createdAt]
    avg_resolution_hours = (
        round(sum((c.resolvedAt - c.createdAt).total_seconds() for c in resolved) / len(resolved) / 3600, 1)
        if resolved else None
    )

    today_logs = await VehicleLog.find(VehicleLog.date == today_string()).to_list()
    active_vehicles = sum(1 for log in today_logs if log.isActive)
    areas_completed_today = sorted({area for log in today_logs for area in log.areasCompleted})

    return {
        "windowDays": days or 7,
        "complaints": {
            "total": len(complaints),
            "byStatus": dict(status_counts),
            "byCategory": dict(category_counts),
            "avgResolutionHours": avg_resolution_hours,
        },
        "todayVehicles": {
            "activeVehicles": active_vehicles,
            "totalVehiclesLogged": len(today_logs),
            "areasCompleted": areas_completed_today,
        },
    }
