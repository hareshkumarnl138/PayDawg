import os
import tempfile
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

# Tests use an isolated in-memory database rather than shared developer state.
os.environ["LLM_PROVIDER"] = "none"
os.environ["DEMO_MODE"] = "true"

from app.main import app
from app.db.database import get_db
from app.db.models import Base

_engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
Base.metadata.create_all(_engine)
_TestSession = sessionmaker(bind=_engine, autoflush=False, expire_on_commit=False)


def override_get_db():
    db = _TestSession()
    try:
        yield db
    finally:
        db.close()

app.dependency_overrides[get_db] = override_get_db
client = TestClient(app)


def sample(key="test-key-0001", **overrides):
    data = {"merchant_id": "test_shop", "amount": "25.00", "currency": "USD", "customer_ref": "buyer-a", "idempotency_key": key}
    data.update(overrides)
    return data


def reset():
    from app.db.models import Payment, PaymentEvent, MerchantBaseline
    with _TestSession() as db:
        db.query(PaymentEvent).delete()
        db.query(Payment).delete()
        db.query(MerchantBaseline).delete()
        db.commit()


def test_health():
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_create_payment_and_detail():
    reset()
    response = client.post("/v1/payments", json=sample())
    assert response.status_code == 201
    body = response.json()
    assert body["verdict"] in {"wag", "growl", "bark"}
    assert body["decision_source"] == "rules-only"
    detail = client.get(f"/v1/payments/{body['id']}")
    assert detail.status_code == 200
    assert len(detail.json()["events"]) >= 1


def test_idempotent_replay_returns_original_payment():
    reset()
    payload = sample("test-key-idempotent")
    first = client.post("/v1/payments", json=payload)
    second = client.post("/v1/payments", json=payload)
    assert first.status_code == 201
    assert second.status_code == 200
    assert first.json()["id"] == second.json()["id"]


def test_idempotency_conflict_rejects_payload_change():
    reset()
    first = client.post("/v1/payments", json=sample("test-key-conflict"))
    second = client.post("/v1/payments", json=sample("test-key-conflict", amount="99.00"))
    assert first.status_code == 201
    assert second.status_code == 409


def test_bark_does_not_create_paypal_order():
    reset()
    for i in range(5):
        seeded = sample(f"test-seed-{i:03d}", customer_ref="velocity-buyer", amount=str(10+i))
        assert client.post("/v1/payments", json=seeded).status_code in (200, 201)
    payload = sample("test-final-bark", customer_ref="velocity-buyer", amount="25.00")
    response = client.post("/v1/payments", json=payload)
    assert response.status_code in (200, 201)
    assert response.json()["verdict"] == "bark"
    assert response.json()["paypal_order_id"] is None


def test_demo_reset_is_available_in_demo_mode():
    reset()
    response = client.post("/v1/demo/reset")
    assert response.status_code == 200
    assert response.json()["reset"] is True
