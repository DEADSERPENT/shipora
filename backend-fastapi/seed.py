"""Small, idempotent mock-data seed for the retrieval-tool demo (delivery
issues, vehicle tracking, shipments, analytics). Only needed when the app
falls back to mongomock_motor (an in-memory store that resets to empty on
every restart), which would otherwise make every retrieval query answer
"nothing found." No-ops immediately if any delivery agent already exists
(e.g. a real MongoDB/Atlas with real data is connected), so it can never
clobber real data."""

import logging
from datetime import datetime, timedelta

from auth_utils import hash_password
from models.admin import Admin
from models.customer import Customer, Location
from models.delivery_agent import DeliveryAgent
from models.delivery_issue import DeliveryIssue
from models.shipment import ParcelDetails, Party, Shipment, generate_tracking_number
from models.tracking_log import TrackingLog
from utils.dates import today_string
log = logging.getLogger("shipora.seed")


async def seed_mock_data() -> None:
    if await DeliveryAgent.find_one({}):
        return

    agents = [
        DeliveryAgent(name="Ravi Kumar", email="ravi.kumar@shipora.demo", password=hash_password("demo1234"),
                      phone="9880000001", vehicleNo="KA01AB1234", vehicleType="van", licenseNo="KA0120230001", assignedArea="Koramangala"),
        DeliveryAgent(name="Suresh Babu", email="suresh.babu@shipora.demo", password=hash_password("demo1234"),
                      phone="9880000002", vehicleNo="KA02CD5678", vehicleType="bike", licenseNo="KA0120230002", assignedArea="Indiranagar"),
    ]
    for a in agents:
        await a.insert()

    await Admin(name="Meera Nair", email="ops@shipora.demo", password=hash_password("demo1234"), organization="Shipora Operations").insert()

    customer = Customer(name="Anita Rao", email="anita.rao@shipora.demo", password=hash_password("demo1234"),
                        phone="9880000010", address="12, 4th Block, Koramangala, Bengaluru",
                        location=Location(lat=12.9352, lng=77.6245))
    await customer.insert()

    today = today_string()
    logs = [
        TrackingLog(driverId=agents[0].id, date=today, lat=12.9352, lng=77.6245, currentArea="Koramangala",
                    eta="15 mins", areasCompleted=["Koramangala 1st Block", "Koramangala 4th Block"], lastUpdated=datetime.utcnow(), isActive=True),
        TrackingLog(driverId=agents[1].id, date=today, lat=12.9719, lng=77.6412, currentArea="Indiranagar",
                    eta="30 mins", areasCompleted=["Indiranagar 100 Feet Road"], lastUpdated=datetime.utcnow(), isActive=True),
    ]
    for entry in logs:  # not `log`: that would shadow the module logger used at the end of this function
        await entry.insert()

    recipient = Party(name="Vijay Shankar", phone="9880000020", address="45, 100 Feet Road, Indiranagar, Bengaluru",
                      location=Location(lat=12.9719, lng=77.6412))
    sender = Party(name=customer.name, phone=customer.phone, address=customer.address, location=customer.location)
    # (status path to walk, assigned agent index, service type)
    seed_shipments = [
        (["CREATED"], None, "same_day"),
        (["CREATED", "PICKUP_SCHEDULED"], 0, "same_day"),
        (["CREATED", "PICKUP_SCHEDULED", "PICKED_UP", "IN_TRANSIT"], 0, "same_day"),
        (["CREATED", "PICKUP_SCHEDULED", "PICKED_UP", "IN_TRANSIT", "OUT_FOR_DELIVERY"], 1, "same_day"),
        (["CREATED", "PICKUP_SCHEDULED", "PICKED_UP", "IN_TRANSIT", "OUT_FOR_DELIVERY", "DELIVERED"], 1, "same_day"),
    ]
    shipments = []
    for path, agent_idx, service in seed_shipments:
        s = Shipment(
            trackingNumber=generate_tracking_number(), customerId=customer.id, customerName=customer.name,
            sender=sender, recipient=recipient,
            parcel=ParcelDetails(description="Demo parcel", category="electronics", weightKg=2.5, declaredValue=4500.0),
            serviceType=service, fare=96.0, distanceKm=4.4, paymentMethod="cash",
            assignedAgentId=agents[agent_idx].id if agent_idx is not None else None,
            estimatedDelivery=datetime.utcnow() + timedelta(hours=4),
        )
        for status in path:
            s.record(status, "admin", None, "seed")
        if path[-1] == "OUT_FOR_DELIVERY":
            s.deliveryAttempts = 1
        if path[-1] == "DELIVERED":
            s.deliveryAttempts = 1
            s.deliveredAt = datetime.utcnow()
        await s.insert()
        shipments.append(s)

    # createdAt/resolvedAt are set by DeliveryIssue's own before_event(Insert)
    # hook (always "now"), so backdate them afterwards via a raw update — gives
    # get_operations_summary's day-windowed counts and avgResolutionHours
    # something realistic to compute instead of everything landing on "today."
    seed_issues = [
        dict(subject="Parcel not delivered on time", category="delayed_delivery",
             description="My parcel was due yesterday and still shows out for delivery.",
             customerName="Anita Rao", customerEmail="anita.rao@shipora.demo",
             status="open", created_days_ago=1, shipment=3),
        dict(subject="Agent was very rude", category="agent_behaviour",
             description="The delivery agent spoke rudely when I asked about the delivery time.",
             customerName="Vijay Shankar", customerEmail="vijay.s@example.com",
             status="in_progress", created_days_ago=2),
        dict(subject="Box arrived crushed", category="damaged_parcel",
             description="The outer box was crushed and the contents were damaged on arrival.",
             customerName="Anita Rao", customerEmail="anita.rao@shipora.demo",
             status="resolved", created_days_ago=4, resolved_days_ago=3, shipment=4),
        dict(subject="Delivered to wrong address", category="wrong_address",
             description="Tracking says delivered but the parcel went to the neighbouring street.",
             customerName=None, customerEmail=None, isAnonymous=True,
             status="resolved", created_days_ago=6, resolved_days_ago=5),
        dict(subject="Parcel lost in transit", category="lost_parcel",
             description="No scan updates for over a week.",
             customerName="Farhan Sheikh", customerEmail="farhan.sheikh@example.com",
             status="closed", created_days_ago=8, resolved_days_ago=7),
    ]
    now = datetime.utcnow()
    for c in seed_issues:
        ship = shipments[c["shipment"]] if "shipment" in c else None
        issue = DeliveryIssue(
            subject=c["subject"], category=c["category"], description=c["description"],
            customerName=c.get("customerName"), customerEmail=c.get("customerEmail"),
            isAnonymous=c.get("isAnonymous", False), status=c["status"],
            shipmentId=ship.id if ship else None, trackingNumber=ship.trackingNumber if ship else None,
        )
        await issue.insert()
        created_at = now - timedelta(days=c["created_days_ago"])
        update = {"createdAt": created_at, "updatedAt": created_at}
        if "resolved_days_ago" in c:
            update["resolvedAt"] = now - timedelta(days=c["resolved_days_ago"])
        await issue.get_motor_collection().update_one({"_id": issue.id}, {"$set": update})

    log.info(f"Seeded {len(agents)} delivery agents, 1 customer, {len(shipments)} shipments, {len(logs)} tracking logs, {len(seed_issues)} delivery issues (mock demo data).")
