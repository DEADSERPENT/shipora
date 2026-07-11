from datetime import datetime
from typing import Iterable, Optional

from models.complaint import Complaint
from models.driver import Driver
from models.vehicle_log import VehicleLog


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
        "wasteType": doc.wasteType,
        "pickupSchedule": doc.pickupSchedule,
        "residentType": doc.residentType,
    }


def driver_payload(doc) -> dict:
    return {
        "id": str(doc.id),
        "role": doc.role,
        "name": doc.name,
        "email": doc.email,
        "vehicleNo": doc.vehicleNo,
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
        "wasteType": doc.wasteType,
        "pickupSchedule": doc.pickupSchedule,
        "residentType": doc.residentType,
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
        "licenseNo": doc.licenseNo,
        "assignedArea": doc.assignedArea,
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


def driver_subset(driver: Optional[Driver], fields: Iterable[str]) -> Optional[dict]:
    if driver is None:
        return None
    out = {"_id": str(driver.id)}
    for f in fields:
        out[f] = getattr(driver, f)
    return out


def vehicle_log_json(log: VehicleLog, driver: Optional[Driver] = None, driver_fields: Iterable[str] = ()) -> dict:
    return {
        "_id": str(log.id),
        "driverId": driver_subset(driver, driver_fields) if driver_fields else str(log.driverId),
        "date": log.date,
        "lat": log.lat,
        "lng": log.lng,
        "currentArea": log.currentArea,
        "eta": log.eta,
        "areasCompleted": log.areasCompleted,
        "lastUpdated": iso(log.lastUpdated),
        "isActive": log.isActive,
        "createdAt": iso(log.createdAt),
        "updatedAt": iso(log.updatedAt),
    }


def complaint_json(c: Complaint, mask_anonymous: bool = False) -> dict:
    resident_name = c.residentName
    resident_email = c.residentEmail
    if mask_anonymous and c.isAnonymous:
        resident_name = "Anonymous"
        resident_email = "—"
    return {
        "_id": str(c.id),
        "residentId": str(c.residentId) if c.residentId else None,
        "residentName": resident_name,
        "residentEmail": resident_email,
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


SUPPORT_DEFAULTS = {
    "phone": "1800-ECO-TRACK",
    "email": "support@ecotrack.in",
    "whatsapp": "+91 98765 43210",
    "officeAddress": "City Municipal Office, Ground Floor, Civic Center",
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
