"""Optional LLM analysis with schema validation, one retry, and safe fallback."""
import json
import httpx
from app.config import settings
from app.models import LLMAnalysis

async def _ollama(payload: dict) -> str:
    prompt = (
        "Assess payment risk. Return ONLY JSON with risk_level low|medium|high and reasons array of short strings. "
        "Do not invent facts. Input: " + json.dumps(payload)
    )
    async with httpx.AsyncClient(timeout=45) as client:
        response = await client.post(settings.ollama_url, json={"model": settings.ollama_model, "prompt": prompt, "stream": False, "format": "json"})
    response.raise_for_status()
    data = response.json()
    return data.get("response", data)

async def _http_api(payload: dict) -> str:
    if not settings.http_api_url:
        raise ValueError("LLM_HTTP_API_URL is not configured")
    headers = {"Content-Type": "application/json"}
    if settings.http_api_key:
        headers["Authorization"] = "Bearer " + settings.http_api_key
    body = {"model": settings.http_api_model, "input": payload, "response_format": {"type": "json_object"}}
    async with httpx.AsyncClient(timeout=45) as client:
        response = await client.post(settings.http_api_url, json=body, headers=headers)
    response.raise_for_status()
    data = response.json()
    if isinstance(data, dict) and "risk_level" in data:
        return data
    if isinstance(data, dict) and isinstance(data.get("output"), str):
        return data["output"]
    if isinstance(data, dict) and isinstance(data.get("response"), str):
        return data["response"]
    return data

async def analyze(payment: dict, baseline: dict, flags: list[str]) -> dict:
    provider = settings.llm_provider
    if provider == "none":
        return {"analysis": None, "decision_source": "rules-only"}
    payload = {"payment": {k: payment.get(k) for k in ("amount", "currency", "customer_id", "description")},
               "baseline": baseline, "flags": flags}
    caller = _ollama if provider == "ollama" else _http_api if provider == "http_api" else None
    if caller is None:
        return {"analysis": None, "decision_source": "rules-only"}
    for _attempt in range(2):
        try:
            result = await caller(payload)
            if isinstance(result, str):
                result = json.loads(result)
            analysis = LLMAnalysis.model_validate(result)
            return {"analysis": analysis.model_dump(), "decision_source": provider}
        except Exception:
            continue
    return {"analysis": None, "decision_source": "rules-only"}
