from datetime import datetime, timezone
from app.screening.rules import evaluate_rules

def payment(amount=20, customer='c1', created_at=None):
    return {'merchant_id':'demo-merchant','amount':amount,'customer_id':customer,'created_at':created_at or datetime.now(timezone.utc).isoformat()}

def test_exact_duplicate_is_hard_block():
    p = payment()
    result = evaluate_rules(p, {'payment_count':10,'average_amount':20,'max_amount':30}, [p])
    assert result['hard_block'] is True
    assert result['risk_level'] == 'high'
    assert 'exact_duplicate' in result['flags']

def test_large_amount_is_medium_signal():
    result = evaluate_rules(payment(500,'new'), {'payment_count':20,'average_amount':20,'max_amount':30}, [])
    assert 'unusual_amount' in result['flags']
    assert result['risk_level'] == 'medium'

def test_new_customer_flag():
    result = evaluate_rules(payment(20,'new'), {'payment_count':10,'average_amount':20,'max_amount':30}, [])
    assert 'new_customer' in result['flags']
