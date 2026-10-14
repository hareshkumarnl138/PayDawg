"""Regression tests for the hardening pass: startup validation, admin token, capture safety,
webhook matching, idempotency race, customer history, timezone, AI cap, Notebook cap."""
from contextlib import contextmanager
from datetime import datetime, timezone, timedelta

import pytest

from app import config, ratelimit
from app.rails.base import RailError
from app.rails.mock import MockRail


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


def notebook():
    from app.db import db_session
    with db_session() as db:
        return dict(db.execute("SELECT * FROM notebook WHERE merchant_id='demo-merchant'").fetchone())


def make_growl(client, order='g1'):
    client.post('/v1/payments', json={'amount': 20, 'customer_id': 'baseline-' + order, 'order_ref': 'b-' + order})
    large = client.post('/v1/payments', json={'amount': 500, 'customer_id': 'big-' + order, 'order_ref': order}).json()
    assert large['verdict'] == 'Growl' and large['status'] == 'held'
    return large


# ---------- startup validation ----------
def test_bad_rail_mode_fails_at_startup():
    from app.main import validate_config
    with override(rail_provider='banana'):
        with pytest.raises(RuntimeError, match='PAYPAL_MODE'):
            validate_config()


def test_bad_llm_provider_and_timezone_fail_at_startup():
    from app.main import validate_config
    with override(llm_provider='gpt-nonsense'):
        with pytest.raises(RuntimeError, match='LLM_PROVIDER'):
            validate_config()
    with override(merchant_timezone='Mars/Olympus'):
        with pytest.raises(RuntimeError, match='MERCHANT_TIMEZONE'):
            validate_config()
    with override(merchant_timezone='Asia/Kolkata'):
        validate_config()


# ---------- admin token ----------
def test_admin_token_protects_the_console_but_not_payment_creation(client):
    with override(admin_token='s3cret'):
        assert client.get('/health').status_code == 200
        assert client.post('/v1/payments', json={'amount': 5, 'customer_id': 'a'}).status_code == 200
        assert client.get('/v1/payments').status_code == 401
        assert client.get('/v1/payments', headers={'X-Admin-Token': 'wrong'}).status_code == 401
        assert client.get('/v1/payments', headers={'X-Admin-Token': 's3cret'}).status_code == 200
        assert client.get('/v1/payments', headers={'Authorization': 'Bearer s3cret'}).status_code == 200
        assert client.post('/v1/demo/reset').status_code == 401
        assert client.post('/v1/payments/x/approve').status_code == 401
        assert client.post('/v1/payments/x/void').status_code == 401


def test_console_is_open_when_no_admin_token_is_set(client):
    with override(admin_token=''):
        assert client.get('/v1/payments').status_code == 200


# ---------- capture safety ----------
def test_failed_capture_puts_a_held_payment_back_so_it_can_be_retried(client, monkeypatch):
    import app.main as m
    growl = make_growl(client)

    class FailingCapture(MockRail):
        async def capture(self, payment):
            raise RailError('boom')
    monkeypatch.setattr(m, 'get_rail', lambda: FailingCapture())
    assert client.post('/v1/payments/' + growl['id'] + '/approve').status_code == 502
    assert client.get('/v1/payments/' + growl['id']).json()['status'] == 'held'
    monkeypatch.setattr(m, 'get_rail', lambda: MockRail())
    retry = client.post('/v1/payments/' + growl['id'] + '/approve')
    assert retry.status_code == 200 and retry.json()['status'] == 'captured'


def test_capture_in_progress_cannot_be_started_twice_or_voided(client):
    from app.db import db_session
    from app.models import utc_now
    growl = make_growl(client)
    with db_session() as db:
        db.execute("UPDATE payments SET status='approved', updated_at=? WHERE id=?", (utc_now(), growl['id']))
    assert client.post('/v1/payments/' + growl['id'] + '/approve').status_code == 409
    assert client.post('/v1/payments/' + growl['id'] + '/void').status_code == 409


def test_abandoned_capture_can_be_retried(client):
    from app.db import db_session
    growl = make_growl(client)
    old = (datetime.now(timezone.utc) - timedelta(minutes=10)).isoformat()
    with db_session() as db:
        db.execute("UPDATE payments SET status='approved', updated_at=? WHERE id=?", (old, growl['id']))
    done = client.post('/v1/payments/' + growl['id'] + '/approve')
    assert done.status_code == 200 and done.json()['status'] == 'captured'


def test_return_urls_come_from_public_base_url(client, monkeypatch):
    import app.main as m
    seen = {}

    class Recording(MockRail):
        async def create(self, payment, intent):
            seen.update(payment)
            return await super().create(payment, intent)
    monkeypatch.setattr(m, 'get_rail', lambda: Recording())
    with override(public_base_url='https://pay.example.com'):
        client.post('/v1/payments', json={'amount': 5, 'customer_id': 'a'})
    assert seen['return_url'] == 'https://pay.example.com/paypal/return'
    assert seen['cancel_url'] == 'https://pay.example.com/paypal/cancel'


# ---------- webhook ----------
class VerifiedRail:
    async def _request(self, *args, **kwargs):
        return {'verification_status': 'SUCCESS'}


def test_webhook_matches_on_authorization_id_and_dedupes(client, monkeypatch):
    import app.main as m
    from app.db import db_session
    growl = make_growl(client)
    with db_session() as db:
        db.execute("UPDATE payments SET provider_authorization_id='AUTH123' WHERE id=?", (growl['id'],))
    monkeypatch.setattr(m, 'get_rail', lambda: VerifiedRail())
    event = {'id': 'WH-1', 'event_type': 'PAYMENT.AUTHORIZATION.VOIDED', 'resource': {'id': 'AUTH123'}}
    with override(rail_provider='paypal', paypal_webhook_id='WEBHOOK'):
        first = client.post('/webhooks/paypal', json=event)
        again = client.post('/webhooks/paypal', json=event)
    assert first.json() == {'received': True, 'matched': True}
    assert again.json() == {'received': True, 'duplicate': True}
    assert client.get('/v1/payments/' + growl['id']).json()['status'] == 'voided'


def test_webhook_rejects_non_json_body(client, monkeypatch):
    with override(rail_provider='paypal', paypal_webhook_id='WEBHOOK'):
        bad = client.post('/webhooks/paypal', content=b'not json', headers={'Content-Type': 'application/json'})
        listy = client.post('/webhooks/paypal', json=[1, 2])
    assert bad.status_code == 400 and listy.status_code == 400


# ---------- idempotency race ----------
def _hash(amount, customer):
    from app.main import request_fingerprint
    return request_fingerprint({'merchant_id': 'demo-merchant', 'amount': float(amount), 'currency': 'USD',
                                'customer_id': customer, 'description': 'Demo purchase', 'order_ref': None})


def _inject_rival(monkeypatch, request_hash):
    """Insert a same-key payment between the idempotency check and the insert, as a racing request would."""
    import app.main as m
    from app.db import db_session
    real = m.decide

    async def racing(payment, nb, recent):
        with db_session() as db:
            db.execute("""INSERT INTO payments (id,merchant_id,idempotency_key,request_hash,amount,currency,customer_id,description,
                          verdict,risk_level,reasons_json,flags_json,decision_source,status,rail,created_at,updated_at)
                          VALUES('rival','demo-merchant','race-key',?,30,'USD','race','Demo purchase','Wag','low','[]','[]','rules-only',
                          'captured','mock',?,?)""", (request_hash, payment['created_at'], payment['created_at']))
        return await real(payment, nb, recent)
    monkeypatch.setattr(m, 'decide', racing)


def test_idempotency_race_returns_the_winners_payment(client, monkeypatch):
    _inject_rival(monkeypatch, _hash(30, 'race'))
    r = client.post('/v1/payments', json={'amount': 30, 'customer_id': 'race'}, headers={'Idempotency-Key': 'race-key'})
    assert r.status_code == 200 and r.json()['id'] == 'rival'


def test_idempotency_race_with_a_different_request_is_a_409_not_a_500(client, monkeypatch):
    _inject_rival(monkeypatch, 'different-hash')
    r = client.post('/v1/payments', json={'amount': 30, 'customer_id': 'race'}, headers={'Idempotency-Key': 'race-key'})
    assert r.status_code == 409


# ---------- screening ----------
def test_long_standing_customer_is_not_new_after_100_other_payments(client):
    with override(rate_limit_attempts=0, merchant_surge_limit=10**6):
        client.post('/v1/payments', json={'amount': 20, 'customer_id': 'seed'})
        first = client.post('/v1/payments', json={'amount': 21, 'customer_id': 'oldtimer', 'order_ref': 'o1'}).json()
        assert first['status'] == 'captured'
        for i in range(105):
            client.post('/v1/payments', json={'amount': 20, 'customer_id': 'c%d' % i, 'order_ref': 'x%d' % i})
        again = client.post('/v1/payments', json={'amount': 22, 'customer_id': 'oldtimer', 'order_ref': 'o2'}).json()
    assert 'new_customer' not in again['flags']


def test_odd_hour_uses_the_merchant_timezone_hook(monkeypatch):
    from app.screening import rules
    base = {'merchant_id': 'demo-merchant', 'amount': 20, 'customer_id': 'c', 'created_at': datetime.now(timezone.utc).isoformat()}
    nb = {'payment_count': 0, 'average_amount': 0, 'max_amount': 0}
    monkeypatch.setattr(rules, '_now', lambda: datetime(2026, 1, 5, 3, 0, tzinfo=timezone.utc))
    assert 'odd_hour' in rules.evaluate_rules(base, nb, [])['flags']
    monkeypatch.setattr(rules, '_now', lambda: datetime(2026, 1, 5, 12, 0, tzinfo=timezone.utc))
    assert 'odd_hour' not in rules.evaluate_rules(base, nb, [])['flags']


@pytest.mark.asyncio
async def test_ai_can_request_review_but_never_block(monkeypatch):
    import app.engine as engine
    now = datetime.now(timezone.utc).isoformat()

    async def scary(*args, **kwargs):
        return {'analysis': {'risk_level': 'high', 'reasons': ['looks like a scam']}, 'decision_source': 'http_api'}
    monkeypatch.setattr(engine, 'analyze', scary)
    p = {'id': 'p', 'merchant_id': 'demo-merchant', 'amount': 10, 'currency': 'USD', 'customer_id': 'c1', 'description': 'x', 'created_at': now}
    nb = {'payment_count': 0, 'average_amount': 0, 'max_amount': 0, 'active_hours': list(range(24))}
    result = await engine.decide(p, nb, [])
    assert result['verdict'] == 'Growl'
    dup = dict(p, status='captured')
    assert (await engine.decide(p, nb, [dup]))['verdict'] == 'Bark'


# ---------- Notebook and limiter ----------
def test_big_approved_payment_teaches_the_notebook_only_up_to_the_limit(client):
    client.post('/v1/payments', json={'amount': 20, 'customer_id': 'base'})
    big = client.post('/v1/payments', json={'amount': 600, 'customer_id': 'whale', 'order_ref': 'w'}).json()
    assert big['verdict'] == 'Growl'
    client.post('/v1/payments/' + big['id'] + '/approve')
    nb = notebook()
    assert nb['payment_count'] == 2
    assert nb['max_amount'] == pytest.approx(100.0)       # 20 average x 5, not 600
    assert nb['average_amount'] == pytest.approx(60.0)


def test_limiter_memory_is_bounded(monkeypatch):
    clock = {'t': 1000.0}
    monkeypatch.setattr(ratelimit, 'monotonic', lambda: clock['t'])
    limiter = ratelimit.RateLimiter()
    with override(rate_limit_global_attempts=0):      # per-client buckets only, so they all accumulate
        for i in range(1200):
            limiter.hit('ip-%d' % i)
        assert len(limiter.hits) >= 1200
        clock['t'] += 60
        limiter.hit('fresh')
        assert len(limiter.hits) < 5
