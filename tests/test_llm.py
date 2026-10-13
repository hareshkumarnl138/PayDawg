import pytest
from app.screening.llm import analyze

@pytest.mark.asyncio
async def test_none_provider_is_rules_only(monkeypatch):
    from app import config
    monkeypatch.setattr(config.settings, 'llm_provider', 'none')
    result = await analyze({'amount': 1}, {}, [])
    assert result == {'analysis': None, 'decision_source': 'rules-only'}
