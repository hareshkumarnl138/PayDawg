"""Deterministic risk rules, modelled on how real gateways screen payments.

Hard blocks (the LLM can never override these):
  * duplicate  - same customer + amount + order_ref inside a short window (a double-click or a
                 replayed request, like the duplicate-transaction window on card gateways).
                 A different order_ref means a new purchase, so repeat buying is fine.
  * velocity   - one customer making too many payments inside the velocity window.
Soft signals add to a 0-100 risk score (>= 40 means review, i.e. Growl):
  unusual_amount 50, large_order 50 (above HARD_REVIEW_AMOUNT, never discounted), merchant_surge 40,
  new_customer 20, odd_hour 20, and -20 for a customer
  who already has a captured payment (trusted repeat customer).

"Unusual", "odd hour" and "surge" are judged against what Dawg's Notebook has learned about this shop
(app/notebook.py), so a busy evening shop is not treated like a quiet 9-to-6 one.
"""
from datetime import datetime
from zoneinfo import ZoneInfo
from app.config import settings
from app.notebook import surge_limit, unusual_above, usual_hours

WEIGHTS = {"unusual_amount": 50, "merchant_surge": 40, "new_customer": 20, "odd_hour": 20, "large_order": 50}
TRUSTED_DISCOUNT = 20
REVIEW_THRESHOLD = 40


def _now() -> datetime:
    """Current time in the merchant's timezone (MERCHANT_TIMEZONE), else the server's local time."""
    if settings.merchant_timezone:
        return datetime.now(ZoneInfo(settings.merchant_timezone))
    return datetime.now().astimezone()


def evaluate_rules(payment: dict, notebook: dict, recent_payments: list[dict]) -> dict:
    flags, reasons = [], []
    now = _now()
    amount = float(payment["amount"])
    customer = str(payment["customer_id"])
    merchant_id = payment["merchant_id"]
    order_ref = (payment.get("order_ref") or "").strip()
    window_seconds = settings.duplicate_window_seconds
    velocity_seconds = settings.velocity_window_minutes * 60
    duplicate = False
    customer_seen = False
    trusted = False
    customer_velocity = 0
    merchant_velocity = 0
    for old in recent_payments:
        if old.get("merchant_id") != merchant_id:
            continue
        try:
            age = (now - datetime.fromisoformat(old["created_at"]).astimezone()).total_seconds()
        except (ValueError, TypeError):
            continue
        if age < 0:
            age = 0
        status = old.get("status")
        same_customer = old.get("customer_id") == customer
        if same_customer:
            customer_seen = True
            if status == "captured":
                trusted = True
            same_order = (old.get("order_ref") or "").strip() == order_ref
            if age <= window_seconds and same_order and status not in ("blocked", "failed") and float(old.get("amount", 0)) == amount:
                duplicate = True
        if age <= velocity_seconds:
            merchant_velocity += 1
            if same_customer:
                customer_velocity += 1
    velocity_breach = customer_velocity >= settings.velocity_limit
    if duplicate:
        flags.append("exact_duplicate")
        reasons.append(f"Exact duplicate: same customer, amount, and order reference within {window_seconds} seconds. "
                       "A repeat purchase should carry a new order reference.")
    if velocity_breach:
        flags.append("velocity_breach")
        reasons.append(f"Velocity breach: this customer already made {customer_velocity} payments in the last "
                       f"{settings.velocity_window_minutes} minutes.")
    baseline_count = int(notebook.get("payment_count", 0) or 0)
    unusual_limit = unusual_above(notebook)
    if unusual_limit is not None and amount > unusual_limit:
        flags.append("unusual_amount")
        reasons.append("Amount is far above this merchant's recorded payment baseline.")
    ceiling = settings.hard_review_amount
    if ceiling > 0 and amount > ceiling:
        flags.append("large_order")
        reasons.append(f"Single payment above the shop's review ceiling of {ceiling:,.2f}: held for the shop to confirm.")
    surge_at = surge_limit(notebook, now)
    if merchant_velocity >= surge_at:
        flags.append("merchant_surge")
        reasons.append(f"Merchant surge: {merchant_velocity} payments from the whole shop in the last "
                       f"{settings.velocity_window_minutes} minutes, at or above this shop's alert level of {surge_at} "
                       "(possible card-testing burst).")
    if not customer_seen and baseline_count:
        flags.append("new_customer")
        reasons.append("This customer has not appeared in the merchant's recent payment history.")
    if now.hour not in usual_hours(notebook):
        flags.append("odd_hour")
        reasons.append(f"Payment arrived at {now.hour:02d}:00, outside the merchant's usual active hours.")
    hard_block = duplicate or velocity_breach
    score = sum(WEIGHTS.get(f, 0) for f in flags)
    if trusted and score:
        score = max(0, score - TRUSTED_DISCOUNT)
        reasons.append("Returning customer with a captured payment: risk score reduced.")
    if "large_order" in flags and not hard_block:
        score = max(score, REVIEW_THRESHOLD)   # a returning-customer discount can never wave a huge payment through
    if hard_block:
        score = 100
        level = "high"
    elif score >= REVIEW_THRESHOLD:
        level = "medium"
    else:
        level = "low"
        if not flags:
            reasons.append("No deterministic risk flags were found.")
    return {"risk_level": level, "risk_score": score, "flags": flags, "reasons": reasons, "hard_block": hard_block}

# Stable convenience alias for tests and callers.
screen_payment = evaluate_rules
