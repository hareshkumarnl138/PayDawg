"""Combines deterministic checks with optional LLM analysis."""
from app.screening.rules import evaluate_rules
from app.screening.llm import analyze

async def decide(payment: dict, notebook: dict, recent_payments: list[dict]) -> dict:
    rules = evaluate_rules(payment, notebook, recent_payments)
    llm_result = await analyze(payment, notebook, rules["flags"])
    llm = llm_result["analysis"]
    reasons = list(rules["reasons"])
    level = rules["risk_level"]
    source = llm_result["decision_source"]
    if rules["hard_block"]:
        level = "high"
        source = "hard-rules"
    elif llm:
        ranks = {"low": 0, "medium": 1, "high": 2}
        # The AI may ask for a human review (Growl) but can never block a payment on its own:
        # only the deterministic hard rules produce a Bark.
        llm_level = "medium" if llm["risk_level"] == "high" else llm["risk_level"]
        level = max((level, llm_level), key=lambda x: ranks[x])
        for reason in llm.get("reasons", []):
            if reason and reason not in reasons:
                reasons.append(reason)
    verdict = {"low": "Wag", "medium": "Growl", "high": "Bark"}[level]
    if not reasons:
        reasons = ["No additional risk reasons were supplied."]
    return {"verdict": verdict, "risk_level": level, "reasons": reasons,
            "flags": rules["flags"], "risk_score": rules["risk_score"], "hard_block": rules["hard_block"], "decision_source": source}

async def decide_payment(payment, notebook, recent_payments):
    return await decide(payment, notebook, recent_payments)
