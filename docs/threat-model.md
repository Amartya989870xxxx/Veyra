# Veyra — threat model and scope

**Phase 0 deliverable** · 2026-08-26
Companion to [`research/matrix.yaml`](../research/matrix.yaml), which holds the per-scenario detail.

---

## 1. What Veyra defends

A merchant accepting online payments through a payment platform. Veyra observes that
merchant's payment event stream and answers one question:

> Has the *shape* of this merchant's payment activity changed, and if so, does the change
> look like coordinated abuse or like legitimate demand?

It is an **observability and alerting** system, not a payment authorisation system. It
produces incidents for people to act on. It does not decline payments (ADR-006).

## 2. What is in scope

Abuse that produces an observable change in **aggregate** payment telemetry within an hour.
Thirteen attack scenarios and four adversarial compositions, grouped by loss mechanism:

| Family | Scenarios | Merchant loses |
|---|---|---|
| Instrument abuse | `card_testing_burst`, `bin_enumeration_attack` | Authorisation fees, processor standing |
| Account abuse | `distributed_account_abuse`, `device_farm_ring`, `account_takeover_wave` | Fraudulent GMV, chargebacks, fulfilment |
| Incentive abuse | `promo_coupon_abuse` | Marketing budget, distorted acquisition metrics |
| Composition shift | `geographic_anomaly_burst`, `payment_method_shift_anomaly` | Fraudulent GMV, cross-border dispute exposure |
| Merchant level | `merchant_compromise_burst` | Fraudulent GMV, settlement hold, platform liability |
| Post-transaction | `refund_abuse_wave`, `cod_rto_abuse`, `dispute_cohort_wave` | Refunded GMV, shipping, inventory |
| Platform level | `cross_merchant_coordinated_ring` | Distributed GMV across merchants |
| Adversarial | `ring_under_flash_sale`, `low_volume_relationship_anomaly`, `dual_cluster_benign_and_malicious`, `slow_ramp_infiltration` | As above, while evading detection |

Ten legitimate scenarios exist solely so the attacks have something to be told apart from.
Every attack row names at least one, and the confusion graph is required to be symmetric —
check C4 in `research/validate.py`. **The generator cannot build an attack without also
building what hides it.**

## 3. What is out of scope

| Excluded | Why |
|---|---|
| Transaction-level fraud scoring | Different unit of detection; the platform already does this (ADR-001) |
| Authentication and credential-stuffing defence | An authentication-security product, not a payment-risk one. Appears only as a contextual signal |
| Real-time payment blocking | Not defensible from a synthetic-data prototype (ADR-006) |
| Merchant onboarding and KYC risk | Different data, different lifecycle |
| Dispute evidence generation | A separate track direction in the buildathon brief |
| Inventory scalping / SKU targeting | Real, and deliberately deferred — declared in `external_lookalikes` so a later matrix version must add it properly |
| Money laundering / settlement-layer abuse | Not visible in merchant payment telemetry |

## 4. Defence-only boundary

The buildathon risk track requires defence-only work (§32), and the matrix is written to
respect it.

**What this repository contains.** Descriptions of what attack patterns look like *in
aggregate telemetry*, so that they can be detected. Synthetic generators that produce
those aggregate shapes in fabricated data. Detection models, evaluation harnesses, and an
offline evasion suite that attacks **our own detector** to measure where it stops working.

**What it does not contain, and will not.** Credential testing or stuffing tooling. Card
testing or enumeration tooling. Attack automation of any kind. Anything that runs against
a live system, ours or anyone else's. Detection-evasion tooling intended for use against
third-party defences.

The distinction in practice: a `mechanism` field says *"attempts arrive against a rapidly
growing set of never-before-seen instruments, most declining"* — the observable signature.
It never says how to obtain instruments, which merchants are soft targets, or how to pace
attempts to avoid a rate limit. The red-team suite (roadmap §7.2) sweeps evasion
parameters against Veyra in simulation to produce a detection-floor chart; its output is a
measurement of our own weakness, which is a defensive artifact.

All attack data is synthetic and offline. No real payment data, card number, credential or
production identifier enters this repository at any point.

## 5. Adversary model

**Assumed capabilities.** Controls many accounts, devices, network endpoints and payment
instruments. Can pace, ramp and distribute activity. Can observe which of their attempts
succeed and adapt. Can time activity to coincide with legitimate merchant events.

**Assumed limits.** Cannot read Veyra's model, thresholds or feature set. Cannot alter the
merchant's historical baseline. Cannot suppress event emission. Cannot make one physical
device present as unlimited independent fingerprints at zero cost — the cost of entity
diversity is what makes relationship features work at all, and if that assumption fails,
family J degrades. Stated because it is load-bearing.

**Adaptation is modelled explicitly** rather than assumed away, as nine evasion knobs
(roadmap §7.2) swept to find each detector's detection floor. `slow_ramp_infiltration` is
the case realistic enough to have been promoted from an evasion knob to a first-class
matrix scenario.

## 6. Known blind spots

Stated here rather than discovered by a judge.

- **Fan-out below the cross-merchant threshold.** An operator spread thinly enough across
  enough merchants stays under every per-merchant threshold and under the platform
  fan-out threshold too. `cross_merchant_coordinated_ring` measures where that floor sits;
  it does not eliminate it.
- **Attacks slower than the longest detection window.** An operator ramping over days is
  drift, not a spike, and Veyra is a spike detector. The 1h window with a 28d baseline is
  the limit of what it sees.
- **Cold-start merchants.** Under 14 days of history means a category baseline and
  `baseline_confidence: LOW` (ADR-002). A merchant attacked from day one has no normal to
  deviate from.
- **Single-transaction high-value fraud.** One fraudulent ₹500,000 payment is invisible to
  an incident detector. It is a transaction-scoring problem, and out of scope by design.
- **Entity spoofing at zero cost.** If device and network fingerprints become free to
  fabricate uniquely, family J loses its signal and Veyra falls back to families A–I.
  Evasion E3 measures how much that costs the detector.

## 7. Data handling

No real payment data. No card numbers, and no card metadata beyond a hashed BIN prefix in
synthetic records. No credentials, OTPs or production identifiers. Public research datasets
(roadmap §7.1) are fetched by script with checksums, never committed, and used under their
own terms — IEEE-CIS for non-commercial research, Kaggle datasets under their competition
rules. `.gitignore` excludes `data/real/` and bulk data formats.

## 8. Source discipline

Every claim in reports and presentation is labelled by origin:

| Label | Meaning |
|---|---|
| **Razorpay-published fact** | Cited to a Razorpay documentation URL |
| **External research** | Cited to a named public source |
| **Synthetic benchmark assumption** | A parameter we chose; the value is printed with the result |
| **Veyra experimental result** | Produced by our own evaluation, on synthetic or public data |

Cost constants are assumptions (ADR-005) and are never presented as Razorpay economics.
Veyra does not claim to detect all fraud, and does not claim to outperform any production
payment-risk platform.
