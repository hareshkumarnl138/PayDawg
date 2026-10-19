"""The AI step, run against a fake Ollama (httpx.MockTransport): good reply, bad replies, timeouts, and its limits.

This proves PayDawg's side: what it sends, how it reads replies, and that the AI can never block a payment.
It cannot prove what a real Llama model will say: that needs Ollama running.
"""
import json
import httpx
import pytest
from app import config
from app.engine import decide
from app.screening import llm

PAY = {"amount": 20.0, "currency": "USD", "customer_id": "c1", "description": "Pen"}
NOTEBOOK = {"payment_count": 10, "average_amount": 20.0, "max_amount": 40.0, "known_customers": ["c1"]}


@pytest.fixture()
def ollama(monkeypatch):
    """Point the app at a fake Ollama. Set .reply (str) or .error (exception/status) per test."""
    state = type("S", (), {"reply": None, "status": 200, "raise_exc": None, "calls": []})()

    def handler(request: httpx.Request):
        state.calls.append(json.loads(request.content))
        if state.raise_exc:
            raise state.raise_exc
        reply = state.reply.pop(0) if isinstance(state.reply, list) else state.reply
        return httpx.Response(state.status, json={"response": reply})

    real = httpx.AsyncClient
    monkeypatch.setattr(llm.httpx, "AsyncClient", lambda **kw: real(transport=httpx.MockTransport(handler), **kw))
    object.__setattr__(config.settings, "llm_provider", "ollama")
    yield state
    object.__setattr__(config.settings, "llm_provider", "none")


@pytest.mark.asyncio
async def test_good_reply_is_used_and_labelled(ollama):
    ollama.reply = json.dumps({"risk_level": "medium", "reasons": ["Odd description."]})
    out = await llm.analyze(PAY, NOTEBOOK, [])
    assert out["decision_source"] == "ollama"
    assert out["analysis"]["risk_level"] == "medium" and out["analysis"]["reasons"] == ["Odd description."]


@pytest.mark.asyncio
async def test_request_carries_only_the_needed_fields(ollama):
    ollama.reply = json.dumps({"risk_level": "low", "reasons": []})
    await llm.analyze({**PAY, "order_ref": "SECRET-REF", "merchant_id": "m1"}, NOTEBOOK, ["new_customer"])
    sent = ollama.calls[0]
    assert sent["stream"] is False and sent["format"] == "json"
    assert "SECRET-REF" not in sent["prompt"] and "merchant_id" not in sent["prompt"]
    assert "new_customer" in sent["prompt"]


@pytest.mark.asyncio
async def test_garbage_reply_retries_once_then_falls_back(ollama):
    ollama.reply = "I think this payment is probably fine!"
    out = await llm.analyze(PAY, NOTEBOOK, [])
    assert out == {"analysis": None, "decision_source": "rules-only"}
    assert len(ollama.calls) == 2


@pytest.mark.asyncio
async def test_wrong_shape_reply_falls_back(ollama):
    ollama.reply = json.dumps({"risk_level": "catastrophic", "reasons": []})
    assert (await llm.analyze(PAY, NOTEBOOK, []))["decision_source"] == "rules-only"


@pytest.mark.asyncio
async def test_server_error_and_timeout_fall_back(ollama):
    ollama.status = 500
    assert (await llm.analyze(PAY, NOTEBOOK, []))["decision_source"] == "rules-only"
    ollama.status, ollama.raise_exc = 200, httpx.ReadTimeout("slow")
    assert (await llm.analyze(PAY, NOTEBOOK, []))["decision_source"] == "rules-only"
    ollama.raise_exc = httpx.ConnectError("Ollama is not running")
    assert (await llm.analyze(PAY, NOTEBOOK, []))["decision_source"] == "rules-only"


@pytest.mark.asyncio
async def test_second_attempt_can_succeed(ollama):
    ollama.reply = ["not json", json.dumps({"risk_level": "low", "reasons": ["Fine."]})]
    out = await llm.analyze(PAY, NOTEBOOK, [])
    assert out["decision_source"] == "ollama" and len(ollama.calls) == 2


@pytest.mark.asyncio
async def test_ai_high_becomes_growl_never_bark(ollama):
    ollama.reply = json.dumps({"risk_level": "high", "reasons": ["Model is very worried."]})
    decision = await decide({**PAY, "id": "p1", "merchant_id": "m1"}, NOTEBOOK, [])
    assert decision["verdict"] == "Growl" and decision["hard_block"] is False
    assert "Model is very worried." in decision["reasons"]
    assert decision["decision_source"] == "ollama"


@pytest.mark.asyncio
async def test_ai_low_cannot_lower_a_rule_growl(ollama):
    ollama.reply = json.dumps({"risk_level": "low", "reasons": ["Seems fine."]})
    big = {**PAY, "amount": 5000.0, "id": "p2", "merchant_id": "m1"}
    decision = await decide(big, NOTEBOOK, [])
    assert decision["verdict"] == "Growl"


@pytest.mark.asyncio
async def test_hard_rule_bark_is_not_overridden_by_ai(ollama):
    ollama.reply = json.dumps({"risk_level": "low", "reasons": ["Seems fine."]})
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc).isoformat()
    pay = {**PAY, "id": "p3", "merchant_id": "m1", "order_ref": "A1"}
    recent = [{"merchant_id": "m1", "customer_id": "c1", "amount": 20.0, "order_ref": "A1", "status": "captured", "created_at": now, "id": "p0"}]
    decision = await decide(pay, NOTEBOOK, recent)
    assert decision["verdict"] == "Bark" and decision["decision_source"] == "hard-rules"


def test_unknown_provider_is_rules_only(monkeypatch):
    import asyncio
    object.__setattr__(config.settings, "llm_provider", "mystery")
    try:
        assert asyncio.run(llm.analyze(PAY, NOTEBOOK, []))["decision_source"] == "rules-only"
    finally:
        object.__setattr__(config.settings, "llm_provider", "none")


def test_http_api_provider_reads_common_reply_shapes(monkeypatch):
    import asyncio
    real = httpx.AsyncClient
    for reply in ({"risk_level": "low", "reasons": []}, {"output": json.dumps({"risk_level": "medium", "reasons": ["x"]})},
                  {"response": json.dumps({"risk_level": "low", "reasons": []})}):
        monkeypatch.setattr(llm.httpx, "AsyncClient",
                            lambda r=reply, **kw: real(transport=httpx.MockTransport(lambda req: httpx.Response(200, json=r)), **kw))
        object.__setattr__(config.settings, "llm_provider", "http_api")
        object.__setattr__(config.settings, "http_api_url", "http://fake.invalid/v1")
        try:
            assert asyncio.run(llm.analyze(PAY, NOTEBOOK, []))["decision_source"] == "http_api"
        finally:
            object.__setattr__(config.settings, "llm_provider", "none")
            object.__setattr__(config.settings, "http_api_url", "")


def test_api_records_and_returns_ai_source(client, ollama):
    """End to end through the API: the AI's verdict contribution is stored and visible to the dashboard."""
    ollama.reply = json.dumps({"risk_level": "medium", "reasons": ["Gift card purchase looks odd."]})
    body = {"merchant_id": "demo-merchant", "customer_id": "c9", "amount": 12.0, "currency": "USD",
            "description": "gift cards", "order_ref": "o9"}
    created = client.post("/v1/payments", json=body, headers={"Idempotency-Key": "ai-1"}).json()
    assert created["verdict"] == "Growl" and created["decision_source"] == "ollama"
    assert "Gift card purchase looks odd." in created["reasons"]
    listed = client.get("/v1/payments").json()["payments"]
    assert any(p["id"] == created["id"] and p["decision_source"] == "ollama" for p in listed)
