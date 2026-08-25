# ADR-003 — Window labels are lifted by an explicit rule

**Status:** Accepted · Phase 0 · 2026-08-26

## Context

ADR-001 makes the window the scored unit, but truth — synthetic and real alike — arrives
per transaction. Something must turn transaction truth into window truth, and that rule
determines every metric in the project.

No public dataset carries incident-level labels, so the same rule must serve both the
synthetic benchmark and any real dataset (roadmap §7.1).

## Decision

```
window is POSITIVE  iff  n_abusive     >= K
                    and  abusive_share >= max(M, merchant_baseline_rate * 3)

defaults: K = 5, M = 0.20
```

The `merchant_baseline_rate * 3` term matters on real data, where a merchant with a 4%
standing fraud rate should not have every window labelled positive by the flat 20% floor.

**Three classes, not two.** `NORMAL`, `LEGIT_SPIKE`, `FRAUD_SPIKE`. Collapsing the first
two would hide the only false-positive number that matters: "did not fire on a Tuesday"
and "did not fire on a flash sale" are entirely different achievements. Detection is
binary (`FRAUD_SPIKE` vs the rest); reporting is three-way.

**Sensitivity is published, not assumed.** Every report carries the headline metrics
recomputed across `K ∈ {3, 5, 10}` and `M ∈ {0.1, 0.2, 0.4}`. A result that moves
materially under a different labelling rule is an artifact of the rule, and we would
rather find that ourselves.

## Consequences

- The boundary windows of an incident — where the attack is ramping and only two abusive
  transactions have landed — are labelled negative. Detection latency is therefore
  measured against the first *positive* window, which understates how early the system
  reacted. Accepted: it errs against us.
- On real data the lift depends on the pseudo-merchant segmentation, which is itself a
  choice (roadmap §7.1). Segmentation and lifting parameters are both reported.
- Changing K or M invalidates cross-run comparison. Both are recorded in `eval_store`
  with every run.

## Alternatives rejected

**Any abusive transaction makes the window positive (K=1, M=0).** Labels nearly every
window in a busy merchant positive during a diffuse attack, and makes precision
uninterpretable.

**Labelling by generator intent rather than by content.** Tempting for synthetic data —
we know which windows we attacked — but it cannot transfer to real data, and it labels a
window positive when the injected attack happened to place no transactions in it.
