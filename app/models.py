"""Pydantic API models and shared data shapes."""
from datetime import datetime, timezone
from typing import Literal
from pydantic import BaseModel, Field, ConfigDict

Verdict = Literal["Wag", "Growl", "Bark"]
RiskLevel = Literal["low", "medium", "high"]

def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()

class PaymentCreate(BaseModel):
    merchant_id: str = "demo-merchant"
    amount: float = Field(gt=0, le=1000000)
    currency: str = Field(default="USD", min_length=3, max_length=3)
    customer_id: str = Field(min_length=1, max_length=128)
    description: str = Field(default="Demo purchase", max_length=255)
    return_url: str = "http://localhost:8000/?payment=success"
    cancel_url: str = "http://localhost:8000/?payment=cancelled"

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
