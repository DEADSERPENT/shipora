from datetime import datetime
from typing import Iterable, Optional

from models.delivery_agent import DeliveryAgent
from models.delivery_issue import DeliveryIssue
from models.shipment import Shipment
from models.tracking_log import TrackingLog


def iso(dt: Optional[datetime]) -> Optional[str]:
    if dt is None:
        return None
    return dt.isoformat(timespec="milliseconds") + "Z"


def user_payload(doc) -> dict:
    return {
        "id": str(doc.id),
        "role": doc.role,
        "name": doc.name,
        "email": doc.email,
        "location": {"lat": doc.location.lat, "lng": doc.location.lng},
        "address": doc.address,
        "customerType": doc.customerType,
    }


def driver_payload(doc) -> dict:
    return {
        "id": str(doc.id),
        "role": doc.role,
        "name": doc.name,
        "email": doc.email,
        "vehicleNo": doc.vehicleNo,
        "vehicleType": doc.vehicleType,
        "assignedArea": doc.assignedArea,
    }


def admin_payload(doc) -> dict:
    return {
        "id": str(doc.id),
        "role": doc.role,
        "name": doc.name,
        "email": doc.email,
        "organization": doc.organization,
    }


def user_profile_json(doc) -> dict:
    return {
        "_id": str(doc.id),
        "name": doc.name,
        "email": doc.email,
        "phone": doc.phone,
        "address": doc.address,
        "location": {"lat": doc.location.lat, "lng": doc.location.lng},
        "customerType": doc.customerType,
        "deliveryInstructions": doc.deliveryInstructions,
        "role": doc.role,
        "createdAt": iso(doc.createdAt),
        "updatedAt": iso(doc.updatedAt),
    }


def driver_profile_json(doc) -> dict:
    return {
        "_id": str(doc.id),
        "name": doc.name,
        "email": doc.email,
        "phone": doc.phone,
        "vehicleNo": doc.vehicleNo,
        "vehicleType": doc.vehicleType,
        "licenseNo": doc.licenseNo,
        "assignedArea": doc.assignedArea,
        "availability": doc.availability,
        "role": doc.role,
        "createdAt": iso(doc.createdAt),
        "updatedAt": iso(doc.updatedAt),
    }


def admin_profile_json(doc) -> dict:
    return {
        "_id": str(doc.id),
        "name": doc.name,
        "email": doc.email,
        "organization": doc.organization,
        "role": doc.role,
        "createdAt": iso(doc.createdAt),
        "updatedAt": iso(doc.updatedAt),
    }


def driver_subset(driver: Optional[DeliveryAgent], fields: Iterable[str]) -> Optional[dict]:
    if driver is None:
        return None
    out = {"_id": str(driver.id)}
    for f in fields:
        out[f] = getattr(driver, f)
    return out


def vehicle_log_json(log: TrackingLog, driver: Optional[DeliveryAgent] = None, driver_fields: Iterable[str] = ()) -> dict:
    return {
        "_id": str(log.id),
        "driverId": driver_subset(driver, driver_fields) if driver_fields else str(log.driverId),
        "date": log.date,
        "lat": log.lat,
        "lng": log.lng,
        "currentArea": log.currentArea,
        "eta": log.eta,
        "areasCompleted": log.areasCompleted,
        "activeShipmentIds": log.activeShipmentIds,
        "deliveredCount": log.deliveredCount,
        "lastUpdated": iso(log.lastUpdated),
        "isActive": log.isActive,
        "createdAt": iso(log.createdAt),
        "updatedAt": iso(log.updatedAt),
    }


def delivery_issue_json(c: DeliveryIssue, mask_anonymous: bool = False) -> dict:
    customer_name = c.customerName
    customer_email = c.customerEmail
    if mask_anonymous and c.isAnonymous:
        customer_name = "Anonymous"
        customer_email = "—"
    return {
        "_id": str(c.id),
        "customerId": str(c.customerId) if c.customerId else None,
        "customerName": customer_name,
        "customerEmail": customer_email,
        "shipmentId": str(c.shipmentId) if c.shipmentId else None,
        "trackingNumber": c.trackingNumber,
        "isAnonymous": c.isAnonymous,
        "subject": c.subject,
        "category": c.category,
        "description": c.description,
        "status": c.status,
        "adminReply": c.adminReply,
        "resolvedAt": iso(c.resolvedAt),
        "createdAt": iso(c.createdAt),
        "updatedAt": iso(c.updatedAt),
    }


def _party_json(p) -> dict:
    return {
        "name": p.name,
        "phone": p.phone,
        "address": p.address,
        "location": {"lat": p.location.lat, "lng": p.location.lng} if p.location else None,
    }


def shipment_json(s: Shipment, agent: Optional[DeliveryAgent] = None) -> dict:
    return {
        "_id": str(s.id),
        "trackingNumber": s.trackingNumber,
        "customerId": str(s.customerId),
        "customerName": s.customerName,
        "sender": _party_json(s.sender),
        "recipient": _party_json(s.recipient),
        "parcel": s.parcel.model_dump(),
        "serviceType": s.serviceType,
        "fare": s.fare,
        "distanceKm": s.distanceKm,
        "paymentMethod": s.paymentMethod,
        "status": s.status,
        "statusHistory": [
            {"status": e.status, "at": iso(e.at), "byRole": e.byRole, "byId": e.byId, "note": e.note}
            for e in s.statusHistory
        ],
        "assignedAgentId": str(s.assignedAgentId) if s.assignedAgentId else None,
        "assignedAgent": (
            {"_id": str(agent.id), "name": agent.name, "phone": agent.phone, "vehicleNo": agent.vehicleNo, "vehicleType": agent.vehicleType}
            if agent else None
        ),
        "pickupScheduledAt": iso(s.pickupScheduledAt),
        "estimatedDelivery": iso(s.estimatedDelivery),
        "deliveredAt": iso(s.deliveredAt),
        "deliveryAttempts": s.deliveryAttempts,
        "createdAt": iso(s.createdAt),
        "updatedAt": iso(s.updatedAt),
    }


def shipment_public_json(s: Shipment) -> dict:
    """Public tracking view: status + timeline (status and time only) — no names,
    phones, addresses, notes or agent details."""
    return {
        "trackingNumber": s.trackingNumber,
        "status": s.status,
        "serviceType": s.serviceType,
        "estimatedDelivery": iso(s.estimatedDelivery),
        "deliveredAt": iso(s.deliveredAt),
        "timeline": [{"status": e.status, "at": iso(e.at)} for e in s.statusHistory],  # no notes: they can name the agent / customer
    }


SUPPORT_DEFAULTS = {
    "phone": "1800-SHIPORA",
    "email": "support@shipora.in",
    "whatsapp": "+91 98765 43210",
    "officeAddress": "Shipora Customer Care, Operations Hub",
    "officeHours": "Mon – Fri · 9 AM – 5 PM",
}


def support_config_json(doc) -> dict:
    if doc is None:
        return dict(SUPPORT_DEFAULTS)
    return {
        "phone": doc.phone,
        "email": doc.email,
        "whatsapp": doc.whatsapp,
        "officeAddress": doc.officeAddress,
        "officeHours": doc.officeHours,
    }
