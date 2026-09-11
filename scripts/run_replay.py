#!/usr/bin/env python3
from __future__ import annotations

import argparse
from datetime import timedelta
from decimal import Decimal

from nse_paper_agent.data.provider import load_bars_csv
from nse_paper_agent.persistence.db import Database
from nse_paper_agent.persistence.repository import Repository
from nse_paper_agent.paper_broker.broker import PaperBroker
from nse_paper_agent.risk.engine import RiskEngine
from nse_paper_agent.strategy.baseline import BaselineBreakoutStrategy
from nse_paper_agent.domain.models import Quote, Regime, ExitReason


def build_config():
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
        "execution": {
            "last_price_slippage_bps": 25,
        },
        "safety": {
            "global_kill_switch": False,
            "emergency_kill_file": "/never",
        },
    }


def snapshot(repo, risk, quotes, now):
    equity = risk.equity(quotes)
    gross = equity - repo.cash()

    repo.record_account_snapshot_and_checkpoint(
        symbol=next(iter(quotes)),
        bar_end=now,
        cash=repo.cash(),
        equity=equity,
        gross=gross,
        daily_start_equity=repo.db.get_state(
            "daily_start_equity",
            50000.0,
        ),
        drawdown5=0.0,
    )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--bars", required=True)
    parser.add_argument("--db", required=True)
    args = parser.parse_args()

    bars = load_bars_csv(args.bars)
    symbols = sorted({bar.symbol for bar in bars})

    cfg = build_config()

    db = Database(args.db)
    db.initialize()

    repo = Repository(db)

    # Initialize account state only for a brand-new database.
    # Never overwrite persisted account state during restart/recovery.
    if repo.db.get_state("cash") is None:
        repo.set_cash(cfg["account"]["starting_capital"])

    if repo.db.get_state("daily_start_equity") is None:
        repo.db.set_state(
            "daily_start_equity",
            cfg["account"]["starting_capital"],
        )

    broker = PaperBroker(cfg, repo)
    risk = RiskEngine(cfg, repo)
    strategy = BaselineBreakoutStrategy()

    # Restore strategy history from durable storage before processing
    # any new bars. This is required for correct indicator state after
    # a process restart.
    history = {
        symbol: repo.market_bars(symbol)
        for symbol in symbols
    }

    for bar in sorted(bars, key=lambda item: item.end):
        now = bar.end

        # A completed bar must never be processed twice after restart.
        checkpoint = repo.get_checkpoint(bar.symbol)
        if checkpoint is not None and now.isoformat() <= checkpoint:
            continue

        history[bar.symbol].append(bar)

        # Persist every completed market bar.
        repo.record_bar(bar)

        quote = Quote(
            bar.symbol,
            now,
            bar.close * Decimal("0.999"),
            bar.close * Decimal("1.001"),
            bar.close,
            bar.volume,
        )

        # Persist every replay quote.
        repo.record_quote(quote)

        quotes = {bar.symbol: quote}

        # Manage existing positions before evaluating new entries.
        position = repo.positions().get(bar.symbol)

        if position:
            if quote.bid <= position.stop_price:
                broker.sell(
                    bar.symbol,
                    quote,
                    now,
                    position.strategy_version,
                    ExitReason.STOP,
                )
                repo.cooldown(
                    bar.symbol,
                    now + timedelta(
                        minutes=cfg["risk"]["stop_cooldown_minutes"]
                    ),
                    "stop_loss",
                )
            elif quote.bid >= position.target_price:
                broker.sell(
                    bar.symbol,
                    quote,
                    now,
                    position.strategy_version,
                    ExitReason.TARGET,
                )

        if len(history[bar.symbol]) >= 35:
            position_exists = bar.symbol in repo.positions()
            cooldown = repo.in_cooldown(bar.symbol, now)

            signal = strategy.evaluate(
                history[bar.symbol],
                now,
                Regime.RISK_ON,
                0.5,
                position_exists,
                cooldown,
                True,
                True,
            )

            repo.record_signal(
                signal,
                f"replay:{signal.symbol}:{signal.bar_end.isoformat()}",
            )

            if signal.eligible and not position_exists:
                equity = risk.equity(quotes)

                decision = risk.can_buy(
                    now,
                    quotes,
                    equity,
                    Regime.RISK_ON,
                )

                repo.record_risk(
                    now,
                    "ENTRY",
                    decision.allowed,
                    decision.reason,
                    {"symbol": bar.symbol, "score": signal.score},
                )

                if decision.allowed:
                    qty = risk.quantity(
                        quote.ask,
                        equity,
                        quote,
                        decision.size_factor,
                    )

                    if qty > 0:
                        broker.buy(
                            bar.symbol,
                            qty,
                            quote,
                            now,
                            signal.strategy_version,
                        )

        # Persist the account state after processing the bar.
        snapshot(repo, risk, quotes, now)

    print(
        {
            "symbols": len(symbols),
            "bars": len(bars),
            "cash": repo.cash(),
            "open_positions": list(repo.positions()),
        }
    )

    db.close()


if __name__ == "__main__":
    main()
