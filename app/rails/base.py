"""Rail contract shared by live and simulated payment providers."""
from abc import ABC, abstractmethod

class RailError(RuntimeError):
    pass

class Rail(ABC):
    name = "base"
    simulated = False

    @abstractmethod
    async def create(self, payment: dict, intent: str) -> dict:
        """Create a provider order; return order_id and optional approval_url."""

    @abstractmethod
    async def authorize(self, payment: dict) -> dict:
        """Authorize an approved order."""

    @abstractmethod
    async def capture(self, payment: dict) -> dict:
        """Capture an authorized order or approved CAPTURE-intent order."""

    @abstractmethod
    async def void(self, payment: dict) -> dict:
        """Void an authorization."""

    @abstractmethod
    async def refund(self, payment: dict) -> dict:
        """Refund a captured payment."""
