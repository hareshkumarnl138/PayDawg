"""PayPal REST Orders v2 sandbox adapter."""
import time
import httpx
from app.config import settings
from app.rails.base import Rail, RailError

# Ask PayPal for the full response: the default "minimal" one may leave out the authorization/capture details we read.
FULL = {"Prefer": "return=representation"}


def request_id(payment, step):
    """PayPal-Request-Id makes a retried call return the first result instead of acting twice (kept 6 hours).
    Used for order creation only: a second create would be a second order. Authorize, capture and void are
    already refused by PayPal when repeated, and a replayed old error would wrongly block a legitimate retry."""
    return {"PayPal-Request-Id": f'{payment["id"]}:{step}'[:108]}


class PayPalRail(Rail):
    name = "paypal"
    simulated = False

    def __init__(self):
        self._token = None
        self._token_expiry = 0

    async def _access_token(self):
        if not settings.paypal_client_id or not settings.paypal_client_secret:
            raise RailError("PayPal sandbox credentials are missing.")
        if self._token and time.time() < self._token_expiry - 30:
            return self._token
        async with httpx.AsyncClient(timeout=20) as client:
            response = await client.post(
                settings.paypal_base_url + "/v1/oauth2/token",
                auth=(settings.paypal_client_id, settings.paypal_client_secret),
                data={"grant_type": "client_credentials"},
                headers={"Accept": "application/json", "Accept-Language": "en_US"},
            )
        if response.is_error:
            raise RailError(f"PayPal OAuth failed ({response.status_code}).")
        data = response.json()
        self._token = data["access_token"]
        self._token_expiry = time.time() + int(data.get("expires_in", 300))
        return self._token

    async def _request(self, method, path, *, json_body=None, headers=None):
        token = await self._access_token()
        merged = {"Authorization": "Bearer " + token, "Content-Type": "application/json"}
        merged.update(headers or {})
        async with httpx.AsyncClient(timeout=25) as client:
            response = await client.request(method, settings.paypal_base_url + path, json=json_body, headers=merged)
        if response.is_error:
            # Do not log response bodies: provider errors can contain sensitive details.
            raise RailError(f"PayPal API {method} {path} failed ({response.status_code}).")
        return response.json() if response.content else {}

    async def create(self, payment, intent):
        body = {
            "intent": intent,
            "purchase_units": [{
                "reference_id": payment["id"],
                "custom_id": payment["id"],
                "description": (payment.get("description") or "PayDawg payment")[:127],
                "amount": {"currency_code": payment["currency"], "value": f'{payment["amount"]:.2f}'},
            }],
            "application_context": {
                "return_url": payment.get("return_url") or settings.public_base_url + "/paypal/return",
                "cancel_url": payment.get("cancel_url") or settings.public_base_url + "/paypal/cancel",
                "user_action": "PAY_NOW",
            },
        }
        data = await self._request("POST", "/v2/checkout/orders", json_body=body,
                                  headers={**FULL, **request_id(payment, "create")})
        # PayPal names the buyer link "approve" (older shape) or "payer-action" (newer shape).
        approval = next((x.get("href") for x in data.get("links", []) if x.get("rel") in ("approve", "payer-action")), None)
        return {"order_id": data["id"], "approval_url": approval, "status": data.get("status"), "intent": intent}

    async def authorize(self, payment):
        # Checked against PayPal's Orders v2 docs: POST /v2/checkout/orders/{id}/authorize with {} after buyer approval;
        # the authorization id is at purchase_units[].payments.authorizations[].id.
        order_id = payment.get("provider_order_id")
        if not order_id:
            raise RailError("PayPal order ID is missing.")
        data = await self._request("POST", f"/v2/checkout/orders/{order_id}/authorize", json_body={},
                                  headers=FULL)
        auth = data.get("purchase_units", [{}])[0].get("payments", {}).get("authorizations", [{}])[0]
        return {"authorization_id": auth.get("id"), "status": auth.get("status"), "raw": data}

    async def capture(self, payment):
        # Checked against PayPal's docs: capture a held authorization with /v2/payments/authorizations/{id}/capture
        # (any amount up to the authorized total), or capture an approved CAPTURE-intent order directly.
        order_id = payment.get("provider_order_id")
        auth_id = payment.get("provider_authorization_id")
        if auth_id:
            data = await self._request("POST", f"/v2/payments/authorizations/{auth_id}/capture",
                                       json_body={"amount": {"currency_code": payment["currency"], "value": f'{payment["amount"]:.2f}'}, "final_capture": True},
                                       headers=FULL)
            capture = data
        elif order_id:
            data = await self._request("POST", f"/v2/checkout/orders/{order_id}/capture", json_body={},
                                       headers=FULL)
            capture = data.get("purchase_units", [{}])[0].get("payments", {}).get("captures", [{}])[0]
        else:
            raise RailError("PayPal order or authorization ID is missing.")
        return {"capture_id": capture.get("id"), "status": capture.get("status"), "raw": data}

    async def void(self, payment):
        # Checked against PayPal's docs: only an uncaptured, unexpired, not-yet-voided authorization can be voided.
        auth_id = payment.get("provider_authorization_id")
        if not auth_id:
            raise RailError("No PayPal authorization ID is recorded; cannot void.")
        data = await self._request("POST", f"/v2/payments/authorizations/{auth_id}/void", json_body={})
        return {"status": data.get("status", "VOIDED"), "raw": data}

    async def refund(self, payment):
        capture_id = payment.get("provider_capture_id")
        if not capture_id:
            raise RailError("No PayPal capture ID is recorded; cannot refund.")
        data = await self._request("POST", f"/v2/payments/captures/{capture_id}/refund", json_body={})
        return {"refund_id": data.get("id"), "status": data.get("status"), "raw": data}
