"""SIMULATED rail for local development; it never moves real money."""
import uuid
from app.rails.base import Rail

class MockRail(Rail):
    name = "mock"
    simulated = True

    async def create(self, payment, intent):
        return {"order_id": "mock-order-" + uuid.uuid4().hex[:12],
                "approval_url": None, "intent": intent, "simulated": True}

    async def authorize(self, payment):
        return {"authorization_id": "mock-auth-" + uuid.uuid4().hex[:12], "simulated": True}

    async def capture(self, payment):
        return {"capture_id": "mock-capture-" + uuid.uuid4().hex[:12], "status": "COMPLETED", "simulated": True}

    async def void(self, payment):
        return {"status": "VOIDED", "simulated": True}

    async def refund(self, payment):
        return {"refund_id": "mock-refund-" + uuid.uuid4().hex[:12], "status": "REFUNDED", "simulated": True}
