# Strategy Health

DoorDieAgent measures strategy health from completed paper-trade outcomes. The health layer is observational: it does not change risk limits, rewrite strategy code, or bypass promotion governance.

## Evidence

For each active strategy the engine computes:

- completed trade sample count;
- mean net P&L (expectancy);
- cumulative trade-sequence drawdown from the paper-account baseline;
- conservative confidence based on a normal-approximation lower confidence bound for positive expectancy;
- expectancy by observed market regime.

Non-finite outcomes are ignored rather than allowed to influence selection.

## Degradation

A strategy remains operationally active while evidence is insufficient. Once enough observations exist, a strategy is paused when either:

- its measured drawdown exceeds the configured health limit; or
- positive long-run expectancy has materially deteriorated in the recent outcome window.

The StrategyPool separately requires valid positive evidence before health-based selection. If no healthy eligible strategy exists, selection fails closed unless the explicitly configured single-strategy bootstrap path is in use.

## Separation of authority

Strategy health can recommend that a strategy should no longer be selected. It cannot loosen or modify the RiskEngine, PaperBroker, immutable safety controls, or production identity. Production promotion remains subject to validation, shadow operation, human approval, and immutable identity governance.
