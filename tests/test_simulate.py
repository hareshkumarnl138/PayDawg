"""demo_shop/simulate.py, run against the real app in-process instead of over the network."""
import importlib.util
from contextlib import contextmanager
from pathlib import Path
import pytest
from app import config

spec = importlib.util.spec_from_file_location("simulate", Path(__file__).resolve().parent.parent / "demo_shop" / "simulate.py")
simulate = importlib.util.module_from_spec(spec)
spec.loader.exec_module(simulate)


@contextmanager
def override(**values):
    old = {k: getattr(config.settings, k) for k in values}
    for k, v in values.items():
        object.__setattr__(config.settings, k, v)
    try:
        yield
    finally:
        for k, v in old.items():
            object.__setattr__(config.settings, k, v)


class ClientGateway(simulate.Gateway):
    def __init__(self, client):
        super().__init__("http://testserver", "")
        self.client, self.sent = client, []

    def call(self, method, path, body=None, key=None, admin=False):
        reply = self.client.request(method, path, json=body, headers={"Idempotency-Key": key} if key else {})
        if path == "/v1/payments" and method == "POST":
            self.sent.append((body, key, reply.json()))
        return reply.status_code, reply.json(), reply.headers


def make(client, monkeypatch, *argv):
    monkeypatch.setattr(simulate.Simulator, "sleep", lambda self, seconds: None)
    args = simulate.build_parser().parse_args(list(argv))
    return simulate.Simulator(ClientGateway(client), args)


def test_a_run_streams_a_realistic_mix(client, monkeypatch, capsys):
    sim = make(client, monkeypatch, "--orders", "45", "--seed", "3")
    with override(rate_limit_attempts=0):
        sim.start()
        sim.loop()
        sim.summary()
    out = capsys.readouterr().out
    assert "SIMULATED trading history" in out and "Sent " in out
    verdicts = [paid.get("verdict") for _, _, paid in sim.gw.sent]
    assert verdicts.count("Wag") > verdicts.count("Growl") > 0 and "Bark" in verdicts
    flags = [f for _, _, paid in sim.gw.sent for f in paid.get("flags", [])]
    assert "exact_duplicate" in flags and "velocity_breach" in flags and "unusual_amount" in flags
    assert "merchant_surge" not in flags                     # a busy normal stream is not a surge
    keys = [key for _, key, _ in sim.gw.sent]
    assert len(keys) == len(set(keys))                      # a double-click is two requests, not a replay
    assert all(body["amount"] == round(body["amount"], 2) for body, _, _ in sim.gw.sent)


def test_review_plays_the_shop_owner(client, monkeypatch):
    sim = make(client, monkeypatch, "--orders", "1", "--review", "--seed", "1")
    sim.start()
    held = sim.send(sim.body("someone-001", [("bed", 7)], sim.ref()), "far bigger order than usual")
    assert held["status"] == "held" and sim.held
    sim.held = [(0, pid) for _, pid in sim.held]               # make the review due now
    sim.review_due()
    status = client.get("/v1/payments/" + held["id"]).json()["status"]
    assert status in ("captured", "voided")


def test_it_refuses_real_paypal_mode(client, monkeypatch):
    sim = make(client, monkeypatch, "--orders", "1")
    with override(rail_provider="paypal"):
        with pytest.raises(SystemExit) as stop:
            sim.start()
    assert "PAYPAL_MODE=mock" in str(stop.value)


def test_no_history_leaves_a_new_shop_empty(client, monkeypatch, capsys):
    sim = make(client, monkeypatch, "--orders", "1", "--no-history")
    sim.start()
    assert "Notebook: empty" in capsys.readouterr().out
    assert client.get("/v1/notebook").json()["learned_from"] == 0
