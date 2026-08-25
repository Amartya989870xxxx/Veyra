# Architecture decision records

Decisions that are expensive to reverse, recorded at the point they were made and why.
Each states what was decided, what it costs, and what was rejected. A decision that
turns out wrong gets a new ADR superseding the old one — the old one is not edited.

| ADR | Decision | Status |
|---|---|---|
| [001](ADR-001-detection-unit.md) | The unit of detection is the merchant-window, not the transaction | Accepted |
| [002](ADR-002-windows-and-baselines.md) | Four detection windows, three baseline windows, hour-of-week baselines | Accepted |
| [003](ADR-003-label-definition.md) | Window labels are lifted from transaction truth by an explicit, published rule | Accepted |
| [004](ADR-004-downstream-signals.md) | Disputes and RTO are label sources and are structurally barred from features | Accepted |
| [005](ADR-005-cost-model.md) | Expected loss drives thresholds; every constant is a declared assumption | Accepted |
| [006](ADR-006-decision-tiers.md) | Four tiers, and the system recommends rather than blocks | Accepted |
| [007](ADR-007-synthetic-data-contract.md) | The generator is bound by a contract enforced in CI | Accepted |
