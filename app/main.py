"""PayDawg FastAPI MVP."""
import hashlib
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from app.config import settings
from app.db import init_db, db_session, add_event, update_status, payment_dict, record_notebook_payment
from app.models import PaymentCreate
from app.engine import decide
from app.rails.base import RailError
from app.rails.mock import MockRail
from app.rails.paypal import PayPalRail

app = FastAPI(title="PayDawg", version="1.0.0", description="Risk-aware payment orchestration MVP")
DASHBOARD = Path(__file__).resolve().parent.parent / "dashboard"
app.mount("/dashboard", StaticFiles(directory=str(DASHBOARD)), name="dashboard")

def get_rail():
    if settings.rail_provider == "mock":
        return MockRail()
    if settings.rail_provider == "paypal":
        return PayPalRail()
    raise HTTPException(500, "Unsupported PAYPAL_MODE. Choose mock or paypal.")

@app.on_event("startup")
def startup():
    init_db()

@app.get("/", include_in_schema=False)
def dashboard():
    return FileResponse(DASHBOARD / "index.html")

@app.get("/health")
def health():
    return {"ok": True, "rail": settings.rail_provider, "llm": settings.llm_provider,
            "simulated": settings.rail_provider == "mock"}

@app.post("/v1/payments")
async def create_payment(body: PaymentCreate, idempotency_key: str | None = Header(default=None, alias="Idempotency-Key")):
    if settings.rail_provider == "paypal" and (not settings.paypal_client_id or not settings.paypal_client_secret):
        raise HTTPException(503, "PayPal sandbox credentials are not configured.")
    request_data = body.model_dump()
    request_data["currency"] = body.currency.upper()
    request_hash = hashlib.sha256(json.dumps(request_data, sort_keys=True).encode()).hexdigest()
    key = (idempotency_key or "").strip() or None
    with db_session() as db:
        merchant = db.execute("SELECT id FROM merchants WHERE id=?", (body.merchant_id,)).fetchone()
        if not merchant:
            raise HTTPException(404, "Merchant not found.")
        if key:
            existing = db.execute("SELECT * FROM payments WHERE merchant_id=? AND idempotency_key=?", (body.merchant_id, key)).fetchone()
            if existing:
                if existing["request_hash"] != request_hash:
                    raise HTTPException(409, "Idempotency key was already used for a different request.")
                return payment_dict(existing)
        notebook_row = db.execute("SELECT * FROM notebook WHERE merchant_id=?", (body.merchant_id,)).fetchone()
        notebook = dict(notebook_row) if notebook_row else {}
        recent = [dict(row) for row in db.execute(
            "SELECT merchant_id, amount, customer_id, created_at, status FROM payments WHERE merchant_id=? ORDER BY created_at DESC LIMIT 100",
            (body.merchant_id,)).fetchall()]
        pid = str(uuid.uuid4())
        created_at = datetime.now(timezone.utc).isoformat()
        payment = {"id": pid, **request_data, "created_at": created_at}
        decision = await decide(payment, notebook, recent)
        status = "blocked" if decision["verdict"] == "Bark" else "screened"
        db.execute("""INSERT INTO payments
            (id,merchant_id,idempotency_key,request_hash,amount,currency,customer_id,description,verdict,risk_level,reasons_json,flags_json,decision_source,status,rail,created_at,updated_at)
            VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (pid, body.merchant_id, key, request_hash, body.amount, body.currency.upper(), body.customer_id,
             body.description, decision["verdict"], decision["risk_level"], json.dumps(decision["reasons"]),
             json.dumps(decision["flags"]), decision["decision_source"], status, settings.rail_provider, created_at, created_at))
        add_event(db, pid, "payment.created", None, "created", {"amount": body.amount, "currency": body.currency.upper()})
        add_event(db, pid, "payment.screened", "created", status,
                  {"verdict": decision["verdict"], "reasons": decision["reasons"], "decision_source": decision["decision_source"]})
        if status == "blocked":
            return payment_dict(db.execute("SELECT * FROM payments WHERE id=?", (pid,)).fetchone())
        record_notebook_payment(db, body.merchant_id, body.amount)
        stored = dict(db.execute("SELECT * FROM payments WHERE id=?", (pid,)).fetchone())
    intent = "AUTHORIZE" if decision["verdict"] == "Growl" else "CAPTURE"
    try:
        result = await get_rail().create({**stored, "return_url": body.return_url, "cancel_url": body.cancel_url}, intent)
    except Exception as exc:
        with db_session() as db:
            update_status(db, pid, "failed", "rail.create_failed", {"error": str(exc)[:200]})
        raise HTTPException(502, "Payment rail could not create the order.") from exc
    with db_session() as db:
        db.execute("UPDATE payments SET provider_order_id=?, approval_url=?, updated_at=? WHERE id=?",
                   (result.get("order_id"), result.get("approval_url"), datetime.now(timezone.utc).isoformat(), pid))
        add_event(db, pid, "rail.order_created", status, status, {"rail": settings.rail_provider, "intent": intent, "simulated": result.get("simulated", False)})
        return payment_dict(db.execute("SELECT * FROM payments WHERE id=?", (pid,)).fetchone())

@app.get("/v1/payments")
def list_payments(limit: int = 100):
    limit = max(1, min(limit, 500))
    with db_session() as db:
        rows = db.execute("SELECT * FROM payments ORDER BY created_at DESC LIMIT ?", (limit,)).fetchall()
        return {"payments": [payment_dict(row) for row in rows]}

@app.get("/v1/payments/{payment_id}")
def get_payment(payment_id: str):
    with db_session() as db:
        row = db.execute("SELECT * FROM payments WHERE id=?", (payment_id,)).fetchone()
        if not row:
            raise HTTPException(404, "Payment not found.")
        result = payment_dict(row)
        result["events"] = [dict(e) for e in db.execute("SELECT * FROM events WHERE payment_id=? ORDER BY id", (payment_id,)).fetchall()]
        return result

@app.post("/v1/payments/{payment_id}/approve")
async def approve_payment(payment_id: str):
    with db_session() as db:
        row = db.execute("SELECT * FROM payments WHERE id=?", (payment_id,)).fetchone()
        if not row:
            raise HTTPException(404, "Payment not found.")
        payment = dict(row)
        if payment["status"] not in {"screened", "held", "approved"}:
            raise HTTPException(409, f"Payment cannot be approved from status {payment['status']}.")
        if payment["status"] == "approved":
            return payment_dict(row)
        capture_authorization = payment["verdict"] == "Growl" and payment["status"] in {"held", "approved"}
    try:
        rail = get_rail()
        if payment["verdict"] == "Growl" and not capture_authorization:
            result = await rail.authorize(payment)
            auth_id = result.get("authorization_id")
            if not auth_id and not result.get("simulated"):
                raise RailError("Provider did not return an authorization ID.")
            new_status = "held"
        else:
            result = await rail.capture(payment)
            new_status = "captured"
    except Exception as exc:
        with db_session() as db:
            update_status(db, payment_id, "failed", "rail.approve_failed", {"error": str(exc)[:200]})
        raise HTTPException(502, "Payment rail approval/capture failed. Check sandbox order approval and server logs.") from exc
    with db_session() as db:
        if result.get("authorization_id"):
            db.execute("UPDATE payments SET provider_authorization_id=? WHERE id=?", (result["authorization_id"], payment_id))
        if result.get("capture_id"):
            db.execute("UPDATE payments SET provider_capture_id=? WHERE id=?", (result["capture_id"], payment_id))
        update_status(db, payment_id, new_status, "payment.authorized" if new_status == "held" else "payment.captured",
                      {"rail": settings.rail_provider, "simulated": result.get("simulated", False)})
        return payment_dict(db.execute("SELECT * FROM payments WHERE id=?", (payment_id,)).fetchone())

@app.post("/v1/payments/{payment_id}/void")
async def void_payment(payment_id: str):
    with db_session() as db:
        row = db.execute("SELECT * FROM payments WHERE id=?", (payment_id,)).fetchone()
        if not row:
            raise HTTPException(404, "Payment not found.")
        payment = dict(row)
        if payment["verdict"] != "Growl" or payment["status"] not in {"held", "approved"}:
            raise HTTPException(409, "Only authorized Growl payments can be voided.")
    try:
        result = await get_rail().void(payment)
    except Exception as exc:
        raise HTTPException(502, "Payment rail could not void the authorization.") from exc
    with db_session() as db:
        update_status(db, payment_id, "failed", "payment.voided", {"rail": settings.rail_provider, "simulated": result.get("simulated", False)})
        return payment_dict(db.execute("SELECT * FROM payments WHERE id=?", (payment_id,)).fetchone())

@app.post("/webhooks/paypal")
async def paypal_webhook(request: Request):
    payload = await request.json()
    # TODO: Verify the header set and verification endpoint against current PayPal webhook docs before production use.
    if settings.rail_provider != "paypal" or not settings.paypal_webhook_id:
        raise HTTPException(503, "PayPal webhook verification is not configured.")
    headers = {
        "auth_algo": request.headers.get("paypal-auth-algo", ""),
        "cert_url": request.headers.get("paypal-cert-url", ""),
        "transmission_id": request.headers.get("paypal-transmission-id", ""),
        "transmission_sig": request.headers.get("paypal-transmission-sig", ""),
        "transmission_time": request.headers.get("paypal-transmission-time", ""),
        "webhook_id": settings.paypal_webhook_id,
        "webhook_event": payload,
    }
    try:
        verified = await get_rail()._request("POST", "/v1/notifications/verify-webhook-signature", json_body=headers)
    except Exception as exc:
        raise HTTPException(502, "Could not verify PayPal webhook.") from exc
    if verified.get("verification_status") != "SUCCESS":
        raise HTTPException(400, "Invalid PayPal webhook signature.")
    event_id = payload.get("id")
    if not event_id:
        raise HTTPException(400, "Webhook event ID is required.")
    resource = payload.get("resource") or {}
    related = resource.get("supplementary_data", {}).get("related_ids", {})
    order_id = related.get("order_id") or resource.get("id")
    with db_session() as db:
        try:
            db.execute("INSERT INTO webhook_events(event_id, received_at) VALUES(?,datetime('now'))", (event_id,))
        except Exception:
            return {"received": True, "duplicate": True}
        row = db.execute("SELECT * FROM payments WHERE provider_order_id=? OR provider_capture_id=?",
                         (order_id, order_id)).fetchone()
        if not row:
            return {"received": True, "matched": False}
        payment_id, old_status = row["id"], row["status"]
        event_type = payload.get("event_type", "")
        if event_type == "PAYMENT.CAPTURE.COMPLETED":
            update_status(db, payment_id, "captured", "webhook.paypal.capture_completed", {"event_id": event_id})
        elif event_type in {"PAYMENT.CAPTURE.REFUNDED", "PAYMENT.CAPTURE.REVERSED"}:
            update_status(db, payment_id, "refunded", "webhook.paypal.refund_or_reversal", {"event_id": event_id})
        elif event_type in {"PAYMENT.AUTHORIZATION.VOIDED", "CHECKOUT.ORDER.VOIDED"}:
            update_status(db, payment_id, "failed", "webhook.paypal.voided", {"event_id": event_id})
        else:
            add_event(db, payment_id, "webhook.paypal.received", old_status, old_status, {"event_id": event_id, "event_type": event_type})
    return {"received": True, "matched": True}
