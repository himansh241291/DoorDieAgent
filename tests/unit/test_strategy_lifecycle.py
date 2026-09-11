import pytest

from nse_paper_agent.research.lifecycle import StrategyState, transition


def test_strategy_lifecycle_allows_only_forward_transitions():
    state = StrategyState.CANDIDATE
    for target in (
        StrategyState.VALIDATED,
        StrategyState.SHADOW,
        StrategyState.APPROVED,
        StrategyState.PRODUCTION,
    ):
        state = transition(state, target)
    assert state is StrategyState.PRODUCTION


def test_strategy_lifecycle_rejects_skipping_states():
    with pytest.raises(ValueError, match="invalid strategy transition"):
        transition(StrategyState.CANDIDATE, StrategyState.SHADOW)
    with pytest.raises(ValueError, match="invalid strategy transition"):
        transition(StrategyState.VALIDATED, StrategyState.PRODUCTION)


def test_strategy_lifecycle_rejects_reverse_and_production_transitions():
    with pytest.raises(ValueError, match="invalid strategy transition"):
        transition(StrategyState.SHADOW, StrategyState.VALIDATED)
    with pytest.raises(ValueError, match="invalid strategy transition"):
        transition(StrategyState.PRODUCTION, StrategyState.APPROVED)
