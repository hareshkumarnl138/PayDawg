"""The buyer's side of the PayPal redirect: browsers get a Dawg page, API clients keep getting JSON."""
import uuid
import pytest
from app.rails.mock import MockRail

HTML = {'Accept': 'text/html,application/xhtml+xml'}


class ApprovalRail(MockRail):
    """Behaves like PayPal: create() returns an approval link, so the payment waits for the buyer."""
    async def create(self, payment, intent):
        return {'order_id': 'ORD-' + uuid.uuid4().hex[:10], 'approval_url': 'https://paypal.test/approve',
                'intent': intent, 'simulated': False}


class BrokenCapture(ApprovalRail):
    async def capture(self, payment):
        raise RuntimeError('boom: secret-internal-detail')


def _history(client):
    """Two captured payments so a big one later looks unusual (Growl)."""
    for i in range(2):
        r = client.post('/v1/payments', json={'amount': 10, 'customer_id': 'regular', 'order_ref': f'h{i}'})
        assert r.json()['status'] == 'captured'


def _screened(client, monkeypatch, amount, rail=ApprovalRail, customer='buyer'):
    import app.main as m
    _history(client)
    monkeypatch.setattr(m, 'get_rail', lambda: rail())
    p = client.post('/v1/payments', json={'amount': amount, 'customer_id': customer, 'order_ref': 'live'}).json()
    assert p['status'] == 'screened', p
    return p


def test_wag_return_shows_the_happy_dawg_page(client, monkeypatch):
    p = _screened(client, monkeypatch, 11)
    assert p['verdict'] == 'Wag'
    r = client.get('/paypal/return', params={'token': p['provider_order_id']}, headers=HTML)
    assert r.status_code == 200 and r.headers['content-type'].startswith('text/html')
    assert 'data-mood="wag"' in r.text and 'Wag! All done.' in r.text
    assert client.get('/v1/payments/' + p['id']).json()['status'] == 'captured'


def test_growl_return_says_held_and_hides_the_reasons(client, monkeypatch):
    p = _screened(client, monkeypatch, 500)
    assert p['verdict'] == 'Growl'
    r = client.get('/paypal/return', params={'token': p['provider_order_id']}, headers=HTML)
    assert 'data-mood="growl"' in r.text and 'holding it' in r.text
    assert 'unusual' not in r.text.lower() and 'risk' not in r.text.lower()   # no screening logic leaks to the buyer
    assert client.get('/v1/payments/' + p['id']).json()['status'] == 'held'


def test_json_clients_still_get_json(client, monkeypatch):
    p = _screened(client, monkeypatch, 11)
    r = client.get('/paypal/return', params={'token': p['provider_order_id']})
    assert r.headers['content-type'].startswith('application/json')
    assert r.json()['status'] == 'captured'


def test_returning_twice_is_idempotent_and_never_captures_twice(client, monkeypatch):
    p = _screened(client, monkeypatch, 11)
    first = client.get('/paypal/return', params={'token': p['provider_order_id']}, headers=HTML)
    again = client.get('/paypal/return', params={'token': p['provider_order_id']}, headers=HTML)
    assert first.status_code == again.status_code == 200
    assert 'Wag! All done.' in again.text
    events = [e['event_type'] for e in client.get('/v1/payments/' + p['id']).json()['events']]
    assert events.count('paypal.buyer_approved') == 1, events   # the second visit did not settle again


def test_unknown_token_is_a_friendly_404_for_browsers_and_json_for_apis(client):
    page = client.get('/paypal/return', params={'token': 'nope'}, headers=HTML)
    assert page.status_code == 404 and 'data-mood="bark"' in page.text
    api = client.get('/paypal/return', params={'token': 'nope'})
    assert api.status_code == 404 and api.headers['content-type'].startswith('application/json')


def test_failed_capture_shows_the_apology_page_without_leaking_the_error(client, monkeypatch):
    p = _screened(client, monkeypatch, 11, rail=BrokenCapture)
    r = client.get('/paypal/return', params={'token': p['provider_order_id']}, headers=HTML)
    assert r.status_code == 502 and 'data-mood="tired"' in r.text
    assert 'secret-internal-detail' not in r.text and 'boom' not in r.text
    assert 'do not pay twice' in r.text


def test_cancel_page_and_state(client, monkeypatch):
    p = _screened(client, monkeypatch, 11)
    r = client.get('/paypal/cancel', params={'token': p['provider_order_id']}, headers=HTML)
    assert r.status_code == 200 and 'nothing was charged' in r.text
    assert client.get('/v1/payments/' + p['id']).json()['status'] == 'failed'
    assert client.get('/paypal/cancel').json()['status'] == 'cancelled'


def test_page_escapes_everything_dynamic():
    from app.pages import result_page
    html = result_page('captured', {'id': '<script>alert(1)</script>', 'amount': 5, 'currency': '"><img src=x>'})
    assert '<script>alert(1)</script>' not in html and '<img src=x>' not in html
    assert '&lt;script&gt;' in html
    assert 'data-mood="tired"' in result_page('no-such-outcome')   # unknown outcome falls back safely


def test_page_assets_are_served_by_the_app(client):
    assert client.get('/dashboard/dawg.js').status_code == 200
    assert client.get('/dashboard/dawg.css').status_code == 200
