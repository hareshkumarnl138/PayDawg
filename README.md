# PayDawg

> A payment gateway that thinks before it charges.

PayDawg is a hackathon MVP that screens payment requests before routing them through PayPal Sandbox. It combines deterministic fraud signals, a merchant-specific baseline (the Dawg's Notebook), and an optional LLM risk explanation to produce three verdicts:

- **Wag** — low risk; proceed through the PayPal Sandbox checkout flow.
- **Growl** — medium risk; hold for explicit merchant review.
- **Bark** — high risk or hard-rule violation; block before creating a PayPal order.

PayPal remains responsible for payment operations. This project is a demo, not a licensed payment gateway or a production fraud-prevention system. It must use synthetic data and sandbox credentials only.

## MVP scope

- FastAPI REST API with idempotent payment creation
- Deterministic duplicate, velocity, and merchant-baseline checks
- Optional structured LLM risk analysis with safe rules-only fallback
- SQLite payments, per-merchant baseline, and append-only events
- Demo dashboard and scripted Wag/Growl/Bark scenarios
- PayPal Sandbox adapter configuration and webhook verification guidance
- Unit tests and GitHub Actions test workflow

## Quick start

Requires Python 3.11 or newer.

```bash
python -m venv .venv
# Windows PowerShell:
.venv\\Scripts\\Activate.ps1
# macOS/Linux:
# source .venv/bin/activate
python -m pip install --upgrade pip
pip install -r requirements.txt
cp .env.example .env  # Windows: Copy-Item .env.example .env
uvicorn app.main:app --reload
```

Open <http://127.0.0.1:8000/docs> for the API and <http://127.0.0.1:8000/> for the dashboard.

## Configuration

See `.env.example`. The application should start without third-party keys in local demo mode. To enable LLM explanations, configure the provider and API key. To enable PayPal operations, supply Sandbox client credentials and complete the verification steps in the official PayPal developer console. Never commit `.env` or credentials.

## API

- `GET /health` — health check
- `POST /v1/payments` — screen and create a payment record
- `GET /v1/payments` — list payments
- `GET /v1/payments/{payment_id}` — payment details and events
- `POST /v1/payments/{payment_id}/approve` — merchant approval for held payments (requires configured rail support)
- `POST /v1/payments/{payment_id}/void` — void a held payment (requires configured rail support)
- `POST /v1/demo/reset` — reset demo data; local/demo use only

Payment status is not considered captured simply because an AI verdict is Wag. Buyer approval, PayPal API results, and verified webhooks must drive the actual payment status.

## Decisions and safety properties

- Exact idempotency-key replay returns the original request result and cannot create another charge.
- A repeated payment signal and idempotent request replay are separate concepts.
- Hard rules (for example, a configured duplicate or velocity breach) cannot be overridden by the LLM.
- LLM timeout or invalid structured output falls back to deterministic rules and records `rules-only`.
- A held transaction requires a deliberate merchant action.
- Webhooks must be signature-verified before they can mutate payment state.
- This demo does not claim to guarantee fraud detection. Thresholds are illustrative and require evaluation before any real-world use.

## Testing

```bash
pytest -q
```

Tests use local data and mocked third-party calls; they do not move money. Sandbox integration tests must be run separately after credentials are configured.

## Deployment checklist

1. Configure secrets through the host's environment/secret manager.
2. Use a persistent SQLite volume or migrate to a managed database before relying on deployed data.
3. Set an explicit CORS policy and trusted webhook settings.
4. Verify PayPal webhook signatures and order lifecycle using Sandbox buyer and seller accounts.
5. Run the test suite and exercise Wag, Growl, Bark, duplicate replay, velocity, and LLM-down scenarios.
6. Add hosted URL, screenshots, AI-tool disclosure, and a public demo video to the hackathon submission.

## Architecture

```text
Demo Shop / Dashboard
        | REST
        v
FastAPI orchestration -> Rules + Merchant Baseline -> optional LLM
        |                         |                     |
        v                         v                     v
PayPal Sandbox adapter      SQLite payments, notebook and append-only events
        ^
        | verified webhooks update payment status
```

## License

MIT. See [LICENSE](LICENSE).

## Disclaimer

PayDawg is a hackathon prototype. Verdicts are decision support, not a guarantee or certification of fraud. Never use this prototype to process real payments without a formal security, compliance, reliability, and payment-provider review.
