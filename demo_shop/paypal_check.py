"""Guided check of the REAL PayPal sandbox flow (needs PAYPAL_MODE=paypal and sandbox credentials in .env).

  python demo_shop/paypal_check.py wag     a small payment from a new customer  -> expect Wag, captured
  python demo_shop/paypal_check.py growl   then a big one from another customer -> expect Growl, held
  python demo_shop/paypal_check.py bark    the same order sent twice            -> expect Bark, blocked

Run `wag` first so the shop has history, then `growl`. Use USD: a sandbox account usually cannot take INR.
Set ADMIN_TOKEN in this terminal if the server has one. It also works in mock mode (no approval step).
"""
import json
import os
import sys
import time
import urllib.request
from urllib.error import HTTPError

BASE = os.getenv('PAYDAWG_URL', 'http://127.0.0.1:8000')
TOKEN = os.getenv('ADMIN_TOKEN', '')


def call(method, path, body=None):
    headers = {'Content-Type': 'application/json'}
    if TOKEN:
        headers['X-Admin-Token'] = TOKEN
    req = urllib.request.Request(BASE + path, data=json.dumps(body).encode() if body is not None else None,
                                 headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=40) as r:
            return json.loads(r.read().decode())
    except HTTPError as exc:
        print(f'\n{method} {path} failed: HTTP {exc.code}\n{exc.read().decode()[:400]}')
        if exc.code == 401:
            print('The server has an ADMIN_TOKEN. Set the same value in this terminal first.')
        if exc.code == 502:
            print('502 = PayPal refused or could not be reached. Check the server terminal and your sandbox credentials.')
        raise SystemExit(1)


def pay(amount, customer, order_ref):
    return call('POST', '/v1/payments', {'amount': amount, 'currency': 'USD', 'customer_id': customer,
                                         'description': 'PayDawg sandbox check', 'order_ref': order_ref})


def follow(p):
    print(f"\nDawg says: {p['verdict']}   status: {p['status']}   id: {p['id']}")
    print('Why:', '; '.join(p.get('reasons') or []) or '-')
    if p['status'] == 'blocked':
        if p.get('approval_url'):
            print('Blocked. A buyer may still see the PayPal approve screen, but Dawg never authorizes or captures it, so no money moves.')
            print('Try it: open ' + p['approval_url'] + ' with a sandbox buyer, approve, and Dawg says no when PayPal sends you back.')
        else:
            print('Blocked before PayPal: no order was created and no money moved.')
        return
    if p.get('approval_url'):
        print('\n1) Open this link in your browser:\n\n   ' + p['approval_url'])
        print('\n2) Log in with a PayPal SANDBOX BUYER account (developer.paypal.com > Testing Tools > Sandbox Accounts)')
        print('3) Approve the payment. Waiting here (up to 5 minutes)...')
        for _ in range(100):
            time.sleep(3)
            p = call('GET', '/v1/payments/' + p['id'])
            if p['status'] != 'screened':
                break
        else:
            print('Still waiting for approval. Check the browser, then look at the dashboard.')
            return
        print(f"\nAfter approval -> status: {p['status']}")
    if p['status'] == 'held':
        choice = input('\nThe money is held at PayPal. Type  capture  or  void  (Enter to skip): ').strip().lower()
        if choice in ('capture', 'void'):
            p = call('POST', f"/v1/payments/{p['id']}/" + ('approve' if choice == 'capture' else 'void'))
            print('Final status:', p['status'])
    print('\nDone. Check the dashboard and the events list for this payment.')


if __name__ == '__main__':
    mode = (sys.argv[1] if len(sys.argv) > 1 else '').lower()
    stamp = str(int(time.time()))
    if mode == 'wag':
        follow(pay(11, 'sandbox-regular', 'sbx-' + stamp))
    elif mode == 'growl':
        follow(pay(500, 'sandbox-newcomer-' + stamp[-4:], 'sbx-' + stamp))
    elif mode == 'bark':
        pay(7, 'sandbox-twice', 'sbx-dup-' + stamp)
        follow(pay(7, 'sandbox-twice', 'sbx-dup-' + stamp))
    else:
        print(__doc__)
