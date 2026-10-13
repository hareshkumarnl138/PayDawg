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

def test_mock_growl_authorize_and_void(client):
    client.post('/v1/payments', json={'amount':20,'customer_id':'baseline-user','description':'baseline'})
    large = client.post('/v1/payments', json={'amount':500,'customer_id':'different-user','description':'large'}).json()
    assert large['verdict'] == 'Growl'
    authorized = client.post('/v1/payments/' + large['id'] + '/approve')
    assert authorized.status_code == 200
    assert authorized.json()['status'] == 'held'
    voided = client.post('/v1/payments/' + large['id'] + '/void')
    assert voided.status_code == 200
    assert voided.json()['status'] == 'failed'

def test_event_trail_is_returned(client):
    result = client.post('/v1/payments', json={'amount':10,'customer_id':'a'}).json()
    detail = client.get('/v1/payments/' + result['id']).json()
    assert len(detail['events']) >= 2
