"""PayPal webhook endpoint. Signature verification is mandatory before mutation."""
import json
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, Header, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.db.database import get_db
from app.db.models import Payment
from app.payments.paypal_adapter import PayPalAdapter
from app.services.audit import append_event

router = APIRouter(tags=["webhooks"])


@router.post("/webhooks/paypal")
async def paypal_webhook(request: Request, db: Session = Depends(get_db), paypal_auth_algo: str | None = Header(default=None), paypal_cert_url: str | None = Header(default=None), paypal_transmission_id: str | None = Header(default=None), paypal_transmission_sig: str | None = Header(default=None), paypal_transmission_time: str | None = Header(default=None)) -> dict:
    event = await request.json()
    headers = {"paypal-auth-algo": paypal_auth_algo, "paypal-cert-url": paypal_cert_url, "paypal-transmission-id": paypal_transmission_id, "paypal-transmission-sig": paypal_transmission_sig, "paypal-transmission-time": paypal_transmission_time}
    verified = await PayPalAdapter().verify_webhook_signature({k: v for k, v in headers.items() if v}, event)
    if not verified:
        raise HTTPException(status_code=400, detail="PayPal webhook signature verification failed")
    resource = event.get("resource") or {}
    related = resource.get("supplementary_data", {}).get("related_ids", {})
    order_id = resource.get("id") or related.get("order_id")
    payment = db.scalar(select(Payment).where(Payment.paypal_order_id == order_id)) if order_id else None
    if not payment:
        append_only_orphan = {"event_id": event.get("id"), "event_type": event.get("event_type"), "resource_id": resource.get("id"), "received_at": datetime.now(timezone.utc).isoformat()}
        # Unknown but verified event: acknowledge only after noting it in server log; don't mutate unrelated rows.
        return {"received": True, "matched": False, "details": append_only_orphan}
    event_type = event.get("event_type", "unknown")
    status_map = {
        "CHECKOUT.ORDER.APPROVED": "buyer_approved",
        "PAYMENT.AUTHORIZATION.CREATED": "held",
        "PAYMENT.CAPTURE.COMPLETED": "captured",
        "PAYMENT.CAPTURE.DENIED": "failed",
        "PAYMENT.AUTHORIZATION.VOIDED": "voided",
        "CHECKOUT.ORDER.VOIDED": "voided",
    }
    next_status = status_map.get(event_type)
    if next_status:
        previous = payment.status
        payment.status = next_status
        payment.updated_at = datetime.now(timezone.utc)
        if next_status == "captured":
            capture_id = resource.get("id")
            payment.paypal_capture_id = capture_id
        append_event(db, payment, "paypal.webhook", {"event_type": event_type, "previous_status": previous, "new_status": next_status, "event_id": event.get("id")})
        if next_status == "captured":
            from app.ai.baseline import update_baseline
            update_baseline(db, payment)
        db.commit()
    else:
        append_event(db, payment, "paypal.webhook_unmapped", {"event_type": event_type, "event_id": event.get("id")})
        db.commit()
    return {"received": True, "matched": True, "event_type": event_type}
