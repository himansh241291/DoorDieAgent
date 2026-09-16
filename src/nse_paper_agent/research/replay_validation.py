from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from decimal import Decimal
from hashlib import sha256
import json
from pathlib import Path
from typing import Iterable
from zoneinfo import ZoneInfo

from nse_paper_agent.data.provider import load_bars_csv
from nse_paper_agent.data.symbols import resolve_benchmark_symbol
from nse_paper_agent.domain.models import Bar, ExitReason, Quote, Regime, RegimeSnapshot
from nse_paper_agent.persistence.db import Database
from nse_paper_agent.persistence.repository import Repository
from nse_paper_agent.paper_broker.broker import PaperBroker
from nse_paper_agent.regime.engine import RegimeEngine
from nse_paper_agent.regime.intelligence import MarketIntelligence
from nse_paper_agent.research.challenger import ChallengerFactory
from nse_paper_agent.research.validation_plan import ValidationPlan
from nse_paper_agent.risk.engine import RiskEngine
from nse_paper_agent.session import SessionGuard
from nse_paper_agent.strategy.baseline import BaselineBreakoutStrategy

IST = ZoneInfo("Asia/Kolkata")
BASE_VERSION = "baseline-breakout-v1"


@dataclass(frozen=True)
class ReplayValidationResult:
    split: str
    start_date: str
    end_date: str
    bars: int
    trading_days: int
    trades: int
    wins: int
    losses: int
    net_pnl: float
    expectancy: float
    win_rate: float
    max_drawdown: float
    forced_exits: int
    stop_exits: int
    target_exits: int
    final_cash: float

    def as_dict(self) -> dict[str, float | int | str]:
        return {
            "split": self.split,
            "start_date": self.start_date,
            "end_date": self.end_date,
            "bars": self.bars,
            "trading_days": self.trading_days,
            "trades": self.trades,
            "wins": self.wins,
            "losses": self.losses,
            "net_pnl": self.net_pnl,
            "expectancy": self.expectancy,
            "net_expectancy": self.expectancy,
            "win_rate": self.win_rate,
            "max_drawdown": self.max_drawdown,
            "forced_exits": self.forced_exits,
            "stop_exits": self.stop_exits,
            "target_exits": self.target_exits,
            "final_cash": self.final_cash,
        }


@dataclass(frozen=True)
class ValidationReplayResult:
    plan: ValidationPlan
    development: ReplayValidationResult
    holdout: ReplayValidationResult

    def as_dict(self) -> dict[str, object]:
        return {
            "plan": {
                "proposal_id": self.plan.proposal_id,
                "base_version": self.plan.base_version,
                "challenger_version": self.plan.challenger_version,
                "hypothesis": self.plan.hypothesis,
                "allowed_change_scope": self.plan.allowed_change_scope,
                "target": self.plan.target,
                "parameters": dict(self.plan.parameters),
                "data_window": self.plan.data_window,
                "min_trading_days": self.plan.min_trading_days,
                "risk_config_hash": self.plan.risk_config_hash,
            },
            "development": self.development.as_dict(),
            "holdout": self.holdout.as_dict(),
        }


def _config() -> dict:
    return {
        "account": {
            "starting_capital": 50000.0,
            "minimum_cash_reserve": 2000.0,
            "max_open_positions": 5,
            "max_gross_position": 10000.0,
            "buy_fee": 20.0,
            "sell_fee": 20.0,
            "risk_per_trade": 0.003,
        },
        "risk": {
            "hard_stop_pct": 0.015,
            "take_profit_pct": 0.05,
            "daily_loss_limit_pct": 0.02,
            "rolling_drawdown_pct": 0.04,
            "rolling_drawdown_days": 5,
            "rolling_block_hours": 48,
            "stop_cooldown_minutes": 120,
            "slippage_bps": 10,
            "max_spread_bps": 50,
        },
        "market": {
            "benchmark": "NIFTY50",
            "bar_interval_minutes": 5,
            "minimum_breadth_symbols": 5,
            "regime": {
                "benchmark_min_bars": 50,
                "volatility_window": 20,
                "volatility_history": 60,
                "breadth_window": 20,
            },
        },
        "execution": {"last_price_slippage_bps": 25},
        "session": {
            "pre_open": "09:00",
            "open": "09:15",
            "entry_cutoff": "14:45",
            "close": "15:30",
            "calendar_path": str(Path(__file__).resolve().parents[3] / "config" / "nse_holidays.yaml"),
        },
        "safety": {"global_kill_switch": False, "emergency_kill_file": "/never"},
        "legacy_fixture_without_benchmark": True,
    }


def _risk_config(cfg: dict) -> dict:
    return cfg["risk"] | cfg["account"] | cfg["execution"]


def _risk_config_hash(cfg: dict) -> str:
    payload = json.dumps(_risk_config(cfg), sort_keys=True, separators=(",", ":"), default=str).encode()
    return sha256(payload).hexdigest()


def _split_dates(bars: Iterable[Bar], fraction: float = 0.70) -> tuple[list[str], list[str]]:
    dates = sorted({bar.end.astimezone(IST).date().isoformat() for bar in bars})
    if len(dates) < 2:
        raise ValueError("validation requires at least two trading days")
    cut = max(1, min(len(dates) - 1, int(len(dates) * fraction)))
    return dates[:cut], dates[cut:]


def _record_eod(repo: Repository, risk: RiskEngine, now, quotes: dict[str, Quote], cfg: dict) -> None:
    trading_date = now.astimezone(IST).date().isoformat()
    if repo.db.get_state("last_eod_trading_date") == trading_date:
        return
    equity = risk.equity(quotes)
    gross = equity - repo.cash()
    previous = repo.eod_marks(cfg["risk"]["rolling_drawdown_days"] - 1)
    values = [float(mark["equity"]) for mark in reversed(previous)]
    peak = max(values + [equity]) if values else equity
    drawdown = (peak - equity) / peak if peak > 0 else 0.0
    repo.record_eod_snapshot(
        trading_date=trading_date,
        ts=now,
        cash=repo.cash(),
        equity=equity,
        gross=gross,
        daily_start_equity=repo.db.get_state("daily_start_equity", cfg["account"]["starting_capital"]),
        drawdown5=drawdown,
    )


def _run_split(
    all_bars: list[Bar],
    active_dates: set[str],
    split_name: str,
    db_path: str,
    strategy,
) -> ReplayValidationResult:
    cfg = _config()
    benchmark_symbol = resolve_benchmark_symbol(cfg["market"]["benchmark"], {bar.symbol for bar in all_bars})
    has_benchmark = benchmark_symbol is not None
    trading_symbols = [symbol for symbol in sorted({bar.symbol for bar in all_bars}) if symbol != benchmark_symbol]
    all_symbols = {bar.symbol for bar in all_bars}
    split_start = min(active_dates)

    db = Database(db_path)
    db.initialize()
    repo = Repository(db)
    repo.set_cash(cfg["account"]["starting_capital"])
    repo.set_state("daily_start_equity", cfg["account"]["starting_capital"])
    broker = PaperBroker(cfg, repo)
    risk = RiskEngine(cfg, repo)
    session = SessionGuard(cfg)
    regime_engine = RegimeEngine()
    intelligence = MarketIntelligence(
        benchmark_min_bars=50,
        volatility_window=20,
        volatility_history=60,
        breadth_window=20,
        breadth_min_symbols=cfg["market"]["minimum_breadth_symbols"],
    )

    history = {
        symbol: [
            bar
            for bar in all_bars
            if bar.symbol == symbol
            and bar.end.astimezone(IST).date().isoformat() < split_start
            and session.regular_bar_start(bar.start)
        ]
        for symbol in all_symbols
    }
    latest_quotes: dict[str, Quote] = {}
    split_bars = [
        bar
        for bar in all_bars
        if bar.end.astimezone(IST).date().isoformat() in active_dates
    ]

    for bar in sorted(split_bars, key=lambda item: item.end):
        now = bar.end
        if not session.regular_bar_start(bar.start):
            continue
        session.ensure_daily_state(repo, now, cfg["account"]["starting_capital"])
        session_state = session.snapshot(now)
        history[bar.symbol].append(bar)
        repo.record_bar(bar)
        quote = Quote(
            bar.symbol,
            now,
            bar.close * Decimal("0.999"),
            bar.close * Decimal("1.001"),
            bar.close,
            bar.volume,
        )
        repo.record_quote(quote)
        latest_quotes[bar.symbol] = quote

        position = repo.positions().get(bar.symbol)
        if position and session_state.exits_allowed:
            if quote.bid <= position.stop_price:
                broker.sell(bar.symbol, quote, now, position.strategy_version, ExitReason.STOP)
                repo.cooldown(
                    bar.symbol,
                    now + timedelta(minutes=cfg["risk"]["stop_cooldown_minutes"]),
                    "stop_loss",
                )
            elif quote.bid >= position.target_price:
                broker.sell(bar.symbol, quote, now, position.strategy_version, ExitReason.TARGET)
            elif session_state.state.value == "EOD":
                broker.sell(bar.symbol, quote, now, position.strategy_version, ExitReason.FORCED)

        if bar.symbol in trading_symbols and session_state.entries_allowed and len(history[bar.symbol]) >= 35:
            if has_benchmark:
                metrics = intelligence.calculate(
                    history[benchmark_symbol],
                    {symbol: history[symbol] for symbol in trading_symbols},
                )
                regime_snapshot = regime_engine.classify(
                    now,
                    metrics.get("close"),
                    metrics.get("sma20"),
                    metrics.get("sma50"),
                    metrics.get("breadth20"),
                    metrics.get("vol_percentile"),
                    metrics.get("vol_shock"),
                    True,
                )
            elif cfg["legacy_fixture_without_benchmark"]:
                regime_snapshot = RegimeSnapshot(now, Regime.RISK_ON, {}, "legacy_fixture_without_benchmark")
            else:
                regime_snapshot = regime_engine.classify(now, None, None, None, None, None, None, True)

            repo.record_regime(regime_snapshot)
            held = bar.symbol in repo.positions()
            cooling = repo.in_cooldown(bar.symbol, now)
            signal = strategy.evaluate(
                history[bar.symbol],
                now,
                regime_snapshot.regime,
                0.5,
                held,
                cooling,
                True,
                True,
            )
            repo.record_signal(
                signal,
                f"validation:{split_name}:{signal.symbol}:{signal.bar_end.isoformat()}",
            )

            if signal.eligible and not held:
                equity = risk.equity(latest_quotes)
                decision = risk.can_buy(now, latest_quotes, equity, regime_snapshot.regime)
                repo.record_risk(
                    now,
                    "ENTRY",
                    decision.allowed,
                    decision.reason,
                    {
                        "symbol": bar.symbol,
                        "score": signal.score,
                        "regime": regime_snapshot.regime.value,
                        "strategy": signal.strategy_version,
                    },
                )
                if decision.allowed:
                    qty = risk.quantity(quote.ask, equity, quote, decision.size_factor)
                    if qty > 0:
                        broker.buy(bar.symbol, qty, quote, now, signal.strategy_version)

        equity = risk.equity(latest_quotes)
        repo.record_account_snapshot_and_checkpoint(
            symbol=bar.symbol,
            bar_end=now,
            cash=repo.cash(),
            equity=equity,
            gross=equity - repo.cash(),
            daily_start_equity=repo.db.get_state("daily_start_equity", cfg["account"]["starting_capital"]),
            drawdown5=0.0,
            trading_date=now.astimezone(IST).date().isoformat(),
            is_eod=False,
        )
        if session_state.state.value == "EOD" and session_state.is_trading_day:
            _record_eod(repo, risk, now, latest_quotes, cfg)

    marks = repo.eod_marks(10000)
    equities = [float(mark["equity"]) for mark in reversed(marks)]
    peak = None
    max_dd = 0.0
    for equity in equities:
        peak = equity if peak is None else max(peak, equity)
        max_dd = max(max_dd, (peak - equity) / peak if peak else 0.0)

    trades = repo.db.conn.execute(
        "SELECT net_pnl, exit_reason FROM closed_trades ORDER BY id"
    ).fetchall()
    pnls = [float(row["net_pnl"]) for row in trades]
    final_cash = repo.cash()
    dates = sorted(active_dates)
    db.close()
    return ReplayValidationResult(
        split=split_name,
        start_date=dates[0],
        end_date=dates[-1],
        bars=len(split_bars),
        trading_days=len(dates),
        trades=len(pnls),
        wins=sum(p > 0 for p in pnls),
        losses=sum(p <= 0 for p in pnls),
        net_pnl=sum(pnls),
        expectancy=(sum(pnls) / len(pnls)) if pnls else 0.0,
        win_rate=(sum(p > 0 for p in pnls) / len(pnls)) if pnls else 0.0,
        max_drawdown=max_dd,
        forced_exits=sum(row["exit_reason"] == "FORCED" for row in trades),
        stop_exits=sum(row["exit_reason"] == "STOP" for row in trades),
        target_exits=sum(row["exit_reason"] == "TARGET" for row in trades),
        final_cash=final_cash,
    )


def execute_validation(plan: ValidationPlan, bars_path: str, work_dir: str) -> ValidationReplayResult:
    cfg = _config()
    if plan.split_policy != "chronological":
        raise ValueError(f"unsupported validation split policy: {plan.split_policy}")
    if plan.allowed_change_scope not in ChallengerFactory.SUPPORTED_SCOPES:
        raise ValueError(f"unsupported validation scope: {plan.allowed_change_scope}")
    if not plan.target:
        raise ValueError("validation plan requires a challenger target")
    if plan.base_version != BASE_VERSION:
        raise ValueError(f"unsupported validation base version: {plan.base_version}")

    expected_hash = _risk_config_hash(cfg)
    if plan.risk_config_hash != expected_hash:
        raise ValueError("validation plan risk configuration does not match canonical replay safety configuration")

    bars = load_bars_csv(bars_path)
    dev_dates, holdout_dates = _split_dates(bars)
    if len(dev_dates) < plan.min_trading_days:
        raise ValueError(
            f"development split has insufficient trading days: {len(dev_dates)} < {plan.min_trading_days}"
        )
    if len(holdout_dates) < max(1, plan.min_trading_days // 2):
        raise ValueError(f"holdout split is too short: {len(holdout_dates)}")

    challenger = ChallengerFactory().build(BaselineBreakoutStrategy(), plan).strategy
    work = Path(work_dir)
    work.mkdir(parents=True, exist_ok=True)
    development = _run_split(
        bars,
        set(dev_dates),
        "development",
        str(work / "validation-dev.sqlite3"),
        challenger,
    )
    holdout = _run_split(
        bars,
        set(holdout_dates),
        "holdout",
        str(work / "validation-holdout.sqlite3"),
        challenger,
    )
    return ValidationReplayResult(plan, development, holdout)
