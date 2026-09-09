from nse_paper_agent.data.provider import load_bars_csv
def test_fixture_is_deterministic():
 a=load_bars_csv('tests/fixtures/sample_bars.csv'); b=load_bars_csv('tests/fixtures/sample_bars.csv'); assert [(x.symbol,x.end,x.close) for x in a]==[(x.symbol,x.end,x.close) for x in b]
