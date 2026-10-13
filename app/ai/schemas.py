"""Typed contracts shared by the AI engine and HTTP API."""
from datetime import datetime
from decimal import Decimal
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, field_validator

Verdict = Literal["wag", "growl", "bark"]
RiskLevel = Literal["low", "medium", "high"]


class PaymentRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    merchant_id: str = Field(min_length=1, max_length=100)
    amount: Decimal = Field(gt=Decimal("0"), max_digits=12, decimal_places=2)
    currency: str = Field(default="USD", min_length=3, max_length=3)
    customer_ref: str = Field(min_length=1, max_length=150)
    idempotency_key: str = Field(min_length=8, max_length=200)

    @field_validator("currency")
    @classmethod
    def normalize_currency(cls, value: str) -> str:
        value = value.upper()
        if not value.isalpha():
            raise ValueError("currency must be a three-letter alphabetic code")
        return value


class RiskAnalysis(BaseModel):
    risk_level: RiskLevel
    reasons: list[str] = Field(min_length=1, max_length=8)


class EventResponse(BaseModel):
    event_type: str
    payload: dict
    created_at: datetime


class PaymentResponse(BaseModel):
    id: str
    merchant_id: str
    amount: Decimal
    currency: str
    customer_ref: str
    status: str
    verdict: Verdict
    risk_level: RiskLevel
    reasons: list[str]
    rule_flags: dict[str, bool]
    decision_source: str
    paypal_order_id: str | None = None
    paypal_authorization_id: str | None = None
    paypal_capture_id: str | None = None
    created_at: datetime
    updated_at: datetime
    events: list[EventResponse] = []
