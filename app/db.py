"""SQLite persistence. Events are append-only by application convention."""
import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from app.config import settings
from app.models import utc_now

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
            updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS payments (
            id TEXT PRIMARY KEY, merchant_id TEXT NOT NULL REFERENCES merchants(id),
            idempotency_key TEXT, request_hash TEXT NOT NULL, amount REAL NOT NULL,
            currency TEXT NOT NULL, customer_id TEXT NOT NULL, description TEXT NOT NULL,
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

def record_notebook_payment(db, merchant_id, amount):
    row = db.execute("SELECT payment_count, average_amount, max_amount FROM notebook WHERE merchant_id=?", (merchant_id,)).fetchone()
    if not row:
        return
    count = row["payment_count"]
    avg = ((row["average_amount"] * count) + amount) / (count + 1)
    db.execute("UPDATE notebook SET payment_count=?, average_amount=?, max_amount=?, updated_at=? WHERE merchant_id=?",
               (count + 1, avg, max(row["max_amount"], amount), utc_now(), merchant_id))
