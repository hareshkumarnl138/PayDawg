"""Deterministic risk rules. Exact duplicates and velocity breaches are hard blocks."""
from datetime import datetime
from app.config import settings

def evaluate_rules(payment: dict, notebook: dict, recent_payments: list[dict]) -> dict:
    flags, reasons = [], []
    now = datetime.now().astimezone()
    amount = float(payment["amount"])
    customer = str(payment["customer_id"])
    merchant_id = payment["merchant_id"]
    window_seconds = settings.duplicate_window_minutes * 60
    velocity_seconds = settings.velocity_window_minutes * 60
    duplicate = False
    customer_seen = False
    velocity_count = 0
    for old in recent_payments:
        if old.get("merchant_id") != merchant_id:
            continue
        try:
            age = (now - datetime.fromisoformat(old["created_at"]).astimezone()).total_seconds()
        except (ValueError, TypeError):
            continue
        if age < 0:
            age = 0
        if old.get("customer_id") == customer:
            customer_seen = True
            if age <= window_seconds and float(old.get("amount", 0)) == amount:
                duplicate = True
        if age <= velocity_seconds:
            velocity_count += 1
    if duplicate:
        flags.append("exact_duplicate")
        reasons.append("Exact duplicate: same merchant, customer, and amount within the duplicate window.")
    if velocity_count >= settings.velocity_limit:
        flags.append("velocity_breach")
        reasons.append(f"Velocity breach: {velocity_count} recent payments already fall inside the {settings.velocity_window_minutes}-minute window.")
    baseline_count = int(notebook.get("payment_count", 0) or 0)
    average = float(notebook.get("average_amount", 0) or 0)
    maximum = float(notebook.get("max_amount", 0) or 0)
    if baseline_count and amount > max(average * settings.large_amount_multiple, maximum * 1.5, 0):
        flags.append("unusual_amount")
        reasons.append("Amount is well above this merchant's recorded payment baseline.")
    if not customer_seen and baseline_count:
        flags.append("new_customer")
        reasons.append("This customer has not appeared in the merchant's recent payment history.")
    active_hours = notebook.get("active_hours", "[9,10,11,12,13,14,15,16,17,18]")
    try:
        import json
        hours = json.loads(active_hours) if isinstance(active_hours, str) else active_hours
    except (ValueError, TypeError):
        hours = list(range(9, 19))
    if now.hour not in hours:
        flags.append("odd_hour")
        reasons.append(f"Payment arrived at {now.hour:02d}:00, outside the merchant's usual active hours.")
    hard_block = duplicate or velocity_count >= settings.velocity_limit
    if hard_block:
        level = "high"
    elif "unusual_amount" in flags or len(flags) >= 2:
        level = "medium"
    elif flags:
        level = "low"
    else:
        level = "low"
        reasons.append("No deterministic risk flags were found.")
    return {"risk_level": level, "flags": flags, "reasons": reasons, "hard_block": hard_block}

# Stable convenience alias for tests and callers.
screen_payment = evaluate_rules
