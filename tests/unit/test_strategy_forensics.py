import sqlite3

from nse_paper_agent.research.strategy_forensics import analyze_db


def _db(path):
    conn = sqlite3.connect(path)
    conn.executescript(
        """
        CREATE TABLE closed_trades(
            id INTEGER PRIMARY KEY,
            symbol TEXT, entry_price REAL, exit_price REAL,
            entry_ts_utc TEXT, exit_ts_utc TEXT,
            exit_reason TEXT, holding_seconds INTEGER, net_pnl REAL
        );
        CREATE TABLE market_bars(
            symbol TEXT, start_utc TEXT, end_utc TEXT,
            high REAL, low REAL, close REAL
        );
        """
    )
    conn.execute(
        "INSERT INTO closed_trades VALUES(1,?,?,?,?,?,?,?,?)",
        (
            "TEST",
            100.0,
            99.0,
            "2026-01-01T10:00:00+00:00",
            "2026-01-01T10:30:00+00:00",
            "FORCED",
            1800,
            -10.0,
        ),
    )
    bars = [
        ("TEST","2026-01-01T10:00:00+00:00","2026-01-01T10:05:00+00:00",101,99,100.5),
        ("TEST","2026-01-01T10:05:00+00:00","2026-01-01T10:10:00+00:00",103,99.5,102),
        ("TEST","2026-01-01T10:10:00+00:00","2026-01-01T10:15:00+00:00",100.5,97,98),
        ("TEST","2026-01-01T10:15:00+00:00","2026-01-01T10:20:00+00:00",99,98,98.5),
        ("TEST","2026-01-01T10:20:00+00:00","2026-01-01T10:25:00+00:00",100,98,99),
        ("TEST","2026-01-01T10:25:00+00:00","2026-01-01T10:30:00+00:00",100,98,99),
        ("TEST","2026-01-01T10:55:00+00:00","2026-01-01T11:00:00+00:00",104,103,104),
        ("TEST","2026-01-01T11:25:00+00:00","2026-01-01T11:30:00+00:00",106,105,106),
        ("TEST","2026-01-01T11:55:00+00:00","2026-01-01T12:00:00+00:00",108,105,106),
    ]
    conn.executemany("INSERT INTO market_bars VALUES(?,?,?,?,?,?)", bars)
    conn.commit()
    conn.close()


def test_analyze_db_extracts_path_and_mfe_mae(tmp_path):
    path = tmp_path / "state.sqlite3"
    _db(path)
    result = analyze_db(path)

    assert result["trades"] == 1
    trade = result["trade_paths"][0]
    assert trade["mfe"] == 0.03
    assert trade["mae"] == -0.03
    assert trade["forward_close_returns"]["5m"] == 0.005
    assert trade["forward_close_returns"]["15m"] == -0.02
    assert trade["forward_close_returns"]["60m"] == 0.04
    assert trade["forward_close_returns"]["120m"] == 0.06
