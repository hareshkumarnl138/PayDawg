"""Dawg's Notebook: what PayDawg learns about each shop, from captured payments only.

Three things are learned, so the rules judge a payment against THIS shop's normal instead of fixed demo numbers:
  * basket size  - average and biggest captured payment (the "unusual amount" rule)
  * usual hours  - when the shop's captured payments arrive (the "odd hour" rule)
  * pace         - the shop's busiest normal 10 minutes (the "shop-wide surge" rule)

Only money that was really captured teaches the Notebook, so blocked, held or abandoned payments cannot
shift what "normal" means. A brand-new shop has learned nothing yet: it is judged by the configured
surge level (MERCHANT_SURGE_LIMIT), and Dawg only starts calling an hour odd once he has seen HOURS_NEED captured
payments (then against the default 09:00-18:59 plus every hour the shop has proven busy in).
"""
import json
import math
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from app.config import settings

DEFAULT_ACTIVE_HOURS = list(range(9, 19))
HOUR_MIN_COUNT = 3        # an hour becomes "usual" once it has this many captured payments...
HOUR_MIN_SHARE = 0.02     # ...and at least this share of all captured payments
HOURS_NEED = 20           # captured payments Dawg needs before he judges the hour of a payment at all
PACE_MULTIPLE = 2         # a surge is this many times the shop's busiest normal window
PACE_DECAY = 0.995        # per window: an old busy spell fades to about half within a day


def to_local(moment: datetime) -> datetime:
    """A timestamp in the merchant's timezone (MERCHANT_TIMEZONE), else the server's local time."""
    if settings.merchant_timezone:
        return moment.astimezone(ZoneInfo(settings.merchant_timezone))
    return moment.astimezone()


def parse_time(value) -> datetime | None:
    try:
        moment = datetime.fromisoformat(value) if isinstance(value, str) else value
    except (TypeError, ValueError):
        return None
    if not isinstance(moment, datetime):
        return None
    return moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)


def window_seconds() -> int:
    return max(1, settings.velocity_window_minutes) * 60


def window_id(moment: datetime) -> int:
    """Which fixed window (VELOCITY_WINDOW_MINUTES long) a moment falls in; consecutive windows differ by 1."""
    return int(moment.timestamp() // window_seconds())


def hour_counts(notebook: dict) -> list[int]:
    raw = notebook.get("hour_counts")
    try:
        counts = json.loads(raw) if isinstance(raw, str) else raw
    except (TypeError, ValueError):
        counts = None
    if not isinstance(counts, list) or len(counts) != 24:
        return [0] * 24
    return [int(c) if isinstance(c, (int, float)) and c > 0 else 0 for c in counts]


def configured_hours(notebook: dict) -> set[int]:
    raw = notebook.get("active_hours", DEFAULT_ACTIVE_HOURS)
    try:
        hours = json.loads(raw) if isinstance(raw, str) else raw
        return {int(h) for h in hours if 0 <= int(h) <= 23}
    except (TypeError, ValueError):
        return set(DEFAULT_ACTIVE_HOURS)


def learned_hours(notebook: dict) -> set[int]:
    counts = hour_counts(notebook)
    total = sum(counts)
    if not total:
        return set()
    return {h for h, c in enumerate(counts) if c >= HOUR_MIN_COUNT and c >= HOUR_MIN_SHARE * total}


def judges_hours(notebook: dict) -> bool:
    """Has Dawg seen enough sales to call an hour odd for THIS shop? A brand-new online shop has no "usual hours"
    yet, and flagging everything outside 09:00-18:59 held perfectly normal evening orders from new customers."""
    return int(notebook.get("payment_count", 0) or 0) >= HOURS_NEED


def usual_hours(notebook: dict) -> set[int]:
    """The configured hours plus every hour the shop has proven busy in. Learning only ever adds hours."""
    return configured_hours(notebook) | learned_hours(notebook)


def learned_peak(notebook: dict, now: datetime) -> float:
    """The shop's busiest normal window so far, faded with time. The window in progress never counts,
    so a burst cannot raise its own bar while it is happening."""
    peak = float(notebook.get("pace_peak") or 0)
    window = int(notebook.get("pace_window") or 0)
    count = int(notebook.get("pace_count") or 0)
    current = window_id(now)
    if not window:
        return 0.0
    if current > window:
        return max(peak, count) * PACE_DECAY ** (current - window)
    return peak


def surge_limit(notebook: dict, now: datetime) -> int:
    """Shop-wide payments in one window that count as a surge: twice the learned busiest window,
    and never below MERCHANT_SURGE_LIMIT (all a brand-new shop has to go on)."""
    return max(settings.merchant_surge_limit, math.ceil(PACE_MULTIPLE * learned_peak(notebook, now)))


def unusual_above(notebook: dict) -> float | None:
    """Amounts above this are unusual for the shop; None until it has captured anything."""
    if not int(notebook.get("payment_count", 0) or 0):
        return None
    average = float(notebook.get("average_amount", 0) or 0)
    maximum = float(notebook.get("max_amount", 0) or 0)
    return max(average * settings.large_amount_multiple, maximum * 2, 0)


def learn(notebook: dict, amount: float, created_at, captured_at: datetime, teach_pace: bool) -> dict:
    """The Notebook after one captured payment. Pure: returns the new column values.

    Hours come from when the customer paid (created_at). Pace counts captures in the window they happen;
    callers pass teach_pace=False for a payment that was part of a surge or approved long after it arrived
    (a merchant clearing a backlog of held payments is not the shop's normal pace).
    """
    count = int(notebook.get("payment_count", 0) or 0)
    average = float(notebook.get("average_amount", 0) or 0)
    maximum = float(notebook.get("max_amount", 0) or 0)
    hours = hour_counts(notebook)
    paid_at = parse_time(created_at) or captured_at
    hours[to_local(paid_at).hour] += 1
    peak = float(notebook.get("pace_peak") or 0)
    window = int(notebook.get("pace_window") or 0)
    in_window = int(notebook.get("pace_count") or 0)
    if teach_pace:
        current = window_id(captured_at)
        if not window:
            window, in_window = current, 1
        elif current > window:
            peak = max(peak, in_window) * PACE_DECAY ** (current - window)
            window, in_window = current, 1
        else:
            in_window += 1
    return {"payment_count": count + 1, "average_amount": ((average * count) + amount) / (count + 1),
            "max_amount": max(maximum, amount), "hour_counts": json.dumps(hours),
            "pace_peak": peak, "pace_window": window, "pace_count": in_window}


def hours_text(hours) -> str:
    """[7, 8, 9, 22, 23, 0] -> '22:00-09:59' style ranges, joined by commas."""
    hours = sorted(set(hours))
    if not hours:
        return "none yet"
    if len(hours) == 24:
        return "all day"
    runs, start, prev = [], hours[0], hours[0]
    for h in hours[1:]:
        if h != prev + 1:
            runs.append([start, prev])
            start = h
        prev = h
    runs.append([start, prev])
    if len(runs) > 1 and runs[0][0] == 0 and runs[-1][1] == 23:  # a run that crosses midnight
        runs[0][0] = runs[-1][0]
        runs.pop()
    return ", ".join(f"{a:02d}:00-{b:02d}:59" for a, b in runs)


def summary(notebook: dict, now: datetime, recent_count: int) -> dict:
    """What the dashboard shows: the learned values and the limits the rules will apply right now."""
    hours = usual_hours(notebook)
    simulated = int(notebook.get("seeded_payments", 0) or 0)
    count = int(notebook.get("payment_count", 0) or 0)
    return {
        "merchant_id": notebook.get("merchant_id"),
        "learned_from": count,
        "simulated_history": simulated,
        "live_learned": max(0, count - simulated),
        "usual_basket": round(float(notebook.get("average_amount", 0) or 0), 2) if count else None,
        "biggest": round(float(notebook.get("max_amount", 0) or 0), 2) if count else None,
        "unusual_above": round(unusual_above(notebook), 2) if count else None,
        "usual_hours": sorted(hours),
        "usual_hours_text": hours_text(hours),
        "learned_hours": sorted(learned_hours(notebook)),
        "added_hours": sorted(learned_hours(notebook) - configured_hours(notebook)),
        "now_hour": now.hour,
        "hours_judged": judges_hours(notebook),
        "hours_need": HOURS_NEED,
        "busiest_window": round(learned_peak(notebook, now), 1),
        "surge_above": surge_limit(notebook, now),
        "surge_floor": settings.merchant_surge_limit,
        "window_minutes": settings.velocity_window_minutes,
        "recent_count": recent_count,
    }


def ai_baseline(notebook: dict) -> dict:
    """The few learned numbers an AI model needs; internal bookkeeping stays out of prompts."""
    return {k: notebook.get(k) for k in ("payment_count", "average_amount", "max_amount")}


def demo_history(now: datetime) -> dict:
    """SIMULATED: a Notebook for a pet shop that has traded for about two weeks. Mock mode only.

    600 captured payments averaging about $32, the biggest $164, busiest 10 minutes 60 payments,
    selling mostly 07:00-22:59 merchant time. It lets the live simulator start from a shop with a past
    instead of a brand-new one. No payment rows are created; the dashboard labels it as simulated.
    """
    curve = [2, 1, 0, 0, 0, 1, 3, 13, 22, 30, 34, 40, 48, 46, 38, 34, 34, 38, 44, 50, 52, 40, 24, 6]
    return {"payment_count": 600, "average_amount": 31.8, "max_amount": 164.0, "hour_counts": json.dumps(curve),
            "pace_peak": 60.0, "pace_window": window_id(now) - 1, "pace_count": 0, "seeded_payments": 600}
