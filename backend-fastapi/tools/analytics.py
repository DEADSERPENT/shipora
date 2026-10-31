"""Tool schema + executor for cross-cutting operational analytics — delivery-issue
counts by status/category, shipment pipeline, today's active vehicle/delivery activity. Bound
into general_agent (the catch-all specialist), since these queries span
multiple domains rather than belonging to one specialist.

Plain-Python aggregation over .find()/.find_all(), same demo-scale style
routes/analytics.py already uses and justifies — a $group pipeline would
only be worth it at much higher row counts."""

from collections import Counter
from datetime import datetime, timedelta

from models.delivery_issue import DeliveryIssue
from models.shipment import Shipment
from models.tracking_log import TrackingLog
from utils.dates import today_string

def format_ops_summary(d: dict) -> str:
    """The summary as plain sentences, written from the data, with each figure's own reporting period. Used whenever a model
    cannot be trusted to phrase it (it only promised, or is unavailable)."""
    if "shipments" not in d:
        return d.get("note", "Operations figures aren't available to this account.")
    s, c, v = d["shipments"], d["complaints"], d["todayVehicles"]
    by = ", ".join(f"{n} {k.replace('_', ' ').lower()}" for k, n in sorted(s["byStatus"].items())) or "none"
    iss = ", ".join(f"{n} {k.replace('_', ' ')}" for k, n in sorted(c["byStatus"].items())) or "none"
    res = f" Average resolution time is {c['avgResolutionHours']} hours." if c.get("avgResolutionHours") is not None else ""
    return (f"Operations summary. Shipments (all time): {s['total']} in total — {by}. "
            f"Delivery issues (last {d['windowDays']} days): {c['total']} — {iss}.{res} "
            f"Today: {v['activeVehicles']} of {v['totalVehiclesLogged']} vehicles active and {v['deliveredToday']} parcels delivered.")


TOOL_GET_OPERATIONS_SUMMARY = {
    "name": "get_operations_summary",
    "description": (
        "Get a cross-cutting summary of Shipora delivery operations: shipment counts by status, "
        "delivery-issue counts by status and category over a time window (default last 7 days, NOT "
        "just today), average issue resolution time, and today's active vehicle/delivery activity. "
        "When summarizing, report the shipment pipeline, the delivery-issue numbers AND the vehicle "
        "activity — do not omit any part. Use this for broad questions like 'summarize today's "
        "operations', 'what's today's performance', 'how many issues were solved', or "
        "'how many parcels were delivered today' — not for single-entity lookups (use the "
        "tracking/issue tools for those)."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "days": {"type": "integer", "description": "Window for delivery-issue stats, in days. Defaults to 7."},
        },
        "required": [],
    },
}


async def execute_get_operations_summary(days: int = 7, current_user: dict = None) -> dict:
    if (current_user or {}).get("role") != "admin":
        return {"note": "Company-wide operations figures are available to Operations accounts only."}
    cutoff = datetime.utcnow() - timedelta(days=days or 7)
    complaints = await DeliveryIssue.find(DeliveryIssue.createdAt >= cutoff).to_list()
    status_counts = Counter(c.status for c in complaints)
    category_counts = Counter(c.category for c in complaints)

    resolved = [c for c in complaints if c.status in ("resolved", "closed") and c.resolvedAt and c.createdAt]
    avg_resolution_hours = (
        round(sum((c.resolvedAt - c.createdAt).total_seconds() for c in resolved) / len(resolved) / 3600, 1)
        if resolved else None
    )

    today_logs = await TrackingLog.find(TrackingLog.date == today_string()).to_list()
    shipments = await Shipment.find_all().to_list()
    shipment_status_counts = Counter(s.status for s in shipments)
    active_vehicles = sum(1 for log in today_logs if log.isActive)
    areas_completed_today = sorted({area for log in today_logs for area in log.areasCompleted})

    window = days or 7
    return {
        "windowDays": window,
        "periodText": f"Delivery-issue figures cover the last {window} days.",
        "shipmentsPeriodText": "Shipment counts are all time (every shipment on record).",
        "vehiclesPeriodText": "Vehicle and delivery activity is for today.",
        "shipments": {"total": len(shipments), "byStatus": dict(shipment_status_counts)},
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
            "deliveredToday": sum(log.deliveredCount for log in today_logs),
        },
    }
