# ADR-004 — Downstream signals are label sources, structurally barred from features

**Status:** Accepted · Phase 0 · 2026-08-26

## Context

Disputes, chargebacks and return-to-origin outcomes are the strongest available indicators
that a transaction was fraudulent. They are also unavailable when the decision has to be
made: a chargeback arrives 14–90 days after the payment, an RTO after a delivery attempt.

The brief (§6.10) is explicit — these may be used for training and evaluation, but must
not be blindly included as real-time input features.

A model that trains on `dispute_rate` scores beautifully offline and cannot run in
production. The failure is silent: nothing errors, the metrics simply become fiction.

## Decision

Every feature in `research/features.yaml` carries `downstream_only`. Three are true today:
`I.dispute_rate`, `I.rto_rate`, `I.chargeback_rate`.

Three enforcement points, because a convention that lives only in a document will be
violated:

1. **`research/validate.py` check C7** — a downstream-only feature referenced by a
   non-retrospective scenario fails the Phase 0 gate. Already active.
2. **A unit test over the feature registry** (Phase 1) — asserts no downstream-only
   feature appears in any assembled feature vector.
3. **Event-time separation in the generator** (Phase 2) — dispute and RTO events carry
   timestamps 14–90 days after their originating transaction, so a past-only window
   builder cannot see them even if the barrier above were removed.

Refunds are deliberately **not** downstream-only. A refund is initiated by the merchant
within minutes to days and is genuinely observable in near-real time; the refund-abuse
scenario depends on that. `I.refund_latency_median` is the feature that keeps this honest —
it measures the delay rather than assuming it away.

## Consequences

- `dispute_cohort_wave` is not a real-time detector and is scored only on
  `retrospective_label_quality`: given the disputes that eventually arrived, could the
  originating window have been flagged at the time from what was then observable?
- Disputes remain valuable as a label source for real datasets, which is how IEEE-CIS is
  used.
- Any future signal with a settlement delay must declare `downstream_only` when added, and
  C7 will reject it if it is then referenced by a live scenario.

## Alternatives rejected

**Feature with a lag term** (`dispute_rate_as_of_30_days_ago`). Defensible in principle
and rejected on scope: it needs a full point-in-time feature store to be correct, and one
mistake reintroduces the leak invisibly.

**Convention only.** Documented rules of this kind are violated under deadline pressure,
which is exactly when it matters.
