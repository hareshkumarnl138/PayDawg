# PayDawg

PayDawg is a payment gateway that thinks before it charges. It sits between a shop and PayPal and gives every payment a verdict before any money moves: **Wag** (charge it), **Growl** (authorize and hold it until the merchant captures or voids it) or **Bark** (block it, nothing is charged). It is a hackathon MVP running on the PayPal Sandbox, not a production fraud system.

## How PayDawg uses PayPal and AI

**PayPal (REST API, Sandbox).** PayDawg talks to PayPal's [Orders v2](https://developer.paypal.com/docs/api/orders/v2/) and Payments v2 APIs on the Sandbox (`app/rails/paypal.py`):
- **OAuth 2.0** client-credentials login; the access token is reused until it expires.
- **Create order**: a Wag gets a `CAPTURE` order; a Growl, and a Bark the buyer may still see, get an `AUTHORIZE` order. Creation sends a `PayPal-Request-Id`, so a retried request cannot create a second order.
- **Buyer approval**: the buyer approves on PayPal's own page and PayPal sends them back to PayDawg's `/paypal/return` (or `/paypal/cancel`), which shows the result with Dawg.
- **Capture** an approved order (Wag), or **authorize** it and hold the money (Growl) until the merchant clicks **Capture** (capture the authorization) or **Void** (release it) in the dashboard. A Bark is never authorized or captured.
- **Webhooks** (optional): signatures are checked with PayPal's verify-webhook-signature call, and capture, refund and void events update the payment.

**AI in the product (optional).** Screening is rules-first. With `LLM_PROVIDER=ollama`, a local **Llama 3.2** model through **Ollama** (or any JSON HTTP model with `http_api`) gives a second opinion on each payment: it sees only the amount, currency, customer number, description, the shop's averages and the rule flags, and answers a risk level with plain-language reasons. The AI can ask for a review (Growl) but can **never block or charge** a payment on its own; only the deterministic hard rules produce a Bark. If the model is slow, off or answers nonsense, the rules decide alone. Payments the AI reviewed carry an **AI** tag in the dashboard. (Dawg's Notebook, which learns each shop's normal, is plain counting, not machine learning.) Details: [The optional AI](#the-optional-ai-llm_provider).

**AI in building it.** We used **Claude** (Anthropic) as an AI coding assistant for writing code and tests, reviewing it, and testing the PayPal flows against fakes.

**Tools and technologies.** Python 3.11, FastAPI, Uvicorn, Pydantic, httpx, SQLite, python-dotenv; plain HTML, CSS and JavaScript (no framework), an inline-SVG mascot and the Web Audio API for his sounds; pytest and pytest-asyncio with a fake PayPal and a fake Ollama; GitHub Actions for CI. Fonts in the demo shop are bundled under the SIL Open Font License.

**Sponsor integrations.**
- **Render:** the live demo runs on Render, deployed from the `render.yaml` blueprint in this repo (see [Deploying it](#deploying-it)).
- **Postman:** `postman/PayDawg.postman_collection.json` is a ready-made collection of the API with tests (normal payment, a held $750 payment, a double-click Bark, the console endpoints). Import it, set `baseUrl`, and run it; it passes in mock and PayPal mode (checked with Newman). Postman can also import the live OpenAPI description at `/openapi.json`.

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

**Windows without git:** on GitHub click **Code > Download ZIP**, extract it, and double-click `start.bat`. It creates the virtual environment, installs the requirements, copies `.env.example` to `.env` and starts the server (needs Python 3.11+ installed; if Python is missing it says so and where to get it).

## Run mock mode

Keep `PAYPAL_MODE=mock` in `.env`, then run:

```bash
uvicorn app.main:app --reload --no-proxy-headers
```

Open http://127.0.0.1:8000 for the dashboard, http://127.0.0.1:8000/shop for the demo pet shop and http://127.0.0.1:8000/docs for API docs.

**When Dawg barks (PayPal mode):** with `BARK_STAGE=after_approval` (the default) a Bark buyer still sees PayPal's approve screen, then Dawg stops the payment when PayPal sends them back ("Woof! Dawg says no."). Dawg creates that PayPal order as authorize-only and never authorizes or captures it, so no money moves and the buyer is not told why. `BARK_STAGE=before_paypal` is the stricter setting: a Bark never reaches PayPal at all. In the shop a Bark is declined with a neutral message; mock mode has no PayPal screen, so it declines straight away.

**SIMULATED buyer approval:** mock mode has no real buyer, so the buyer-approval step is simulated when a payment is created. A **Wag** is captured immediately; a **Growl** is authorized and **held** until the merchant clicks **Capture** or **Void** on the dashboard; a **Bark** is blocked and no order is created.

**Meet Dawg.** The dashboard has a mascot, a German Shepherd who changes face and makes a dog noise for each verdict: happy yips for Wag, a growl for Growl, and barks for Bark (synthesized in the browser, no sound files; a speaker button on his speech bubble mutes him, and browsers only allow sound after your first click or key press). A text bubble says what he found. Want real barks instead of the built-in ones? Drop CC0 or your own recordings named `bark`, `growl` and `happy` (`.ogg`, `.wav`, `.mp3` or `.m4a`) into `dashboard/sounds/` (see the README there); any missing one keeps the built-in sound. He trots in to speak, can be dragged out of the way, and the Capture/Void buttons glow when a Growl is waiting. In mock mode a **Demo shop** panel on the dashboard sends real requests to the API (normal purchase, buy again, bulk, double-click, card-testing burst, and more) so you can watch the rules work without a script.

**Rate limit.** One client may send `RATE_LIMIT_ATTEMPTS` (12) payment requests per `RATE_LIMIT_WINDOW_SECONDS` (10), and the whole shop `RATE_LIMIT_GLOBAL_ATTEMPTS` (120). The next one gets **HTTP 429** with a `Retry-After` header and is locked out for `RATE_LIMIT_LOCK_SECONDS` (15); in the shop the buyer sees "Too many payment attempts from your connection". Responses carry `X-RateLimit-Limit` and `X-RateLimit-Remaining`. `GET /v1/rate-limit` reports the lock, and `POST /v1/demo/reset` (mock mode only) clears demo data. State is in memory per process; set `RATE_LIMIT_ATTEMPTS=0` to disable.

Payment statuses: `created`, `screened` (shown as "waiting for buyer"), `blocked` (Bark), `held` (Growl authorized), `approved` (shown as "processing": a capture is running; if it never finishes, the dashboard offers **Retry capture** after 2 minutes), `captured`, `voided`, `refunded`, `failed`. The dashboard's totals count every payment, while its table shows the newest 100. The merchant's Notebook (usual amounts, hours and pace) only learns from payments that are **captured**, never from held, voided or blocked ones.

## The pet shop and live traffic

**Leash & Larder** (`/shop`) is a small demo pet shop whose checkout runs through PayDawg, so a demo is a real purchase instead of a button press. It plays the merchant's own website: prices live on its server (the browser cannot change what it pays), it talks to PayDawg only through `POST /v1/payments` like any shop would, and PayDawg gets a stable customer number, never the buyer's email. In mock mode the receipt is stamped **PAID**, **ON HOLD** or **DECLINED** straight away. With `PAYPAL_MODE=paypal` the buyer approves the payment on the PayPal sandbox and lands on Dawg's result page, which links back to the shop (`SHOP_URL`, default `/shop`; leave it empty to hide the link). Its fonts are bundled (SIL Open Font License, `shop/fonts/OFL.txt`), so it also works offline.

**Live traffic (mock mode).** With the server running, in a second window:

```bash
python demo_shop/simulate.py            # about 7 orders a minute until Ctrl+C
python demo_shop/simulate.py --review   # also captures or voids held orders, like a shop owner
```

Most orders are ordinary: returning and first-time customers buying 1-3 things from the shop's real catalog. Mixed in at random are the things Dawg is there for: an order far bigger than usual (Growl), a double-clicked Pay button (Bark) and a card tester firing quick orders of the cheapest item (Bark from the sixth). An empty shop first gets about two weeks of SIMULATED trading history in its Notebook (`POST /v1/demo/seed`, mock mode only, no payments are created), so the stream starts from a shop with a normal to compare against. `--no-history` starts from a brand-new shop instead, `--reset` clears the demo first, `--speed 2` doubles the pace and `--minutes 3` stops after three minutes. Real PayPal orders need a person to approve each one, so the simulator refuses to run in paypal mode; use the shop for that.

## How screening works

Modelled on how real gateways behave (duplicate-transaction windows, per-card velocity limits, review-vs-block, risk scores):

- **Hard Bark** (the optional AI can neither create nor override these):
  - *Exact duplicate*: same customer, amount and `order_ref` within `DUPLICATE_WINDOW_SECONDS` (default 120). A double-click or replayed request. Send a **new `order_ref`** for a genuine repeat purchase and it is not a duplicate.
  - *Velocity*: one customer making `VELOCITY_LIMIT` (5) or more payments inside `VELOCITY_WINDOW_MINUTES` (10).
- **Soft signals** add to a 0-100 risk score; 40 or more is a **Growl** (authorize and hold): unusual amount (50), large order (50), shop-wide surge (40, a card-testing pattern), new customer (20), odd hour (20). A customer with an earlier captured payment gets a 20-point discount, except on a large order, which is always held.
- **Review ceiling:** any single payment above `HARD_REVIEW_AMOUNT` (default 500, `0` turns it off) is a Growl even for a brand-new shop that has not learned a normal yet, and a returning-customer discount cannot wave it through.
- A bulk order is a single payment with a bigger amount: buying 4 x 18 as 72 is not unusual, because the threshold is 5x the shop average (or 2x its largest payment).
- An *idempotency key* is different from `order_ref`: the same key returns the original result (safe retries); a new `order_ref` is a new purchase.
- With the optional AI on, the hard rules run once more just before a payment is stored, so a double-click or a burst sent while the AI was still thinking is still caught.

**Dawg's Notebook learns each shop's normal**, from captured payments only, so the soft signals fit the shop instead of fixed demo numbers (`app/notebook.py`):

- *Unusual amount*: above `LARGE_AMOUNT_MULTIPLE` (5) times the shop's average captured payment, or twice its largest.
- *Usual hours*: the default 09:00-18:59, plus every hour in which the shop has at least 3 captured payments making up 2% or more of its sales, so an evening shop stops being flagged in the evening. Dawg only judges the hour once the shop has 20 captured payments: before that he has no idea when it is busy, and a normal evening order from a first-time customer would otherwise be held.
- *Pace*: a surge is at least twice the shop's busiest normal 10 minutes so far (that peak fades to about half over a day), and never below `MERCHANT_SURGE_LIMIT` (15), which is all a brand-new shop has to go on. The 10 minutes in progress never count, and a payment that was part of a surge, or captured long after it arrived, never teaches it. So a busy shop is not treated as an attack, and an attacker cannot raise the bar quickly: it can at most double every 10 minutes.

A brand-new shop is judged by the configured surge level (`MERCHANT_SURGE_LIMIT`) and the review ceiling, and is strict about pace until it has history; the hour is ignored until Dawg has seen 20 captured payments. An outlier never stretches what Dawg thinks is normal: a big payment teaches the Notebook only up to the "unusual" limit, whether the merchant approved it or a trusted customer made it. The dashboard's **Dawg's Notebook** panel shows what has been learned and the limits in force right now (`GET /v1/notebook`).

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

Tests use a temporary SQLite database and mock rail; they do not contact PayPal or an LLM (the AI path is tested against a fake Ollama).

## PayPal Sandbox (the real thing)

Everything above runs in mock mode. To drive PayPal's real sandbox:

1. On developer.paypal.com, open **Apps & Credentials** with **Sandbox** selected, create an app, and copy its Client ID and Secret.
2. In `.env` set `PAYPAL_MODE=paypal`, `PAYPAL_CLIENT_ID`, `PAYPAL_CLIENT_SECRET`, keep `PAYPAL_BASE_URL=https://api-m.sandbox.paypal.com`, and set an `ADMIN_TOKEN` (without one the server starts but warns that anyone who can reach it can capture or void payments). Never commit credentials.
3. Restart the server, then in a second terminal (same `ADMIN_TOKEN` in that terminal):

```bash
python demo_shop/paypal_check.py wag     # small payment -> Wag, you approve it in the browser, it is captured
python demo_shop/paypal_check.py growl   # $750 from a new customer -> Growl, held; you choose capture or void
python demo_shop/paypal_check.py bark    # same order twice -> Bark, blocked (never authorized or captured)
```

The script prints PayPal's approval link. Open it, log in with a **sandbox buyer** account (Testing Tools > Sandbox Accounts), approve, and PayPal sends the buyer back to `PUBLIC_BASE_URL/paypal/return`, which shows Dawg's result page. Use **USD**: sandbox accounts usually cannot take INR.

**What the buyer sees.** `/paypal/return` and `/paypal/cancel` render a small Dawg page in a browser (Wag: charged; Growl: held for the shop; Bark: "Woof! Dawg says no.", nothing charged; cancel: nothing charged; unknown link; failed last step). Refreshing the page, or opening an old cancel link, shows what really happened to the payment. Scripts and API clients still get JSON. The page never shows screening reasons or risk scores.

**Checked against PayPal's docs** (Orders v2): create order with `PayPal-Request-Id`, authorize after buyer approval, capture of an authorization or an approved order, void, refund, and the webhook-verification request fields. The adapter asks for PayPal's full response (`Prefer: return=representation`) because the default minimal reply may omit the authorization details. Our requests are verified against a fake PayPal in `tests/test_paypal_rail.py`; whether PayPal's real servers accept them is what `paypal_check.py` is for.

Webhooks (optional): create a sandbox webhook pointing at `PUBLIC_BASE_URL/webhooks/paypal` (needs a public https address, for example a tunnel), and set `PAYPAL_WEBHOOK_ID`. The Capture and Void buttons do not depend on webhooks.

This is a hackathon MVP, not production software.

## Deploying it

**On Render (what the live demo uses):** in Render choose **New > Blueprint**, pick this repository, and enter the PayPal Sandbox `PAYPAL_CLIENT_ID` and `PAYPAL_CLIENT_SECRET` when asked. `render.yaml` sets everything else: PayPal mode, the start command, `TRUST_PROXY_HEADERS=true` (Render's proxy adds the visitor's address) and the merchant timezone. `PUBLIC_BASE_URL` can stay unset there, because PayDawg uses the `RENDER_EXTERNAL_URL` that Render provides. The blueprint leaves `ADMIN_TOKEN` unset so judges can use the console with Sandbox money; set one for anything else. Render's free plan sleeps when idle, so the first visit can take up to a minute.

Anywhere else:
- Run `uvicorn app.main:app --host 0.0.0.0 --port $PORT --no-proxy-headers`. uvicorn honours `X-Forwarded-For` from allowed peers **by default**, and a forged one would otherwise earn its sender a fresh rate-limit quota. Behind a proxy you control, keep `--no-proxy-headers` and set `TRUST_PROXY_HEADERS=true`: PayDawg then keys the limiter on the address your proxy appended (the last one in `X-Forwarded-For`), never on one the client wrote.
- `RATE_LIMIT_GLOBAL_ATTEMPTS` (120 per window) is a shop-wide ceiling, so even a client rotating its apparent address cannot create payments without limit. Set it to 0 to disable.
- Set `PUBLIC_BASE_URL` to the public https address (PayPal redirects buyers back to `PUBLIC_BASE_URL/paypal/return`). On Render it defaults to `RENDER_EXTERNAL_URL`.
- Set `ADMIN_TOKEN`. Without it anyone who can reach the server can list, approve or void payments. With it, the dashboard asks for the token once per browser session. Creating payments (`POST /v1/payments`) stays open because that is the merchant app's call. Console actions sent by a browser from another website are refused either way (the `Origin` must be this server or `PUBLIC_BASE_URL`).
- SQLite lives in `DATABASE_PATH`. Free hosts such as Render's free tier have an ephemeral disk, so the database resets on every redeploy or restart. Fine for a demo, not for real money.
- The server refuses to start, with a message naming the setting, when `.env` has an invalid `PAYPAL_MODE`, `LLM_PROVIDER`, `MERCHANT_TIMEZONE` or `BARK_STAGE`, a number that is not a number, or a limit that would quietly break screening (for example `VELOCITY_LIMIT=0`, which would block every payment).
- Set `MERCHANT_TIMEZONE` (for example `Asia/Kolkata`) so the odd-hour rule and the hours the Notebook learns use the shop's clock, not the server's (a cloud server usually runs on UTC).

## The optional AI (`LLM_PROVIDER`)

`ollama` calls a local Ollama server. `http_api` posts `{"model", "input": {payment, baseline, flags}, "response_format": {"type": "json_object"}}` to `LLM_HTTP_API_URL` and expects JSON `{"risk_level": "low|medium|high", "reasons": [...]}` back, either directly or as a JSON string in an `output` or `response` field. This is a simple custom contract, not the OpenAI or Anthropic API shape, so point it at a small adapter. Each call times out after `LLM_TIMEOUT_SECONDS` (10). An unreadable answer is retried once; a model that is off or too slow is not asked twice, so a buyer never waits more than one timeout. Either way the payment then falls back to rules only (the failure is logged as a warning without customer data).

### Try the AI step in two minutes

1. Real model: install [Ollama](https://ollama.com), run `ollama pull llama3.2`, set `LLM_PROVIDER=ollama` in `.env`, restart.
2. No model installed: run `python demo_shop/fake_ollama.py` in a second window (a stand-in on Ollama's own port, not a real model), set `LLM_PROVIDER=ollama`, restart.

Payments the AI reviewed carry a small **AI** tag in the dashboard, and its plain-English reason appears next to the rules' reasons. If Ollama is off, slow or answers nonsense, the payment is simply decided by the rules. The AI sees only the amount, currency, customer ID, description, the Notebook averages and the rule flags (never the order reference or card data), and `/health` shows which provider is active.

## Known limits

Single-tenant console: `ADMIN_TOKEN` is one operator credential, not a per-merchant login. The read and action endpoints take a `merchant_id` (default `demo-merchant`) so shops do not see each other by accident, but anyone holding the token can pass any merchant id. Behind a reverse proxy, set `TRUST_PROXY_HEADERS=true` so the rate limit keys on each visitor instead of on the proxy; it trusts only the last `X-Forwarded-For` address, so put exactly one proxy you control in front. Velocity is keyed on `customer_id`, which a caller controls, so it slows a repeat customer rather than a determined attacker; the shop-wide surge rule is what catches a spread-out burst. The Notebook's hours and pace are simple, explainable counts (one row per shop), not a statistical model, and a patient attacker who gets payments captured could still nudge them over time. Not production software. Money is stored as floating-point numbers (fine for two-decimal currencies; zero-decimal currencies such as JPY are untested). The rate limiter and idempotency checks are per process. The PayPal sandbox create, authorize, capture and void flow has been run end to end against PayPal's real sandbox (Wag captured, Growl captured, Growl voided, Bark blocked; use `demo_shop/paypal_check.py`). Webhook verification and refunds follow PayPal's current docs and are tested against a fake PayPal, but have not been run against the real sandbox.

## Environment

See `.env.example`. Settings are read from environment variables and a local `.env` file. Never put secrets in source control.
