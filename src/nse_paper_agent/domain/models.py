from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Any
class Regime(str, Enum):
    RISK_ON = "RISK_ON"; CAUTIOUS = "CAUTIOUS"; RANGE_BOUND = "RANGE_BOUND"; RISK_OFF = "RISK_OFF"; DATA_DEGRADED = "DATA_DEGRADED"
class Side(str, Enum): BUY = "BUY"; SELL = "SELL"
class ExitReason(str, Enum): STOP = "STOP"; TARGET = "TARGET"; FORCED = "FORCED"; MANUAL = "MANUAL"
@dataclass(frozen=True)
class Quote:
    symbol: str; ts: datetime; bid: Decimal|None; ask: Decimal|None; last: Decimal|None; volume: Decimal=Decimal("0")
@dataclass(frozen=True)
class Bar:
    symbol: str; start: datetime; end: datetime; open: Decimal; high: Decimal; low: Decimal; close: Decimal; volume: Decimal
@dataclass
class Position:
    symbol: str; qty: int; entry_price: Decimal; stop_price: Decimal; target_price: Decimal; entry_fee: Decimal; strategy_version: str; entry_ts: datetime; last_mark: Decimal
@dataclass(frozen=True)
class Fill:
    idempotency_key: str; symbol: str; side: Side; qty: int; price: Decimal; fee: Decimal; ts: datetime; strategy_version: str; slippage_estimate: Decimal; reason: str
@dataclass(frozen=True)
class SentimentObservation:
    symbol: str; ts: datetime; score: float|None; confidence: float; source: str; fresh_until: datetime|None; components: dict[str,float]=field(default_factory=dict)
@dataclass(frozen=True)
class RegimeSnapshot:
    ts: datetime; regime: Regime; metrics: dict[str,float]; reason: str
@dataclass(frozen=True)
class RiskDecision:
    allowed: bool; reason: str; size_factor: float=1.0; events: tuple[str,...]=()
@dataclass(frozen=True)
class Signal:
    symbol: str; bar_end: datetime; strategy_version: str; eligible: bool; reason: str; score: float|None=None; metadata: dict[str,Any]=field(default_factory=dict)
