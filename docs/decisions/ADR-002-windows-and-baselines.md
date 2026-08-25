# ADR-002 — Window set and baseline construction

**Status:** Accepted · Phase 0 · 2026-08-26

## Context

The brief (§10) lists 1m, 5m, 15m, 1h and 24h as detection horizons, and (§9) argues a
raw count is meaningless without a merchant-specific expectation.

## Decision

**Detection windows: 1m, 5m, 15m, 1h.** Every window is scored, on a 60s grid.

**Baseline windows: 24h, 7d, 28d.** These build the expectation. **24h is explicitly not
a detection window** — an alert whose evidence needs a full day to accumulate is a
post-mortem, not a detection, and reporting it alongside 1m detections would inflate
recall with findings no merchant could act on.

Baselines are keyed:

```
merchant × feature × window_size × hour_of_week
```

with robust statistics — median or EWMA for location, **MAD for scale, never stddev**,
because a single past spike poisons a standard deviation and permanently desensitises the
merchant.

```
deviation = (observed − expected) / max(MAD, floor)
```

**Cold start.** A merchant with fewer than 14 days of history falls back to a
category-level population baseline, and every incident it produces carries
`baseline_confidence: LOW`. New merchants are scored, not skipped, but the incident says
what it is standing on.

**Population term.** `seasonal_festival_spike` is a population event: peer merchants move
together. A merchant-only baseline cannot see that and will alert on every festival. The
baseline therefore carries a category-level concurrent-movement term, so a merchant rising
with its whole category deviates less than one rising alone.

**Baselines fit on the training period only.** Refitting across the full timeline is
temporal leakage. Enforced by gate G4.

## Consequences

- Storage is `merchants × features × 4 window sizes × 168 hour-of-week buckets`. Large but
  bounded, and the reason `baseline_store` is its own store (roadmap §30).
- Sparse merchants have thin hour-of-week buckets. Buckets below a support threshold widen
  to day-of-week, then to a flat merchant baseline, and the fallback level is recorded.
- Slow-ramp attacks (`slow_ramp_infiltration`) that stay inside short-window tolerance are
  caught, if at all, by the 1h window. This is a known and accepted limitation, measured
  as a detection floor rather than hidden.

## Alternatives rejected

**24h as a detection window.** Rejected above.

**Global rather than per-merchant baselines.** 500 transactions/hour is an emergency for
one merchant and a Tuesday for another. A global baseline detects merchant size.

**Stddev for scale.** One historical spike raises the scale permanently, so the merchant
that was attacked once becomes the merchant that can never be alerted on again.
