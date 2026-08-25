# Tyche — Evaluation Report

**Run ID:** `run_01a022da1e21425b826714f979a7ad99`
**Dataset:** `ds_dfd5b063f4e49d3c`
**Generated:** 2026-08-21T05:45:47.997708+00:00

> **This is a research prototype evaluated on synthetic data.** Every number below was
> produced by a generator we wrote. It measures whether agent-behaviour and campaign
> context add information *on this benchmark*. It does not establish real-world performance,
> and it was not trained on or validated against any Razorpay data.

## 1. Dataset

| Property | Value |
|---|---|
| Transactions | 10,027 |
| Agent actions | 48,691 |
| Sessions | 8,327 |
| Delegations | 1,578 |
| Episodes (split groups) | 2,996 |
| Distinct campaigns | 28 |
| Abusive transactions | 1,508 (15.0%) |
| Hard negatives | 2,691 (31.6% of legitimate traffic) |

### Composition by class

| Class | Transactions |
|---|---|
| COORDINATED_ABUSE | 507 |
| LEGIT_AGENT | 3,513 |
| LEGIT_HUMAN | 5,006 |
| SUSPICIOUS_AUTOMATION | 1,001 |

### Composition by scenario

| Scenario | Transactions |
|---|---|
| agent_authorization_mismatch | 285 |
| agent_enterprise_bulk | 689 |
| agent_fast_comparison | 534 |
| agent_retry_hammer | 204 |
| agent_routine_purchase | 1,671 |
| agent_sequence_anomaly | 231 |
| agent_subscription_runs | 619 |
| agent_velocity_abuse | 281 |
| campaign_coupon_abuse | 156 |
| campaign_device_farm | 109 |
| campaign_instrument_probing | 75 |
| campaign_new_account_rush | 33 |
| campaign_sku_targeting | 134 |
| flash_sale_burst | 669 |
| household_shared_device | 253 |
| human_high_value | 160 |
| human_normal | 2,636 |
| human_repeat_buyer | 902 |
| retry_payment_failure | 386 |

Hard-negative scenarios — legitimate traffic deliberately built to trip naive rules:
`agent_enterprise_bulk`, `agent_fast_comparison`, `flash_sale_burst`, `household_shared_device`, `human_high_value`, `retry_payment_failure`.

## 2. Methodology

**Split.** Stratified group split. Groups (generated episodes) are the atomic unit; stratification is on (label_class, scenario). Splitting individual transactions would place the
same device farm on both sides of the wall and inflate every detector.

| Split | Transactions | Groups | Campaigns | Abusive | Hard negatives |
|---|---|---|---|---|---|
| train | 7,034 | 2,110 | 18 | 1,069 | 1,875 |
| validation | 1,590 | 466 | 5 | 263 | 446 |
| holdout | 1,403 | 420 | 5 | 176 | 370 |

**Leakage check:** `leakage_free = True`

| Overlap | train↔validation | train↔holdout | validation↔holdout |
|---|---|---|---|
| Groups | 0 | 0 | 0 |
| Campaigns | 0 | 0 | 0 |
| Customers | 0 | 0 | 0 |
| Devices | 0 | 0 | 0 |

Merchants, SKUs and coupons are shared global catalog entities and overlap by design.

All operating points below were selected on the validation split.

**Training protocol.** Population baselines fit on train only. Component models fit on
train. Fusion weights fit on *grouped out-of-fold* component predictions from train.
Operating points chosen on validation by minimum expected loss under a review-rate cap.
The holdout was scored once, with frozen thresholds, and never used for tuning.

**Positive prediction** means BLOCK *or* REVIEW: both stop the loss. Their very different
costs are handled in the expected-loss model rather than folded into precision.

## 3. Results

### Holdout (frozen thresholds, scored once)

| Detector | Precision | Recall | F1 | PR-AUC | FP rate | Expected loss |
|---|---|---|---|---|---|---|
| Baseline 1 — static rules | 0.348 | 0.977 | 0.513 | 0.888 | 26.2% | ₹17,100 |
| Baseline 2 — transaction-only ML | 0.907 | 0.835 | 0.870 | 0.951 | 1.2% | ₹64,941 |
| Tyche — full agent + campaign context | 0.994 | 0.994 | 0.994 | 0.999 | 0.1% | ₹2,807 |

### Validation (used for threshold selection)

| Detector | Precision | Recall | F1 | PR-AUC | FP rate | Expected loss |
|---|---|---|---|---|---|---|
| Baseline 1 — static rules | 0.414 | 0.901 | 0.568 | 0.838 | 25.2% | ₹198,253 |
| Baseline 2 — transaction-only ML | 0.932 | 0.890 | 0.911 | 0.946 | 1.3% | ₹240,150 |
| Tyche — full agent + campaign context | 0.985 | 0.996 | 0.991 | 1.000 | 0.3% | ₹9,819 |

## 4. Decision mix and merchant cost (holdout)

| Detector | Review threshold | Block threshold | Allow | Review | Block | Blocked legit GMV | Prevented loss | Expected loss |
|---|---|---|---|---|---|---|---|---|
| Baseline 1 — static rules | 0.05 | 0.25 | 64.8% | 24.8% | 10.4% | ₹0 | ₹940,853 | ₹17,100 |
| Baseline 2 — transaction-only ML | 0.15 | 0.85 | 88.5% | 1.6% | 9.9% | ₹0 | ₹880,013 | ₹64,941 |
| Tyche — full agent + campaign context | 0.15 | 0.70 | 87.5% | 0.1% | 12.4% | ₹0 | ₹941,306 | ₹2,807 |

**Cost assumptions** (synthetic, configurable, not sourced industry figures):

| Parameter | Value | Meaning |
|---|---|---|
| `fn_cost_multiplier` | 1.0 | Merchant loss per missed abusive transaction, as a multiple of its amount |
| `chargeback_fee_flat` | ₹750 | Flat dispute-handling fee per missed abuse |
| `fp_cost_multiplier` | 0.25 | Lost margin/goodwill per wrongly blocked legitimate transaction |
| `review_cost_flat` | ₹40 | Analyst cost per manual review |

A reviewed transaction is modelled as caught: reviewed abuse counts as prevented loss plus
an analyst cost. That is an optimistic assumption about analyst effectiveness and it is
stated here rather than buried in the code.

## 5. Hard negatives and legitimate automation (holdout)

This is the section that decides whether the system is safe to deploy. `hard_negatives` is
legitimate traffic engineered to look suspicious — flash-sale bursts, shared household
devices, enterprise bulk buyers, very fast legitimate agents, gateway-retry storms. Any flag
here is a false positive on a paying customer.

| Detector | Slice | Transactions | False positives | FP rate |
|---|---|---|---|---|
| Baseline 1 — static rules | hard_negatives | 370 | 200 | 54.1% |
| Baseline 1 — static rules | legit_agent | 455 | 156 | 34.3% |
| Baseline 1 — static rules | legit_human | 772 | 166 | 21.5% |
| Baseline 2 — transaction-only ML | hard_negatives | 370 | 12 | 3.2% |
| Baseline 2 — transaction-only ML | legit_agent | 455 | 15 | 3.3% |
| Baseline 2 — transaction-only ML | legit_human | 772 | 0 | 0.0% |
| Tyche — full agent + campaign context | hard_negatives | 370 | 0 | 0.0% |
| Tyche — full agent + campaign context | legit_agent | 455 | 1 | 0.2% |
| Tyche — full agent + campaign context | legit_human | 772 | 0 | 0.0% |

## 6. Detection on the target loss class (holdout)

| Detector | Slice | Transactions | Recall | Missed |
|---|---|---|---|---|
| Baseline 1 — static rules | coordinated_abuse | 87 | 0.954 | 4 |
| Baseline 1 — static rules | suspicious_automation | 89 | 1.000 | 0 |
| Baseline 2 — transaction-only ML | coordinated_abuse | 87 | 0.678 | 28 |
| Baseline 2 — transaction-only ML | suspicious_automation | 89 | 0.989 | 1 |
| Tyche — full agent + campaign context | coordinated_abuse | 87 | 0.989 | 1 |
| Tyche — full agent + campaign context | suspicious_automation | 89 | 1.000 | 0 |

### Campaign detection lead time

Context windows are past-only, so the first transaction of a campaign has no cluster to
observe. This measures the cost of that honesty: how many transactions into a campaign the
first flag lands.

| Detector | Campaigns | Detected | Median txns before first flag | Calibration error |
|---|---|---|---|---|
| Baseline 1 — static rules | 5 | 5 | 0.0 | 0.048 |
| Baseline 2 — transaction-only ML | 5 | 5 | 0.0 | 0.019 |
| Tyche — full agent + campaign context | 5 | 5 | 0.0 | 0.009 |

## 7. Per-scenario behaviour — Tyche (holdout)

| Scenario | Transactions | Ground truth | Recall | FP rate |
|---|---|---|---|---|
| agent_authorization_mismatch | 38 | abusive | 1.000 | — |
| agent_enterprise_bulk | 40 | legitimate | — | 0.0% |
| agent_fast_comparison | 79 | legitimate | — | 0.0% |
| agent_retry_hammer | 12 | abusive | 1.000 | — |
| agent_routine_purchase | 246 | legitimate | — | 0.0% |
| agent_sequence_anomaly | 13 | abusive | 1.000 | — |
| agent_subscription_runs | 90 | legitimate | — | 1.1% |
| agent_velocity_abuse | 26 | abusive | 1.000 | — |
| campaign_coupon_abuse | 24 | abusive | 1.000 | — |
| campaign_device_farm | 19 | abusive | 1.000 | — |
| campaign_instrument_probing | 12 | abusive | 1.000 | — |
| campaign_new_account_rush | 9 | abusive | 0.889 | — |
| campaign_sku_targeting | 23 | abusive | 1.000 | — |
| flash_sale_burst | 155 | legitimate | — | 0.0% |
| household_shared_device | 22 | legitimate | — | 0.0% |
| human_high_value | 23 | legitimate | — | 0.0% |
| human_normal | 390 | legitimate | — | 0.0% |
| human_repeat_buyer | 131 | legitimate | — | 0.0% |
| retry_payment_failure | 51 | legitimate | — | 0.0% |

## 8. Threshold sweep and expected-loss curve (validation)

Best point per block threshold. The chosen operating point minimises expected loss subject to the review-rate cap.

### Baseline 1 — static rules

| Review | Block | Precision | Recall | F1 | FP rate | Review rate | Blocked legit GMV | Prevented loss | Expected loss |
|---|---|---|---|---|---|---|---|---|---|
| 0.05 | 0.05 | 0.414 | 0.901 | 0.568 | 25.2% | 0.0% | ₹8,036,226 | ₹1,004,220 | ₹2,191,055 |
| 0.05 | 0.10 | 0.414 | 0.901 | 0.568 | 25.2% | 0.0% | ₹8,036,226 | ₹1,004,220 | ₹2,191,055 |
| 0.05 | 0.15 | 0.414 | 0.901 | 0.568 | 25.2% | 18.4% | ₹67,954 | ₹1,004,220 | ₹210,707 |
| 0.05 | 0.20 | 0.414 | 0.901 | 0.568 | 25.2% | 23.4% | ₹15,824 | ₹1,004,220 | ₹200,834 |
| 0.05 | 0.25 | 0.414 | 0.901 | 0.568 | 25.2% | 24.1% | ₹3,739 | ₹1,004,220 | ₹198,253 |
| 0.05 | 0.30 | 0.414 | 0.901 | 0.568 | 25.2% | 25.6% | ₹3,739 | ₹1,004,220 | ₹199,213 |
| 0.05 | 0.35 | 0.414 | 0.901 | 0.568 | 25.2% | 25.9% | ₹3,739 | ₹1,004,220 | ₹199,413 |
| 0.05 | 0.40 | 0.414 | 0.901 | 0.568 | 25.2% | 26.5% | ₹0 | ₹1,004,220 | ₹198,878 |
| 0.05 | 0.45 | 0.414 | 0.901 | 0.568 | 25.2% | 27.3% | ₹0 | ₹1,004,220 | ₹199,358 |
| 0.05 | 0.50 | 0.414 | 0.901 | 0.568 | 25.2% | 28.4% | ₹0 | ₹1,004,220 | ₹200,038 |
| 0.05 | 0.55 | 0.414 | 0.901 | 0.568 | 25.2% | 30.1% | ₹0 | ₹1,004,220 | ₹201,118 |
| 0.05 | 0.60 | 0.414 | 0.901 | 0.568 | 25.2% | 30.3% | ₹0 | ₹1,004,220 | ₹201,238 |

### Baseline 2 — transaction-only ML

| Review | Block | Precision | Recall | F1 | FP rate | Review rate | Blocked legit GMV | Prevented loss | Expected loss |
|---|---|---|---|---|---|---|---|---|---|
| 0.05 | 0.05 | 0.839 | 0.890 | 0.863 | 3.4% | 0.0% | ₹164,615 | ₹947,468 | ₹279,903 |
| 0.10 | 0.10 | 0.886 | 0.890 | 0.888 | 2.3% | 0.0% | ₹104,532 | ₹947,468 | ₹264,883 |
| 0.15 | 0.15 | 0.932 | 0.890 | 0.911 | 1.3% | 0.0% | ₹83,934 | ₹947,468 | ₹259,733 |
| 0.15 | 0.20 | 0.932 | 0.890 | 0.911 | 1.3% | 0.5% | ₹32,375 | ₹947,468 | ₹247,163 |
| 0.15 | 0.25 | 0.932 | 0.890 | 0.911 | 1.3% | 0.7% | ₹27,174 | ₹947,468 | ₹245,983 |
| 0.15 | 0.30 | 0.932 | 0.890 | 0.911 | 1.3% | 0.8% | ₹25,855 | ₹947,468 | ₹245,693 |
| 0.15 | 0.35 | 0.932 | 0.890 | 0.911 | 1.3% | 0.9% | ₹24,840 | ₹947,468 | ₹245,520 |
| 0.15 | 0.40 | 0.932 | 0.890 | 0.911 | 1.3% | 1.0% | ₹3,743 | ₹947,468 | ₹240,325 |
| 0.15 | 0.45 | 0.932 | 0.890 | 0.911 | 1.3% | 1.0% | ₹3,743 | ₹947,468 | ₹240,325 |
| 0.15 | 0.50 | 0.932 | 0.890 | 0.911 | 1.3% | 1.5% | ₹3,048 | ₹947,468 | ₹240,472 |
| 0.15 | 0.55 | 0.932 | 0.890 | 0.911 | 1.3% | 1.5% | ₹3,048 | ₹947,468 | ₹240,472 |
| 0.15 | 0.60 | 0.932 | 0.890 | 0.911 | 1.3% | 1.5% | ₹3,048 | ₹947,468 | ₹240,472 |

### Tyche — full agent + campaign context

| Review | Block | Precision | Recall | F1 | FP rate | Review rate | Blocked legit GMV | Prevented loss | Expected loss |
|---|---|---|---|---|---|---|---|---|---|
| 0.05 | 0.05 | 0.978 | 0.996 | 0.987 | 0.5% | 0.0% | ₹6,345 | ₹1,176,599 | ₹11,205 |
| 0.10 | 0.10 | 0.981 | 0.996 | 0.989 | 0.4% | 0.0% | ₹5,104 | ₹1,176,599 | ₹10,895 |
| 0.15 | 0.15 | 0.985 | 0.996 | 0.991 | 0.3% | 0.0% | ₹4,367 | ₹1,176,599 | ₹10,711 |
| 0.15 | 0.20 | 0.985 | 0.996 | 0.991 | 0.3% | 0.1% | ₹4,367 | ₹1,176,599 | ₹10,751 |
| 0.15 | 0.25 | 0.985 | 0.996 | 0.991 | 0.3% | 0.1% | ₹2,868 | ₹1,176,599 | ₹10,416 |
| 0.15 | 0.30 | 0.985 | 0.996 | 0.991 | 0.3% | 0.2% | ₹2,012 | ₹1,176,599 | ₹10,242 |
| 0.15 | 0.35 | 0.985 | 0.996 | 0.991 | 0.3% | 0.2% | ₹2,012 | ₹1,176,599 | ₹10,242 |
| 0.15 | 0.40 | 0.985 | 0.996 | 0.991 | 0.3% | 0.2% | ₹2,012 | ₹1,176,599 | ₹10,242 |
| 0.15 | 0.45 | 0.985 | 0.996 | 0.991 | 0.3% | 0.2% | ₹2,012 | ₹1,176,599 | ₹10,242 |
| 0.15 | 0.50 | 0.985 | 0.996 | 0.991 | 0.3% | 0.2% | ₹2,012 | ₹1,176,599 | ₹10,242 |
| 0.15 | 0.55 | 0.985 | 0.996 | 0.991 | 0.3% | 0.2% | ₹2,012 | ₹1,176,599 | ₹10,242 |
| 0.15 | 0.60 | 0.985 | 0.996 | 0.991 | 0.3% | 0.3% | ₹776 | ₹1,176,599 | ₹9,973 |

## 9. Learned fusion weights

Logistic-regression coefficients over component scores, fitted on grouped out-of-fold
predictions from the training split. `avail_*` terms are the availability flags that let the
model treat a missing component as *unknown* rather than as zero risk.

| Fusion input | Coefficient |
|---|---|
| transaction_risk | +2.521 |
| behavior_risk | +5.324 |
| campaign_risk | +7.444 |
| intent_deviation | +1.659 |
| rule_violation_score | +2.409 |
| avail_transaction_risk | -0.006 |
| avail_behavior_risk | -0.006 |
| avail_campaign_risk | -0.006 |
| avail_intent_deviation | -5.312 |
| avail_rule_violation_score | -0.006 |

Intercept: `-5.177`

## 10. What this does and does not show

**What it shows.** On this benchmark, adding agent-behaviour, authorization and
entity-graph/temporal context to transaction-level signals improves detection of coordinated
automated abuse, and does so while keeping the false-positive rate on engineered hard
negatives low. The comparison is an ablation: the transaction-only baseline uses the same
estimator, seed and training split, and differs only in the features it can see.

**What it does not show.**

1. **Real-world performance.** The data is synthetic. The abuse patterns are ones we chose
   to generate, and a detector evaluated on its own author's imagination has an obvious
   advantage. High absolute scores here should be read as "the signal is present and
   learnable in this benchmark", not as an expected production number.
2. **Robustness to adaptive abuse.** Nothing here is adversarial in the game-theoretic
   sense. An abuser who knows the features would jitter their timings and rotate devices.
3. **That the benchmark is neutral.** It is not, and it took explicit work to get it closer.
   An earlier version made `actor_type == AGENT` almost perfectly separating, which would
   have validated exactly the premise this product rejects — that automation is fraud. The
   composition was rebalanced and campaign traffic was given ordinary transaction-level
   marginals so that abuse has to be found in relationships rather than in a single field.
   That history is documented in `docs/evaluation.md`.
4. **Anything about Razorpay systems.** No proprietary data, API or model was used or
   approximated.
