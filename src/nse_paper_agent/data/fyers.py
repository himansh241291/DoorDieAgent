from __future__ import annotations

import json
import time
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

from nse_paper_agent.domain.models import Bar

FYERS_HISTORY_URL = "https://api-t1.fyers.in/data/history"
IST = ZoneInfo("Asia/Kolkata")


class FyersDataError(RuntimeError):
    """Raised when FYERS historical-data retrieval or validation fails."""


@dataclass(frozen=True)
class FyersHistoryConfig:
    app_id: str
    access_token: str
    base_url: str = FYERS_HISTORY_URL
    resolution: str = "5"
    request_timeout_seconds: float = 30.0
    max_retries: int = 4
    retry_backoff_seconds: float = 1.0
    min_request_interval_seconds: float = 2.0
    max_days_per_request: int = 100


class FyersHistoricalClient:
    """Read-only FYERS v3 historical candle client for NSE 5-minute data."""

    def __init__(self, config: FyersHistoryConfig):
        if not config.app_id.strip() or not config.access_token.strip():
            raise ValueError("FYERS app_id and access_token are required")
        if config.resolution != "5":
            raise ValueError("DoorDieAgent FYERS ingestion currently supports only 5-minute candles")
        if config.min_request_interval_seconds < 0:
            raise ValueError("min_request_interval_seconds must be non-negative")
        if not 1 <= config.max_days_per_request <= 100:
            raise ValueError("FYERS minute history requests must use 1..100 days per chunk")
        self.config = config
        self._last_request_monotonic: float | None = None

    def _pace(self) -> None:
        if self._last_request_monotonic is None:
            return
        wait = self.config.min_request_interval_seconds - (
            time.monotonic() - self._last_request_monotonic
        )
        if wait > 0:
            time.sleep(wait)

    def _request(self, params: dict[str, str]) -> dict:
        query = urlencode(params)
        request = Request(
            f"{self.config.base_url}?{query}",
            headers={"Authorization": f"{self.config.app_id}:{self.config.access_token}"},
            method="GET",
        )
        last_error: Exception | None = None
        for attempt in range(self.config.max_retries + 1):
            self._pace()
            self._last_request_monotonic = time.monotonic()
            try:
                with urlopen(request, timeout=self.config.request_timeout_seconds) as response:
                    payload = json.load(response)
                if not isinstance(payload, dict):
                    raise FyersDataError("FYERS response is not a JSON object")
                return payload
            except HTTPError as exc:
                body = exc.read().decode("utf-8", errors="replace")
                last_error = FyersDataError(f"FYERS HTTP {exc.code}: {body[:300]}")
                if exc.code not in {408, 429, 500, 502, 503, 504} or attempt >= self.config.max_retries:
                    raise last_error from exc
            except (URLError, TimeoutError, json.JSONDecodeError, OSError) as exc:
                last_error = FyersDataError(f"FYERS request failed: {exc}")
                if attempt >= self.config.max_retries:
                    raise last_error from exc
            time.sleep(self.config.retry_backoff_seconds * (2**attempt))
        raise last_error or FyersDataError("FYERS request failed")

    def fetch(self, symbol: str, start: date, end: date) -> list[Bar]:
        """Fetch one <=100-day range and normalize it to DoorDieAgent Bar objects."""
        if end < start:
            raise ValueError("end must be on or after start")
        if (end - start).days > self.config.max_days_per_request:
            raise ValueError("FYERS minute history request exceeds configured chunk size")
        payload = self._request(
            {
                "symbol": symbol,
                "resolution": self.config.resolution,
                "date_format": "1",
                "range_from": start.isoformat(),
                "range_to": end.isoformat(),
            }
        )
        if payload.get("s") != "ok":
            raise FyersDataError(
                f"FYERS history failed for {symbol}: code={payload.get('code')} message={payload.get('message', '')}"
            )
        candles = payload.get("candles")
        if candles is None:
            return []
        if not isinstance(candles, list):
            raise FyersDataError(f"FYERS candles payload for {symbol} is not a list")
        return [self._bar(symbol, candle) for candle in candles]

    def fetch_range(self, symbol: str, start: date, end: date) -> list[Bar]:
        """Fetch an arbitrary date range by deterministic <=100-day chunks."""
        if end < start:
            raise ValueError("end must be on or after start")
        out: dict[datetime, Bar] = {}
        cursor = start
        while cursor <= end:
            chunk_end = min(cursor + timedelta(days=self.config.max_days_per_request - 1), end)
            for bar in self.fetch(symbol, cursor, chunk_end):
                out[bar.start] = bar
            cursor = chunk_end + timedelta(days=1)
        return [out[key] for key in sorted(out)]

    @staticmethod
    def _bar(symbol: str, candle: list) -> Bar:
        if len(candle) < 6:
            raise FyersDataError(f"Malformed FYERS candle for {symbol}: expected 6 fields")
        try:
            timestamp = int(candle[0])
            start = datetime.fromtimestamp(timestamp, timezone.utc).astimezone(IST)
            open_price, high, low, close = (Decimal(str(value)) for value in candle[1:5])
            volume = Decimal(str(candle[5]))
        except (TypeError, ValueError, InvalidOperation) as exc:
            raise FyersDataError(f"Malformed FYERS candle for {symbol}: {candle!r}") from exc
        if min(open_price, high, low, close) <= 0:
            raise FyersDataError(f"Non-positive OHLC in FYERS candle for {symbol}: {candle!r}")
        if high < max(open_price, close) or low > min(open_price, close) or low <= 0:
            raise FyersDataError(f"Inconsistent OHLC in FYERS candle for {symbol}: {candle!r}")
        if volume < 0:
            raise FyersDataError(f"Negative volume in FYERS candle for {symbol}: {candle!r}")
        end = start + timedelta(minutes=5)
        return Bar(symbol, start, end, open_price, high, low, close, volume)
