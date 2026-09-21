import json
import sqlite3

from nse_paper_agent.research.strategy_family_economics import analyze_db, analyze_family


def _make_db(path, trades, fills):
    conn = sqlite3.connect(path)
    conn.executescript(
        """
        CREATE TABLE closed_trades(
            qty INTEGER, entry_price REAL, exit_price REAL,
            entry_fee REAL, exit_fee REAL, gross_pnl REAL, net_pnl REAL,
            holding_seconds INTEGER, exit_reason TEXT
        );
        CREATE TABLE simulated_fills(
            qty INTEGER, price REAL, fee REAL, slippage_estimate REAL, side TEXT
        );
        """
    )
    conn.executemany(
        "INSERT INTO closed_trades VALUES(?,?,?,?,?,?,?,?,?)",
        trades,
    )
    conn.executemany(
        "INSERT INTO simulated_fills VALUES(?,?,?,?,?)",
        fills,
    )
    conn.commit()
    conn.close()


def test_analyze_db_calculates_costs_and_holding(tmp_path):
    db = tmp_path / "state.sqlite3"
    _make_db(
        db,
        [
            (10, 100, 102, 20, 20, 20, -20, 1800, "FORCED"),
            (10, 100, 105, 20, 20, 50, 10, 3600, "TARGET"),
        ],
        [
            (10, 100.1, 20, 0.1, "BUY"),
            (10, 101.9, 20, 0.1, "SELL"),
        ],
    )
    result = analyze_db(db)
    assert result["trades"] == 2
    assert result["gross_pnl"] == 70
    assert result["net_pnl"] == -10
    assert result["fees"] == 80
    assert result["average_holding_minutes"] == 45
    assert result["wins"] == 1
    assert result["losses"] == 1


def test_analyze_family_applies_numeric_gate(tmp_path):
    root = tmp_path / "sweep"
    (root / "results").mkdir(parents=True)
    (root / "work" / "demo-v1").mkdir(parents=True)

    trades = [(10, 100, 101, 20, 20, 10, -30, 60, "FORCED")]
    fills = [(10, 100, 20, 0.1, "BUY"), (10, 100, 20, 0.1, "SELL")]
    _make_db(root / "work" / "demo-v1" / "development.sqlite3", trades, fills)
    _make_db(root / "work" / "demo-v1" / "holdout.sqlite3", trades, fills)

    (root / "results" / "demo-v1.json").write_text(
        json.dumps(
            {
                "development": {
                    "trades": 1,
                    "net_pnl": -30,
                    "expectancy": -30,
                    "max_drawdown": 0.01,
                },
                "holdout": {
                    "trades": 1,
                    "net_pnl": -30,
                    "expectancy": -30,
                    "max_drawdown": 0.05,
                },
            }
        ),
        encoding="utf-8",
    )

    result = analyze_family(root, "demo-v1")
    assert result["numeric_gate"]["eligible"] is False
    assert "insufficient_development_trades" in result["numeric_gate"]["failures"]
    assert "insufficient_holdout_trades" in result["numeric_gate"]["failures"]
    assert "holdout_drawdown_exceeded" in result["numeric_gate"]["failures"]
    assert "holdout_expectancy_not_positive" in result["numeric_gate"]["failures"]
