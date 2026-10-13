"""Merchant baseline helpers. Only approved/captured payments contribute."""
import json
from datetime import datetime, timezone
from sqlalchemy import select, func
from sqlalchemy.orm import Session
from app.db.models import MerchantBaseline, Payment


def get_baseline(db: Session, merchant_id: str) -> dict:
    record = db.get(MerchantBaseline, merchant_id)
    if not record:
        return {"merchant_id": merchant_id, "avg_amount": 0.0, "max_amount": 0.0, "common_currency": "USD", "active_hours": [], "payment_count": 0}
    return {"merchant_id": record.merchant_id, "avg_amount": record.avg_amount, "max_amount": record.max_amount, "common_currency": record.common_currency, "active_hours": json.loads(record.active_hours_json or "[]"), "payment_count": record.payment_count}


def update_baseline(db: Session, payment: Payment) -> MerchantBaseline:
    """Update baseline after a verified successful capture/approved outcome only."""
    baseline = db.get(MerchantBaseline, payment.merchant_id)
    if baseline is None:
        baseline = MerchantBaseline(merchant_id=payment.merchant_id, avg_amount=0.0, max_amount=0.0, common_currency=payment.currency, active_hours_json="[]", payment_count=0)
        db.add(baseline)
        db.flush()
    count = baseline.payment_count
    baseline.avg_amount = ((baseline.avg_amount * count) + payment.amount) / (count + 1)
    baseline.max_amount = max(baseline.max_amount, payment.amount)
    baseline.common_currency = payment.currency if count == 0 else baseline.common_currency
    active = set(json.loads(baseline.active_hours_json or "[]"))
    created = payment.created_at
    if created and created.tzinfo:
        created = created.astimezone(timezone.utc)
    active.add((created or datetime.now(timezone.utc)).hour)
    baseline.active_hours_json = json.dumps(sorted(active))
    baseline.payment_count = count + 1
    baseline.updated_at = datetime.now(timezone.utc)
    db.add(baseline)
    return baseline
