"""Dawg's Notebook learns each shop's usual hours and pace from captured payments (app/notebook.py)."""
import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
import pytest
from app import config
from app import notebook as nb
from app.screening import rules


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


@pytest.fixture(autouse=True)
def utc_merchant():
    with override(merchant_timezone="UTC"):
        yield


def at(hour, minute=0, day=5):
    return datetime(2026, 1, day, hour, minute, tzinfo=timezone.utc)


def counts(**by_hour):
    c = [0] * 24
    for h, n in by_hour.items():
        c[int(h[1:])] = n
    return json.dumps(c)


# ---------- usual hours ----------
def test_a_new_shop_uses_the_configured_hours():
    assert nb.usual_hours({}) == set(range(9, 19))
    assert nb.learned_hours({}) == set()


def test_an_hour_is_learned_after_enough_captured_payments():
    assert nb.learned_hours({"hour_counts": counts(h20=2)}) == set()
    assert nb.learned_hours({"hour_counts": counts(h20=3)}) == {20}


def test_a_rare_hour_in_a_big_history_is_not_learned():
    # 3 payments at 03:00 out of 600 is 0.5%: still an odd hour for this shop
    assert 3 not in nb.learned_hours({"hour_counts": counts(h3=3, h12=597)})


def test_learning_only_adds_hours():
    hours = nb.usual_hours({"active_hours": "[9,10]", "hour_counts": counts(h21=10)})
    assert hours == {9, 10, 21}


def test_evening_shop_is_not_flagged_at_its_busy_hour(monkeypatch):
    payment = {"merchant_id": "m", "amount": 20, "customer_id": "c", "created_at": at(20).isoformat()}
    monkeypatch.setattr(rules, "_now", lambda: at(20, 30))
    known = {"payment_count": nb.HOURS_NEED, "average_amount": 20, "max_amount": 20}
    assert "odd_hour" in rules.evaluate_rules(payment, known, [])["flags"]
    assert "odd_hour" not in rules.evaluate_rules(payment, {**known, "hour_counts": counts(h20=5)}, [])["flags"]


def test_a_brand_new_shop_is_not_judged_on_the_hour(monkeypatch):
    # With no sales yet there are no "usual hours" to compare with, so a normal evening order is not flagged
    # (it used to be: new customer 20 + odd hour 20 = a Growl for every first-time evening customer).
    payment = {"merchant_id": "m", "amount": 20, "customer_id": "c", "created_at": at(21).isoformat()}
    monkeypatch.setattr(rules, "_now", lambda: at(21, 15))
    young = {"payment_count": nb.HOURS_NEED - 1, "average_amount": 20, "max_amount": 20}
    assert "odd_hour" not in rules.evaluate_rules(payment, young, [])["flags"]
    assert rules.evaluate_rules(payment, young, [])["risk_level"] == "low"
    assert "odd_hour" in rules.evaluate_rules(payment, {**young, "payment_count": nb.HOURS_NEED}, [])["flags"]


def test_hours_text():
    assert nb.hours_text([]) == "none yet"
    assert nb.hours_text(range(24)) == "all day"
    assert nb.hours_text([9, 10, 11]) == "09:00-11:59"
    assert nb.hours_text([7, 8, 20, 21]) == "07:00-08:59, 20:00-21:59"
    assert nb.hours_text([22, 23, 0, 1]) == "22:00-01:59"


def test_bad_stored_values_fall_back_safely():
    assert nb.hour_counts({"hour_counts": "not json"}) == [0] * 24
    assert nb.hour_counts({"hour_counts": "[1,2]"}) == [0] * 24
    assert nb.configured_hours({"active_hours": "oops"}) == set(range(9, 19))


# ---------- pace ----------
def learn_many(book, n, when, teach=True):
    for _ in range(n):
        book.update(nb.learn(book, 20.0, when.isoformat(), when, teach))
    return book


def test_a_new_shop_uses_the_configured_surge_floor():
    with override(merchant_surge_limit=15):
        assert nb.surge_limit({}, at(12)) == 15


def test_the_window_in_progress_never_raises_its_own_bar():
    book = learn_many({}, 40, at(12, 1))
    # still inside the 12:00 window: those 40 do not count yet
    assert nb.learned_peak(book, at(12, 5)) == 0
    with override(merchant_surge_limit=15):
        assert nb.surge_limit(book, at(12, 5)) == 15
        # once the window is over it is part of the shop's normal: surge = 2 x 40
        assert nb.surge_limit(book, at(12, 12)) == 80


def test_the_busiest_window_is_kept_and_fades_slowly():
    book = learn_many({}, 30, at(12, 1))
    book = learn_many(book, 5, at(12, 11))            # quieter next window
    assert nb.learned_peak(book, at(12, 15)) == pytest.approx(30 * nb.PACE_DECAY)
    a_day_later = nb.learned_peak(book, at(12, 15, day=6))
    assert 10 < a_day_later < 20                       # roughly halves in a day


def test_surge_payments_do_not_teach_pace():
    book = learn_many({}, 50, at(12, 1), teach=False)
    assert nb.learned_peak(book, at(13)) == 0
    assert book["payment_count"] == 50                 # the amounts are still learned


def test_learning_records_hour_and_amount():
    book = nb.learn({}, 30.0, at(21, 15).isoformat(), at(21, 16), True)
    assert json.loads(book["hour_counts"])[21] == 1
    assert book["payment_count"] == 1 and book["average_amount"] == 30.0 and book["max_amount"] == 30.0


def test_busy_shop_is_not_a_surge_but_a_flood_is(monkeypatch):
    now = at(12, 30)
    monkeypatch.setattr(rules, "_now", lambda: now)
    book = learn_many({"payment_count": 0}, 60, at(12, 1))          # a normal busy window of 60
    book = {**book, "active_hours": list(range(24))}
    recent = [{"merchant_id": "m", "customer_id": f"c{i}", "amount": 20, "status": "captured",
               "created_at": (now - timedelta(seconds=4 * i)).isoformat()} for i in range(70)]
    pay = {"merchant_id": "m", "amount": 20, "customer_id": "c-new", "created_at": now.isoformat()}
    assert "merchant_surge" not in rules.evaluate_rules(pay, book, recent)["flags"]
    flood = recent + [dict(r, customer_id=f"bot{i}") for i, r in enumerate(recent[:55])]
    result = rules.evaluate_rules(pay, book, flood)
    level = nb.surge_limit(book, now)
    assert 110 < level < 121                            # about 2 x 60, faded a little over 3 windows
    assert "merchant_surge" in result["flags"] and f"alert level of {level}" in " ".join(result["reasons"])


# ---------- simulated history ----------
def test_demo_history_is_a_plausible_two_weeks():
    history = nb.demo_history(at(12))
    assert sum(json.loads(history["hour_counts"])) == history["payment_count"] == history["seeded_payments"] == 600
    assert nb.usual_hours(history) == set(range(7, 23))
    with override(merchant_surge_limit=15):
        assert nb.surge_limit(history, at(12)) == 120
    assert nb.unusual_above(history) == pytest.approx(328.0)


def test_ai_baseline_carries_only_learned_amounts():
    base = nb.ai_baseline({"merchant_id": "m", "payment_count": 3, "average_amount": 9, "max_amount": 12,
                           "hour_counts": "[]", "pace_peak": 4})
    assert base == {"payment_count": 3, "average_amount": 9, "max_amount": 12}


# ---------- through the API ----------
def stored_notebook():
    from app.db import db_session
    with db_session() as db:
        return dict(db.execute("SELECT * FROM notebook WHERE merchant_id='demo-merchant'").fetchone())


def test_a_captured_payment_teaches_hours_and_pace(client):
    paid = client.post("/v1/payments", json={"amount": 20, "customer_id": "c1", "order_ref": "a"}).json()
    assert paid["status"] == "captured"
    book = stored_notebook()
    hour = nb.to_local(nb.parse_time(paid["created_at"])).hour
    assert json.loads(book["hour_counts"])[hour] == 1
    assert book["pace_count"] == 1 and book["pace_window"] == nb.window_id(datetime.now(timezone.utc))


def test_a_blocked_payment_teaches_nothing(client):
    body = {"amount": 20, "customer_id": "c1", "order_ref": "same"}
    client.post("/v1/payments", json=body)
    dup = client.post("/v1/payments", json=body).json()
    assert dup["verdict"] == "Bark"
    assert stored_notebook()["payment_count"] == 1


def test_a_surge_flagged_capture_does_not_teach_pace(client):
    from app.db import db_session, mark_captured
    with override(merchant_surge_limit=1, rate_limit_attempts=0):
        client.post("/v1/payments", json={"amount": 20, "customer_id": "a", "order_ref": "1"})
        second = client.post("/v1/payments", json={"amount": 20, "customer_id": "b", "order_ref": "2"}).json()
    assert "merchant_surge" in second["flags"]
    if second["status"] != "captured":
        with db_session() as db:
            mark_captured(db, second["id"], "test.capture")
    book = stored_notebook()
    assert book["payment_count"] == 2 and book["pace_count"] == 1


def test_notebook_endpoint_and_seed(client):
    fresh = client.get("/v1/notebook").json()
    assert fresh["learned_from"] == 0 and fresh["unusual_above"] is None
    assert fresh["surge_above"] == config.settings.merchant_surge_limit
    seeded = client.post("/v1/demo/seed").json()
    assert seeded["simulated_history"] == 600 and seeded["live_learned"] == 0
    assert seeded["surge_above"] == 120 and seeded["usual_hours_text"] == "07:00-22:59"
    assert seeded["added_hours"] == [7, 8, 19, 20, 21, 22]          # beyond the default 09:00-18:59
    normal = client.post("/v1/payments", json={"amount": 45, "customer_id": "c1", "order_ref": "n"}).json()
    big = client.post("/v1/payments", json={"amount": 384, "customer_id": "c2", "order_ref": "b"}).json()
    assert normal["verdict"] == "Wag" and big["verdict"] == "Growl" and "unusual_amount" in big["flags"]
    after = client.get("/v1/notebook").json()
    assert after["live_learned"] == 1 and after["recent_count"] == 2


def test_seed_is_mock_only_and_needs_the_admin_token(client):
    with override(rail_provider="paypal"):
        assert client.post("/v1/demo/seed").status_code == 403
    with override(admin_token="secret"):
        assert client.post("/v1/demo/seed").status_code == 401
        assert client.get("/v1/notebook").status_code == 401
        assert client.get("/v1/notebook", headers={"X-Admin-Token": "secret"}).status_code == 200
    assert client.get("/v1/notebook", params={"merchant_id": "nobody"}).status_code == 404


def test_reset_forgets_learned_hours_and_pace(client):
    client.post("/v1/demo/seed")
    assert client.post("/v1/demo/reset").status_code == 200
    book = stored_notebook()
    assert (book["payment_count"], book["hour_counts"], book["pace_peak"], book["seeded_payments"]) == (0, "[]", 0, 0)


def test_shop_wide_count_is_not_capped_at_100_rows(client):
    """The old query read only the newest 100 payments, so a learned alert level above 100 could never fire."""
    from app.db import db_session
    now = datetime.now(timezone.utc)
    with db_session() as db:
        db.execute("UPDATE notebook SET pace_peak=60, pace_window=?, payment_count=500, average_amount=30, "
                   "max_amount=150, active_hours=? WHERE merchant_id='demo-merchant'",
                   (nb.window_id(now) - 1, json.dumps(list(range(24)))))
        for i in range(125):
            ts = (now - timedelta(seconds=2 * i + 1)).isoformat()
            db.execute("INSERT INTO payments(id,merchant_id,request_hash,amount,currency,customer_id,description,verdict,"
                       "risk_level,reasons_json,flags_json,decision_source,status,rail,created_at,updated_at) "
                       "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                       (f"p{i}", "demo-merchant", "h", 20, "USD", f"c{i}", "x", "Wag", "low", "[]", "[]", "rules-only",
                        "captured", "mock", ts, ts))
    result = client.post("/v1/payments", json={"amount": 20, "customer_id": "c-late", "order_ref": "z"}).json()
    assert "merchant_surge" in result["flags"]


def test_an_old_database_gets_the_new_notebook_columns(tmp_path, monkeypatch):
    from app import db
    path = str(tmp_path / "old.sqlite3")
    conn = sqlite3.connect(path)
    conn.executescript("""
        CREATE TABLE merchants (id TEXT PRIMARY KEY, name TEXT NOT NULL, created_at TEXT NOT NULL);
        CREATE TABLE notebook (merchant_id TEXT PRIMARY KEY, payment_count INTEGER NOT NULL DEFAULT 0,
            average_amount REAL NOT NULL DEFAULT 0, max_amount REAL NOT NULL DEFAULT 0,
            active_hours TEXT NOT NULL DEFAULT '[9,10,11,12,13,14,15,16,17,18]', updated_at TEXT NOT NULL);
        INSERT INTO merchants VALUES ('demo-merchant', 'Old', '2026-01-01');
        INSERT INTO notebook(merchant_id, payment_count, average_amount, max_amount, updated_at)
            VALUES ('demo-merchant', 7, 12.5, 40, '2026-01-01');
    """)
    conn.commit()
    conn.close()
    with override(database_path=path):
        monkeypatch.setattr(db, "settings", config.settings)
        db.init_db()
        with db.db_session() as s:
            row = dict(s.execute("SELECT * FROM notebook").fetchone())
    assert row["payment_count"] == 7 and row["hour_counts"] == "[]" and row["pace_peak"] == 0
