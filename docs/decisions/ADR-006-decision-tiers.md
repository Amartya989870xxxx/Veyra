# ADR-006 — Four tiers, and the system recommends rather than blocks

**Status:** Accepted · Phase 0 · 2026-08-26

## Context

v1 emitted `ALLOW / REVIEW / BLOCK` per transaction. The brief (§20) argues against
`risk > 0.5 → block` as an architecture, and says an alert/review workflow is both safer
and easier to demonstrate than automatic transaction blocking.

## Decision

| Tier | Meaning | Merchant sees |
|---|---|---|
| `OBSERVE` | Logged, no alert. Score elevated but not actionable | nothing |
| `ALERT` | Notify. Something is happening and the merchant should know | dashboard + notification |
| `REVIEW` | Queue for a human. Evidence is strong enough to spend analyst time | case in the review queue |
| `RESTRICT` | Recommend a specific defensive control on a named cohort | recommendation + one-click action |

**`RESTRICT` recommends. It never acts.** The recommendation names the cohort — these 146
accounts, these 9 devices — and the control, and a human applies it. Veyra is a research
prototype evaluated on synthetic data; it does not get to decline live payments on that
basis.

Thresholds between tiers are set by ADR-005's expected-loss minimisation on validation,
then frozen before the holdout is scored once.

**Hard signals bypass the score.** A small set of unambiguous conditions escalate
regardless of model output, and are recorded as bypasses so the report can separate
model-driven from rule-driven decisions. v1's `BLOCKING_VIOLATIONS` mechanism carries over;
its contents change with the domain.

**Degraded components cannot escalate.** If the relationship engine is unavailable, the
system may still `ALERT`, but not `RESTRICT` — a containment recommendation on a partial
picture is worse than none. Inherited from v1's `BLOCK_CRITICAL_COMPONENTS`.

## Consequences

- Two thresholds to tune rather than one, both chosen on validation.
- Metrics must state which tiers count as a positive prediction. Convention: `ALERT`,
  `REVIEW` and `RESTRICT` are all positives for precision and recall, since all three
  surface the incident; their differing costs are handled in the expected-loss model.
- `OBSERVE` produces the data for the "false alerts per merchant per day" denominator
  without contributing to alert fatigue.

## Alternatives rejected

**Binary flag/no-flag.** Discards the distinction between "worth knowing" and "worth an
analyst's hour", which is most of the operational value.

**Automatic blocking at high scores.** Rejected on the brief's reasoning and on our own:
we cannot honestly estimate the cost of a wrong block, so we should not be making them.
