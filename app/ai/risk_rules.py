"""Deterministic, explainable fraud signals. Thresholds are demo settings, not production rules."""
from datetime import datetime, timedelta, timezone
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.config import get_settings
from app.db.models import MerchantBaseline, Payment
from app.ai.schemas import PaymentRequest


def evaluate_rules(db: Session, request: PaymentRequest, *, now: datetime | None = None) -> tuple[dict[str, bool], list[str]]:
    settings = get_settings()
    now = now or datetime.now(timezone.utc)
    amount = float(request.amount)
    flags = {"duplicate": False, "velocity_breach": False, "amount_outlier": False, "new_customer": False, "odd_hour": False}
    reasons: list[str] = []

    duplicate_cutoff = now - timedelta(seconds=settings.duplicate_window_seconds)
    duplicate = db.scalar(select(Payment.id).where(
        Payment.merchant_id == request.merchant_id,
        Payment.customer_ref == request.customer_ref,
        Payment.amount == amount,
        Payment.currency == request.currency,
        Payment.created_at >= duplicate_cutoff,
        Payment.status.notin_(["blocked", "failed"]),
    ).limit(1))
    if duplicate:
        flags["duplicate"] = True
        reasons.append("Same customer and amount were submitted recently for this merchant")

    velocity_cutoff = now - timedelta(seconds=settings.velocity_window_seconds)
    velocity_count = db.scalar(select(Payment.id).where(
        Payment.merchant_id == request.merchant_id,
        Payment.customer_ref == request.customer_ref,
        Payment.created_at >= velocity_cutoff,
        Payment.status.notin_(["blocked", "failed"]),
    ).limit(settings.velocity_max_payments))
    # Count explicitly; an existing request is never inferred from a mere limit query.
    from sqlalchemy import func
    count = db.scalar(select(func.count()).select_from(Payment).where(
        Payment.merchant_id == request.merchant_id,
        Payment.customer_ref == request.customer_ref,
        Payment.created_at >= velocity_cutoff,
        Payment.status.notin_(["blocked", "failed"]),
    )) or 0
    if count >= settings.velocity_max_payments:
        flags["velocity_breach"] = True
        reasons.append("This customer has made too many payment attempts in a short time")

    baseline = db.get(MerchantBaseline, request.merchant_id)
    if baseline and baseline.payment_count >= settings.min_baseline_samples and baseline.avg_amount > 0:
        if amount > baseline.avg_amount * settings.amount_outlier_multiplier:
            flags["amount_outlier"] = True
            reasons.append(f"Amount is more than {settings.amount_outlier_multiplier:g}x this merchant's average payment")
        if request.currency != baseline.common_currency:
            reasons.append(f"Currency differs from this merchant's usual currency ({baseline.common_currency})")
    else:
        reasons.append("Insufficient merchant history; using conservative screening defaults")

    prior_customer = db.scalar(select(Payment.id).where(
        Payment.merchant_id == request.merchant_id,
        Payment.customer_ref == request.customer_ref,
        Payment.status.in_(["approved", "captured"]),
    ).limit(1))
    flags["new_customer"] = prior_customer is None
    if flags["new_customer"]:
        reasons.append("No previously approved payment was found for this customer")

    # Time-of-day is a low-confidence signal; do not auto-block solely on it.
    active_hours = []
    if baseline:
        try:
            import json
            active_hours = json.loads(baseline.active_hours_json)
        except (ValueError, TypeError):
            active_hours = []
    if active_hours and now.hour not in active_hours:
        flags["odd_hour"] = True
        reasons.append("Payment arrived outside this merchant's usual active hours")
    return flags, reasons
