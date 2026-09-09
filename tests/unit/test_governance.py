from nse_paper_agent.research.governance import PromotionGate,evaluate_candidate
def test_promotion_requires_human_approval():
 good={"trades":60,"max_drawdown":.02,"net_expectancy":10}; ok,reasons=evaluate_candidate(good,good,good,PromotionGate(),False); assert not ok and "human_approval_required" in reasons
