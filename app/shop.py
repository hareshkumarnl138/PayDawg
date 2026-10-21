"""Leash & Larder: a demo pet shop whose checkout runs through PayDawg.

It plays the part of a merchant's own website:
  * Prices live here on the server, so a buyer cannot change what they pay from the browser.
  * It talks to PayDawg only through the public API (POST /v1/payments), exactly as a shop on its own
    server would, and never reads PayDawg's database. The call below runs in-process; a separate shop would
    make the identical request with httpx.AsyncClient(base_url="https://your-paydawg-server").
  * PayDawg gets a stable customer number, never the buyer's email.
In mock mode the payment is SIMULATED. In paypal mode the buyer approves it on the PayPal sandbox and comes
back through PayDawg's /paypal/return page.
"""
import hashlib
import re
from decimal import Decimal
from pathlib import Path

import httpx
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field, field_validator

from app.config import settings
from app.ratelimit import client_key

SHOP_DIR = Path(__file__).resolve().parent.parent / "shop"
SHOP_NAME = "Leash & Larder"
MERCHANT_ID = "demo-merchant"
CURRENCY = "USD"            # the PayPal sandbox business account takes USD
MAX_QTY = 10
MAX_LINES = 20
ORDER_PREFIX = "LL-"

CATALOG = {
    "biscuits": {"name": "Peanut butter biscuits", "detail": "500 g bag", "price": "8.50", "icon": "bone"},
    "salmon": {"name": "Salmon training treats", "detail": "200 g pouch", "price": "6.75", "icon": "fish"},
    "ball": {"name": "Rubber fetch ball", "detail": "Floats, 7 cm", "price": "7.25", "icon": "ball"},
    "rope": {"name": "Rope tug toy", "detail": "Cotton, 40 cm", "price": "12.00", "icon": "rope"},
    "leash": {"name": "Reflective leash", "detail": "1.8 m, padded handle", "price": "18.00", "icon": "leash"},
    "bowls": {"name": "Steel bowl pair", "detail": "Two 750 ml bowls", "price": "22.00", "icon": "bowl"},
    "jacket": {"name": "Rain jacket", "detail": "Size M, reflective trim", "price": "29.00", "icon": "coat"},
    "bed": {"name": "Orthopedic bed", "detail": "90 x 70 cm, washable cover", "price": "64.00", "icon": "bed"},
}

router = APIRouter(prefix="/shop", include_in_schema=False)


class Line(BaseModel):
    sku: str = Field(max_length=32)
    qty: int = Field(ge=1, le=MAX_QTY)


class Checkout(BaseModel):
    email: str = Field(min_length=3, max_length=254)
    items: list[Line] = Field(min_length=1, max_length=MAX_LINES)
    # One checkout attempt, made by the page. Retrying the same attempt can never charge twice.
    attempt: str = Field(pattern=r"^[A-Za-z0-9-]{8,64}$")

    @field_validator("email")
    @classmethod
    def _email(cls, value):
        value = value.strip().lower()
        if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", value):
            raise ValueError("enter an email address like name@example.com")
        return value


def customer_number(email: str) -> str:
    """The same email always gives the same customer number, so Dawg recognises a returning buyer."""
    return "shopper-" + hashlib.sha256(email.encode()).hexdigest()[:10]


def price(items: list[Line]) -> tuple[list[dict], Decimal]:
    """Merge repeated items and price everything from the catalog."""
    qty: dict[str, int] = {}
    for line in items:
        if line.sku not in CATALOG:
            raise HTTPException(422, "That item is not in the shop any more. Refresh the page and try again.")
        qty[line.sku] = qty.get(line.sku, 0) + line.qty
    lines, total = [], Decimal("0")
    for sku, count in qty.items():
        if count > MAX_QTY:
            raise HTTPException(422, f"You can order at most {MAX_QTY} of each item.")
        unit = Decimal(CATALOG[sku]["price"])
        total += unit * count
        lines.append({"sku": sku, "name": CATALOG[sku]["name"], "qty": count,
                      "unit": f"{unit:.2f}", "line_total": f"{unit * count:.2f}"})
    return lines, total


@router.get("")
def shop_page():
    return FileResponse(SHOP_DIR / "index.html")


@router.get("/api/catalog")
def catalog():
    return {"shop": SHOP_NAME, "currency": CURRENCY, "mode": settings.rail_provider,
            "simulated": settings.rail_provider == "mock", "max_qty": MAX_QTY,
            "items": [{"sku": sku, **item} for sku, item in CATALOG.items()]}


@router.post("/api/checkout")
async def checkout(order: Checkout, request: Request):
    lines, total = price(order.items)
    # The order number comes from a hash of the whole attempt: stable when the same checkout is retried,
    # and two different attempts cannot share one (which would look like a double-click to the rules).
    ref = ORDER_PREFIX + hashlib.sha256(order.attempt.encode()).hexdigest()[:8].upper()
    summary = ", ".join(f'{line["qty"]} x {line["name"]}' for line in lines)
    payment = {"merchant_id": MERCHANT_ID, "amount": float(total), "currency": CURRENCY,
               "customer_id": customer_number(order.email),
               "description": f"{SHOP_NAME} order {ref}: {summary}"[:255], "order_ref": ref}
    receipt = {"order": ref, "lines": lines, "total": f"{total:.2f}", "currency": CURRENCY,
               "simulated": settings.rail_provider == "mock"}

    # The buyer's address goes with the request, so PayDawg's rate limit applies to each buyer, not to the shop.
    transport = httpx.ASGITransport(app=request.app, client=(client_key(request), 0))
    try:
        async with httpx.AsyncClient(transport=transport, base_url="http://paydawg.internal", timeout=60) as gateway:
            reply = await gateway.post("/v1/payments", json=payment,
                                       headers={"Idempotency-Key": "shop-" + order.attempt})
    except httpx.HTTPError:
        return {**receipt, "outcome": "unavailable"}
    if reply.status_code == 429:
        return {**receipt, "outcome": "busy", "retry_after": int(reply.headers.get("retry-after") or 15)}
    if reply.status_code in (404, 502, 503):
        return {**receipt, "outcome": "unavailable"}
    if reply.status_code != 200:
        return {**receipt, "outcome": "error"}
    paid = reply.json()
    status, url = paid.get("status"), paid.get("approval_url")
    # A retried attempt replays the original payment, so check what already happened before redirecting.
    outcome = {"blocked": "declined", "captured": "paid", "held": "held"}.get(status)
    if status == "blocked" and url:
        # BARK_STAGE=after_approval: the buyer still sees PayPal's approve screen. Dawg stops the payment when
        # PayPal sends them back, and nothing is charged. The shop does not say why this one is different.
        outcome = "redirect"
    elif outcome is None:
        outcome = "redirect" if status == "screened" and url else "error"
    result = {**receipt, "outcome": outcome}
    if outcome == "redirect":
        result["url"] = url
    return result
