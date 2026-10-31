"""Shipment booking for the customer API (routes/shipments.py): same-day Bengaluru rules, pricing, tracking-number allocation."""

from datetime import datetime, timedelta
from typing import Optional

from pymongo.errors import DuplicateKeyError

from models.customer import Customer
from models.shipment import ParcelDetails, Party, Shipment, generate_tracking_number
from services import geo, pricing
from services.shipments import ShipmentError


async def book(customer: Customer, recipient: Party, parcel: ParcelDetails, payment_method: str, *,
               sender: Optional[Party] = None, service_type: str = "same_day", created_by_role: str = "user",
               created_by_id: Optional[str] = None, note: str = "Shipment created") -> Shipment:
    """Validates, prices and inserts a shipment. Raises ShipmentError(422/500) with a customer-facing message."""
    sender = sender or Party(name=customer.name, phone=customer.phone, address=customer.address, location=customer.location)
    if recipient.location is None:
        raise ShipmentError(422, "Pick the delivery location on the map (Bengaluru only).")
    for party, what in ((sender, "pickup location"), (recipient, "delivery location")):
        problem = geo.outside_reason(party.location, what)
        if problem:
            raise ShipmentError(422, problem)
    if sender.location is None:
        raise ShipmentError(422, "Pick the pickup location on the map (Bengaluru only).")
    try:
        quote = pricing.estimate(sender.location, recipient.location, parcel.weightKg)
    except pricing.EstimateError as err:
        raise ShipmentError(422, str(err))

    shipment = Shipment(
        trackingNumber=generate_tracking_number(),
        customerId=customer.id,
        customerName=customer.name,
        sender=sender,
        recipient=recipient,
        parcel=parcel,
        serviceType=service_type,
        fare=quote["fare"],
        distanceKm=quote["distanceKm"],
        paymentMethod=payment_method,
        estimatedDelivery=datetime.utcnow() + timedelta(minutes=quote["etaMinutes"]),
    )
    shipment.record("CREATED", created_by_role, created_by_id or str(customer.id), note)

    for _ in range(6):  # 10 million possible IDs: collisions are rare but real at volume, and the unique index rejects them
        try:
            await shipment.insert()
            return shipment
        except DuplicateKeyError:
            shipment.trackingNumber = generate_tracking_number()
    raise ShipmentError(500, "Could not allocate a tracking number.")
