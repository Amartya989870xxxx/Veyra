# ADR-001 — The unit of detection is the merchant-window

**Status:** Accepted · Phase 0 · 2026-08-26

## Context

v1 scored individual transactions. The research brief argues (§3, §7) that the strongest
fraud signals are visible only when transactions are examined collectively — a single
transaction in a card-testing burst is unremarkable, and the burst is obvious.

Scoring transactions and aggregating afterwards was considered. It fails on the central
case: a transaction that is individually normal, in a window that is collectively
abnormal, gets a low score no matter how the scores are later combined. The information
that makes it suspicious does not exist at the row level.

## Decision

The scored unit is:

```
(merchant_id, window_size, window_end)
```

Windows are scored on a 60-second grid. An **incident** is a maximal run of flagged
windows for one merchant, gap tolerance 2 windows, assembled by the incident manager.

Two reporting layers:

- **Window level** — a continuous score, giving a smooth PR-AUC and a calibration curve.
- **Incident level** — the headline. Recall, precision, detection latency, missed GMV.

## Consequences

- Feature code operates on window aggregates. No feature may read a single row's outcome.
- The evaluation needs a match rule between predicted and true incidents. Defined in the
  roadmap Phase 5: any temporal overlap, greedy one-to-one by earliest start, extra
  overlapping predictions count as false positives.
- Per-transaction explanations are no longer available, and were never the product. An
  incident names the cohort and the evidence; it does not rule on individual payments.
- Merchants with very low volume produce mostly-empty windows. Handled by the baseline
  confidence policy in ADR-002, not by dropping them.

## Alternatives rejected

**Transaction-level scoring with post-hoc aggregation.** Fails the collective-signal case
above, which is the entire premise of the project.

**Cluster as the unit.** Attractive — abuse is cluster-shaped — but clusters have no
natural time boundary, cannot be enumerated for a negative class, and make "false alerts
per merchant per day" undefinable. Clusters remain a *feature* (family J) and are scored
inside windows.
