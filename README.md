# PayDawg

PayDawg is a small FastAPI payment-screening MVP. Verdicts are **Wag** (low risk), **Growl** (review/authorization), and **Bark** (block). It is a learning/demo project, not a production fraud system.

## Safety and scope

- Default rail is `PAYPAL_MODE=mock`. **SIMULATED:** mock transactions never contact PayPal or move money.
- The PayPal adapter is intended for PayPal **Sandbox only**. Never use live credentials.
- UPI is a **SIMULATED stub only**; no UPI or bank integration exists.
- LLM analysis is optional. Default `LLM_PROVIDER=none` uses deterministic rules only.
- Exact duplicates and velocity breaches are hard Bark decisions and cannot be overridden by the LLM.
- Events are append-only from the application; this is not a tamper-proof audit store.
- No user accounts, ML training, mobile app, or public refund endpoint in this MVP.

## Requirements and setup

Python 3.11+.

```bash
git clone https://github.com/hk8387121-cpu/PayDawg.git
cd PayDawg
python -m venv .venv
# Windows PowerShell:
.venv\Scripts\Activate.ps1
# macOS/Linux: source .venv/bin/activate
python -m pip install -r requirements.txt
copy .env.example .env
```

On macOS/Linux use `cp .env.example .env`. The default configuration runs without credentials.

## Run mock mode

Keep `PAYPAL_MODE=mock` in `.env`, then run:

```bash
uvicorn app.main:app --reload
```

Open http://127.0.0.1:8000 for the dashboard and http://127.0.0.1:8000/docs for API docs.

**SIMULATED buyer approval:** mock mode has no real buyer, so the buyer-approval step is simulated when a payment is created. A **Wag** is captured immediately; a **Growl** is authorized and **held** until the merchant clicks **Capture** or **Void** on the dashboard; a **Bark** is blocked and no order is created.

Payment statuses: `created`, `screened`, `blocked` (Bark), `held` (Growl authorized), `approved`, `captured`, `voided`, `refunded`, `failed`. The merchant's Notebook (usual amounts) only learns from payments that are **captured**, never from held, voided or blocked ones.

## Tests and demo

```bash
pytest
# With the app running, in a second terminal:
python demo_shop/send_demo.py
```

The demo sends a normal payment, an out-of-pattern amount, and an exact duplicate. On a fresh database the result is **Wag (captured)**, **Growl (held)**, **Bark (blocked)**. It uses different idempotency keys so the duplicate reaches screening.

The app remembers earlier payments (duplicate and velocity rules, fixed idempotency keys), so running the demo a second time just replays the same three payments. To start a fresh take, with the same `DATABASE_PATH` the server uses (mock mode only):

```bash
python demo_shop/reset_demo.py
python demo_shop/send_demo.py
```

`reset_demo.py` refuses to run unless `PAYPAL_MODE=mock` (pass `--force` to override).

Tests use a temporary SQLite database and mock rail; they do not contact PayPal or an LLM.

## PayPal Sandbox

1. Create a REST app in the PayPal Developer Dashboard's Sandbox.
2. Put its sandbox client ID and secret in `.env`; never commit credentials.
3. Set `PAYPAL_MODE=paypal` and retain `PAYPAL_BASE_URL=https://api-m.sandbox.paypal.com`.
4. Configure the sandbox webhook ID if testing webhooks.
5. Create an order and follow its buyer approval URL before attempting an operation requiring buyer approval.

**TODO before relying on live sandbox lifecycle paths:** verify current PayPal Orders v2 authorization, capture, void, refund, and webhook signature verification requirements against official developer docs. Manually test the entire sandbox lifecycle. This MVP is not production-ready.

## Environment

See `.env.example`. Settings are read from environment variables and a local `.env` file. Never put secrets in source control.
