from datetime import datetime, timedelta, timezone
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from app.db.models import Base, Payment, MerchantBaseline
from app.ai.schemas import PaymentRequest
from app.ai.risk_rules import evaluate_rules


def session():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)()


def payment(pid, *, customer="buyer-a", amount=10.0, status="captured", created=None):
    created = created or datetime.now(timezone.utc)
    p = Payment(id=pid, merchant_id="shop", idempotency_key=pid, amount=amount, currency="USD", customer_ref=customer, status=status, verdict="wag", risk_level="low", reasons_json="[]", rule_flags_json="{}", decision_source="rules-only", request_fingerprint=pid, created_at=created, updated_at=created)
    return p


def request(*, customer="buyer-new", amount="20.00", key="new-123456"):
    return PaymentRequest(merchant_id="shop", amount=amount, currency="USD", customer_ref=customer, idempotency_key=key)


def test_duplicate_signal_detected():
    db=session();db.add(payment("old", customer="buyer-new", amount=20.0));db.commit()
    flags, reasons=evaluate_rules(db, request())
    assert flags["duplicate"] is True
    assert any("submitted recently" in x for x in reasons)


def test_velocity_breach_detected():
    db=session()
    for i in range(5): db.add(payment(f"v{i}", customer="buyer-new", amount=10+i))
    db.commit()
    flags,_=evaluate_rules(db, request())
    assert flags["velocity_breach"] is True


def test_amount_outlier_uses_merchant_baseline():
    db=session();db.add(MerchantBaseline(merchant_id="shop", avg_amount=20, max_amount=30, common_currency="USD", active_hours_json="[]", payment_count=5));db.commit()
    flags,_=evaluate_rules(db, request(amount="100.00"))
    assert flags["amount_outlier"] is True


def test_old_attempt_is_not_velocity_breach():
    db=session();db.add(payment("old", customer="buyer-new", amount=10, created=datetime.now(timezone.utc)-timedelta(hours=1)));db.commit()
    flags,_=evaluate_rules(db, request())
    assert flags["velocity_breach"] is False
