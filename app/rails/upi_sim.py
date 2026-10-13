"""SIMULATED ONLY: UPI placeholder. No UPI provider or bank integration exists."""
from app.rails.base import Rail, RailError

class UpiSimRail(Rail):
    name = "upi_sim"
    simulated = True

    async def create(self, payment, intent):
        raise RailError("SIMULATED UPI stub: no payment flow is implemented.")

    async def authorize(self, payment):
        raise RailError("SIMULATED UPI stub: authorization is not implemented.")

    async def capture(self, payment):
        raise RailError("SIMULATED UPI stub: capture is not implemented.")

    async def void(self, payment):
        raise RailError("SIMULATED UPI stub: void is not implemented.")

    async def refund(self, payment):
        raise RailError("SIMULATED UPI stub: refund is not implemented.")
