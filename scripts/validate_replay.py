#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json

from nse_paper_agent.persistence.db import Database
from nse_paper_agent.research.validation import require_long_duration, validate_replay


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate a completed DoorDieAgent replay database")
    parser.add_argument("--db", required=True)
    parser.add_argument("--min-trading-days", type=int, default=60)
    args = parser.parse_args()

    db = Database(args.db)
    db.initialize()
    try:
        result = validate_replay(db)
        require_long_duration(result, args.min_trading_days)
        print(json.dumps(result.as_dict(), indent=2, sort_keys=True))
    finally:
        db.close()


if __name__ == "__main__":
    main()
