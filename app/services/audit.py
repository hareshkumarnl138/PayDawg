"""Append-only audit event helpers."""
import json
from sqlalchemy.orm import Session
from app.db.models import Payment, PaymentEvent


def append_event(db: Session, payment: Payment, event_type: str, payload: dict | None = None) -> PaymentEvent:
    event = PaymentEvent(payment_id=payment.id, event_type=event_type, payload_json=json.dumps(payload or {}, separators=(",", ":")))
    db.add(event)
    return event
