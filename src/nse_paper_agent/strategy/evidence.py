from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from math import isfinite
from statistics import mean
from typing import Iterable, Mapping
from zoneinfo import ZoneInfo


IST = ZoneInfo("Asia/Kolkata")


@dataclass(frozen=True)
class StrategyOutcome:
    version: str
    net_pnl: float
    exit_ts: datetime
    regime: str | None = None
    symbol: str | None = None
    entry_ts: datetime | None = None
    exit_reason: str | None = None
    holding_seconds: int | None = None


@dataclass(frozen=True)
class AggregateEvidence:
    samples: int
    expectancy: float | None
    win_rate: float | None
    avg_win: float | None
    avg_loss: float | None
    profit_factor: float | None
    gross_profit: float
    gross_loss: float
    net_pnl: float
    max_losing_streak: int


@dataclass(frozen=True)
class BucketEvidence:
    samples: int
    expectancy: float | None
    win_rate: float | None
    net_pnl: float


@dataclass(frozen=True)
class StrategyEvidence:
    version: str
    overall: AggregateEvidence
    recent: AggregateEvidence
    by_regime: Mapping[str, AggregateEvidence] = field(default_factory=dict)
    by_symbol: Mapping[str, BucketEvidence] = field(default_factory=dict)
    by_time_bucket: Mapping[str, BucketEvidence] = field(default_factory=dict)
    by_exit_reason: Mapping[str, BucketEvidence] = field(default_factory=dict)


class StrategyEvidenceEngine:
    """Build deterministic, descriptive evidence from completed paper trades.

    This layer only measures observed outcomes. It does not choose strategies,
    modify strategy code, or modify any risk control.
    """

    def __init__(self, recent_window: int = 20):
        if recent_window <= 0:
            raise ValueError("recent_window must be positive")
        self.recent_window = recent_window

    @staticmethod
    def _aggregate(rows: list[StrategyOutcome]) -> AggregateEvidence:
        pnls = [float(row.net_pnl) for row in rows if isfinite(float(row.net_pnl))]
        if not pnls:
            return AggregateEvidence(0, None, None, None, None, None, 0.0, 0.0, 0.0, 0)

        wins = [pnl for pnl in pnls if pnl > 0]
        losses = [pnl for pnl in pnls if pnl < 0]
        gross_profit = sum(wins)
        gross_loss = sum(losses)
        expectancy = mean(pnls)
        win_rate = len(wins) / len(pnls)
        avg_win = mean(wins) if wins else None
        avg_loss = mean(losses) if losses else None
        profit_factor = (
            gross_profit / abs(gross_loss)
            if gross_loss < 0
            else (float("inf") if gross_profit > 0 else None)
        )

        max_streak = 0
        streak = 0
        for pnl in pnls:
            if pnl < 0:
                streak += 1
                max_streak = max(max_streak, streak)
            else:
                streak = 0

        return AggregateEvidence(
            samples=len(pnls),
            expectancy=expectancy,
            win_rate=win_rate,
            avg_win=avg_win,
            avg_loss=avg_loss,
            profit_factor=profit_factor,
            gross_profit=gross_profit,
            gross_loss=gross_loss,
            net_pnl=sum(pnls),
            max_losing_streak=max_streak,
        )

    @staticmethod
    def _bucket(rows: list[StrategyOutcome]) -> BucketEvidence:
        aggregate = StrategyEvidenceEngine._aggregate(rows)
        return BucketEvidence(
            samples=aggregate.samples,
            expectancy=aggregate.expectancy,
            win_rate=aggregate.win_rate,
            net_pnl=aggregate.net_pnl,
        )

    @staticmethod
    def _time_bucket(ts: datetime | None) -> str | None:
        if ts is None:
            return None
        local = ts.astimezone(IST)
        minutes = local.hour * 60 + local.minute
        if minutes < 11 * 60 + 30:
            return "MORNING"
        if minutes < 13 * 60 + 30:
            return "MIDDAY"
        return "AFTERNOON"

    def compute(
        self,
        outcomes: Iterable[StrategyOutcome],
        active_versions: Iterable[str],
    ) -> Mapping[str, StrategyEvidence]:
        grouped: dict[str, list[StrategyOutcome]] = {}
        active = set(active_versions)

        for outcome in outcomes:
            if outcome.version not in active:
                continue
            if not isfinite(float(outcome.net_pnl)):
                continue
            grouped.setdefault(outcome.version, []).append(outcome)

        result: dict[str, StrategyEvidence] = {}
        for version in sorted(active):
            rows = sorted(grouped.get(version, []), key=lambda row: row.exit_ts)
            recent = rows[-self.recent_window :]

            by_regime_rows: dict[str, list[StrategyOutcome]] = {}
            by_symbol_rows: dict[str, list[StrategyOutcome]] = {}
            by_time_rows: dict[str, list[StrategyOutcome]] = {}
            by_exit_rows: dict[str, list[StrategyOutcome]] = {}

            for row in rows:
                if row.regime:
                    by_regime_rows.setdefault(row.regime, []).append(row)
                if row.symbol:
                    by_symbol_rows.setdefault(row.symbol, []).append(row)
                bucket = self._time_bucket(row.entry_ts)
                if bucket:
                    by_time_rows.setdefault(bucket, []).append(row)
                if row.exit_reason:
                    by_exit_rows.setdefault(row.exit_reason, []).append(row)

            result[version] = StrategyEvidence(
                version=version,
                overall=self._aggregate(rows),
                recent=self._aggregate(recent),
                by_regime={name: self._aggregate(values) for name, values in sorted(by_regime_rows.items())},
                by_symbol={name: self._bucket(values) for name, values in sorted(by_symbol_rows.items())},
                by_time_bucket={name: self._bucket(values) for name, values in sorted(by_time_rows.items())},
                by_exit_reason={name: self._bucket(values) for name, values in sorted(by_exit_rows.items())},
            )

        return result
