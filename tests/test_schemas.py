import pytest
from pydantic import ValidationError
from app.ai.schemas import PaymentRequest


def test_currency_is_normalized():
    payload = PaymentRequest(merchant_id="shop", amount="1.00", currency="usd", customer_ref="buyer", idempotency_key="12345678")
    assert payload.currency == "USD"


def test_negative_amount_is_rejected():
    with pytest.raises(ValidationError):
        PaymentRequest(merchant_id="shop", amount="-1", currency="USD", customer_ref="buyer", idempotency_key="12345678")


def test_extra_fields_are_rejected():
    with pytest.raises(ValidationError):
        PaymentRequest(merchant_id="shop", amount="1", currency="USD", customer_ref="buyer", idempotency_key="12345678", card_number="4111111111111111")
