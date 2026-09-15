# Adaptive Strategy Lifecycle

DoorDieAgent is designed to operate as a survival-first adaptive paper-trading system, not as a single-strategy bot.

## Operating loop

```text
Observe market
  -> classify market state / regime
  -> evaluate multiple strategies
  -> compare only strategies with validated health
  -> apply immutable risk controls
  -> paper execute
  -> record outcome and context
  -> update strategy health
  -> detect degradation
  -> research challengers
  -> validate challengers on unseen data
  -> shadow-test
  -> human approval
  -> activate
```

## Separation of responsibilities

**Strategy** decides whether its own setup exists and returns a signal.

**StrategyPool** registers strategies and selects among eligible, explicitly active strategies using recorded health. It must never change risk limits or strategy code.

**RiskEngine** remains authoritative for account and trade safety. A strategy selection can never bypass risk checks.

**Research/Governance** evaluates candidates and controls promotion. Research output cannot directly rewrite production strategy code.

**Production identity** remains tied to a version/config/risk manifest so an unexpected strategy change cannot silently become production.

## Strategy states

The existing promotion lifecycle is deliberately separate from runtime availability. Runtime availability is:

- `RESEARCH`: not eligible for live-paper selection.
- `SHADOW`: observes live conditions without controlling entries.
- `ACTIVE`: explicitly approved for runtime selection.
- `PAUSED`: temporarily ineligible while exits remain governed by the normal risk/execution lifecycle.
- `RETIRED`: permanently excluded from selection.

Promotion remains a governed process; activation is not inferred from recent profitability.

## Selection rules

A strategy is selectable only when all of the following are true:

1. It is explicitly `ACTIVE`.
2. It has recorded evidence (`samples > 0`).
3. Expectancy is finite and positive.
4. Recorded drawdown is finite and valid.
5. Confidence is positive and finite.
6. If regime-specific evidence exists, it is positive for the current regime.
7. Its current signal is eligible.
8. Its registration permits the current regime.

Among selectable strategies, ranking is deterministic: higher expectancy first, then lower drawdown, then higher confidence, then larger sample size, then explicit registration priority, then version as a stable final tie-breaker.

No arbitrary normalization factor is used in runtime ranking.

## Fail-closed behaviour

Missing or invalid strategy health does not create a trade. If no healthy eligible strategy exists, the pool returns `no_healthy_eligible_strategy` and the caller must not manufacture a fallback signal.

Strategy selection does not alter:

- position limits;
- cash reserve;
- risk-per-trade;
- hard stops;
- circuit breakers;
- data-health requirements;
- execution conservatism;
- kill-switch behaviour.

## Learning boundary

The agent may learn from observations and outcomes, but learning produces **evidence and proposals**, not unrestricted self-modification.

```text
Observation
  -> evidence
  -> research hypothesis
  -> validation
  -> shadow
  -> approval
  -> activation
```

A losing streak must never cause automatic risk expansion, stop widening, martingale behaviour, or removal of a safety control.

## Current status

The current V1 baseline remains frozen as a rejected research baseline. The adaptive portfolio layer is being introduced without changing the V1 strategy or risk configuration. New strategies must enter through the same governed lifecycle.
