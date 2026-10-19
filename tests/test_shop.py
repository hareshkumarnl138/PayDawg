"""The demo pet shop (app/shop.py): server-side prices, checkout through PayDawg's public API, both modes."""
from contextlib import contextmanager
import pytest
from app import config
from app.shop import CATALOG, customer_number


@contextmanager
def override(**values):
    old = {k: getattr(config.settings, k) for k in values}
    for k, v in values.items():
        object.__setattr__(config.settings, k, v)
    try:
        yield
    finally:
        for k, v in old.items():
            object.__setattr__(config.settings, k, v)


def order(client, items, email="sam@example.com", attempt="attempt-0001"):
    return client.post("/shop/api/checkout", json={"email": email, "attempt": attempt,
                                                   "items": [{"sku": s, "qty": q} for s, q in items]})


def payments(client):
    return client.get("/v1/payments").json()["payments"]


def test_shop_page_and_catalog(client):
    page = client.get("/shop")
    assert page.status_code == 200 and "Leash &amp; Larder" in page.text
    assert client.get("/shop/assets/shop.js").status_code == 200
    catalog = client.get("/shop/api/catalog").json()
    assert catalog["simulated"] is True and len(catalog["items"]) == len(CATALOG)
    assert all({"sku", "name", "price", "icon"} <= set(item) for item in catalog["items"])


def test_a_normal_order_is_priced_on_the_server_and_paid(client):
    reply = order(client, [("biscuits", 2), ("leash", 1)]).json()
    assert reply["outcome"] == "paid" and reply["total"] == "35.00" and reply["simulated"] is True
    assert reply["order"].startswith("LL-") and [l["line_total"] for l in reply["lines"]] == ["17.00", "18.00"]
    [stored] = payments(client)
    assert stored["amount"] == 35.0 and stored["order_ref"] == reply["order"] and stored["status"] == "captured"
    assert stored["customer_id"] == customer_number("sam@example.com")
    assert "sam@example.com" not in str(stored)            # PayDawg never sees the email


def test_the_browser_cannot_set_the_price(client):
    sneaky = client.post("/shop/api/checkout", json={"email": "a@b.co", "attempt": "attempt-0002", "amount": 0.01,
                                                     "items": [{"sku": "bed", "qty": 1, "price": "0.01"}]}).json()
    assert sneaky["total"] == "64.00"
    assert payments(client)[0]["amount"] == 64.0


@pytest.mark.parametrize("items", [[], [("caviar", 1)], [("bed", 0)], [("bed", 11)], [("bed", 6), ("bed", 5)]])
def test_bad_carts_are_rejected_without_a_payment(client, items):
    assert order(client, items).status_code == 422
    assert payments(client) == []


@pytest.mark.parametrize("email,attempt", [("not-an-email", "attempt-0003"), ("a@b.co", "short"), ("a@b.co", "bad attempt!")])
def test_bad_details_are_rejected(client, email, attempt):
    assert order(client, [("ball", 1)], email=email, attempt=attempt).status_code == 422


def test_attempts_with_a_common_prefix_get_different_order_numbers(client):
    a = order(client, [("ball", 1)], attempt="same-prefix-1").json()
    b = order(client, [("ball", 1)], attempt="same-prefix-2").json()
    assert a["order"] != b["order"] and b["outcome"] == "paid"


def test_retrying_the_same_checkout_never_charges_twice(client):
    first = order(client, [("rope", 1)]).json()
    again = order(client, [("rope", 1)]).json()
    assert first["order"] == again["order"] and again["outcome"] == "paid"
    assert len(payments(client)) == 1


def test_a_big_order_is_held_once_the_shop_has_history(client):
    client.post("/v1/demo/seed")
    reply = order(client, [("bed", 6)], email="new@example.com").json()
    assert reply["outcome"] == "held" and reply["total"] == "384.00"
    assert payments(client)[0]["status"] == "held"


def test_a_buyer_hammering_checkout_is_declined_by_velocity(client):
    with override(rate_limit_attempts=0):
        outcomes = [order(client, [("ball", 1)], email="speedy@example.com", attempt=f"attempt-v{i:04d}").json()["outcome"]
                    for i in range(6)]
    assert outcomes[:5] == ["paid"] * 5 and outcomes[5] == "declined"


def test_the_rate_limit_applies_to_the_buyer(client):
    with override(rate_limit_attempts=2, rate_limit_global_attempts=0):
        results = [order(client, [("ball", 1)], email=f"b{i}@example.com", attempt=f"attempt-r{i:04d}").json()
                   for i in range(3)]
    assert [r["outcome"] for r in results] == ["paid", "paid", "busy"]
    assert results[2]["retry_after"] > 0


def test_paypal_mode_sends_the_buyer_to_paypal(client, monkeypatch):
    from app.rails import paypal as pp
    calls = []

    async def fake_request(self, method, path, *, json_body=None, headers=None):
        calls.append((method, path, json_body))
        return {"id": "ORDER-123", "status": "CREATED",
                "links": [{"rel": "payer-action", "href": "https://www.sandbox.paypal.com/checkoutnow?token=ORDER-123"}]}

    monkeypatch.setattr(pp.PayPalRail, "_request", fake_request)
    with override(rail_provider="paypal", paypal_client_id="id", paypal_client_secret="secret"):
        assert client.get("/shop/api/catalog").json()["simulated"] is False
        reply = order(client, [("jacket", 1)]).json()
    assert reply["outcome"] == "redirect" and reply["url"].startswith("https://www.sandbox.paypal.com/")
    method, path, body = calls[0]
    assert path == "/v2/checkout/orders" and body["purchase_units"][0]["amount"]["value"] == "29.00"
    assert body["application_context"]["return_url"].endswith("/paypal/return")


def test_paypal_mode_bark_never_reaches_paypal(client, monkeypatch):
    from app.rails import paypal as pp
    calls = []

    async def fake_request(self, method, path, *, json_body=None, headers=None):
        calls.append(path)
        return {"id": f"ORDER-{len(calls)}", "links": [{"rel": "approve", "href": "https://www.sandbox.paypal.com/x"}]}

    monkeypatch.setattr(pp.PayPalRail, "_request", fake_request)
    with override(rail_provider="paypal", paypal_client_id="id", paypal_client_secret="secret", rate_limit_attempts=0):
        replies = [order(client, [("ball", 1)], email="loop@example.com", attempt=f"attempt-p{i:04d}").json()
                   for i in range(6)]
    assert replies[5]["outcome"] == "declined" and len(calls) == 5


def test_the_buyer_pages_link_back_to_the_shop(client):
    page = client.get("/paypal/cancel", headers={"Accept": "text/html"})
    assert 'href="/shop"' in page.text and "Back to the shop" in page.text
    with override(shop_url=""):
        assert "Back to the shop" not in client.get("/paypal/cancel", headers={"Accept": "text/html"}).text


def test_shop_endpoints_stay_out_of_the_api_docs(client):
    paths = client.get("/openapi.json").json()["paths"]
    assert not any(p.startswith("/shop") for p in paths)
