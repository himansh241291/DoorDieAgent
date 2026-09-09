# NSE Paper Agent

A survival-first, unattended **NSE equity paper-trading research agent**. It uses simulated money and simulated fills only. There is intentionally no live broker implementation, broker credential handling, or broker order endpoint.

## Architecture

```text
MarketDataProvider -> completed 5m bars/quotes -> indicators -> deterministic strategy
                                      |                  |
                                      v                  v
                                 DataHealth         RegimeEngine
                                      |                  |
                                      +------> RiskEngine <---- SentimentProvider
                                                   |
                                             PaperBroker
                                                   |
                                             SQLite WAL
                                                   |
                                      audit / metrics / alerts
```

The build order is deliberate:

1. **Persistence + replay + deterministic paper broker first.**
2. Offline fixtures and tests must pass before a live market-data adapter is introduced.
3. The real-time adapter remains an explicit integration boundary and is not an execution adapter.
4. No broker credentials are accepted or required.

## Safety model

- Starting paper capital: ₹50,000.
- ₹2,000 minimum cash reserve.
- At most five positions.
- ₹10,000 gross allocation cap per position.
- ₹20 buy and ₹20 sell friction.
- 1.5% hard stop and 5% target.
- No averaging down, martingale, pyramiding, or recovery sizing.
- Risk budget defaults to 0.30% of marked equity.
- Daily 2% loss circuit breaker.
- Five completed EOD marks with >=4% peak-to-trough drawdown block new buys for 48 hours.
- Stale/invalid/wide/crossed quotes block entries.
- Global and file kill switches block new buys but do not disable exits.
- Exits are evaluated before entries.
- Buy fills use ask + slippage; sell fills use bid - slippage; last-only data receives larger conservative slippage and is logged by the adapter.
- Strategy files cannot weaken immutable risk controls.

## Strategy

Production baseline is deterministic long-only momentum breakout:

- completed 5-minute bar only;
- close crosses from at/below 20-SMA to above 20-SMA;
- RSI(14) strictly between 50 and 70;
- liquidity filter;
- allowed market regime;
- no held symbol or stop cooldown;
- entry cutoff 14:45 IST.

Regimes: `RISK_ON`, `CAUTIOUS`, `RANGE_BOUND`, `RISK_OFF`, `DATA_DEGRADED`.

Sentiment is optional and fallible. Missing news does not create a signal. The composite score is bounded to [-1,+1] and is a filter/ranking feature only.

## Strategy governance

Production, challenger, and research are separated. Strategy definitions are versioned YAML. Research can produce specifications and validation reports, but it cannot write executable production code. Promotion is deterministic and defaults to human approval.

The repository contains disabled-by-default challenger examples only; they are not enabled by this baseline.

## Setup

### Install system dependencies

```bash
sudo apt-get update
sudo apt-get install -y python3.11 python3.11-venv sqlite3
```

### Dedicated user and directories

```bash
sudo useradd --system --home /opt/nse-paper-agent --shell /usr/sbin/nologin nse-paper
sudo mkdir -p /opt/nse-paper-agent /etc/nse-paper-agent /var/lib/nse-paper-agent /var/log/nse-paper-agent /var/backups/nse-paper-agent /run/nse-paper-agent
sudo chown -R nse-paper:nse-paper /opt/nse-paper-agent /var/lib/nse-paper-agent /var/log/nse-paper-agent /var/backups/nse-paper-agent /run/nse-paper-agent
```

### Virtual environment

```bash
sudo -u nse-paper python3.11 -m venv /opt/nse-paper-agent/.venv
sudo -u nse-paper /opt/nse-paper-agent/.venv/bin/pip install --upgrade pip
sudo -u nse-paper /opt/nse-paper-agent/.venv/bin/pip install -r /opt/nse-paper-agent/requirements.txt
sudo -u nse-paper /opt/nse-paper-agent/.venv/bin/pip install -e /opt/nse-paper-agent
```

Copy configuration and holidays into `/etc/nse-paper-agent/`; update the holiday file from an authoritative NSE exchange calendar before operation. Do not assume Monday-Friday means an open session.

## Offline-first acceptance gate

Run before any market feed is introduced:

```bash
cd /opt/nse-paper-agent
.venv/bin/pytest
.venv/bin/python scripts/initialize_db.py --config config/production.paper.yaml
.venv/bin/python scripts/run_replay.py --bars tests/fixtures/sample_bars.csv --db /tmp/replay.sqlite3
```

The replay harness is deterministic and has no network or broker access.

## Live-market paper trading

The intended current deployment is **live-market paper trading**: the agent may consume live/near-real-time NSE market data, but every entry and exit is simulated and settled by `PaperBroker`. There is no path from the current process to a real broker order endpoint. This distinction is deliberate and must remain true for the current WSL deployment.

The longer-term goal is to validate this research system sufficiently that a separately reviewed real-money execution deployment could be built in the future. That future conversion is documented in `docs/LIVE_TRADING_MIGRATION.md` and is **not implemented as a configuration switch**. In particular, do not add broker credentials or change `app.mode` to obtain live trading. A future live broker adapter must be separately security-reviewed, credential-isolated, reconciliation-capable, and explicitly human-approved.

## WSL2 deployment

WSL2 is supported for continuous operation. Enable systemd in `/etc/wsl.conf`, restart WSL with `wsl --shutdown` from Windows, and follow `docs/WSL.md`. WSL must remain running throughout NSE market hours. The agent fails closed when data becomes stale or unavailable.

For a server-like WSL deployment, use the supplied systemd service, an unprivileged Linux user, and persistent Linux filesystem paths. Do not place the SQLite database or logs on a Windows-mounted `/mnt/c` path when avoidable; keep transactional state on the Linux filesystem.

See `docs/WSL.md` for the complete WSL setup and `docs/LIVE_TRADING_MIGRATION.md` for the future real-money migration boundary.

## Live market-data adapter

`LiveMarketDataAdapterPlaceholder` is intentionally non-functional. A deployment-specific market-data adapter may be added only for **market-data ingestion** and must implement `MarketDataProvider`. It must never expose an execution method and must preserve completed-bar semantics, timestamps, quote-health metadata, reconnection backoff, and audit logging.

Do not use Yahoo Finance/yfinance as an execution-grade feed. Historical backfill may use a clearly labelled research-only source.

## Configuration

Environment variables are read from a protected EnvironmentFile. Secrets are never hardcoded. The only network destination in the project is the optional notification webhook; it is read from an environment variable and is not an execution endpoint.

The service refuses debug mode, test data, non-paper mode, and weakened immutable risk settings.

## systemd

Install the unit files:

```bash
sudo cp systemd/*.service systemd/*.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now nse-paper-agent.service
sudo systemctl enable --now nse-paper-maintenance.timer
```

Commands:

```bash
sudo systemctl status nse-paper-agent
sudo systemctl restart nse-paper-agent
sudo systemctl stop nse-paper-agent
sudo systemctl status nse-paper-maintenance.timer
journalctl -u nse-paper-agent -f
```

## Health and backups

```bash
sudo -u nse-paper /opt/nse-paper-agent/.venv/bin/nse-paper-health --config /etc/nse-paper-agent/production.paper.yaml
sudo -u nse-paper /opt/nse-paper-agent/.venv/bin/python scripts/backup_db.py --config /etc/nse-paper-agent/production.paper.yaml
sqlite3 /var/lib/nse-paper-agent/state.sqlite3 'PRAGMA integrity_check;'
```

SQLite uses WAL and `synchronous=FULL`. Trade/fill state changes are transactional. Fill and signal idempotency keys prevent duplicate operations across retries.

## Recovery

On restart, the agent loads persisted cash/positions, reconnects to data, checks feed health, evaluates existing exits first, and only then considers entries. It never resets the account automatically.

## Observability

Structured JSONL is written to `agent.jsonl` with rotating files. Events include startup/shutdown, session state, data health, signals, risk decisions, regime, sentiment, entries, exits, circuit breakers, and errors. Optional notifications use the same event model without secrets.

## Assumptions

- Quote timestamps are timezone-aware and normalized to UTC internally.
- NSE session logic is evaluated in Asia/Kolkata.
- A stop/target conflict is resolved conservatively by evaluating the stop first.
- Gap-down stops execute at the first conservative executable bid available; no favorable historical fill is invented.
- If a quote has only last price, a larger configured slippage is applied.
- The baseline replay fixture is illustrative and is not a profitability claim.
- The provided holiday list is an operational template and must be maintained from an authoritative exchange source.

## Risk disclosure

This is educational paper-trading software. Paper results do not guarantee live results. Historical and live-paper results are vulnerable to data quality, slippage, spread, survivorship bias, latency, gaps, and regime change. No promise of profitability or income is made.

## Before any future real-money deployment

This repository is intentionally **not** a live-trading system. A future real-money project would require a separate security and compliance review, broker integration isolated behind an independent deployment boundary, credential management, order/reconciliation controls, kill-switch testing, exchange/broker failure handling, market-data licensing review, regulatory review, operational on-call procedures, independent backtesting/validation, and a human-approved change-management process. Do not attach broker credentials to this project as-is.
