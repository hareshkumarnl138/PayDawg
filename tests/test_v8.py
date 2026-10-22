"""v8: the review ceiling, Bark after PayPal approval, the return/cancel guards, and the required email."""
from contextlib import contextmanager
from app import config
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


def events(client, pid):
    return [e["event_type"] for e in client.get("/v1/payments/" + pid).json()["events"]]


# --- the review ceiling ---------------------------------------------------------------------------------

def test_a_huge_first_order_on_a_brand_new_shop_is_held(client):
    p = pay(client, 640)                      # the Notebook has learned nothing yet, so only the ceiling can catch it
    assert p["verdict"] == "Growl" and p["status"] == "held"
    assert "large_order" in p["flags"]


def test_the_ceiling_is_a_strict_greater_than_and_can_be_switched_off(client):
    assert pay(client, 500, ref="a")["verdict"] == "Wag"
    with override(hard_review_amount=0):
        assert pay(client, 900, customer="c2", ref="b")["verdict"] == "Wag"
    with override(hard_review_amount=100):
        assert pay(client, 101, customer="c3", ref="c")["verdict"] == "Growl"


def test_a_trusted_returning_customer_cannot_wave_a_huge_payment_through(client):
    with override(hard_review_amount=450):
        for i in range(3):
            assert pay(client, 400, customer="vip", ref=f"h{i}")["status"] == "captured"
        big = pay(client, 460, customer="vip", ref="big")      # trusted discount would take 50 down to 30
    assert big["verdict"] == "Growl" and big["risk_level"] == "medium"


# --- Bark after PayPal approval -------------------------------------------------------------------------

def fake_paypal(monkeypatch):
    calls = []

    async def fake_request(self, method, path, *, json_body=None, headers=None):
        calls.append((method, path, json_body))
        n = len(calls)
        return {"id": f"ORDER-{n}", "status": "CREATED",
                "links": [{"rel": "payer-action", "href": f"https://www.sandbox.paypal.com/checkoutnow?token=ORDER-{n}"}]}

    monkeypatch.setattr(pp.PayPalRail, "_request", fake_request)
    return calls


PAYPAL = dict(rail_provider="paypal", paypal_client_id="id", paypal_client_secret="secret", rate_limit_attempts=0)


def barked(client):
    first = pay(client, 20, customer="dup", ref="same")
    assert first["status"] == "screened"
    return pay(client, 20, customer="dup", ref="same", description="again")   # exact duplicate -> Bark


def test_bark_still_shows_the_paypal_screen_but_never_moves_money(client, monkeypatch):
    calls = fake_paypal(monkeypatch)
    with override(**PAYPAL, bark_stage="after_approval"):
        second = barked(client)
        assert second["verdict"] == "Bark" and second["status"] == "blocked"
        assert second["approval_url"].startswith("https://www.sandbox.paypal.com/")
        assert calls[-1][2]["intent"] == "AUTHORIZE"                      # an order that is never captured
        page = client.get("/paypal/return", params={"token": second["provider_order_id"]}, headers=HTML)
        assert page.status_code == 200 and "Woof! Dawg says no." in page.text and 'data-mood="bark"' in page.text
        assert "duplicate" not in page.text.lower() and "risk" not in page.text.lower()
        client.get("/paypal/return", params={"token": second["provider_order_id"]}, headers=HTML)
    paths = [c[1] for c in calls]
    assert not any("capture" in p or "authorize" in p for p in paths), paths   # no money step, ever
    stored = client.get("/v1/payments/" + second["id"]).json()
    assert stored["status"] == "blocked"
    assert events(client, second["id"]).count("paypal.buyer_returned_blocked") == 1


def test_bark_json_clients_are_told_nothing_was_charged(client, monkeypatch):
    fake_paypal(monkeypatch)
    with override(**PAYPAL, bark_stage="after_approval"):
        second = barked(client)
        r = client.get("/paypal/return", params={"token": second["provider_order_id"]}).json()
    assert r["status"] == "blocked" and "Nothing was charged" in r["message"]


def test_before_paypal_stage_keeps_bark_away_from_paypal(client, monkeypatch):
    calls = fake_paypal(monkeypatch)
    with override(**PAYPAL, bark_stage="before_paypal"):
        second = barked(client)
    assert second["status"] == "blocked" and not second.get("approval_url")
    assert len(calls) == 1                                                # only the first (legitimate) order


def test_a_paypal_failure_on_a_bark_payment_just_declines_it(client, monkeypatch):
    calls = fake_paypal(monkeypatch)
    with override(**PAYPAL, bark_stage="after_approval"):
        first = pay(client, 20, customer="dup", ref="same")
        assert first["status"] == "screened"

        async def broken(self, method, path, *, json_body=None, headers=None):
            raise RuntimeError("paypal is down")
        monkeypatch.setattr(pp.PayPalRail, "_request", broken)
        second = pay(client, 20, customer="dup", ref="same", description="again")
    assert second["verdict"] == "Bark" and second["status"] == "blocked" and not second.get("approval_url")


def test_the_shop_sends_a_bark_buyer_to_paypal_then_dawg_says_no(client, monkeypatch):
    fake_paypal(monkeypatch)
    with override(**PAYPAL, bark_stage="after_approval"):
        replies = [client.post("/shop/api/checkout", json={
            "email": "loop@example.com", "attempt": f"attempt-v8{i:04d}", "items": [{"sku": "ball", "qty": 1}]}).json()
            for i in range(6)]
        assert [r["outcome"] for r in replies] == ["redirect"] * 6          # the 6th is a Bark, but looks the same
        sixth = client.get("/v1/payments").json()["payments"][0]
        assert sixth["status"] == "blocked"
        page = client.get("/paypal/return", params={"token": sixth["provider_order_id"]}, headers=HTML)
        assert "Woof! Dawg says no." in page.text and "Back to the shop" in page.text


# --- return and cancel guards ---------------------------------------------------------------------------

def test_a_return_that_arrives_while_another_is_settling_does_not_settle_again(client, monkeypatch):
    calls = fake_paypal(monkeypatch)
    with override(**PAYPAL):
        p = pay(client, 20)
        assert p["status"] == "screened"
        from app.db import db_session
        with db_session() as db:
            db.execute("UPDATE payments SET status='approved' WHERE id=?", (p["id"],))   # the first return has claimed it
        page = client.get("/paypal/return", params={"token": p["provider_order_id"]}, headers=HTML)
        assert page.status_code == 200 and "Already handled." in page.text
    assert not any("capture" in c[1] for c in calls)


def test_a_normal_return_claims_then_captures_once(client, monkeypatch):
    calls = fake_paypal(monkeypatch)
    captures = []

    async def fake_capture(self, payment):
        captures.append(payment["id"])
        return {"capture_id": "CAP-1", "simulated": False}

    monkeypatch.setattr(pp.PayPalRail, "capture", fake_capture)
    with override(**PAYPAL):
        p = pay(client, 20)
        for _ in range(3):
            client.get("/paypal/return", params={"token": p["provider_order_id"]}, headers=HTML)
        evs = events(client, p["id"])
    assert len(captures) == 1 and evs.count("paypal.buyer_returned") == 1
    assert client.get("/v1/payments/" + p["id"]).json()["status"] == "captured"


def test_a_stale_cancel_link_cannot_overwrite_a_real_result(client, monkeypatch):
    fake_paypal(monkeypatch)

    async def fake_capture(self, payment):
        return {"capture_id": "CAP-1", "simulated": False}

    monkeypatch.setattr(pp.PayPalRail, "capture", fake_capture)
    with override(**PAYPAL):
        p = pay(client, 20)
        client.get("/paypal/return", params={"token": p["provider_order_id"]}, headers=HTML)
        client.get("/paypal/cancel", params={"token": p["provider_order_id"]}, headers=HTML)
        assert client.get("/v1/payments/" + p["id"]).json()["status"] == "captured"
        q = pay(client, 21, customer="c9", ref="o9")
        client.get("/paypal/cancel", params={"token": q["provider_order_id"]}, headers=HTML)
        assert client.get("/v1/payments/" + q["id"]).json()["status"] == "failed"      # a real abandonment still counts


# --- the email is required ------------------------------------------------------------------------------

def test_the_checkout_form_has_no_prefilled_email_and_marks_it_required(client):
    page = client.get("/shop").text
    assert "sam@example.com" not in page and 'id="email"' in page and " required" in page


def test_checkout_without_a_real_email_is_refused_and_creates_no_payment(client):
    for bad in ["", "   ", "nobody", "a@b", "a b@c.com"]:
        r = client.post("/shop/api/checkout", json={"email": bad, "attempt": "attempt-em0001",
                                                    "items": [{"sku": "ball", "qty": 1}]})
        assert r.status_code == 422, bad
    assert client.post("/shop/api/checkout", json={"attempt": "attempt-em0002", "items": [{"sku": "ball", "qty": 1}]}).status_code == 422
    assert client.get("/v1/payments").json()["payments"] == []


# --- Dawg's recordings -------------------------------------------------------------------------------

def test_dog_sounds_lists_only_the_recordings_that_exist(client, tmp_path, monkeypatch):
    import app.main as m
    (tmp_path / "sounds").mkdir()
    (tmp_path / "sounds" / "bark.wav").write_bytes(b"RIFF")
    (tmp_path / "sounds" / "growl.ogg").write_bytes(b"OggS")
    (tmp_path / "sounds" / "notes.txt").write_text("not a sound")
    monkeypatch.setattr(m, "DASHBOARD", tmp_path)
    assert client.get("/dog-sounds").json() == {"bark": "bark.wav", "growl": "growl.ogg"}


def test_dog_sounds_is_empty_when_the_folder_has_no_recordings(client, tmp_path, monkeypatch):
    import app.main as m
    (tmp_path / "sounds").mkdir()
    monkeypatch.setattr(m, "DASHBOARD", tmp_path)
    assert client.get("/dog-sounds").json() == {}


def test_every_listed_recording_is_actually_served(client):
    """Works with or without real recordings in dashboard/sounds/: whatever the list names must download."""
    assert client.get("/dashboard/sounds/README.txt").status_code == 200
    for mood, name in client.get("/dog-sounds").json().items():
        assert mood in {"bark", "growl", "wag"}
        assert client.get(f"/dashboard/sounds/{name}").status_code == 200
