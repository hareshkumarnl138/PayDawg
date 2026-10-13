"""Payment API routes with idempotency, screening, audit logging and merchant actions."""
import hashlib
import json
import logging
import uuid
from datetime import datetime, timezone
from decimal import Decimal
from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from app.ai.baseline import get_baseline
from app.ai.decision_engine import decide_verdict
from app.ai.llm_analyzer import analyze_payment
from app.ai.risk_rules import evaluate_rules
from app.ai.schemas import PaymentRequest, PaymentResponse, EventResponse
from app.config import get_settings
from app.db.database import get_db
from app.db.models import Payment
from app.payments.paypal_adapter import PayPalAdapter, PayPalAPIError, PayPalConfigurationError
from app.services.audit import append_event

router = APIRouter(prefix="/v1", tags=["payments"])
logger = logging.getLogger(__name__)


def _fingerprint(request: PaymentRequest) -> str:
    canonical = json.dumps({"merchant_id": request.merchant_id, "amount": str(request.amount), "currency": request.currency, "customer_ref": request.customer_ref}, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()


def _response(payment: Payment, *, with_events: bool = True) -> PaymentResponse:
    events = []
    if with_events:
        for e in payment.events:
            try:
                payload = json.loads(e.payload_json)
            except ValueError:
                payload = {}
            events.append(EventResponse(event_type=e.event_type, payload=payload, created_at=e.created_at))
    return PaymentResponse(id=payment.id, merchant_id=payment.merchant_id, amount=Decimal(str(payment.amount)).quantize(Decimal("0.01")), currency=payment.currency, customer_ref=payment.customer_ref, status=payment.status, verdict=payment.verdict, risk_level=payment.risk_level, reasons=json.loads(payment.reasons_json), rule_flags=json.loads(payment.rule_flags_json), decision_source=payment.decision_source, paypal_order_id=payment.paypal_order_id, paypal_authorization_id=payment.paypal_authorization_id, paypal_capture_id=payment.paypal_capture_id, created_at=payment.created_at, updated_at=payment.updated_at, events=events)


@router.post("/payments", response_model=PaymentResponse, status_code=status.HTTP_201_CREATED)
async def create_payment(payload: PaymentRequest, request: Request, response: Response, db: Session = Depends(get_db), idempotency_key: str | None = Header(default=None, alias="Idempotency-Key")) -> PaymentResponse:
    settings = get_settings()
    key = idempotency_key or payload.idempotency_key
    if key != payload.idempotency_key:
        raise HTTPException(status_code=400, detail="Idempotency-Key header must match payload.idempotency_key")
    existing = db.scalar(select(Payment).where(Payment.merchant_id == payload.merchant_id, Payment.idempotency_key == key))
    fingerprint = _fingerprint(payload)
    if existing:
        if existing.request_fingerprint != fingerprint:
            raise HTTPException(status_code=409, detail="Idempotency key was already used with a different payment payload")
        response.status_code = status.HTTP_200_OK
        return _response(existing)

    flags, rule_reasons = evaluate_rules(db, payload)
    baseline = get_baseline(db, payload.merchant_id)
    llm_result = await analyze_payment(payload, baseline, flags, rule_reasons)
    decision = decide_verdict(flags, rule_reasons, llm_result)

    payment_id = f"pay_{uuid.uuid4().hex[:24]}"
    # Screening does not prove that money moved. External payment actions are separate states.
    initial_status = "blocked" if decision.verdict == "bark" else "awaiting_buyer" if decision.verdict == "wag" else "review_required"
    payment = Payment(id=payment_id, merchant_id=payload.merchant_id, idempotency_key=key, amount=float(payload.amount), currency=payload.currency, customer_ref=payload.customer_ref, status=initial_status, verdict=decision.verdict, risk_level=decision.risk_level, reasons_json=json.dumps(decision.reasons), rule_flags_json=json.dumps(flags), decision_source=decision.decision_source, request_fingerprint=fingerprint, created_at=datetime.now(timezone.utc), updated_at=datetime.now(timezone.utc))
    db.add(payment)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        existing = db.scalar(select(Payment).where(Payment.merchant_id == payload.merchant_id, Payment.idempotency_key == key))
        if existing and existing.request_fingerprint == fingerprint:
            response.status_code = status.HTTP_200_OK
            return _response(existing)
        raise HTTPException(status_code=409, detail="Idempotency conflict; retry with the original key or a new key")

    append_event(db, payment, "payment.screened", {"verdict": decision.verdict, "risk_level": decision.risk_level, "reasons": decision.reasons, "rule_flags": flags, "decision_source": decision.decision_source})
    if decision.verdict == "bark":
        append_event(db, payment, "payment.blocked", {"reason": "Risk policy returned bark; no PayPal order was created"})
    elif decision.verdict == "growl":
        # A risk verdict is not itself a payment authorization or a funds hold.
        append_event(db, payment, "payment.review_required", {"message": "Merchant review required. No funds are held until a verified PayPal authorization exists."})
    else:
        append_event(db, payment, "payment.awaiting_buyer", {"message": "Payment passed screening. Buyer approval and PayPal capture are still required."})
    db.commit()
    db.refresh(payment)

    # Create a PayPal Sandbox order only when integration is explicitly enabled. The response must retain the external approval link.
    if settings.paypal_enabled and decision.verdict != "bark":
        paypal = PayPalAdapter()
        try:
            intent = "AUTHORIZE" if decision.verdict == "growl" else "CAPTURE"
            order = await paypal.create_order(amount=f"{payload.amount:.2f}", currency=payload.currency, intent=intent, return_url=str(request.base_url).rstrip("/") + "/paypal/return", cancel_url=str(request.base_url).rstrip("/") + "/paypal/cancel", request_id=payment.id)
            payment.paypal_order_id = order.get("id")
            links = order.get("links", [])
            approval = next((item.get("href") for item in links if item.get("rel") in ("approve", "payer-action")), None)
            payment.status = "awaiting_buyer" if approval else "payment_action_required"
            payment.updated_at = datetime.now(timezone.utc)
            append_event(db, payment, "paypal.order_created", {"order_id": payment.paypal_order_id, "intent": intent, "approval_url_available": bool(approval)})
            db.commit()
            db.refresh(payment)
            result = _response(payment)
            # add approval link as an API-level convenience without persisting untrusted URL in the payment model
            result.approval_url = approval
            return result
        except (PayPalAPIError, PayPalConfigurationError) as exc:
            logger.exception("PayPal order creation failed for payment %s", payment.id)
            payment.status = "rail_error"
            payment.updated_at = datetime.now(timezone.utc)
            append_event(db, payment, "paypal.order_creation_failed", {"error": str(exc)})
            db.commit()
            db.refresh(payment)
    return _response(payment)


@router.get("/payments", response_model=list[PaymentResponse])
def list_payments(limit: int = 100, db: Session = Depends(get_db)) -> list[PaymentResponse]:
    limit = max(1, min(limit, 250))
    rows = db.scalars(select(Payment).order_by(Payment.created_at.desc()).limit(limit)).all()
    return [_response(p) for p in rows]


@router.get("/payments/{payment_id}", response_model=PaymentResponse)
def get_payment(payment_id: str, db: Session = Depends(get_db)) -> PaymentResponse:
    payment = db.get(Payment, payment_id)
    if not payment:
        raise HTTPException(status_code=404, detail="Payment not found")
    return _response(payment)


async def _merchant_action(payment_id: str, action: str, db: Session) -> PaymentResponse:
    payment = db.get(Payment, payment_id)
    if not payment:
        raise HTTPException(status_code=404, detail="Payment not found")
    if payment.verdict != "growl":
        raise HTTPException(status_code=409, detail="Only Growl payments can be approved or voided")
    if action == "approve":
        if payment.status != "held":
            raise HTTPException(status_code=409, detail=f"Payment cannot be approved from status '{payment.status}'. A verified PayPal authorization is required first.")
        if not payment.paypal_order_id:
            raise HTTPException(status_code=409, detail="No PayPal order is associated with this payment")
        # PayPal Orders v2 AUTHORIZE must be authorized after buyer approval before capture; don't fake that lifecycle.
        raise HTTPException(status_code=501, detail="Growl capture requires the PayPal buyer-approval and authorization-completion flow, which must be completed before capture is enabled.")
    if payment.status != "held":
        raise HTTPException(status_code=409, detail=f"Payment cannot be voided from status '{payment.status}'. A verified PayPal authorization is required first.")
    if not payment.paypal_authorization_id:
        raise HTTPException(status_code=409, detail="No PayPal authorization exists to void. A local screening verdict is not a funds hold.")
    raise HTTPException(status_code=501, detail="Authorization void endpoint must be wired to the current PayPal Payments v2 authorization ID before this action is enabled.")


@router.post("/payments/{payment_id}/approve", response_model=PaymentResponse)
async def approve_payment(payment_id: str, db: Session = Depends(get_db)) -> PaymentResponse:
    return await _merchant_action(payment_id, "approve", db)


@router.post("/payments/{payment_id}/void", response_model=PaymentResponse)
async def void_payment(payment_id: str, db: Session = Depends(get_db)) -> PaymentResponse:
    return await _merchant_action(payment_id, "void", db)
