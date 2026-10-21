from datetime import datetime, timezone, timedelta
from app.screening.rules import evaluate_rules

def payment(amount=20, customer='c1', created_at=None, order_ref=None, status=None):
    p = {'merchant_id':'demo-merchant','amount':amount,'customer_id':customer,'created_at':created_at or datetime.now(timezone.utc).isoformat()}
    if order_ref: p['order_ref'] = order_ref
    if status: p['status'] = status
    return p

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

def test_velocity_breach_is_hard_block():
    now = datetime.now(timezone.utc)
    recent = [payment(10 + i, 'rapid', (now - timedelta(seconds=20*i)).isoformat()) for i in range(5)]
    result = evaluate_rules(payment(99, 'rapid'), {'payment_count':20,'average_amount':20,'max_amount':30,'active_hours':list(range(24))}, recent)
    assert result['hard_block'] is True
    assert result['risk_level'] == 'high'
    assert 'velocity_breach' in result['flags']


ALL_HOURS = {'payment_count':10,'average_amount':20,'max_amount':30,'active_hours':list(range(24))}

def test_repeat_purchase_with_new_order_ref_is_not_a_duplicate():
    earlier = payment(18, 'c1', order_ref='order-1', status='captured')
    result = evaluate_rules(payment(18, 'c1', order_ref='order-2'), ALL_HOURS, [earlier])
    assert 'exact_duplicate' not in result['flags']
    assert result['risk_level'] == 'low'

def test_same_order_ref_inside_window_is_duplicate():
    earlier = payment(18, 'c1', order_ref='order-1', status='captured')
    result = evaluate_rules(payment(18, 'c1', order_ref='order-1'), ALL_HOURS, [earlier])
    assert result['hard_block'] is True

def test_same_purchase_after_window_is_fine():
    old = (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat()
    earlier = payment(18, 'c1', created_at=old, status='captured')
    result = evaluate_rules(payment(18, 'c1'), ALL_HOURS, [earlier])
    assert 'exact_duplicate' not in result['flags']

def test_blocked_attempt_does_not_make_next_one_a_duplicate():
    earlier = payment(18, 'c1', status='blocked')
    result = evaluate_rules(payment(18, 'c1'), ALL_HOURS, [earlier])
    assert 'exact_duplicate' not in result['flags']

def test_four_separate_purchases_by_one_customer_are_allowed():
    now = datetime.now(timezone.utc)
    recent = [payment(18, 'c1', (now - timedelta(minutes=3 + i)).isoformat(), order_ref='o%d' % i, status='captured') for i in range(4)]
    result = evaluate_rules(payment(18, 'c1', order_ref='o4'), ALL_HOURS, recent)
    assert result['hard_block'] is False

def test_velocity_is_per_customer_not_per_shop():
    now = datetime.now(timezone.utc)
    recent = [payment(10 + i, 'cust-%d' % i, (now - timedelta(seconds=20*i)).isoformat()) for i in range(6)]
    result = evaluate_rules(payment(99, 'someone-else'), ALL_HOURS, recent)
    assert 'velocity_breach' not in result['flags']

def test_merchant_surge_is_a_soft_review_signal():
    now = datetime.now(timezone.utc)
    recent = [payment(1 + i, 'bot-%d' % i, (now - timedelta(seconds=5*i)).isoformat(), status='captured') for i in range(15)]
    result = evaluate_rules(payment(2, 'bot-new'), ALL_HOURS, recent)
    assert 'merchant_surge' in result['flags']
    assert result['hard_block'] is False
    assert result['risk_level'] == 'medium'

def test_bulk_order_of_four_is_not_unusual():
    notebook = {'payment_count':1,'average_amount':18,'max_amount':18,'active_hours':list(range(24))}
    earlier = payment(18, 'c1', status='captured', created_at=(datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat())
    result = evaluate_rules(payment(72, 'c1', order_ref='bulk'), notebook, [earlier])
    assert 'unusual_amount' not in result['flags']

def test_one_soft_flag_alone_stays_low_and_two_review():
    only_new = evaluate_rules(payment(20, 'new'), ALL_HOURS, [])
    assert only_new['risk_level'] == 'low'
    night = dict(ALL_HOURS, active_hours=[], payment_count=20)   # enough sales for Dawg to judge the hour
    both = evaluate_rules(payment(20, 'new'), night, [])
    assert both['risk_level'] == 'medium'

def test_returning_customer_lowers_score():
    night = dict(ALL_HOURS, active_hours=[], payment_count=20)   # enough sales for Dawg to judge the hour
    earlier = payment(20, 'c1', created_at=(datetime.now(timezone.utc) - timedelta(minutes=30)).isoformat(), status='captured')
    result = evaluate_rules(payment(20, 'c1', order_ref='x'), night, [earlier])
    assert result['risk_score'] == 0 or result['risk_level'] == 'low'


def test_failed_attempt_does_not_make_the_retry_a_duplicate():
    earlier = payment(18, 'c1', status='failed')
    result = evaluate_rules(payment(18, 'c1'), ALL_HOURS, [earlier])
    assert 'exact_duplicate' not in result['flags']
