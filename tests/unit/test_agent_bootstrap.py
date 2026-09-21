from nse_paper_agent.agent import TradingAgent
from nse_paper_agent.strategy.portfolio import StrategyPool, StrategyRegistration


class DummyStrategy:
    version = "dummy-v1"

    def evaluate(self, *args, **kwargs):
        raise AssertionError("not called")


def _agent(cfg):
    strategy = DummyStrategy()
    pool = StrategyPool([StrategyRegistration(strategy=strategy)])
    return TradingAgent(
        cfg,
        object(),
        object(),
        object(),
        object(),
        object(),
        strategy,
        object(),
        object(),
        object(),
        object(),
        object(),
        strategy_pool=pool,
    )


def test_single_strategy_bootstrap_is_disabled_by_default():
    agent = _agent({"market": {}, "sentiment": {}, "strategy": {}})
    assert agent._bootstrap_single_strategy is False


def test_single_strategy_bootstrap_requires_explicit_opt_in():
    agent = _agent(
        {"market": {}, "sentiment": {}, "strategy": {"allow_single_active_bootstrap": True}}
    )
    assert agent._bootstrap_single_strategy is True
