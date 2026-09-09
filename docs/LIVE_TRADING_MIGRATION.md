# Future Real-Money Trading Migration Plan

## Current state

This repository is intentionally **paper-only**. The current runtime can ingest live/near-real-time market data only through a deployment-specific market-data boundary, while all entries and exits are simulated by `PaperBroker`. There is no live broker endpoint or broker credential support.

## Future state

Real-money trading must be a separate deployment milestone, not a runtime configuration toggle.

Required gates:

1. Sustained live-paper validation across multiple market regimes.
2. Independent reconciliation of paper fills against captured quotes and execution assumptions.
3. Fault-injection and restart/recovery validation of every risk invariant.
4. Frozen, versioned strategy and immutable risk configuration.
5. Independent security review of credentials, host, network, dependencies, logging, and deployment permissions.
6. Broker/exchange permissions, market-data rights, and applicable regulatory/compliance review.
7. A separately reviewed broker adapter with explicit submission, acknowledgement, rejection, cancellation, and failure semantics.
8. Broker-side position/order reconciliation so local state cannot silently diverge.
9. Credentials isolated from this repository and from the paper service.
10. Controlled emergency cancellation/kill testing.
11. Staged rollout with hard notional limits and human supervision.
12. Explicit human approval for every environment transition.

## Non-negotiable separation

Do **not** convert paper mode to live money by changing `app.mode`, adding an API key, or swapping an environment variable. The eventual live execution component must be separately reviewed and deployed. This paper service must remain incapable of sending broker orders.

## Future architecture

```text
Shared deterministic research/risk logic
          |
    +-----+-----+
    |           |
 PAPER       FUTURE LIVE
    |           |
PaperBroker  Reviewed LiveBroker
    |           |
SQLite      Broker reconciliation
```

A strategy is never promoted to real money merely because paper P&L is positive. The promotion package must include out-of-sample evidence, shadow-paper results, regime analysis, execution-cost sensitivity, failure cases, risk verification, and explicit human approval.
