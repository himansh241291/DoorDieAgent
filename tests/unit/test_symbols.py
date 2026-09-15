from nse_paper_agent.data.symbols import canonical_symbol, resolve_benchmark_symbol


def test_canonical_symbol_removes_exchange_and_index_suffix():
    assert canonical_symbol("NSE:NIFTY50-INDEX") == "NIFTY50"
    assert canonical_symbol("nifty50") == "NIFTY50"


def test_resolve_benchmark_symbol_matches_provider_symbol():
    available = {
        "NSE:NIFTY50-INDEX",
        "NSE:RELIANCE-EQ",
    }
    assert resolve_benchmark_symbol("NIFTY50", available) == "NSE:NIFTY50-INDEX"


def test_resolve_benchmark_symbol_prefers_exact_match():
    available = {
        "NIFTY50",
        "NSE:NIFTY50-INDEX",
    }
    assert resolve_benchmark_symbol("NIFTY50", available) == "NIFTY50"


def test_resolve_benchmark_symbol_returns_none_when_absent():
    assert resolve_benchmark_symbol("NIFTY50", {"NSE:RELIANCE-EQ"}) is None
