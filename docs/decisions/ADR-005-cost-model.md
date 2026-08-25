# ADR-005 — Expected loss selects thresholds; every constant is a declared assumption

**Status:** Accepted · Phase 0 · 2026-08-26

## Context

The buildathon track asks explicitly about false-positive cost (§21). Maximising F1 picks
an operating point that is indifferent between blocking a legitimate customer and missing
an attack, which no merchant is.

The brief also warns (§22, §42) against presenting invented cost constants as though they
were Razorpay economics.

## Decision

**Thresholds minimise expected loss on the validation split, subject to a review-capacity
cap.** Never F1, never accuracy.

```
Expected loss = FN × cost_fn + FP × cost_fp + reviews × review_cost
```

**Exposure** attributed to an incident:

```
exposure = at_risk_gmv × P(loss | incident_type)
         + n_txn × (chargeback_fee + fulfilment_cost + support_cost)
         + promo_exposure                      # incentive-abuse scenarios only
```

`P(loss | incident_type)` is per-scenario-family: a card-testing burst costs
authorisation fees and processor standing, not the notional GMV of declined attempts,
whereas a promo-abuse incident costs real marketing budget. A single flat multiplier over
GMV would badly misprice both.

**Every constant is labelled `ASSUMPTION`, lives in config, and is printed in the report
beside the number it produced.** No cost figure is presented as sourced industry data
unless it carries a citation to a Razorpay-published document.

**The review-effectiveness assumption is stated, not buried.** A reviewed incident is
modelled as caught: prevented loss plus analyst cost. That is optimistic about analysts,
it is inherited from v1, and it belongs in the report's assumptions table rather than in a
function body.

## Consequences

- Reported expected-loss figures are only as good as the constants. This is why the
  ablation between detectors — same constants, different systems — is the defensible
  comparison, and the absolute rupee figure is not.
- Sensitivity of the chosen threshold to the cost constants should be reported alongside
  the label-sensitivity table from ADR-003.
- Different scenario families having different `P(loss)` means the cost model needs the
  predicted incident type, not just a score. The incident object carries it.

## Alternatives rejected

**Maximise F1.** Equal treatment of the two error types, which contradicts the track.

**A single GMV multiplier for all incident types.** Misprices card testing (attempts
mostly decline; the loss is fees and processor standing) and promo abuse (loss is budget,
not GMV) in opposite directions.
