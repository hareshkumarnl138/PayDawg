"""v9 sweep: each test pins down a bug found by running PayDawg end to end, so it cannot come back."""
import asyncio
import json
import uuid
from contextlib import contextmanager

import httpx
import pytest

from app import config
from app.db import db_session
from app.rails import paypal as pp

HTML = {"Accept": "text/html"}


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


def pay(client, amount, customer="c1", ref="o1", **extra):
    return client.post("/v1/payments", json={"amount": amount, "customer_id": customer, "order_ref": ref, **extra}).json()


PAYPAL = dict(rail_provider="paypal", paypal_client_id="id", paypal_client_secret="secret", rate_limit_attempts=0)


@pytest.fixture()
def paypal_server(monkeypatch):
    """A fake PayPal behind httpx: counts OAuth logins and API calls, approves every order."""
    calls = {"token": 0, "api": []}

    def handler(request: httpx.Request):
        path = request.url.path
        if path == "/v1/oauth2/token":
            calls["token"] += 1
            return httpx.Response(200, json={"access_token": "tok-%d" % calls["token"], "expires_in": 32400})
        calls["api"].append(path)
        if path == "/v2/checkout/orders":
            oid = "ORD" + uuid.uuid4().hex[:8]
            return httpx.Response(200, json={"id": oid, "status": "CREATED", "links": [
                {"rel": "payer-action", "href": "https://www.sandbox.paypal.com/checkoutnow?token=" + oid}]})
        if path.endswith("/capture"):
            return httpx.Response(200, json={"id": "X", "purchase_units": [{"payments": {"captures": [{"id": "CAP1", "status": "COMPLETED"}]}}]})
        if path.endswith("/authorize"):
            return httpx.Response(200, json={"purchase_units": [{"payments": {"authorizations": [{"id": "AUTH1"}]}}]})
        return httpx.Response(404, json={})

    real = httpx.AsyncClient
    monkeypatch.setattr(pp.httpx, "AsyncClient", lambda **kw: real(transport=httpx.MockTransport(handler), **kw))
    return calls


# --- PayPal OAuth: one login, not one per call ------------------------------------------------------------

def test_a_whole_checkout_logs_in_to_paypal_once(client, paypal_server):
    with override(**PAYPAL):
        for i in range(3):
            p = pay(client, 20 + i, customer=f"c{i}", ref=f"o{i}")
            assert p["status"] == "screened"
            assert client.get("/paypal/return", params={"token": p["provider_order_id"]}).json()["status"] == "captured"
    assert len(paypal_server["api"]) == 6            # 3 creates + 3 captures
    assert paypal_server["token"] == 1, paypal_server  # it used to log in before every one of them


def test_changing_the_credentials_gets_a_fresh_login(client, paypal_server):
    with override(**PAYPAL):
        pay(client, 20, customer="a", ref="a")
    with override(**{**PAYPAL, "paypal_client_secret": "rotated"}):
        pay(client, 21, customer="b", ref="b")
    assert paypal_server["token"] == 2


# --- the AI step cannot open a gap for duplicates ---------------------------------------------------------

def insert_twin(payment):
    """What a second request would have stored while this one was waiting for the AI."""
    with db_session() as db:
        db.execute("""INSERT INTO payments (id,merchant_id,idempotency_key,request_hash,amount,currency,customer_id,description,
                      order_ref,verdict,risk_level,reasons_json,flags_json,decision_source,status,rail,created_at,updated_at)
                      VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                   (str(uuid.uuid4()), payment["merchant_id"], None, "v2:x", payment["amount"], payment["currency"],
                    payment["customer_id"], "twin", payment.get("order_ref"), "Wag", "low", "[]", "[]", "rules-only",
                    "captured", "mock", payment["created_at"], payment["created_at"]))


def test_a_double_click_that_lands_while_the_ai_thinks_is_still_barked(client, monkeypatch):
    import app.engine as engine

    async def slow_ai(payment, baseline, flags):
        insert_twin(payment)          # the other click finished first
        await asyncio.sleep(0)
        return {"analysis": {"risk_level": "low", "reasons": []}, "decision_source": "ollama"}

    monkeypatch.setattr(engine, "analyze", slow_ai)
    with override(llm_provider="ollama"):
        p = pay(client, 20, customer="clicker", ref="same")
    assert p["verdict"] == "Bark" and "exact_duplicate" in p["flags"] and p["decision_source"] == "hard-rules"


def test_without_a_twin_the_ai_verdict_stands(client, monkeypatch):
    import app.engine as engine

    async def calm_ai(payment, baseline, flags):
        return {"analysis": {"risk_level": "low", "reasons": ["fine"]}, "decision_source": "ollama"}

    monkeypatch.setattr(engine, "analyze", calm_ai)
    with override(llm_provider="ollama"):
        p = pay(client, 20, customer="calm", ref="once")
    assert p["verdict"] == "Wag" and p["decision_source"] == "ollama"


# --- Capture / Void cannot clobber each other ------------------------------------------------------------

class GatedRail:
    """A rail whose capture waits until the test lets it finish, so two requests overlap for real."""
    def __init__(self):
        self.captures, self.gate = 0, asyncio.Event()

    async def capture(self, payment):
        self.captures += 1
        await self.gate.wait()
        return {"capture_id": "CAP", "simulated": True}

    async def authorize(self, payment):
        return {"authorization_id": "AUTH", "simulated": True}


@pytest.mark.asyncio
async def test_two_retries_of_a_stuck_capture_cannot_both_run(client, monkeypatch):
    import app.main as m
    p = pay(client, 20, customer="stuck", ref="stuck")          # mock: captured straight away
    with db_session() as db:                                     # pretend the server died mid-capture long ago
        db.execute("UPDATE payments SET status='approved', updated_at='2020-01-01T00:00:00+00:00' WHERE id=?", (p["id"],))
    rail = GatedRail()
    monkeypatch.setattr(m, "get_rail", lambda: rail)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=m.app), base_url="http://testserver") as ac:
        first = asyncio.create_task(ac.post(f"/v1/payments/{p['id']}/approve"))
        await asyncio.sleep(0.05)
        try:
            # Without the claim the second request also starts a capture and waits at the gate.
            second = await asyncio.wait_for(ac.post(f"/v1/payments/{p['id']}/approve"), timeout=5)
        finally:
            rail.gate.set()
        first = await first
    assert first.status_code == 200 and first.json()["status"] == "captured"
    assert second.status_code == 409
    assert rail.captures == 1


def test_a_capture_that_fails_after_a_void_won_leaves_it_voided(client, monkeypatch):
    import app.main as m
    big = pay(client, 950, customer="stranger", ref="big")
    assert big["status"] == "held"

    class LosingRail:
        async def capture(self, payment):
            with db_session() as db:   # the merchant's other tab voided it meanwhile
                db.execute("UPDATE payments SET status='voided' WHERE id=?", (payment["id"],))
            raise RuntimeError("AUTHORIZATION_ALREADY_VOIDED")

    monkeypatch.setattr(m, "get_rail", lambda: LosingRail())
    assert client.post(f"/v1/payments/{big['id']}/approve").status_code == 502
    assert client.get("/v1/payments/" + big["id"]).json()["status"] == "voided"   # it used to flip back to "held"


# --- the buyer pages say what really happened ------------------------------------------------------------

def test_refreshing_after_a_failed_capture_keeps_the_warning(client, monkeypatch, paypal_server):
    async def broken(self, payment):
        raise RuntimeError("network dropped")

    monkeypatch.setattr(pp.PayPalRail, "capture", broken)
    with override(**PAYPAL):
        p = pay(client, 20)
        first = client.get("/paypal/return", params={"token": p["provider_order_id"]}, headers=HTML)
        again = client.get("/paypal/return", params={"token": p["provider_order_id"]}, headers=HTML)
    assert first.status_code == 502 and "tripped over a cable" in first.text
    assert again.status_code == 200 and "tripped over a cable" in again.text and "Already handled" not in again.text


def test_a_return_link_without_a_token(client):
    page = client.get("/paypal/return", headers=HTML)
    assert page.status_code == 404 and "find that" in page.text and "detail" not in page.text
    assert client.get("/paypal/return").status_code == 400


def test_an_old_cancel_link_never_claims_a_charged_payment_was_free(client, paypal_server):
    with override(**PAYPAL):
        p = pay(client, 20)
        client.get("/paypal/return", params={"token": p["provider_order_id"]})
        page = client.get("/paypal/cancel", params={"token": p["provider_order_id"]}, headers=HTML)
        api = client.get("/paypal/cancel", params={"token": p["provider_order_id"]}).json()
    assert "Wag! All done." in page.text and "nothing was charged" not in page.text
    assert api["status"] == "captured"
    assert client.get("/v1/payments/" + p["id"]).json()["status"] == "captured"


def test_a_real_cancel_still_cancels(client, paypal_server):
    with override(**PAYPAL):
        p = pay(client, 20)
        page = client.get("/paypal/cancel", params={"token": p["provider_order_id"]}, headers=HTML)
    assert "nothing was charged" in page.text
    assert client.get("/v1/payments/" + p["id"]).json()["status"] == "failed"


# --- settings that would quietly break screening are refused -----------------------------------------------

@pytest.mark.parametrize("name,value,word", [("velocity_limit", 0, "VELOCITY_LIMIT"), ("velocity_window_minutes", 0, "VELOCITY_WINDOW_MINUTES"),
                                             ("merchant_surge_limit", 0, "MERCHANT_SURGE_LIMIT"), ("bark_stage", "sometimes", "BARK_STAGE"),
                                             ("hard_review_amount", -1, "HARD_REVIEW_AMOUNT")])
def test_bad_settings_stop_the_server_with_a_clear_message(name, value, word):
    from app.main import validate_config
    with override(**{name: value}):
        with pytest.raises(RuntimeError, match=word):
            validate_config()


def test_a_typo_in_a_number_names_the_setting(monkeypatch):
    monkeypatch.setenv("VELOCITY_LIMIT", "five")
    with pytest.raises(RuntimeError, match="VELOCITY_LIMIT"):
        config._int("VELOCITY_LIMIT", "5")


def test_bark_stage_accepts_a_dash_and_credentials_lose_stray_spaces(tmp_path):
    # Settings are read once at import, so check them in a fresh Python (reloading here would split the app's settings).
    import os, subprocess, sys
    from pathlib import Path
    env = {**os.environ, "BARK_STAGE": "Before-PayPal", "PAYPAL_CLIENT_SECRET": "  sekret  ", "ADMIN_TOKEN": "tok "}
    code = "from app.config import settings as s; print(s.bark_stage, repr(s.paypal_client_secret), repr(s.admin_token))"
    out = subprocess.run([sys.executable, "-c", code], cwd=Path(__file__).resolve().parent.parent, env=env,
                         capture_output=True, text=True, timeout=60)
    assert out.stdout.split() == ["before_paypal", "'sekret'", "'tok'"], out.stderr[-400:]


# --- the dashboard's totals count everything ---------------------------------------------------------------

def test_totals_count_every_payment_not_just_the_listed_ones(client):
    with override(rate_limit_attempts=0, rate_limit_global_attempts=0):
        for i in range(103):
            pay(client, 10 + (i % 3), customer=f"t{i}", ref=f"t{i}")
    body = client.get("/v1/payments").json()
    assert len(body["payments"]) == 100
    assert body["totals"]["all"] == 103 and sum(body["totals"][v] for v in ("Wag", "Growl", "Bark")) == 103


# --- an outlier never stretches the Notebook ---------------------------------------------------------------

def test_a_trusted_customers_big_order_does_not_stretch_what_is_normal(client):
    for i in range(3):
        assert pay(client, 20, customer="vip", ref=f"h{i}")["status"] == "captured"
    big = pay(client, 400, customer="vip", ref="big")              # unusual, but a trusted customer: Wag, captured
    assert big["verdict"] == "Wag" and "unusual_amount" in big["flags"]
    nb = client.get("/v1/notebook").json()
    assert nb["biggest"] <= 100, nb                                 # learned at the "unusual" limit, not $400
    assert nb["unusual_above"] <= 200, nb                           # was $800 after one such order


# --- small irritations -------------------------------------------------------------------------------------

def test_a_blank_description_is_just_called_payment(client):
    for description in ("", "   ", None):
        r = client.post("/v1/payments", json={"amount": 5, "customer_id": f"d{description!r}", "description": description})
        assert r.status_code == 200 and r.json()["description"] == "Payment"


def test_console_actions_from_another_website_are_refused(client):
    assert client.post("/v1/demo/reset", headers={"Origin": "https://evil.example"}).status_code == 403
    assert client.post("/v1/demo/reset", headers={"Origin": "http://testserver"}).status_code == 200
    assert client.post("/v1/demo/reset").status_code == 200                       # scripts send no Origin
    with override(public_base_url="https://paydawg.example.com"):                  # behind a proxy that rewrites Host
        assert client.post("/v1/demo/reset", headers={"Origin": "https://paydawg.example.com"}).status_code == 200
    assert client.get("/v1/payments", headers={"Origin": "https://evil.example"}).status_code == 200   # reads are fine


# --- deployment and the Postman collection ------------------------------------------------------------------

def test_behind_a_proxy_the_limiter_uses_the_address_the_proxy_added():
    from app.ratelimit import client_key

    class Req:
        # the client wrote 6.6.6.6 itself; Render's proxy appended the real address
        headers = {"x-forwarded-for": "6.6.6.6, 203.0.113.9"}
        client = type("C", (), {"host": "10.0.0.1"})()

    with override(trust_proxy_headers=True):
        assert client_key(Req()) == "203.0.113.9"


def test_on_render_the_public_address_comes_from_render():
    import os, subprocess, sys
    from pathlib import Path
    root = Path(__file__).resolve().parent.parent
    code = "from app.config import settings; print(settings.public_base_url)"
    base = {k: v for k, v in os.environ.items() if k not in ("PUBLIC_BASE_URL", "RENDER_EXTERNAL_URL")}
    run = lambda extra: subprocess.run([sys.executable, "-c", code], cwd=root, env={**base, **extra},
                                       capture_output=True, text=True, timeout=60).stdout.strip()
    assert run({"RENDER_EXTERNAL_URL": "https://paydawg.onrender.com/"}) == "https://paydawg.onrender.com"
    assert run({"RENDER_EXTERNAL_URL": "https://paydawg.onrender.com", "PUBLIC_BASE_URL": "https://shop.example"}) == "https://shop.example"


def test_every_postman_request_hits_a_real_route():
    import re
    from pathlib import Path
    from app.main import app
    collection = json.loads((Path(__file__).resolve().parent.parent / "postman" / "PayDawg.postman_collection.json").read_text())
    routes = [(m, re.compile("^" + re.sub(r"\{[^}]+\}", "[^/]+", r.path) + "$")) for r in app.routes
              for m in getattr(r, "methods", None) or []]
    for item in collection["item"]:
        method = item["request"]["method"]
        path = "/" + "/".join(item["request"]["url"]["path"])
        path = re.sub(r"\{\{[^}]+\}\}", "x", path)
        assert any(m == method and rx.match(path) for m, rx in routes), (method, path)
