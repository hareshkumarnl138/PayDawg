"""SQLite persistence. Events are append-only by application convention."""
import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from app.config import settings
from app.models import utc_now
from app import notebook as nb

def connect():
    conn = sqlite3.connect(settings.database_path, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn

@contextmanager
def db_session():
    conn = connect()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

NOTEBOOK_LEARNING_COLUMNS = {
    "hour_counts": "TEXT NOT NULL DEFAULT '[]'",
    "pace_peak": "REAL NOT NULL DEFAULT 0",
    "pace_window": "INTEGER NOT NULL DEFAULT 0",
    "pace_count": "INTEGER NOT NULL DEFAULT 0",
    "seeded_payments": "INTEGER NOT NULL DEFAULT 0",
}
NOTEBOOK_RESET = ("payment_count=0, average_amount=0, max_amount=0, hour_counts='[]', pace_peak=0, "
                  "pace_window=0, pace_count=0, seeded_payments=0")


def init_db():
    if settings.database_path != ":memory:":
        Path(settings.database_path).expanduser().resolve().parent.mkdir(parents=True, exist_ok=True)
    with db_session() as db:
        # Preserve any database from the earlier starter schema instead of silently discarding it.
        existing = db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='payments'").fetchone()
        if existing:
            columns = {row["name"] for row in db.execute("PRAGMA table_info(payments)").fetchall()}
            if "request_hash" not in columns or "customer_id" not in columns:
                from datetime import datetime, timezone
                suffix = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
                db.execute("ALTER TABLE payments RENAME TO payments_legacy_" + suffix)
        db.executescript("""
        CREATE TABLE IF NOT EXISTS merchants (
            id TEXT PRIMARY KEY, name TEXT NOT NULL, created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS notebook (
            merchant_id TEXT PRIMARY KEY REFERENCES merchants(id),
            payment_count INTEGER NOT NULL DEFAULT 0,
            average_amount REAL NOT NULL DEFAULT 0,
            max_amount REAL NOT NULL DEFAULT 0,
            active_hours TEXT NOT NULL DEFAULT '[9,10,11,12,13,14,15,16,17,18]',
            updated_at TEXT NOT NULL,
            hour_counts TEXT NOT NULL DEFAULT '[]', pace_peak REAL NOT NULL DEFAULT 0,
            pace_window INTEGER NOT NULL DEFAULT 0, pace_count INTEGER NOT NULL DEFAULT 0,
            seeded_payments INTEGER NOT NULL DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS payments (
            id TEXT PRIMARY KEY, merchant_id TEXT NOT NULL REFERENCES merchants(id),
            idempotency_key TEXT, request_hash TEXT NOT NULL, amount REAL NOT NULL,
            currency TEXT NOT NULL, customer_id TEXT NOT NULL, description TEXT NOT NULL, order_ref TEXT,
            verdict TEXT NOT NULL, risk_level TEXT NOT NULL, reasons_json TEXT NOT NULL,
            flags_json TEXT NOT NULL, decision_source TEXT NOT NULL, status TEXT NOT NULL,
            rail TEXT NOT NULL, provider_order_id TEXT, provider_authorization_id TEXT, provider_capture_id TEXT,
            approval_url TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
            UNIQUE(merchant_id, idempotency_key)
        );
        CREATE INDEX IF NOT EXISTS idx_payments_created ON payments(created_at);
        CREATE INDEX IF NOT EXISTS idx_payments_customer ON payments(merchant_id, customer_id, created_at);
        CREATE TABLE IF NOT EXISTS events (
            id INTEGER PRIMARY KEY AUTOINCREMENT, payment_id TEXT NOT NULL REFERENCES payments(id),
            event_type TEXT NOT NULL, from_status TEXT, to_status TEXT,
            payload_json TEXT NOT NULL DEFAULT '{}', created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS webhook_events (
            event_id TEXT PRIMARY KEY, received_at TEXT NOT NULL
        );
        """)
        if "order_ref" not in {r["name"] for r in db.execute("PRAGMA table_info(payments)").fetchall()}:
            db.execute("ALTER TABLE payments ADD COLUMN order_ref TEXT")
        # Notebook columns added when it learned usual hours and pace; older databases get them here.
        notebook_cols = {r["name"] for r in db.execute("PRAGMA table_info(notebook)").fetchall()}
        for column, ddl in NOTEBOOK_LEARNING_COLUMNS.items():
            if column not in notebook_cols:
                db.execute(f"ALTER TABLE notebook ADD COLUMN {column} {ddl}")
        db.execute("INSERT OR IGNORE INTO merchants(id, name, created_at) VALUES(?,?,?)",
                   ("demo-merchant", "PayDawg Demo Shop", utc_now()))
        db.execute("INSERT OR IGNORE INTO notebook(merchant_id, updated_at) VALUES(?,?)",
                   ("demo-merchant", utc_now()))

def add_event(db, payment_id, event_type, from_status=None, to_status=None, payload=None):
    db.execute(
        "INSERT INTO events(payment_id,event_type,from_status,to_status,payload_json,created_at) VALUES(?,?,?,?,?,?)",
        (payment_id, event_type, from_status, to_status, json.dumps(payload or {}, separators=(",", ":")), utc_now())
    )

def update_status(db, payment_id, status, event_type, payload=None):
    row = db.execute("SELECT status FROM payments WHERE id=?", (payment_id,)).fetchone()
    if not row:
        return None
    old = row["status"]
    if old != status:
        db.execute("UPDATE payments SET status=?, updated_at=? WHERE id=?", (status, utc_now(), payment_id))
    add_event(db, payment_id, event_type, old, status, payload)
    return status

def payment_dict(row):
    if row is None:
        return None
    result = dict(row)
    for source, target in (("reasons_json", "reasons"), ("flags_json", "flags")):
        result[target] = json.loads(result.pop(source))
    return result

def mark_captured(db, payment_id, event_type, payload=None):
    """Move a payment to captured and teach the merchant's Notebook, exactly once.

    The Notebook only learns from money that was really captured, so a Growl that is
    held, voided or never approved cannot skew the baseline.
    """
    row = db.execute("SELECT merchant_id, amount, status, verdict, flags_json, created_at FROM payments WHERE id=?",
                     (payment_id,)).fetchone()
    if not row:
        return None
    first_capture = row["status"] != "captured"
    update_status(db, payment_id, "captured", event_type, payload)
    if first_capture:
        learned = row["amount"]
        if row["verdict"] == "Growl":
            # A merchant-approved outlier teaches the Notebook only up to the "unusual" limit, so one big
            # approved payment cannot make every later big payment look normal.
            book = db.execute("SELECT payment_count, average_amount FROM notebook WHERE merchant_id=?", (row["merchant_id"],)).fetchone()
            if book and book["payment_count"]:
                learned = min(learned, max(book["average_amount"], 1.0) * settings.large_amount_multiple)
        # Pace is the shop's normal flow: a payment that was part of a surge, or captured long after it
        # arrived (a merchant clearing held payments), does not teach it.
        try:
            flags = json.loads(row["flags_json"] or "[]")
        except ValueError:
            flags = []
        now = datetime.now(timezone.utc)
        arrived = nb.parse_time(row["created_at"]) or now
        teach_pace = "merchant_surge" not in flags and (now - arrived).total_seconds() <= nb.window_seconds()
        record_notebook_payment(db, row["merchant_id"], learned, row["created_at"], teach_pace)
    return "captured"

def reset_demo_data():
    """Clear ALL payments, events and Notebook counters (every merchant) so the demo can be run again.

    Development/demo helper only (see demo_shop/reset_demo.py). The merchant row is kept.
    """
    with db_session() as db:
        db.execute("DELETE FROM events")
        db.execute("DELETE FROM webhook_events")
        db.execute("DELETE FROM payments")
        db.execute(f"UPDATE notebook SET {NOTEBOOK_RESET}, updated_at=?", (utc_now(),))


def seed_demo_history(merchant_id):
    """SIMULATED (mock mode only): give one shop's Notebook about two weeks of past trading.

    See notebook.demo_history. Replaces whatever that Notebook had learned; payments are not touched.
    """
    values = nb.demo_history(datetime.now(timezone.utc))
    columns = ", ".join(f"{k}=?" for k in values)
    with db_session() as db:
        db.execute(f"UPDATE notebook SET {columns}, updated_at=? WHERE merchant_id=?",
                   (*values.values(), utc_now(), merchant_id))


def record_notebook_payment(db, merchant_id, amount, created_at=None, teach_pace=True):
    row = db.execute("SELECT * FROM notebook WHERE merchant_id=?", (merchant_id,)).fetchone()
    if not row:
        return
    values = nb.learn(dict(row), amount, created_at, datetime.now(timezone.utc), teach_pace)
    columns = ", ".join(f"{k}=?" for k in values)
    db.execute(f"UPDATE notebook SET {columns}, updated_at=? WHERE merchant_id=?", (*values.values(), utc_now(), merchant_id))
