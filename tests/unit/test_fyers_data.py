from datetime import date, datetime, timedelta, timezone
from unittest.mock import patch

import pytest

from nse_paper_agent.data.fyers import FyersDataError, FyersHistoryConfig, FyersHistoricalClient


class _Response:
    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self):
        import json

        return json.dumps(self.payload).encode()


def test_normalizes_fyers_timestamp_to_ist_and_five_minute_bar():
    client = FyersHistoricalClient(FyersHistoryConfig("APP", "TOKEN"))
    timestamp = int(datetime(2026, 9, 15, 9, 15, tzinfo=timezone(timedelta(hours=5, minutes=30))).timestamp())

    bar = client._bar("NSE:SBIN-EQ", [timestamp, 100, 101, 99, 100.5, 12345])

    assert bar.symbol == "NSE:SBIN-EQ"
    assert bar.start.isoformat() == "2026-09-15T09:15:00+05:30"
    assert bar.end == bar.start + timedelta(minutes=5)
    assert str(bar.close) == "100.5"
    assert str(bar.volume) == "12345"


def test_fetch_builds_documented_history_request_and_returns_bars():
    payload = {"s": "ok", "code": 200, "candles": [[1788839100, 1004.9, 1006.0, 1002.1, 1006.0, 223150]]}
    client = FyersHistoricalClient(FyersHistoryConfig("APP-100", "TOKEN"))

    with patch("nse_paper_agent.data.fyers.urlopen", return_value=_Response(payload)) as mocked:
        bars = client.fetch("NSE:SBIN-EQ", date(2026, 9, 1), date(2026, 9, 1))

    assert len(bars) == 1
    request = mocked.call_args.args[0]
    assert "symbol=NSE%3ASBIN-EQ" in request.full_url
    assert "resolution=5" in request.full_url
    assert "date_format=1" in request.full_url
    assert "range_from=2026-09-01" in request.full_url
    assert "range_to=2026-09-01" in request.full_url
    assert request.headers["Authorization"] == "APP-100:TOKEN"
    assert request.headers["User-agent"].startswith("Mozilla/5.0")
    assert request.headers["Accept"] == "application/json"


def test_fetch_rejects_failed_fyers_response():
    client = FyersHistoricalClient(FyersHistoryConfig("APP", "TOKEN"))

    with patch("nse_paper_agent.data.fyers.urlopen", return_value=_Response({"s": "error", "code": -16, "message": "Invalid token"})):
        with pytest.raises(FyersDataError, match="Invalid token"):
            client.fetch("NSE:SBIN-EQ", date(2026, 9, 1), date(2026, 9, 1))


def test_fetch_range_chunks_without_overlap():
    client = FyersHistoricalClient(FyersHistoryConfig("APP", "TOKEN"))
    calls = []

    def fake_fetch(symbol, start, end):
        calls.append((symbol, start, end))
        return []

    with patch.object(client, "fetch", side_effect=fake_fetch):
        client.fetch_range("NSE:SBIN-EQ", date(2026, 1, 1), date(2026, 7, 1))

    assert calls == [
        ("NSE:SBIN-EQ", date(2026, 1, 1), date(2026, 4, 10)),
        ("NSE:SBIN-EQ", date(2026, 4, 11), date(2026, 7, 1)),
    ]


def test_rejects_unsupported_resolution():
    with pytest.raises(ValueError, match="5-minute"):
        FyersHistoricalClient(FyersHistoryConfig("APP", "TOKEN", resolution="D"))


def test_rejects_inconsistent_ohlc():
    client = FyersHistoricalClient(FyersHistoryConfig("APP", "TOKEN"))
    timestamp = int(datetime(2026, 9, 15, 9, 15, tzinfo=timezone.utc).timestamp())

    with pytest.raises(FyersDataError, match="Inconsistent OHLC"):
        client._bar("NSE:SBIN-EQ", [timestamp, 100, 99, 98, 99.5, 10])
