# ADR-007 — The generator is bound by a contract enforced in CI

**Status:** Accepted · Phase 0 · 2026-08-26

## Context

v1 reported F1 0.994 / PR-AUC 0.999 on its holdout. That is not a good result; it is the
failure mode the brief describes in §13. The model learned the generator.

The mechanism was structural. v1 generated *episodes* — each scenario emitted a
self-contained bundle of transactions — so an episode's identity was recoverable from its
own contents, and no amount of careful splitting could fix that.

Any v2 number is worthless unless the generator is constrained by something stronger than
intention.

## Decision

**Structural inversion.** Merchant timelines are simulated first, in full, with
seasonality, trend and organic arrivals. Scenarios are then injected as *perturbations of
an ongoing stream*, reusing the merchant's own customer pool, amount distribution and
device population. There is no bundle boundary to recognise.

**Five generator rules**, per scenario, declared in `matrix.yaml` and checked in CI:

1. **No sentinel values.** Every injected variable is drawn from a distribution that
   overlaps the benign one. Card-testing amounts sit in the merchant's low tail, never at
   a fixed value.
2. **Intensity is a random variable.** `intensity_range` on every attack row, reaching a
   low end where the attack is genuinely undetectable. If every attack is detectable,
   recall measures our generosity.
3. **Every attack knob also fires benignly.** Retry storms raise decline rate, renewal
   batches raise velocity and instrument count, households raise device reuse, flash sales
   raise new-account rate. Enforced by check C4: the confusion graph must be symmetric, so
   the generator cannot build an attack without also building what hides it.
4. **Attacks reuse the merchant's real entity pools** where realistic. A compromised
   account is an existing account with genuine history.
5. **No feature may separate an attack alone.** `forbid_single_feature_separability`,
   verified by gate G1 — any single feature exceeding 0.90 univariate AUC fails the build.

**Six leakage gates** (roadmap Phase 5). G1 univariate AUC, G2 label shuffle, G3 generator
knob recovery, G4 split integrity, G5 leave-one-scenario-out, G6 cross-generator.

**G5 is the load-bearing one.** Train with an attack family entirely absent and test on it.
A real attacker does not use a technique from the training set, so LOSO recall is the
closest honest proxy for catching something new. It is reported whatever it says.

## Consequences

- v2's headline numbers will be **materially lower than v1's, and that is the point**. Any
  v2 result approaching 0.99 should be treated as evidence of a new leak, not success.
- Generating benign look-alikes for every attack roughly doubles generator work. That cost
  is the price of a testable claim.
- Scenarios composed from others (`ring_under_flash_sale`, `dual_cluster_benign_and_malicious`)
  need paired benign-only instances or they measure nothing. Declared in their recipes.

## Alternatives rejected

**Keeping the v1 episode generator and splitting more carefully.** The leak is structural,
not a splitting artifact.

**Real data only.** No public dataset has incident-level labels, merchant windows and
entity relationships together. Synthetic data is necessary; the contract is what makes it
defensible. Real data enters as the cross-generator check (G6) and the IEEE-CIS benchmark.
