"""The real PayPal adapter, run against a fake PayPal (httpx.MockTransport). Checks what we SEND and how we READ the replies.

This proves our side matches PayPal's documented shapes. It cannot prove PayPal's servers accept it:
that needs one run against the real sandbox.
"""
import json
import httpx
import pytest
from app import config
from app.rails import paypal as pp


@pytest.fixture()
def rail(monkeypatch):
    sent = []
    replies = {}

    def handler(request: httpx.Request):
        is_json = request.headers.get("content-type", "").startswith("application/json")
        body = json.loads(request.content) if request.content and is_json else None
        sent.append({"method": request.method, "path": request.url.path, "headers": dict(request.headers), "body": body})
        if request.url.path == "/v1/oauth2/token":
            return httpx.Response(200, json={"access_token": "tok", "expires_in": 3600})
        for suffix, resp in replies.items():
            if request.url.path.endswith(suffix):
                return httpx.Response(200, json=resp)
        return httpx.Response(404, json={})

    real = httpx.AsyncClient
    monkeypatch.setattr(pp.httpx, "AsyncClient", lambda **kw: real(transport=httpx.MockTransport(handler), **kw))
    object.__setattr__(config.settings, "paypal_client_id", "id")
    object.__setattr__(config.settings, "paypal_client_secret", "secret")
    r = pp.PayPalRail()
    r.sent, r.replies = sent, replies
    return r


PAY = {"id": "pay-1", "amount": 18.0, "currency": "INR", "description": "Pen", "provider_order_id": "ORD1"}


def last(r, suffix):
    return [s for s in r.sent if s["path"].endswith(suffix)][-1]


@pytest.mark.asyncio
async def test_create_order_sends_idempotency_key_and_full_response_request(rail):
    rail.replies["/v2/checkout/orders"] = {"id": "ORD1", "status": "CREATED",
                                          "links": [{"rel": "self", "href": "x"}, {"rel": "approve", "href": "https://pp/approve"}]}
    out = await rail.create(PAY, "CAPTURE")
    req = last(rail, "/v2/checkout/orders")
    assert req["headers"]["paypal-request-id"] == "pay-1:create"
    assert req["headers"]["prefer"] == "return=representation"
    assert req["body"]["intent"] == "CAPTURE"
    assert req["body"]["purchase_units"][0]["amount"] == {"currency_code": "INR", "value": "18.00"}
    assert out["order_id"] == "ORD1" and out["approval_url"] == "https://pp/approve"


@pytest.mark.asyncio
async def test_create_accepts_the_payer_action_link_and_a_missing_description(rail):
    rail.replies["/v2/checkout/orders"] = {"id": "ORD2", "links": [{"rel": "payer-action", "href": "https://pp/pa"}]}
    out = await rail.create({**PAY, "description": None}, "AUTHORIZE")
    assert out["approval_url"] == "https://pp/pa"
    assert last(rail, "/v2/checkout/orders")["body"]["purchase_units"][0]["description"] == "PayDawg payment"


@pytest.mark.asyncio
async def test_authorize_reads_the_authorization_id_from_the_documented_place(rail):
    rail.replies["/authorize"] = {"id": "ORD1", "status": "COMPLETED", "purchase_units": [
        {"payments": {"authorizations": [{"id": "AUTH9", "status": "CREATED"}]}}]}
    out = await rail.authorize(PAY)
    assert out["authorization_id"] == "AUTH9"
    req = last(rail, "/authorize")
    assert req["path"] == "/v2/checkout/orders/ORD1/authorize" and req["body"] == {}
    assert req["headers"]["prefer"] == "return=representation"   # minimal replies may omit the authorization


@pytest.mark.asyncio
async def test_capture_of_a_held_authorization_uses_the_payments_endpoint(rail):
    rail.replies["/capture"] = {"id": "CAP1", "status": "COMPLETED"}
    out = await rail.capture({**PAY, "provider_authorization_id": "AUTH9"})
    req = last(rail, "/capture")
    assert req["path"] == "/v2/payments/authorizations/AUTH9/capture"
    assert req["body"]["amount"] == {"currency_code": "INR", "value": "18.00"} and req["body"]["final_capture"] is True
    assert out["capture_id"] == "CAP1"


@pytest.mark.asyncio
async def test_capture_of_an_approved_order_reads_the_nested_capture_id(rail):
    rail.replies["/capture"] = {"id": "ORD1", "purchase_units": [{"payments": {"captures": [{"id": "CAP2", "status": "COMPLETED"}]}}]}
    out = await rail.capture(PAY)
    assert last(rail, "/capture")["path"] == "/v2/checkout/orders/ORD1/capture"
    assert out["capture_id"] == "CAP2"


@pytest.mark.asyncio
async def test_void_and_refund_hit_the_documented_endpoints(rail):
    rail.replies["/void"] = {"id": "AUTH9", "status": "VOIDED"}
    rail.replies["/refund"] = {"id": "REF1", "status": "COMPLETED"}
    assert (await rail.void({**PAY, "provider_authorization_id": "AUTH9"}))["status"] == "VOIDED"
    assert last(rail, "/void")["path"] == "/v2/payments/authorizations/AUTH9/void"
    assert (await rail.refund({**PAY, "provider_capture_id": "CAP1"}))["refund_id"] == "REF1"
    assert last(rail, "/refund")["path"] == "/v2/payments/captures/CAP1/refund"


@pytest.mark.asyncio
async def test_token_is_fetched_once_and_reused(rail):
    rail.replies["/void"] = {"status": "VOIDED"}
    for _ in range(3):
        await rail.void({**PAY, "provider_authorization_id": "A"})
    assert len([s for s in rail.sent if s["path"] == "/v1/oauth2/token"]) == 1
    assert last(rail, "/void")["headers"]["authorization"] == "Bearer tok"
