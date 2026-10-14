"""Pydantic API models and shared data shapes."""
import math
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Literal
from pydantic import BaseModel, Field, ConfigDict, field_validator

Verdict = Literal["Wag", "Growl", "Bark"]
RiskLevel = Literal["low", "medium", "high"]

MIN_AMOUNT = Decimal("0.01")
MAX_AMOUNT = Decimal("1000000")
MAX_DECIMAL_PLACES = 2


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def clean_text(value: str, field: str) -> str:
    """Trim a text field and reject control characters (NUL and friends corrupt logs and stores)."""
    if not isinstance(value, str):
        raise ValueError(f"{field} must be text")
    value = value.strip()
    if any(ord(ch) < 32 or ord(ch) == 127 for ch in value):
        raise ValueError(f"{field} must not contain control characters")
    return value


class PaymentCreate(BaseModel):
    merchant_id: str = "demo-merchant"
    amount: float = Field(gt=0, le=1000000)
    currency: str = Field(default="USD", min_length=3, max_length=3, pattern=r"^[A-Za-z]{3}$")
    customer_id: str = Field(min_length=1, max_length=128)
    description: str = Field(default="Demo purchase", max_length=255)
    order_ref: str | None = Field(default=None, max_length=128)  # merchant order/invoice number; a new one means a new purchase

    @field_validator("amount", mode="before")
    @classmethod
    def _money_only(cls, value):
        """Reject NaN, infinity and sub-cent precision: the rail can only charge whole cents."""
        if isinstance(value, float) and not math.isfinite(value):
            raise ValueError("amount must be a finite number")
        try:
            amount = Decimal(str(value))
        except (InvalidOperation, ValueError, TypeError):
            raise ValueError("amount must be a number")
        if not amount.is_finite():
            raise ValueError("amount must be a finite number")
        if -amount.as_tuple().exponent > MAX_DECIMAL_PLACES:
            raise ValueError("amount must have at most 2 decimal places")
        if amount < MIN_AMOUNT:
            raise ValueError(f"amount must be at least {MIN_AMOUNT}")
        if amount > MAX_AMOUNT:
            raise ValueError(f"amount must be at most {MAX_AMOUNT}")
        return float(amount)

    @field_validator("merchant_id", "customer_id", mode="before")
    @classmethod
    def _required_text(cls, value, info):
        value = clean_text(value, info.field_name)
        if not value:
            raise ValueError(f"{info.field_name} must not be blank")
        return value

    @field_validator("description", "order_ref", mode="before")
    @classmethod
    def _optional_text(cls, value, info):
        if value is None:
            return value
        return clean_text(value, info.field_name) or None


class LLMAnalysis(BaseModel):
    model_config = ConfigDict(extra="ignore")
    risk_level: RiskLevel
    reasons: list[str] = Field(default_factory=list, max_length=8)


class ScreeningResult(BaseModel):
    verdict: Verdict
    risk_level: RiskLevel
    reasons: list[str]
    flags: list[str]
    decision_source: str = "rules-only"
