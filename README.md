# PayDawg

PayDawg is a small FastAPI payment-screening MVP. Verdicts are **Wag** (low risk), **Growl** (review/authorization), and **Bark** (block). It is a learning/demo project, not a production fraud system.

## Safety and scope

- Default rail is `PAYPAL_MODE=mock`. **SIMULATED:** mock transactions never contact PayPal or move money.
- The PayPal adapter is intended for PayPal **Sandbox only**. Never use live credentials.
- UPI is a **SIMULATED stub only**; no UPI or bank integration exists.
- LLM analysis is optional. Default `LLM_PROVIDER=none` uses deterministic rules only. The AI can ask for a review (Growl) but **can never block a payment**: only the deterministic hard rules produce a Bark, and the AI cannot override them.
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

**Windows without git:** on GitHub click **Code > Download ZIP**, extract it, and double-click `start.bat`. It creates the virtual environment, installs the requirements, copies `.env.example` to `.env` and starts the server (needs Python 3.11+ installed).

## Run mock mode

Keep `PAYPAL_MODE=mock` in `.env`, then run:

```bash
uvicorn app.main:app --reload
```

Open http://127.0.0.1:8000 for the dashboard and http://127.0.0.1:8000/docs for API docs.

**SIMULATED buyer approval:** mock mode has no real buyer, so the buyer-approval step is simulated when a payment is created. A **Wag** is captured immediately; a **Growl** is authorized and **held** until the merchant clicks **Capture** or **Void** on the dashboard; a **Bark** is blocked and no order is created.

**Meet Dawg.** The dashboard has a mascot, a German Shepherd who talks (text bubble plus best-effort browser text-to-speech) and changes face for Wag, Growl and Bark. He trots in to speak, can be dragged out of the way, and the Capture/Void buttons glow when a Growl is waiting. In mock mode a **Demo shop** panel on the dashboard sends real requests to the API (normal purchase, buy again, bulk, double-click, card-testing burst, and more) so you can watch the rules work without a script.

**Rate limit ("too many tries tire the Dawg").** One client may send `RATE_LIMIT_ATTEMPTS` (12) payment requests per `RATE_LIMIT_WINDOW_SECONDS` (10), and the whole shop `RATE_LIMIT_GLOBAL_ATTEMPTS` (120). The next one gets **HTTP 429** with a `Retry-After` header, and the Dawg falls asleep behind a "Beware of DAWGS" sign for `RATE_LIMIT_LOCK_SECONDS` (15). Responses carry `X-RateLimit-Limit` and `X-RateLimit-Remaining`. `GET /v1/rate-limit` reports the lock, and `POST /v1/demo/reset` (mock mode only) clears demo data. State is in memory per process; set `RATE_LIMIT_ATTEMPTS=0` to disable.

Payment statuses: `created`, `screened`, `blocked` (Bark), `held` (Growl authorized), `approved`, `captured`, `voided`, `refunded`, `failed`. The merchant's Notebook (usual amounts) only learns from payments that are **captured**, never from held, voided or blocked ones.

## How screening works

Modelled on how real gateways behave (duplicate-transaction windows, per-card velocity limits, review-vs-block, risk scores):

- **Hard Bark** (the optional AI can neither create nor override these):
  - *Exact duplicate*: same customer, amount and `order_ref` within `DUPLICATE_WINDOW_SECONDS` (default 120). A double-click or replayed request. Send a **new `order_ref`** for a genuine repeat purchase and it is not a duplicate.
  - *Velocity*: one customer making `VELOCITY_LIMIT` (5) or more payments inside `VELOCITY_WINDOW_MINUTES` (10).
- **Soft signals** add to a 0-100 risk score; 40 or more is a **Growl** (authorize and hold): unusual amount (50), merchant-wide surge of `MERCHANT_SURGE_LIMIT` (15) payments in the window (40, a card-testing pattern), new customer (20), odd hour (20). A customer with an earlier captured payment gets a 20-point discount.
- A bulk order is a single payment with a bigger amount: buying 4 x 18 as 72 is not unusual, because the threshold is 5x the shop average (or 2x its largest payment).
- An *idempotency key* is different from `order_ref`: the same key returns the original result (safe retries); a new `order_ref` is a new purchase.

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

**Upgrading an existing database:** idempotency fingerprints changed in this version, so re-running the demo against a `paydawg.sqlite3` created by an older build answers `409` and says so. Run `python demo_shop/reset_demo.py` once (mock mode) and carry on.

Tests use a temporary SQLite database and mock rail; they do not contact PayPal or an LLM.

## PayPal Sandbox (the real thing)

Everything above runs in mock mode. To drive PayPal's real sandbox:

1. On developer.paypal.com, open **Apps & Credentials** with **Sandbox** selected, create an app, and copy its Client ID and Secret.
2. In `.env` set `PAYPAL_MODE=paypal`, `PAYPAL_CLIENT_ID`, `PAYPAL_CLIENT_SECRET`, keep `PAYPAL_BASE_URL=https://api-m.sandbox.paypal.com`, and set an `ADMIN_TOKEN` (without one the server starts but warns that anyone who can reach it can capture or void payments). Never commit credentials.
3. Restart the server, then in a second terminal (same `ADMIN_TOKEN` in that terminal):

```bash
python demo_shop/paypal_check.py wag     # small payment -> Wag, you approve it in the browser, it is captured
python demo_shop/paypal_check.py growl   # big payment from a new customer -> Growl, held; you choose capture or void
python demo_shop/paypal_check.py bark    # same order twice -> Bark, blocked before PayPal
```

The script prints PayPal's approval link. Open it, log in with a **sandbox buyer** account (Testing Tools > Sandbox Accounts), approve, and PayPal sends the buyer back to `PUBLIC_BASE_URL/paypal/return`, which shows Dawg's result page. Use **USD**: sandbox accounts usually cannot take INR.

**What the buyer sees.** `/paypal/return` and `/paypal/cancel` render a small Dawg page in a browser (Wag: charged; Growl: held for the shop; cancel: nothing charged; unknown link; failed last step). Scripts and API clients still get JSON. The page never shows screening reasons or risk scores.

**Checked against PayPal's docs** (Orders v2): create order with `PayPal-Request-Id`, authorize after buyer approval, capture of an authorization or an approved order, void, refund, and the webhook-verification request fields. The adapter asks for PayPal's full response (`Prefer: return=representation`) because the default minimal reply may omit the authorization details. Our requests are verified against a fake PayPal in `tests/test_paypal_rail.py`; whether PayPal's real servers accept them is what `paypal_check.py` is for.

Webhooks (optional): create a sandbox webhook pointing at `PUBLIC_BASE_URL/webhooks/paypal` (needs a public https address, for example a tunnel), and set `PAYPAL_WEBHOOK_ID`. The Capture and Void buttons do not depend on webhooks.

This is a hackathon MVP, not production software.

## Deploying it

- Run `uvicorn app.main:app --host 0.0.0.0 --port $PORT --no-proxy-headers`. uvicorn honours `X-Forwarded-For` from allowed peers **by default**, and a forged one would otherwise earn its sender a fresh rate-limit quota. Behind a proxy you control, instead run with `--forwarded-allow-ips=<proxy ip>` and set `TRUST_PROXY_HEADERS=true` so the limiter keys on the real client.
- `RATE_LIMIT_GLOBAL_ATTEMPTS` (120 per window) is a shop-wide ceiling, so even a client rotating its apparent address cannot create payments without limit. Set it to 0 to disable.
- Set `PUBLIC_BASE_URL` to the public https address (PayPal redirects buyers back to `PUBLIC_BASE_URL/paypal/return`).
- Set `ADMIN_TOKEN`. Without it anyone who can reach the server can list, approve or void payments. With it, the dashboard asks for the token once per browser session. Creating payments (`POST /v1/payments`) stays open because that is the merchant app's call.
- SQLite lives in `DATABASE_PATH`. Free hosts such as Render's free tier have an ephemeral disk, so the database resets on every redeploy or restart. Fine for a demo, not for real money.
- The server refuses to start with an invalid `PAYPAL_MODE`, `LLM_PROVIDER` or `MERCHANT_TIMEZONE`.
- Set `MERCHANT_TIMEZONE` (for example `Asia/Kolkata`) so the odd-hour rule uses the shop's clock, not the server's.

## The optional AI (`LLM_PROVIDER`)

`ollama` calls a local Ollama server. `http_api` posts `{"model", "input": {payment, baseline, flags}, "response_format": {"type": "json_object"}}` to `LLM_HTTP_API_URL` and expects JSON `{"risk_level": "low|medium|high", "reasons": [...]}` back, either directly or as a JSON string in an `output` or `response` field. This is a simple custom contract, not the OpenAI or Anthropic API shape, so point it at a small adapter. Each call times out after `LLM_TIMEOUT_SECONDS` (10), is retried once, and then the payment falls back to rules only (the failure is logged as a warning without customer data).

## Known limits

Single-tenant console: `ADMIN_TOKEN` is one operator credential, not a per-merchant login. The read and action endpoints take a `merchant_id` (default `demo-merchant`) so shops do not see each other by accident, but anyone holding the token can pass any merchant id. Behind a reverse proxy the rate limit uses the IP uvicorn reports, so run it with `--proxy-headers` and a trusted `--forwarded-allow-ips`, or a client can hide behind a spoofed `X-Forwarded-For`. Velocity is keyed on `customer_id`, which a caller controls, so it slows a repeat customer rather than a determined attacker; the shop-wide surge rule is what catches a spread-out burst. Not production software. Money is stored as floating-point numbers (fine for two-decimal currencies; zero-decimal currencies such as JPY are untested). The rate limiter and idempotency checks are per process. The PayPal sandbox authorize, capture and void flow and webhook verification follow PayPal's current docs and are tested against a fake PayPal, but have not yet been run against PayPal's real sandbox: run `demo_shop/paypal_check.py` to do that.

## Environment

See `.env.example`. Settings are read from environment variables and a local `.env` file. Never put secrets in source control.
