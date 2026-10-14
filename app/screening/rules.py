"""Deterministic risk rules, modelled on how real gateways screen payments.

Hard blocks (the LLM can never override these):
  * duplicate  - same customer + amount + order_ref inside a short window (a double-click or a
                 replayed request, like the duplicate-transaction window on card gateways).
                 A different order_ref means a new purchase, so repeat buying is fine.
  * velocity   - one customer making too many payments inside the velocity window.
Soft signals add to a 0-100 risk score (>= 40 means review, i.e. Growl):
  unusual_amount 50, merchant_surge 40, new_customer 20, odd_hour 20, and -20 for a customer
  who already has a captured payment (trusted repeat customer).
"""
import json
from datetime import datetime
from zoneinfo import ZoneInfo
from app.config import settings

WEIGHTS = {"unusual_amount": 50, "merchant_surge": 40, "new_customer": 20, "odd_hour": 20}
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
    average = float(notebook.get("average_amount", 0) or 0)
    maximum = float(notebook.get("max_amount", 0) or 0)
    if baseline_count and amount > max(average * settings.large_amount_multiple, maximum * 2, 0):
        flags.append("unusual_amount")
        reasons.append("Amount is far above this merchant's recorded payment baseline.")
    if merchant_velocity >= settings.merchant_surge_limit:
        flags.append("merchant_surge")
        reasons.append(f"Merchant surge: {merchant_velocity} payments from the whole shop in the last "
                       f"{settings.velocity_window_minutes} minutes (possible card-testing burst).")
    if not customer_seen and baseline_count:
        flags.append("new_customer")
        reasons.append("This customer has not appeared in the merchant's recent payment history.")
    active_hours = notebook.get("active_hours", "[9,10,11,12,13,14,15,16,17,18]")
    try:
        hours = json.loads(active_hours) if isinstance(active_hours, str) else active_hours
    except (ValueError, TypeError):
        hours = list(range(9, 19))
    if now.hour not in hours:
        flags.append("odd_hour")
        reasons.append(f"Payment arrived at {now.hour:02d}:00, outside the merchant's usual active hours.")
    hard_block = duplicate or velocity_breach
    score = sum(WEIGHTS.get(f, 0) for f in flags)
    if trusted and score:
        score = max(0, score - TRUSTED_DISCOUNT)
        reasons.append("Returning customer with a captured payment: risk score reduced.")
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
