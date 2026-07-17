"""Small, idempotent mock-data seed for the retrieval-tool demo (complaints,
vehicle tracking, analytics). Only needed because this dev environment has no
real MongoDB — database.py falls back to mongomock_motor, an in-memory store
that resets to completely empty on every restart, which would otherwise make
every retrieval query answer "nothing found." No-ops immediately if any
driver already exists (e.g. a real MongoDB with real data is connected), so
it can never clobber real data.

Uses only existing models (Driver, VehicleLog, Complaint) — no new schema."""

from datetime import datetime, timedelta

from auth_utils import hash_password
from models.complaint import Complaint
from models.driver import Driver
from models.vehicle_log import VehicleLog
from utils.dates import today_string


async def seed_mock_data() -> None:
    if await Driver.find_one({}):
        return

    drivers = [
        Driver(name="Ravi Kumar", email="ravi.kumar@ecotrack.demo", password=hash_password("demo1234"),
               phone="9880000001", vehicleNo="KA01AB1234", licenseNo="KA0120230001", assignedArea="Koramangala"),
        Driver(name="Suresh Babu", email="suresh.babu@ecotrack.demo", password=hash_password("demo1234"),
               phone="9880000002", vehicleNo="KA02CD5678", licenseNo="KA0120230002", assignedArea="Indiranagar"),
    ]
    for d in drivers:
        await d.insert()

    today = today_string()
    logs = [
        VehicleLog(driverId=drivers[0].id, date=today, lat=12.9352, lng=77.6245, currentArea="Koramangala",
                   eta="15 mins", areasCompleted=["Koramangala 1st Block", "Koramangala 4th Block"], lastUpdated=datetime.utcnow(), isActive=True),
        VehicleLog(driverId=drivers[1].id, date=today, lat=12.9719, lng=77.6412, currentArea="Indiranagar",
                   eta="30 mins", areasCompleted=["Indiranagar 100 Feet Road"], lastUpdated=datetime.utcnow(), isActive=True),
    ]
    for log in logs:
        await log.insert()

    # createdAt/resolvedAt are set by Complaint's own before_event(Insert) hook
    # (always "now"), so backdate them afterwards via a raw update — needed to
    # give get_operations_summary's day-windowed counts and avgResolutionHours
    # something realistic to compute instead of everything landing on "today."
    seed_complaints = [
        dict(subject="Truck skipped our street", category="missed_pickup",
             description="The collection vehicle didn't come to 4th Block today.",
             residentName="Anita Rao", residentEmail="anita.rao@example.com",
             status="open", created_days_ago=1),
        dict(subject="Driver was very rude", category="driver_behaviour",
             description="Spoke rudely when asked about the pickup time.",
             residentName="Vijay Shankar", residentEmail="vijay.s@example.com",
             status="in_progress", created_days_ago=2),
        dict(subject="Bin left overflowing", category="cleanliness",
             description="Waste wasn't fully collected, bin overflowing since yesterday.",
             residentName="Anita Rao", residentEmail="anita.rao@example.com",
             status="resolved", created_days_ago=4, resolved_days_ago=3),
        dict(subject="Wrong pickup time", category="timing",
             description="Truck now comes an hour later than the listed schedule.",
             residentName=None, residentEmail=None, isAnonymous=True,
             status="resolved", created_days_ago=6, resolved_days_ago=5),
        dict(subject="Vehicle leaking waste on the road", category="vehicle_issue",
             description="The collection truck is leaking liquid waste along the street.",
             residentName="Farhan Sheikh", residentEmail="farhan.sheikh@example.com",
             status="closed", created_days_ago=8, resolved_days_ago=7),
    ]
    now = datetime.utcnow()
    for c in seed_complaints:
        complaint = Complaint(
            subject=c["subject"], category=c["category"], description=c["description"],
            residentName=c.get("residentName"), residentEmail=c.get("residentEmail"),
            isAnonymous=c.get("isAnonymous", False), status=c["status"],
        )
        await complaint.insert()
        created_at = now - timedelta(days=c["created_days_ago"])
        update = {"createdAt": created_at, "updatedAt": created_at}
        if "resolved_days_ago" in c:
            update["resolvedAt"] = now - timedelta(days=c["resolved_days_ago"])
        await complaint.get_motor_collection().update_one({"_id": complaint.id}, {"$set": update})

    print(f"Seeded {len(drivers)} drivers, {len(logs)} vehicle logs, {len(seed_complaints)} complaints (mock demo data).")
