import os
import tempfile
from fastapi.testclient import TestClient

# Set before importing app so tests use a clean temporary SQLite file.
_db_file = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
_db_file.close()
os.environ["DATABASE_URL"] = f"sqlite:///{_db_file.name}"
os.environ["LLM_PROVIDER"] = "none"
os.environ["DEMO_MODE"] = "true"

from app.main import app
from app.db.database import init_db
init_db()
client = TestClient(app)


def sample(key="test-key-0001", **overrides):
    data = {"merchant_id": "test_shop", "amount": "25.00", "currency": "USD", "customer_ref": "buyer-a", "idempotency_key": key}
    data.update(overrides)
    return data


def test_health():
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_create_payment_and_detail():
    response = client.post("/v1/payments", json=sample())
    assert response.status_code == 201
    body = response.json()
    assert body["verdict"] in {"wag", "growl", "bark"}
    assert body["decision_source"] == "rules-only"
    detail = client.get(f"/v1/payments/{body['id']}")
    assert detail.status_code == 200
    assert len(detail.json()["events"]) >= 1


def test_idempotent_replay_returns_original_payment():
    payload = sample("test-key-idempotent")
    first = client.post("/v1/payments", json=payload)
    second = client.post("/v1/payments", json=payload)
    assert first.status_code == 201
    assert second.status_code == 200
    assert first.json()["id"] == second.json()["id"]


def test_idempotency_conflict_rejects_payload_change():
    first = client.post("/v1/payments", json=sample("test-key-conflict"))
    second = client.post("/v1/payments", json=sample("test-key-conflict", amount="99.00"))
    assert first.status_code == 201
    assert second.status_code == 409


def test_bark_does_not_create_paypal_order():
    payload = sample("test-key-bark", amount="25.00")
    for i in range(5):
        seeded = sample(f"test-seed-{i:03d}", customer_ref="velocity-buyer", amount=str(10+i))
        assert client.post("/v1/payments", json=seeded).status_code in (200, 201)
    for i in range(5, 10):
        seeded = sample(f"test-seed-{i:03d}", customer_ref="velocity-buyer", amount=str(10+i))
        client.post("/v1/payments", json=seeded)
    payload["customer_ref"] = "velocity-buyer"
    payload["idempotency_key"] = "test-final-bark"
    response = client.post("/v1/payments", json=payload)
    assert response.status_code in (200, 201)
    assert response.json()["verdict"] == "bark"
    assert response.json()["paypal_order_id"] is None


def test_demo_reset_is_available_in_demo_mode():
    response = client.post("/v1/demo/reset")
    assert response.status_code == 200
    assert response.json()["reset"] is True
