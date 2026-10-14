"""Regression tests for the deep-dive findings: money validation, non-finite input,
merchant scoping, fingerprint stability and text hygiene."""
from contextlib import contextmanager

import pytest

from app import config


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


def pay(client, **kw):
    body = {'amount': 18, 'customer_id': 'c1'}
    body.update(kw)
    return client.post('/v1/payments', json=body)


# ---------- money ----------
@pytest.mark.parametrize('amount', [0.001, 1e-09, 0.005, 18.005, 1234.567, 0.009])
def test_sub_cent_and_over_precise_amounts_are_rejected(client, amount):
    r = pay(client, amount=amount, customer_id='precision')
    assert r.status_code == 422
    assert 'decimal places' in str(r.json()['detail']) or 'at least' in str(r.json()['detail'])


@pytest.mark.parametrize('amount', [0.01, 18, 18.5, 18.50, '18.50', 1000000])
def test_real_money_amounts_are_accepted(client, amount):
    assert pay(client, amount=amount, customer_id='ok-%s' % amount, order_ref=str(amount)).status_code == 200


def test_captured_amount_is_exactly_what_the_rail_would_charge(client):
    stored = pay(client, amount='18.50', customer_id='exact').json()['amount']
    assert '%.2f' % stored == '18.50'


# ---------- non-finite input returns 422, not 500 ----------
@pytest.mark.parametrize('raw', [b'{"amount":NaN,"customer_id":"n"}',
                                 b'{"amount":1e999,"customer_id":"n"}',
                                 b'{"amount":-1e999,"customer_id":"n"}'])
def test_non_finite_amount_is_a_clean_422(client, raw):
    r = client.post('/v1/payments', content=raw, headers={'Content-Type': 'application/json'})
    assert r.status_code == 422
    assert 'finite' in str(r.json()['detail'])


def test_non_finite_amount_stores_nothing(client):
    client.post('/v1/payments', content=b'{"amount":NaN,"customer_id":"ghost"}', headers={'Content-Type': 'application/json'})
    assert client.get('/v1/payments').json()['payments'] == []


# ---------- text hygiene ----------
@pytest.mark.parametrize('customer', ['   ', '', 'a\u0000b', '\t\n'])
def test_blank_or_control_customer_ids_are_rejected(client, customer):
    assert pay(client, customer_id=customer).status_code == 422


def test_customer_id_is_trimmed_so_padding_is_not_a_second_customer(client):
    assert pay(client, customer_id='  padded  ').json()['customer_id'] == 'padded'


@pytest.mark.parametrize('currency', ['123', 'U$D', '12A'])
def test_non_alphabetic_currency_is_rejected(client, currency):
    assert pay(client, currency=currency, customer_id='cur').status_code == 422


def test_currency_is_accepted_in_any_case(client):
    assert pay(client, currency='usd', customer_id='cur2').json()['currency'] == 'USD'


def test_overlong_idempotency_key_is_rejected(client):
    assert client.post('/v1/payments', json={'amount': 5, 'customer_id': 'k'},
                       headers={'Idempotency-Key': 'k' * 256}).status_code == 400
    assert client.post('/v1/payments', json={'amount': 5, 'customer_id': 'k'},
                       headers={'Idempotency-Key': 'k' * 255}).status_code == 200


# ---------- fingerprint ----------
def test_fingerprint_ignores_fields_that_are_not_part_of_the_request(client):
    from app.main import request_fingerprint
    base = {'merchant_id': 'demo-merchant', 'amount': 18.0, 'currency': 'USD',
            'customer_id': 'c', 'description': 'd', 'order_ref': None}
    assert request_fingerprint(base) == request_fingerprint({**base, 'return_url': 'http://anything'})
    assert request_fingerprint(base) != request_fingerprint({**base, 'amount': 19.0})


def test_a_key_stored_by_an_older_build_gives_an_actionable_409(client):
    from app.db import db_session
    from app.models import utc_now
    now = utc_now()
    with db_session() as db:
        db.execute("""INSERT INTO payments (id,merchant_id,idempotency_key,request_hash,amount,currency,customer_id,
                      description,verdict,risk_level,reasons_json,flags_json,decision_source,status,rail,created_at,updated_at)
                      VALUES('old','demo-merchant','legacy-key','deadbeefoldstylehash',18,'USD','c1','Demo purchase',
                      'Wag','low','[]','[]','rules-only','captured','mock',?,?)""", (now, now))
    r = client.post('/v1/payments', json={'amount': 18, 'customer_id': 'c1'}, headers={'Idempotency-Key': 'legacy-key'})
    assert r.status_code == 409
    assert 'older build' in r.json()['detail'] and 'reset_demo' in r.json()['detail']


# ---------- merchant scoping ----------
@pytest.fixture()
def rival(client):
    from app.db import db_session
    from app.models import utc_now
    with db_session() as db:
        db.execute("INSERT OR IGNORE INTO merchants(id,name,created_at) VALUES('rival-shop','Rival',?)", (utc_now(),))
        db.execute("INSERT OR IGNORE INTO notebook(merchant_id,updated_at) VALUES('rival-shop',?)", (utc_now(),))
    return client.post('/v1/payments', json={'amount': 777, 'customer_id': 'rival-secret',
                                             'merchant_id': 'rival-shop', 'description': 'CONFIDENTIAL'}).json()


def test_list_does_not_leak_another_merchants_payments(client, rival):
    client.post('/v1/payments', json={'amount': 20, 'customer_id': 'mine'})
    listed = client.get('/v1/payments').json()
    assert listed['merchant_id'] == 'demo-merchant'
    assert all(p['merchant_id'] == 'demo-merchant' for p in listed['payments'])
    assert rival['id'] not in [p['id'] for p in listed['payments']]


def test_detail_and_actions_are_scoped_to_the_merchant(client, rival):
    assert client.get('/v1/payments/' + rival['id']).status_code == 404
    assert client.post('/v1/payments/' + rival['id'] + '/approve').status_code == 404
    assert client.post('/v1/payments/' + rival['id'] + '/void').status_code == 404
    assert client.get('/v1/payments/' + rival['id'], params={'merchant_id': 'rival-shop'}).status_code == 200


def test_each_merchant_has_its_own_notebook_and_duplicate_window(client, rival):
    # the rival's 777 must not make the demo merchant's 777 look normal
    first = client.post('/v1/payments', json={'amount': 20, 'customer_id': 'base'}).json()
    assert first['verdict'] == 'Wag'
    mine = client.post('/v1/payments', json={'amount': 777, 'customer_id': 'whale', 'order_ref': 'w'}).json()
    assert 'unusual_amount' in mine['flags']


# ---------- rate-limit evasion ----------
def rotate(client, n, header='X-Forwarded-For'):
    return [client.post('/v1/payments', json={'amount': 1, 'customer_id': 'spoof-%d' % i},
                        headers={header: '9.9.9.%d' % i}).status_code for i in range(n)]


def test_rotating_forwarded_headers_cannot_buy_unlimited_quota(client):
    """A client that forges a new X-Forwarded-For per request must still hit the shop-wide ceiling."""
    with override(rate_limit_attempts=5, rate_limit_global_attempts=12, rate_limit_window_seconds=10,
                  trust_proxy_headers=True):
        from app.ratelimit import limiter
        limiter.reset()
        codes = rotate(client, 20)
        assert 429 in codes, 'forged forwarding headers bypassed the limiter entirely'
        assert codes.count(200) <= 12


def test_shop_wide_lock_is_reported_and_releases(client, monkeypatch):
    from app import ratelimit
    clock = {'t': 5000.0}
    monkeypatch.setattr(ratelimit, 'monotonic', lambda: clock['t'])
    with override(rate_limit_attempts=5, rate_limit_global_attempts=8, rate_limit_lock_seconds=15,
                  trust_proxy_headers=True):
        ratelimit.limiter.reset()
        rotate(client, 12)
        status = client.get('/v1/rate-limit').json()
        assert status['locked'] is True and status['shop_wide'] is True
        clock['t'] += 16
        assert client.post('/v1/payments', json={'amount': 1, 'customer_id': 'after'}).status_code == 200


def test_forwarded_header_is_ignored_unless_trust_is_enabled():
    from app.ratelimit import client_key

    class Req:
        headers = {'x-forwarded-for': '203.0.113.9'}
        client = type('C', (), {'host': '10.0.0.1'})()

    with override(trust_proxy_headers=False):
        assert client_key(Req()) == '10.0.0.1'
    with override(trust_proxy_headers=True):
        assert client_key(Req()) == '203.0.113.9'


def test_global_ceiling_can_be_switched_off(client):
    with override(rate_limit_attempts=3, rate_limit_global_attempts=0, trust_proxy_headers=True):
        from app.ratelimit import limiter
        limiter.reset()
        assert rotate(client, 10).count(200) == 10


# ---------- dashboard wiring ----------
def test_every_demo_shop_button_has_a_scenario():
    """A button whose scenario is missing fails only when a human clicks it, so check the wiring here."""
    import re
    from pathlib import Path
    root = Path(__file__).resolve().parent.parent
    buttons = set(re.findall(r'data-sc="([a-z]+)"', (root / 'dashboard/index.html').read_text()))
    scenarios = set(re.findall(r'^\s{4}([a-z]+): async', (root / 'dashboard/demoshop.js').read_text(), re.M))
    assert buttons, 'no scenario buttons found'
    assert buttons == scenarios, f'buttons without scenarios: {buttons - scenarios}; unused scenarios: {scenarios - buttons}'


# ---------- hostile bodies cannot choose the status code ----------
def post_raw(client, raw):
    return client.post('/v1/payments', content=raw, headers={'Content-Type': 'application/json'})


def test_deeply_nested_body_is_a_422_not_a_500(client):
    r = post_raw(client, b'{"amount":' + b'[' * 3000 + b']' * 3000 + b',"customer_id":"a"}')
    assert r.status_code == 422
    assert 'nested value omitted' in str(r.json()['detail'])


def test_huge_string_in_an_error_body_is_truncated(client):
    r = client.post('/v1/payments', json={'amount': 5, 'customer_id': 'x' * 5000})
    assert r.status_code == 422
    assert len(str(r.json()['detail'])) < 2000


def test_wide_body_does_not_echo_everything(client):
    r = post_raw(client, b'{"amount":[' + b','.join(b'1' for _ in range(500)) + b'],"customer_id":"a"}')
    assert r.status_code == 422


def test_a_hostile_body_never_leaves_a_payment_behind(client):
    post_raw(client, b'{"amount":' + b'[' * 3000 + b']' * 3000 + b',"customer_id":"a"}')
    post_raw(client, b'{"amount":NaN,"customer_id":"a"}')
    client.post('/v1/payments', json={'amount': 5, 'customer_id': 'x' * 5000})
    assert client.get('/v1/payments').json()['payments'] == []


def test_oversized_body_is_refused_before_it_is_buffered(client):
    from app.main import MAX_BODY_BYTES
    big = b'{"amount":5,"customer_id":"a","description":"' + b'x' * (MAX_BODY_BYTES + 100) + b'"}'
    r = client.post('/v1/payments', content=big, headers={'Content-Type': 'application/json'})
    assert r.status_code == 413
    assert client.post('/v1/payments', json={'amount': 5, 'customer_id': 'normal'}).status_code == 200
