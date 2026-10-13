import pytest
from app.rails.mock import MockRail

@pytest.mark.asyncio
async def test_mock_rail_is_explicitly_simulated():
    rail = MockRail()
    result = await rail.create({'id':'p1','amount':5,'currency':'USD','description':'test'}, 'CAPTURE')
    assert result['simulated'] is True
    assert result['order_id'].startswith('mock-order-')
