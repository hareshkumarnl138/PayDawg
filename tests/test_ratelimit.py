import pytest
from app import config, ratelimit


@pytest.fixture()
def limited(client):
    originals = {k: getattr(config.settings, k) for k in ('rate_limit_attempts', 'rate_limit_window_seconds', 'rate_limit_lock_seconds')}
    object.__setattr__(config.settings, 'rate_limit_attempts', 3)
    object.__setattr__(config.settings, 'rate_limit_window_seconds', 10)
    object.__setattr__(config.settings, 'rate_limit_lock_seconds', 15)
    ratelimit.limiter.reset()
    yield client
    for k, v in originals.items():
        object.__setattr__(config.settings, k, v)
    ratelimit.limiter.reset()


def send(client, i):
    return client.post('/v1/payments', json={'amount': 5 + i, 'customer_id': 'bot-%d' % i})


def test_attempt_after_the_limit_gets_429_with_retry_after(limited):
    codes = [send(limited, i).status_code for i in range(4)]
    assert codes == [200, 200, 200, 429]
    blocked = send(limited, 9)
    assert blocked.status_code == 429
    assert blocked.headers['Retry-After'] == '15' or int(blocked.headers['Retry-After']) <= 15
    assert 'resting' in blocked.json()['detail']


def test_remaining_header_counts_down(limited):
    remaining = [send(limited, i).headers['X-RateLimit-Remaining'] for i in range(3)]
    assert remaining == ['2', '1', '0']


def test_lock_ends_after_lock_seconds(limited, monkeypatch):
    clock = {'t': 1000.0}
    monkeypatch.setattr(ratelimit, 'monotonic', lambda: clock['t'])
    for i in range(4):
        send(limited, i)
    assert send(limited, 5).status_code == 429
    clock['t'] += 16
    assert send(limited, 6).status_code == 200


def test_old_attempts_age_out_of_the_window(limited, monkeypatch):
    clock = {'t': 1000.0}
    monkeypatch.setattr(ratelimit, 'monotonic', lambda: clock['t'])
    for i in range(3):
        assert send(limited, i).status_code == 200
        clock['t'] += 4
    assert send(limited, 7).status_code == 200


def test_status_endpoint_reports_the_lock(limited):
    assert limited.get('/v1/rate-limit').json()['locked'] is False
    for i in range(4):
        send(limited, i)
    status = limited.get('/v1/rate-limit').json()
    assert status['locked'] is True
    assert 1 <= status['retry_after'] <= 15


def test_limiter_can_be_switched_off(limited):
    object.__setattr__(config.settings, 'rate_limit_attempts', 0)
    assert all(send(limited, i).status_code == 200 for i in range(6))


def test_demo_reset_endpoint_clears_payments_in_mock_mode(client):
    client.post('/v1/payments', json={'amount': 10, 'customer_id': 'a'})
    assert client.post('/v1/demo/reset').json() == {'ok': True}
    assert client.get('/v1/payments').json()['payments'] == []
