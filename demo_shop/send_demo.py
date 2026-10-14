"""Submit a normal payment, an out-of-pattern amount, then an exact duplicate."""
import json
import os
import urllib.request
from datetime import datetime, timezone
from urllib.error import HTTPError

BASE_URL = os.getenv('PAYDAWG_URL', 'http://127.0.0.1:8000')

def post_payment(amount, customer, key, description):
    payload = {'merchant_id':'demo-merchant','amount':amount,'currency':'USD','customer_id':customer,'description':description}
    request = urllib.request.Request(BASE_URL + '/v1/payments', data=json.dumps(payload).encode(),
        headers={'Content-Type':'application/json','Idempotency-Key':key}, method='POST')
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            return json.loads(response.read().decode())
    except HTTPError as exc:
        print('Request failed:', exc.code, exc.read().decode())
        raise

if __name__ == '__main__':
    normal = post_payment(18.50, 'demo-customer-01', 'demo-normal-001', 'Normal demo purchase')
    unusual = post_payment(950.00, 'demo-customer-02', 'demo-large-001', 'Out-of-pattern demo purchase')
    duplicate = post_payment(18.50, 'demo-customer-01', 'demo-duplicate-001', 'Repeated demo purchase')
    for label, result in (('normal', normal), ('out-of-pattern', unusual), ('duplicate', duplicate)):
        print('{}: verdict={} status={} id={}'.format(label, result['verdict'], result['status'], result['id']))
    try:
        age = (datetime.now(timezone.utc) - datetime.fromisoformat(normal['created_at'])).total_seconds()
    except (KeyError, ValueError):
        age = 0
    if age > 60:
        print('\nNote: these are REPLAYED payments from an earlier run (same idempotency keys), so nothing new '
              'was created.\nFor a fresh take in mock mode, run: python demo_shop/reset_demo.py   then run this script again.')
    if [normal['verdict'], unusual['verdict'], duplicate['verdict']] != ['Wag', 'Growl', 'Bark']:
        print('\nExpected Wag, Growl, Bark. Earlier demo payments are probably still remembered '
              '(duplicate and velocity rules, fixed idempotency keys).\n'
              'In mock mode, run: python demo_shop/reset_demo.py   then run this script again.')
