from app.ai.decision_engine import decide_verdict
from app.ai.schemas import RiskAnalysis


def test_low_risk_is_wag():
    result = decide_verdict({}, [], RiskAnalysis(risk_level="low", reasons=["Normal pattern"]))
    assert result.verdict == "wag"
    assert result.decision_source == "rules+llm"


def test_medium_risk_is_growl():
    result = decide_verdict({}, [], RiskAnalysis(risk_level="medium", reasons=["Unusual context"]))
    assert result.verdict == "growl"


def test_high_risk_is_bark():
    result = decide_verdict({}, [], RiskAnalysis(risk_level="high", reasons=["High risk signal"]))
    assert result.verdict == "bark"


def test_hard_duplicate_cannot_be_overridden():
    result = decide_verdict({"duplicate": True}, ["duplicate"] , RiskAnalysis(risk_level="low", reasons=["Looks fine"]))
    assert result.verdict == "bark"
    assert result.risk_level == "high"
    assert result.decision_source == "rules-only"


def test_velocity_cannot_be_overridden():
    result = decide_verdict({"velocity_breach": True}, ["too many"], RiskAnalysis(risk_level="low", reasons=["Looks fine"]))
    assert result.verdict == "bark"


def test_amount_outlier_cannot_be_labeled_low():
    result = decide_verdict({"amount_outlier": True}, ["amount outlier"], RiskAnalysis(risk_level="low", reasons=["Looks fine"]))
    assert result.verdict == "growl"


def test_rules_only_fallback_is_explicit():
    result = decide_verdict({}, [], None)
    assert result.verdict == "wag"
    assert result.decision_source == "rules-only"
    assert any("LLM unavailable" in r for r in result.reasons)


def test_rules_only_outlier_requires_review():
    result = decide_verdict({"amount_outlier": True}, ["large amount"], None)
    assert result.verdict == "growl"
