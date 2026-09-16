from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime, time
from zoneinfo import ZoneInfo

from nse_paper_agent.domain.models import Bar, Regime, Signal
from nse_paper_agent.research.validation_plan import ValidationPlan


IST = ZoneInfo("Asia/Kolkata")


@dataclass(frozen=True)
class ChallengerBuildResult:
    strategy: object
    version: str
    change_scope: str
    target: str | None


class BoundedChallenger:
    """Wrap a base strategy with one bounded eligibility change.

    Only eligibility is altered. The underlying strategy, signal score,
    sizing metadata, and all risk controls remain untouched.
    """

    SUPPORTED_SCOPES = frozenset(
        {
            "regime_eligibility",
            "time_of_day_eligibility",
            "symbol_eligibility",
        }
    )

    def __init__(self, base_strategy, plan: ValidationPlan):
        if plan.allowed_change_scope not in self.SUPPORTED_SCOPES:
            raise ValueError(f"unsupported challenger change scope: {plan.allowed_change_scope}")
        if plan.allowed_change_scope in {"regime_eligibility", "time_of_day_eligibility", "symbol_eligibility"} and not plan.target:
            raise ValueError("bounded eligibility challenger requires a target")
        self._base = base_strategy
        self._plan = plan
        self.version = plan.challenger_version

    @property
    def base_version(self) -> str:
        return self._base.version

    def _allowed(self, now: datetime, regime: Regime, symbol: str) -> bool:
        scope = self._plan.allowed_change_scope
        target = str(self._plan.target)
        if scope == "regime_eligibility":
            return regime.value != target
        if scope == "symbol_eligibility":
            return symbol != target
        if scope == "time_of_day_eligibility":
            bucket = target.upper()
            local_time = now.astimezone(IST).time()
            if bucket == "MORNING":
                return local_time >= time(11, 30)
            if bucket == "MIDDAY":
                return local_time < time(11, 30) or local_time >= time(13, 30)
            if bucket == "AFTERNOON":
                return local_time < time(13, 30)
            raise ValueError(f"unsupported time bucket target: {target}")
        return False

    def evaluate(
        self,
        bars: list[Bar],
        now,
        regime: Regime,
        sentiment_score: float | None,
        held: bool,
        cooldown: bool,
        liquid: bool,
        feed_healthy: bool,
    ) -> Signal:
        base_signal = self._base.evaluate(
            bars, now, regime, sentiment_score, held, cooldown, liquid, feed_healthy
        )
        if not base_signal.eligible:
            return Signal(
                base_signal.symbol,
                base_signal.bar_end,
                self.version,
                False,
                base_signal.reason,
                base_signal.score,
                dict(base_signal.metadata),
            )
        if not self._allowed(now, regime, base_signal.symbol):
            metadata = dict(base_signal.metadata)
            metadata["challenger_base_version"] = self._base.version
            metadata["challenger_change_scope"] = self._plan.allowed_change_scope
            metadata["challenger_target"] = self._plan.target
            return Signal(
                base_signal.symbol,
                base_signal.bar_end,
                self.version,
                False,
                "challenger_eligibility_filter",
                base_signal.score,
                metadata,
            )
        metadata = dict(base_signal.metadata)
        metadata["challenger_base_version"] = self._base.version
        metadata["challenger_change_scope"] = self._plan.allowed_change_scope
        metadata["challenger_target"] = self._plan.target
        return Signal(
            base_signal.symbol,
            base_signal.bar_end,
            self.version,
            True,
            "challenger_entry",
            base_signal.score,
            metadata,
        )


class ChallengerFactory:
    """Materialize only explicitly supported bounded challengers."""

    SUPPORTED_SCOPES = BoundedChallenger.SUPPORTED_SCOPES

    def build(self, base_strategy, plan: ValidationPlan) -> ChallengerBuildResult:
        challenger = BoundedChallenger(base_strategy, plan)
        return ChallengerBuildResult(
            strategy=challenger,
            version=challenger.version,
            change_scope=plan.allowed_change_scope,
            target=plan.target,
        )
