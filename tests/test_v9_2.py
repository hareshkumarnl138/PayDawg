"""v9.2: the demo shop refuses placeholder and throwaway email addresses."""
import pytest
from app import config
from app.shop import FAKE_EMAIL_MESSAGE, fake_email_reason


@pytest.fixture()
def strict():
    object.__setattr__(config.settings, "block_fake_emails", True)
    yield


def order(client, email, attempt="attempt-fe0001"):
    return client.post("/shop/api/checkout", json={"email": email, "attempt": attempt, "items": [{"sku": "ball", "qty": 1}]})


@pytest.mark.parametrize("email", ["sam@example.com", "a@example.org", "x@mail.example.com", "me@site.test", "me@thing.invalid",
                                   "me@box.localhost", "u@test.com", "u@MAILINATOR.com", "u@sub.yopmail.com", "u@example.com."])
def test_fake_addresses_are_refused(client, strict, email):
    reply = order(client, email)
    assert reply.status_code == 422 and reply.json()["detail"] == FAKE_EMAIL_MESSAGE
    assert client.get("/v1/payments").json()["payments"] == []        # nothing reached PayDawg


@pytest.mark.parametrize("email", ["vishaal@gmail.com", "a.b@outlook.com", "judge@devpost.com", "me@mycompany.co.in", "x@contest.com"])
def test_real_looking_addresses_pass(client, strict, email):
    assert order(client, email).status_code == 200


def test_the_check_can_be_switched_off(client):
    assert fake_email_reason("sam@example.com") is None               # conftest turns it off by default
    assert order(client, "sam@example.com").status_code == 200


def test_the_setting_defaults_to_on():
    assert config._bool("SOME_UNSET_SETTING_FOR_TEST", True) is True
