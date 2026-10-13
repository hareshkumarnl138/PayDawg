import pytest
from app.engine import decide

@pytest.mark.asyncio
async def test_hard_rule_cannot_be_overridden(monkeypatch):
    import app.engine as engine
    async def risky_llm(*args, **kwargs):
        return {'analysis': {'risk_level': 'low', 'reasons': ['LLM says okay']}, 'decision_source': 'http_api'}
    monkeypatch.setattr(engine, 'analyze', risky_llm)
    from datetime import datetime, timezone
    p = {'id':'p1','merchant_id':'demo-merchant','amount':10,'currency':'USD','customer_id':'c1','description':'test','created_at':datetime.now(timezone.utc).isoformat()}
    result = await decide(p, {'payment_count':10,'average_amount':10,'max_amount':20}, [p])
    assert result['verdict'] == 'Bark'
    assert result['decision_source'] == 'hard-rules'

@pytest.mark.asyncio
async def test_no_flags_maps_to_wag(monkeypatch):
    import app.engine as engine
    async def no_llm(*args, **kwargs):
        return {'analysis': None, 'decision_source': 'rules-only'}
    monkeypatch.setattr(engine, 'analyze', no_llm)
    from datetime import datetime, timezone
    p = {'id':'p1','merchant_id':'demo-merchant','amount':10,'currency':'USD','customer_id':'known','description':'test','created_at':datetime.now(timezone.utc).isoformat()}
    result = await decide(p, {'payment_count':0,'average_amount':0,'max_amount':0,'active_hours':list(range(24))}, [])
    assert result['verdict'] == 'Wag'
