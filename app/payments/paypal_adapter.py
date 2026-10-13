"""PayPal Sandbox REST adapter. Only enabled when explicitly configured.

This adapter intentionally does not claim a payment is captured on order creation.
Buyer approval and PayPal's verified server-side state transitions are required.
"""
import base64
from typing import Any
import httpx
from app.config import get_settings


class PayPalConfigurationError(RuntimeError):
    pass


class PayPalAPIError(RuntimeError):
    pass


class PayPalAdapter:
    def __init__(self) -> None:
        self.settings = get_settings()
        self.base_url = self.settings.paypal_base_url.rstrip("/")

    @property
    def enabled(self) -> bool:
        return bool(self.settings.paypal_enabled and self.settings.paypal_client_id and self.settings.paypal_client_secret and "sandbox" in self.base_url)

    async def _access_token(self) -> str:
        if not self.enabled:
            raise PayPalConfigurationError("PayPal Sandbox is disabled or credentials are missing")
        auth = base64.b64encode(f"{self.settings.paypal_client_id}:{self.settings.paypal_client_secret}".encode()).decode()
        async with httpx.AsyncClient(timeout=12.0) as client:
            response = await client.post(f"{self.base_url}/v1/oauth2/token", headers={"Authorization": f"Basic {auth}", "Content-Type": "application/x-www-form-urlencoded"}, data={"grant_type": "client_credentials"})
        if response.is_error:
            raise PayPalAPIError(f"PayPal token request failed ({response.status_code})")
        return response.json()["access_token"]

    async def create_order(self, *, amount: str, currency: str, intent: str = "CAPTURE", return_url: str, cancel_url: str, request_id: str) -> dict[str, Any]:
        token = await self._access_token()
        payload = {"intent": intent, "purchase_units": [{"reference_id": request_id, "amount": {"currency_code": currency, "value": amount}}], "application_context": {"return_url": return_url, "cancel_url": cancel_url, "user_action": "PAY_NOW"}}
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.post(f"{self.base_url}/v2/checkout/orders", headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json", "PayPal-Request-Id": request_id}, json=payload)
        if response.is_error:
            raise PayPalAPIError(f"PayPal order creation failed ({response.status_code})")
        return response.json()

    async def capture_order(self, order_id: str, request_id: str) -> dict[str, Any]:
        token = await self._access_token()
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.post(f"{self.base_url}/v2/checkout/orders/{order_id}/capture", headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json", "PayPal-Request-Id": request_id}, json={})
        if response.is_error:
            raise PayPalAPIError(f"PayPal capture failed ({response.status_code})")
        return response.json()

    async def get_order(self, order_id: str) -> dict[str, Any]:
        token = await self._access_token()
        async with httpx.AsyncClient(timeout=12.0) as client:
            response = await client.get(f"{self.base_url}/v2/checkout/orders/{order_id}", headers={"Authorization": f"Bearer {token}"})
        if response.is_error:
            raise PayPalAPIError(f"PayPal order lookup failed ({response.status_code})")
        return response.json()

    async def verify_webhook_signature(self, headers: dict[str, str], event: dict) -> bool:
        if not self.settings.paypal_webhook_id:
            return False
        token = await self._access_token()
        payload = {"auth_algo": headers.get("paypal-auth-algo"), "cert_url": headers.get("paypal-cert-url"), "transmission_id": headers.get("paypal-transmission-id"), "transmission_sig": headers.get("paypal-transmission-sig"), "transmission_time": headers.get("paypal-transmission-time"), "webhook_id": self.settings.paypal_webhook_id, "webhook_event": event}
        async with httpx.AsyncClient(timeout=12.0) as client:
            response = await client.post(f"{self.base_url}/v1/notifications/verify-webhook-signature", headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"}, json=payload)
        return response.is_success and response.json().get("verification_status") == "SUCCESS"
