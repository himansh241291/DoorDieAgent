# Strategy Portfolio

DoorDieAgent uses a strategy portfolio rather than a permanent single-strategy dependency.

## Runtime boundary

The StrategyPool is above the RiskEngine. A strategy can propose an eligible signal, but the pool only selects among registered strategies and the RiskEngine remains the final authority for entries.

The portfolio layer must never change immutable account/risk controls, fill rules, kill switches, cooldowns, or exit behavior.

## Bootstrap mode

The first integration registers only `baseline-breakout-v1`. Until the strategy-health evidence pipeline is populated, the pool has an explicit single-active-strategy bootstrap fallback. This is compatibility plumbing, not evidence of strategy quality.

The fallback is intentionally disabled when multiple strategies are active or when a production deployment requires health-scored selection.

## Future adaptive mode

When multiple strategies are available, selection must use persisted evidence:

1. strategy eligibility and availability;
2. regime compatibility;
3. minimum health evidence;
4. recent and rolling expectancy;
5. drawdown and confidence;
6. regime-specific performance;
7. deterministic tie-breaking.

No strategy may self-promote, self-edit, weaken risk controls, or bypass validation/shadow/human-approval gates.

## Lifecycle

`RESEARCH -> VALIDATED -> SHADOW -> APPROVED -> PRODUCTION`

A production strategy identity is immutable for its deployment. A new strategy version is a new identity and must pass governance before production use.

## Design intent

The long-term loop is:

`observe -> evaluate -> select -> trade -> measure -> learn -> validate -> adapt -> survive`

Learning proposes or ranks strategies. Governance decides whether a challenger may become production. Risk always has veto authority.
