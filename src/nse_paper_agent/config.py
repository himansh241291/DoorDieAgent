from __future__ import annotations
from pathlib import Path
from typing import Any
import hashlib, yaml

IMMUTABLE_RISK_KEYS = (
    "account.starting_capital", "account.minimum_cash_reserve", "account.max_open_positions",
    "account.max_gross_position", "account.buy_fee", "account.sell_fee", "account.risk_per_trade",
    "risk.hard_stop_pct", "risk.take_profit_pct", "risk.daily_loss_limit_pct",
    "risk.rolling_drawdown_pct", "risk.rolling_drawdown_days", "risk.rolling_block_hours",
    "risk.stop_cooldown_minutes", "risk.slippage_bps", "risk.max_spread_bps",
)

def _get(d: dict, path: str):
    cur=d
    for p in path.split("."): cur=cur[p]
    return cur

def immutable_risk_hash(cfg: dict) -> str:
    material={k:_get(cfg,k) for k in IMMUTABLE_RISK_KEYS}
    return hashlib.sha256(yaml.safe_dump(material, sort_keys=True).encode()).hexdigest()

def load_yaml(path: str) -> dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f: return yaml.safe_load(f) or {}

def validate_runtime_config(cfg: dict) -> None:
    if cfg["app"]["mode"] != "paper": raise ValueError("only paper mode is permitted")
    if cfg["app"].get("debug"): raise ValueError("debug mode is forbidden for normal service")
    if cfg["app"].get("allow_test_data"): raise ValueError("test data is forbidden for normal service")
    if cfg["account"]["starting_capital"] != 50000.0: raise ValueError("starting capital must remain ₹50,000")
    if cfg["account"]["minimum_cash_reserve"] < 2000.0: raise ValueError("cash reserve cannot be weakened")
    if cfg["account"]["max_open_positions"] > 5: raise ValueError("open-position cap cannot exceed 5")
    if cfg["account"]["max_gross_position"] > 10000.0: raise ValueError("gross-position cap cannot exceed ₹10,000")
    if cfg["risk"]["hard_stop_pct"] != 0.015: raise ValueError("hard stop is immutable at 1.5%")
    if cfg["risk"]["take_profit_pct"] != 0.05: raise ValueError("take profit is immutable at 5%")
    if cfg["account"]["buy_fee"] != 20.0 or cfg["account"]["sell_fee"] != 20.0: raise ValueError("transaction fees are immutable at ₹20")
    if cfg["account"]["risk_per_trade"] != 0.003: raise ValueError("risk per trade is immutable at 0.30%")
    if cfg["risk"]["take_profit_pct"] <= 0: raise ValueError("target must be positive")

def resolve_path(config_path: str, value: str) -> str:
    p=Path(value)
    if p.is_absolute(): return str(p)
    return str((Path(config_path).parent / p).resolve())
