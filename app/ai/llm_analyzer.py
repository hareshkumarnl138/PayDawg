"""Optional structured LLM analyzer. Missing credentials or API errors use rules-only fallback."""
import asyncio
import json
from app.ai.schemas import PaymentRequest, RiskAnalysis
from app.config import get_settings

SYSTEM_PROMPT = """You are a cautious payment-risk analyst for a demo application. You do not authorize, capture, or block money yourself. Evaluate only supplied evidence. A new customer alone is not proof of fraud. Return exactly the requested schema: risk_level low/medium/high and concise reasons. Never invent facts. Hard deterministic rules are enforced outside you and cannot be overridden."""


async def analyze_payment(request: PaymentRequest, baseline: dict, flags: dict[str, bool], rule_reasons: list[str]) -> RiskAnalysis | None:
    settings = get_settings()
    if settings.llm_provider.lower() != "openai" or not settings.openai_api_key:
        return None
    try:
        from openai import AsyncOpenAI
        client = AsyncOpenAI(api_key=settings.openai_api_key, timeout=settings.llm_timeout_seconds, max_retries=0)
        response = await client.chat.completions.create(
            model=settings.openai_model,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": json.dumps({
                    "payment": {"merchant_id": request.merchant_id, "amount": str(request.amount), "currency": request.currency, "customer_ref": request.customer_ref},
                    "merchant_baseline": baseline,
                    "rule_flags": flags,
                    "rule_reasons": rule_reasons,
                })},
            ],
            response_format={"type": "json_schema", "json_schema": {"name": "payment_risk", "strict": True, "schema": {
                "type": "object", "properties": {"risk_level": {"type": "string", "enum": ["low", "medium", "high"]}, "reasons": {"type": "array", "items": {"type": "string"}, "minItems": 1, "maxItems": 8}}, "required": ["risk_level", "reasons"], "additionalProperties": False
            }}},
        )
        content = response.choices[0].message.content
        if not content:
            return None
        return RiskAnalysis.model_validate_json(content)
    except (Exception, asyncio.TimeoutError):
        # Provider failures must never prevent the screening flow from responding.
        return None
