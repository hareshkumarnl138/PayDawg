def test_health_and_create_idempotency(client):
    assert client.get('/health').json()['simulated'] is True
    payload = {'amount':25,'currency':'USD','customer_id':'customer-a','description':'test'}
    first = client.post('/v1/payments', json=payload, headers={'Idempotency-Key':'same-key'})
    second = client.post('/v1/payments', json=payload, headers={'Idempotency-Key':'same-key'})
    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json()['id'] == second.json()['id']

def test_idempotency_key_conflict(client):
    h = {'Idempotency-Key':'key-conflict'}
    assert client.post('/v1/payments', json={'amount':10,'customer_id':'a'}, headers=h).status_code == 200
    assert client.post('/v1/payments', json={'amount':11,'customer_id':'a'}, headers=h).status_code == 409

def test_duplicate_is_blocked(client):
    payload = {'amount':25,'currency':'USD','customer_id':'customer-a','description':'repeat'}
    first = client.post('/v1/payments', json=payload, headers={'Idempotency-Key':'one'}).json()
    second = client.post('/v1/payments', json=payload, headers={'Idempotency-Key':'two'}).json()
    assert first['verdict'] == 'Wag'
    assert second['verdict'] == 'Bark'
    assert second['status'] == 'blocked'

def notebook_count():
    from app.db import db_session
    with db_session() as db:
        return db.execute("SELECT payment_count FROM notebook WHERE merchant_id='demo-merchant'").fetchone()['payment_count']

def make_growl(client):
    client.post('/v1/payments', json={'amount':20,'customer_id':'baseline-user','description':'baseline'})
    large = client.post('/v1/payments', json={'amount':500,'customer_id':'different-user','description':'large'}).json()
    assert large['verdict'] == 'Growl'
    return large

def test_mock_wag_is_captured_and_teaches_notebook(client):
    wag = client.post('/v1/payments', json={'amount':20,'customer_id':'baseline-user'}).json()
    assert wag['verdict'] == 'Wag'
    assert wag['status'] == 'captured'
    assert notebook_count() == 1

def test_mock_growl_is_held_and_not_learned_until_captured(client):
    large = make_growl(client)
    assert large['status'] == 'held'
    assert notebook_count() == 1          # only the captured Wag has taught the Notebook
    captured = client.post('/v1/payments/' + large['id'] + '/approve')
    assert captured.status_code == 200
    assert captured.json()['status'] == 'captured'
    assert notebook_count() == 2

def test_approving_twice_does_not_double_count(client):
    large = make_growl(client)
    client.post('/v1/payments/' + large['id'] + '/approve')
    again = client.post('/v1/payments/' + large['id'] + '/approve')
    assert again.status_code == 409
    assert notebook_count() == 2

def test_void_is_marked_voided_and_not_learned(client):
    large = make_growl(client)
    voided = client.post('/v1/payments/' + large['id'] + '/void')
    assert voided.status_code == 200
    assert voided.json()['status'] == 'voided'
    assert notebook_count() == 1

def test_mark_captured_teaches_notebook_once(client):
    from app.db import db_session, mark_captured
    large = make_growl(client)
    with db_session() as db:
        mark_captured(db, large['id'], 'test.capture')
        mark_captured(db, large['id'], 'test.capture_again')
    assert notebook_count() == 2

def test_reset_demo_data_allows_the_demo_to_run_again(client):
    from app.db import reset_demo_data
    payload = {'amount':18.5,'customer_id':'demo-customer-01'}
    first = client.post('/v1/payments', json=payload, headers={'Idempotency-Key':'demo-normal-001'}).json()
    assert first['verdict'] == 'Wag'
    reset_demo_data()
    assert client.get('/v1/payments').json()['payments'] == []
    assert notebook_count() == 0
    again = client.post('/v1/payments', json=payload, headers={'Idempotency-Key':'demo-normal-001'}).json()
    assert again['verdict'] == 'Wag'
    assert again['id'] != first['id']

def test_event_trail_is_returned(client):
    result = client.post('/v1/payments', json={'amount':10,'customer_id':'a'}).json()
    detail = client.get('/v1/payments/' + result['id']).json()
    assert len(detail['events']) >= 2
