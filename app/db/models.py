"""SQLAlchemy models for payment state, merchant baselines, and audit events."""
from datetime import datetime, timezone
from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class Payment(Base):
    __tablename__ = "payments"
    __table_args__ = (UniqueConstraint("merchant_id", "idempotency_key", name="uq_merchant_idempotency"),)

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    merchant_id: Mapped[str] = mapped_column(String(100), index=True)
    idempotency_key: Mapped[str] = mapped_column(String(200))
    amount: Mapped[float] = mapped_column(Float)
    currency: Mapped[str] = mapped_column(String(3))
    customer_ref: Mapped[str] = mapped_column(String(150), index=True)
    status: Mapped[str] = mapped_column(String(30), default="screened")
    verdict: Mapped[str] = mapped_column(String(20))
    risk_level: Mapped[str] = mapped_column(String(20))
    reasons_json: Mapped[str] = mapped_column(Text, default="[]")
    rule_flags_json: Mapped[str] = mapped_column(Text, default="{}")
    decision_source: Mapped[str] = mapped_column(String(30), default="rules-only")
    request_fingerprint: Mapped[str] = mapped_column(String(64))
    paypal_order_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    paypal_authorization_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    paypal_capture_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)
    events: Mapped[list["PaymentEvent"]] = relationship(back_populates="payment", order_by="PaymentEvent.id", cascade="all, delete-orphan")


class MerchantBaseline(Base):
    __tablename__ = "merchant_baselines"

    merchant_id: Mapped[str] = mapped_column(String(100), primary_key=True)
    avg_amount: Mapped[float] = mapped_column(Float, default=0.0)
    max_amount: Mapped[float] = mapped_column(Float, default=0.0)
    common_currency: Mapped[str] = mapped_column(String(3), default="USD")
    active_hours_json: Mapped[str] = mapped_column(Text, default="[]")
    payment_count: Mapped[int] = mapped_column(Integer, default=0)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)


class PaymentEvent(Base):
    __tablename__ = "payment_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    payment_id: Mapped[str] = mapped_column(ForeignKey("payments.id", ondelete="CASCADE"), index=True)
    event_type: Mapped[str] = mapped_column(String(60))
    payload_json: Mapped[str] = mapped_column(Text, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, index=True)
    payment: Mapped[Payment] = relationship(back_populates="events")
