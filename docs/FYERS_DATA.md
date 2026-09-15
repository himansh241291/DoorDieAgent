# FYERS Historical Data

DoorDieAgent uses FYERS only as a **market-data source**. The current agent remains paper-only; this integration has no order-placement method.

## Local credentials

Store credentials outside the repository:

```text
~/.config/doordieagent/fyers_app_id
~/.config/doordieagent/fyers_access_token
```

Keep both files mode `0600`. Never commit them or paste them into source/configuration tracked by Git.

## Historical API

The client uses FYERS API v3 History API at:

```text
https://api-t1.fyers.in/data/history
```

DoorDieAgent currently normalizes **5-minute** candles only. FYERS minute history is limited to 100 days per request, so the downloader splits longer ranges into non-overlapping 100-calendar-day chunks. FYERS returns candles as `[epoch, open, high, low, close, volume]`, where the timestamp identifies the start of the candle. citeturn798469search1turn798469search7

## Download normalized replay data

Example for the benchmark plus liquid NSE cash-equity symbols:

```bash
mkdir -p data
python scripts/download_fyers_history.py \
  --symbols 'NSE:NIFTY50-INDEX,NSE:RELIANCE-EQ,NSE:TCS-EQ,NSE:HDFCBANK-EQ,NSE:ICICIBANK-EQ,NSE:INFY-EQ,NSE:SBIN-EQ' \
  --start 2025-09-15 \
  --end 2026-09-14 \
  --output data/fyers_5m_1y.csv
```

The downloader is deliberately conservative for historical backfill:

- Requests are paced with a default two-second minimum interval.
- Each completed symbol/date chunk is cached under `<output>.cache/`.
- Existing valid cached chunks are reused on subsequent runs.
- The final replay CSV is rebuilt atomically from the cache.
- A failed or interrupted run can therefore be restarted without redownloading completed chunks.
- `--request-interval` can be increased for a more conservative cadence.

The output uses the same CSV schema consumed by `scripts/run_replay.py`:

```text
symbol,start,end,open,high,low,close,volume
```

The downloader reports the returned candle count and zero-volume count per chunk. Zero volume is reported rather than silently fabricated because market-data quality must be measured before replay conclusions are trusted.

FYERS states that historical data and quotes/market data are available to clients at zero data-feed fees when the app has the relevant permissions. citeturn798469search4

## Research sequence

Use the downloader in this order:

1. Pull a small date range for one stock and the NIFTY50 benchmark.
2. Verify timestamps, session coverage, volume, and duplicate-free output.
3. Pull a larger multi-symbol period.
4. Run the existing deterministic replay without changing strategy/risk rules.
5. Compare trade count, expectancy, drawdown, regime distribution, forced exits, and data-quality metrics.
6. Expand the research universe and period only after the first real-data run is reproducible.

The first real-data run is a **measurement exercise**, not a parameter-optimization exercise. Do not loosen risk controls or strategy gates to manufacture trades.
