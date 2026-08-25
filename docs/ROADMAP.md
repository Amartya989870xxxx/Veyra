# Tyche v2 — Build Roadmap

**Source of truth:** `Tyche_Fraud_Spike_Deep_Problem_Research.md`
**Status:** proposed, not yet started
**Written:** 2026-08-25

---

## 0. The verdict up front

The research brief and the current codebase solve **different problems**.

| | Current code (v1) | Brief (v2) |
|---|---|---|
| Unit of detection | one transaction | `(merchant, window)` → incident |
| Question asked | "is this transaction abusive?" | "has this merchant's payment *shape* changed, and does the change look coordinated?" |
| Label | `LabelClass` per transaction | incident is fraud-spike vs legitimate-spike vs normal |
| Domain vocabulary | agents, delegations, sessions, trust tiers | merchants, instruments, devices, geography, outcomes |
| Output | `ALLOW / REVIEW / BLOCK` on a payment | an **incident object** with evidence, exposure, explanation |
| Hard negative | fast legitimate agent | Diwali sale, influencer campaign, product launch |

So: **the framing is replaced, the engineering is kept.** v1 has real discipline in it that took effort to get right and would be stupid to throw away — past-only feature windows, one context type shared by the online and offline paths, a frozen holdout, components that degrade instead of substituting fake values. All of that survives. What changes is what those machines are pointed at.

### Three facts that shape everything below

1. **There is no version control.** `git init` is task #1. Nothing else is safe until it exists.
2. **There are zero tests.** `tests/` has four empty directories over 11,002 lines of source. The anti-leakage work in Phase 2 is impossible without a test harness, so the harness gets built first.
3. **The v1 headline number is a symptom, not an achievement.** F1 0.994 / PR-AUC 0.999 on the holdout is what §13 of the brief describes: the model learned the generator. Treat that number as a *bug report*. v2 should expect — and publish — materially lower, more honest numbers.

---

## Phase 0 — The research matrix (the §43 gate)

The brief closes with an explicit instruction: do not rebuild until the research matrix is complete. Phase 0 honours that, with one change that makes it worth more than a document.

**Make the matrix executable.** Not prose — a machine-readable spec at `research/matrix.yaml` that becomes the single source that drives the scenario generator, the feature registry, and the evaluation slices. When you add a row to the matrix, a generator scenario, a feature group and an eval slice all appear. When they drift apart, a test fails.

One row per scenario:

```yaml
- id: card_testing_burst
  family: instrument_abuse
  mechanism: >
    Attacker validates a list of stolen/generated card numbers by
    attempting many low-value authorisations against a soft merchant.
  observable_signals:
    - attempt_velocity_up
    - decline_rate_up
    - unique_instruments_up
    - median_amount_down
    - instrument_per_device_up
  time_scale: [1m, 5m, 15m]
  entity_relationships:
    dense: [device->instrument, ip->instrument]
    sparse: [account->device]
  merchant_loss:
    direct: gateway_auth_fees
    downstream: [chargebacks, processor_penalty, mid_risk_rating]
  legitimate_lookalike:
    - gateway_retry_storm          # decline rate up, velocity up, amounts NORMAL
    - subscription_renewal_batch   # velocity up, instruments high, declines moderate
  discriminator: >
    Retry storms reuse a SMALL instrument set with a HIGH repeat rate.
    Card testing shows instrument cardinality growing ~1:1 with attempts.
  features: [C.instrument_per_txn, I.decline_rate_dev, D.median_amount_dev, A.accel_5m]
  synthetic_recipe:
    inject: [velocity, instrument_cardinality, decline_rate, low_amount_concentration]
    forbid_single_feature_separability: true
  eval_metric: [window_pr_auc, incident_recall, detection_latency_p50]
  real_data_proxy: ieee_cis   # see Phase 7
```

**The `legitimate_lookalike` and `discriminator` fields are the most important two.** A scenario without a named look-alike and a stated discriminator is a scenario you cannot evaluate honestly — it is where §5 ("volume anomaly is evidence, not a verdict") becomes code.

### Decisions to lock in Phase 0

These are architectural and expensive to change later. My recommendations:

| Decision | Recommendation | Why |
|---|---|---|
| Detection unit | `(merchant_id, window_size, window_end)` | Directly scoreable, and incidents assemble from it |
| Detection windows | 1m, 5m, 15m, 1h | Fast enough to alert on |
| Baseline windows | 24h, 7d, 28d | 24h is context, **not** a detection window — a 24h alert is a post-mortem |
| Evaluation cadence | score every 60s | Gives real latency measurement |
| Primary score | window-level, continuous | Smooth PR-AUC; incidents assemble from flagged runs |
| Reported headline | **incident-level** | §23 asks for it, and it is the honest unit |

**Deliverables:** `research/matrix.yaml` (18–23 scenarios), `docs/decisions/ADR-001..007`, `docs/threat-model.md`.
**Effort:** 3–4 days. **Gate:** every scenario has ≥1 named look-alike and a stated discriminator.

---

## Phase 1 — Foundations

### 1.1 Repository hygiene (day 1, blocking)

```
git init && git add -A && git commit -m "v1 baseline before fraud-spike pivot"
git checkout -b v2-fraud-spike
```

Commit `tyche.db`? No — add to `.gitignore` along with `.venv/`, `artifacts/`, `reports/*.json`. Tag the v1 commit `v1-agent-commerce` so the old evaluation stays reproducible and citable as prior work.

### 1.2 Test harness before anything else

`tests/` is empty. Build the skeleton now, because Phase 2's leakage gates are tests:

```
tests/unit/          feature functions, baseline maths, window arithmetic
tests/integration/   ingest → aggregate → score → incident, end to end
tests/evaluation/    leakage gates G1–G6 (Phase 5) — these gate CI
tests/failure/       degraded components, missing baselines, clock skew, dupes
tests/property/      NEW: hypothesis-based invariants on the window aggregator
```

Property tests matter here more than usual. The window aggregator is where off-by-one and boundary bugs silently corrupt every downstream number. Invariants worth asserting: sum of 1m counts over an hour equals the 1h count; a window never sees an event at or after `window_end`; baselines are invariant to event insertion order.

### 1.3 Event schema — payment-centric

Replace `app/schemas/events.py` and `enums.py`. Drop `ActionType`, `ActorType`, `TrustTier`, `AgentSession`, `AgentDelegation`.

```
PaymentAttemptEvent    merchant, customer, instrument_fp, instrument_meta(brand/type/issuer_country/bin_hash),
                       device_fp, ip_fp, geo(country/state/city), amount, currency,
                       payment_method, is_cod, coupon_id, order_id, ts
PaymentResultEvent     txn_id, status, failure_code, ts
RefundEvent            txn_id, amount, reason_code, ts
DisputeEvent           txn_id, dispute_type, ts        # downstream label ONLY
OrderStatusEvent       order_id, status(SHIPPED/DELIVERED/RTO), ts
```

**One rule with teeth:** `DisputeEvent` and RTO outcomes are **label sources, never real-time features** (§6.10). Enforce it in code — a `downstream_only: bool` flag on the field registry, and a unit test that fails if any downstream field appears in a feature vector. This is the kind of leak that is invisible in a report and fatal in a demo.

### 1.4 Storage model (§30)

Six stores, six concerns:

| Store | Holds | Notes |
|---|---|---|
| `raw_events` | immutable normalized events | append-only, idempotent on `event_id` |
| `feature_store` | window aggregates per `(merchant, window, ts)` | the join key for everything |
| `baseline_store` | per-merchant expected behaviour + variability | versioned; refit on a schedule |
| `relationship_store` | entity-pair counters and degrees | TTL'd; the graph engine's persistence |
| `incident_store` | incidents + lifecycle + evidence | first-class object |
| `eval_store` | predictions, ground truth, run metadata | makes runs reproducible and diffable |

New Alembic migration. Do not try to migrate v1 data — regenerate.

**Effort:** 4–5 days.

---

## Phase 2 — Data (the phase that decides whether the project is real)

### 2.1 Generator v2 — normal first, injection second

The v1 generator builds *episodes* — a scenario emits a self-contained bundle of transactions. That structure is the root cause of the leakage, because an episode's identity is recoverable from its own contents.

v2 inverts it (§14):

```
1. Build merchant population        size, category, geo mix, method mix, COD share, price distribution
2. Simulate normal timelines        for the full period, per merchant:
                                      seasonality (hour-of-day, day-of-week, festivals)
                                      trend, noise, organic customer arrival process
3. THEN inject scenarios            legitimate spikes and attacks are perturbations of a
                                    merchant's OWN ongoing stream, not appended bundles
4. Lift labels to windows           (see 2.3)
```

The difference matters: an injected attack shares the merchant's normal traffic, its customer pool, its amount distribution and its device population. The model cannot separate attack from background by recognising a bundle boundary.

### 2.2 Anti-leakage as a design constraint, not a review step

Concrete rules for the generator:

- **No sentinel values.** Every attack-injected variable is drawn from a distribution that *overlaps* the normal distribution. If `amount` under card testing is `₹1.00` exactly, you have built §13's bad generator.
- **Attack intensity is a random variable**, sampled per-incident from a wide range — including intensities so low the attack is genuinely undetectable. If every attack is detectable, your recall is meaningless.
- **Every attack knob also fires occasionally under benign scenarios.** Gateway retry storms raise decline rate. Subscription batches raise velocity. Household devices raise device reuse. Flash sales raise new-account rate.
- **Attack traffic uses the merchant's own entity pools** where realistic (a compromised account is a *real* account with history).
- **No global attacker signature.** Devices, IPs and instruments in an attack are drawn from the same fingerprint space as legitimate ones.

### 2.3 Label lifting — the rule that makes incidents scoreable

Both synthetic and real data need transaction-level truth turned into window truth. State it once, apply it everywhere:

```
window is POSITIVE  iff  n_abusive >= K
                    and  abusive_share >= max(M, merchant_baseline_rate * 3)

default K = 5, M = 0.20
```

Then **report the sensitivity** to `K ∈ {3,5,10}` and `M ∈ {0.1,0.2,0.4}` as a table. A result that survives the label definition moving is a result. One that does not is an artifact of the threshold, and you want to know that before a judge asks.

Legitimate spikes get their own label value — `LEGIT_SPIKE` — distinct from `NORMAL`. Three classes, not two, because "did not fire on a flash sale" and "did not fire on a Tuesday" are completely different achievements and collapsing them hides the only FP number that matters.

### 2.4 Scenario library (§15, §37)

Primary attacks: card testing, distributed account/device abuse, promo abuse, geo anomaly, payment-method anomaly, merchant-level abnormal burst.
Downstream: refund anomaly, dispute cohort anomaly, COD/RTO abuse.
Hard negatives: flash sale, influencer campaign, product launch, seasonal/festival, gateway retry storm, subscription batch, international expansion.
Adversarial mixes: fraud ring hidden inside a legitimate spike; moderate volume + extreme relationship density; simultaneous benign and malicious clusters.

**Effort:** 8–10 days. This is the single highest-leverage phase in the project.

---

## Phase 3 — Features

### 3.1 Feature registry driven by the matrix

```python
@feature(family="C", windows=["1m","5m","15m","1h"], downstream_only=False)
def instrument_per_txn(w: WindowAgg) -> float: ...
```

Registry gives you, free: the leakage gate can enumerate every feature; the report can group by family; the `downstream_only` test can enforce §6.10; and matrix rows referencing a non-existent feature fail CI.

Families A–J exactly as §8 lists them. Two implementation notes:

- **Ratios over counts** (§8C). `unique_devices / transactions` transfers across merchant sizes; `unique_devices` does not. Prefer ratios and deviations; keep raw counts only as evidence for the explanation layer.
- **Every feature has a deviation twin.** For feature `f`, also emit `f_dev = (f - baseline(f)) / robust_scale(f)`. The raw value answers "what is it"; the deviation answers "is it abnormal *for this merchant*" — and per §9 the second is what the model should mostly consume.

### 3.2 Baseline engine (§9)

Per merchant, per feature, per window size, per hour-of-week:

```
expected     = robust location  (median or EWMA)
variability  = robust scale     (MAD, not stddev — one spike poisons stddev)
deviation    = (observed - expected) / max(variability, floor)
```

Cold start is a real problem and needs a stated policy: a merchant with under N days of history falls back to a category-level population baseline, and the incident records `baseline_confidence: LOW`. Do not silently score a new merchant against a baseline built from six hours of data.

**Baselines fit on the training period only.** Refitting on the full timeline is temporal leakage, and it is the easiest one to commit by accident.

### 3.3 Relationship engine (§16)

`app/graph/networkx_engine.py` already computes something close to what is needed — `ClusterSummary` has entity counts, span, interarrival CV, concentration. Extend rather than rewrite:

- Per-window bipartite degree distributions: accounts/device, devices/account, instruments/device, accounts/IP, addresses/account
- Concentration measures: Gini and entropy over each degree distribution — "10 devices serving 500 accounts" is a shape, not a count
- Cluster extraction within the window: size, density, and how much of the window's volume the largest cluster carries
- **Cross-merchant**: entities appearing at N merchants in the same window (§6.8) — this is what makes Phase 7's E8 evasion detectable
- Novelty: share of entities never seen in this merchant's history

All of it computed **past-only**, over the window plus a bounded lookback. Preserve the v1 discipline here exactly.

**Effort:** 6–8 days.

---

## Phase 4 — Models and decisions

Three detectors, all tuned properly (§26). A strawman baseline is worse than no baseline — it invalidates the comparison.

**Baseline A — volume only.** Rolling z-score on transaction count. Threshold tuned on validation by expected loss. This is what "just alert on spikes" achieves, and it will have a brutal hard-negative FP rate. That is the point.

**Baseline B — contextual ML.** Gradient boosting on families A–I. No relationship features, no cross-merchant. This is the honest strong baseline.

**Baseline C — Tyche.** B + relationship/graph features + multi-window fusion + cost-sensitive decisioning.

**The experiment the whole project exists to answer:** does C beat B by enough to justify the relationship engine? Run the ablation and report it truthfully. If it does not, that is a finding worth presenting — and far better than a fabricated margin.

### 4.1 Decision layer (§20)

Four tiers, not a binary:

| Tier | Meaning | Merchant sees |
|---|---|---|
| `OBSERVE` | logged, no alert | nothing |
| `ALERT` | notify | dashboard + notification |
| `REVIEW` | queue for analyst | case in review queue |
| `RESTRICT` | recommend defensive control | recommendation + one-click action |

`RESTRICT` **recommends**, it does not auto-block. §20 is explicit that an alert/review workflow is the right prototype scope, and it is also the honest one — a student prototype should not silently decline live payments.

Thresholds chosen on **validation** by expected-loss minimisation under a review-capacity cap (v1's `choose_operating_point` already does this correctly — keep it).

### 4.2 Exposure model (§21, §22)

```
exposure = at_risk_gmv * P(loss | incident_type)
         + n_txn * (chargeback_fee + fulfilment_cost + support_cost)
         + promo_exposure                      # for promo abuse
```

Every constant lives in config, is labelled **ASSUMPTION**, and is printed in the report next to its value (§22). Never present these as Razorpay economics.

**Effort:** 6–7 days.

---

## Phase 5 — Evaluation

### 5.1 Splits — temporal, not random (§25)

```
[--------- TRAIN ---------][-- VAL --][-- TEST --]
 baselines fit here         thresholds  scored ONCE
 models fit here            chosen here frozen
```

Plus **held-out merchants** in the test period, so you measure generalisation to a merchant whose baseline was never learned. And **held-out scenario variants** — see G5.

### 5.2 Metrics (§23, §24)

**Window level:** PR-AUC (the primary — §24 explains why accuracy is meaningless at these base rates), precision/recall/F1 at the operating point, calibration error, reliability curve.

**Incident level** (the headline). Assembly and matching rules, stated explicitly:
- Predicted incident = maximal run of flagged windows for a merchant, gap tolerance 2 windows
- Match = any temporal overlap with a true incident, greedy one-to-one by earliest start
- Extra predicted incidents overlapping an already-matched truth = false positives
- **Detection latency** = `first_flag_time − true_incident_start`, reported as p50/p90
- **Missed-incident GMV** — recall weighted by money, not by count

**Operational:** false alerts per merchant per day (the number that decides whether anyone would run this), alerts per analyst-hour, hard-negative FP rate broken out by look-alike scenario.

**Economic:** expected loss decomposed into FN and FP components, savings vs A and vs B.

### 5.3 Leakage gates — CI tests that must pass

This is the direct answer to §13 and to v1's 0.994.

| Gate | Test | Pass condition |
|---|---|---|
| **G1** | Univariate AUC of every single feature against the label | no feature > 0.90 alone → else investigate and justify |
| **G2** | Retrain on shuffled labels | PR-AUC collapses to base rate ± 0.02 |
| **G3** | Predict generator knobs from feature vector | no label-determining parameter recoverable at R² > 0.8 |
| **G4** | Split integrity | no merchant-window crosses splits; baselines provably fit on train period only |
| **G5** | **Leave-one-scenario-out** — train with `card_testing` entirely absent, test on it | recall > 0.5 → else the model memorises families rather than learning abnormality |
| **G6** | **Cross-generator** — train on Tyche generator, test on PaySim/Sparkov lifted windows | report the PR-AUC drop; large drop = generator overfit |

**G5 is the most valuable single test in the project.** A real attacker does not use a technique from your training set. LOSO recall is the closest honest proxy for "would this catch something new", and reporting it — even at a mediocre value — demonstrates more understanding than any headline F1.

**Effort:** 5–6 days.

---

## Phase 6 — Serving

### 6.1 Incident manager

Correlate flagged windows across window sizes (a 1m and a 5m flag on the same merchant are one incident), deduplicate, track lifecycle `OPEN → ACKNOWLEDGED → CONFIRMED / DISMISSED → CLOSED`, and escalate severity as evidence accumulates. `app/cases/service.py` has the lifecycle bones — evolve it.

### 6.2 Explanation layer (§18) — with a grounding guard

The LLM **explains evidence; it must not invent evidence.** Enforce it mechanically rather than by prompt instruction alone:

1. The LLM receives a structured evidence object — only numbers already computed.
2. It may not emit numerals not present in that object.
3. A post-generation validator extracts every numeric token from the output and asserts each appears in the evidence payload. Fail → fall back to a deterministic template.

`app/intent/` already has a provider abstraction with a null provider and a timeout — repurpose it as `app/explain/`. The system must be fully functional with the LLM disabled, and must say so when it is (v1 does this correctly).

### 6.3 API and dashboard

```
POST /api/v1/events                  ingest (batch)
GET  /api/v1/incidents               list, filter by merchant/severity/status
GET  /api/v1/incidents/{id}          full incident: evidence, exposure, explanation
PATCH /api/v1/incidents/{id}         lifecycle transition
GET  /api/v1/merchants/{id}/baseline current expected behaviour
GET  /api/v1/merchants/{id}/windows  window feature timeline (for the chart)
```

Dashboard, minimum viable: incident list by severity; per-incident timeline with the baseline band and the deviation overlaid; evidence table showing observed vs expected vs deviation; the entity cluster; exposure; the explanation. The chart that sells the whole project is **§27's killer experiment** — two spikes of identical height, one green and one red, side by side, with the feature panel underneath showing why.

**Effort:** 6–8 days.

---

## Phase 7 — Testing against real threats and real data

This is the phase that separates the project from every other buildathon submission, and it is the part of your request that the brief covers least. Three independent tracks.

### 7.1 Real datasets

No public dataset carries incident-level fraud-spike labels. Every one below needs the Phase 2.3 label-lifting rule applied. Being explicit about that limitation is part of the result.

| Dataset | Real? | Time | Merchant | Entity/device | Label | Role in Tyche |
|---|---|---|---|---|---|---|
| **IEEE-CIS (Vesta)** | **Real** | `TransactionDT` (sec offset) | none — use `ProductCD`+`addr1`+`card4` as segment | `DeviceInfo`, `DeviceType`, `id_12`–`id_38`, `card1`–`card6` | `isFraud` | **Primary real benchmark.** Real device-reuse and instrument structure — the only public real set with genuine relationship signal |
| **TalkingData AdTracking** | **Real** | `click_time` | `app`/`channel` | `ip`, `device`, `os` | `is_attributed` | **Velocity + relationship stress test at scale** (~185M rows). Click fraud, not payments — but real bot-farm burst structure |
| **Sparkov** (Shenoy) | Synthetic | full timestamps | **yes, native** | `cc_num`, lat/long | `is_fraud` | **Third-party generator** — merchant-window native, so G6 works directly |
| **PaySim** | Synthetic (real aggregates) | `step` = 1h | agent nodes | `nameOrig`/`nameDest` graph | `isFraud` | Third-party generator, relationship/graph test |
| **BankSim** | Synthetic | step | yes | customer, category | `fraud` | Small third-party generator, quick sanity check |
| **ULB creditcard.csv** | Real but PCA'd | `Time` only | none | none | `Class` | **Weak** — temporal burst sanity only. No relationship features survive PCA |

**IEEE-CIS is the one to invest in.** Concretely: sort by `TransactionDT`; define pseudo-merchant segments as `(ProductCD, addr1)`; build 1m/5m/15m/1h windows per segment; apply label lifting; and check whether Tyche's *relationship* features — device reuse, instrument cardinality growth, degree concentration — carry real signal on real fraud. If they do, that is the strongest claim the project can make.

Licensing is not optional housekeeping: Kaggle competition data generally requires accepting competition rules, IEEE-CIS is research/non-commercial, and none of it should be redistributed in the repo. Ship **download scripts plus checksums**, not data. Cite every source in the report.

### 7.2 Red-team suite — the detection floor

Defense-only, per §32: these are **synthetic offline evasion simulations against our own detector**, not attack tooling. No credential testing, no live infrastructure, no anything that runs against a real system.

Parameterise each attack with an evasion knob and sweep it until detection fails:

| # | Evasion | Knob | Attacks which feature family |
|---|---|---|---|
| E1 | Slow ramp | ramp over T ∈ 1–240 min | A (temporal), acceleration |
| E2 | Dilution | attack share α ∈ 0.5%–50% of merchant traffic | B (volume), all deviations |
| E3 | Device spread | devices per account d ∈ 1–∞ | F, J (relationship) |
| E4 | Amount mimicry | draw amounts from merchant's own history | D (monetary) |
| E5 | Decline mimicry | pre-validate so decline rate stays normal | I (outcomes) |
| E6 | Geo mimicry | match merchant's own geo mix | E (geographic) |
| E7 | Timing mimicry | inter-arrivals from merchant's own process | A (temporal) |
| E8 | Cross-merchant fan-out | spread over N merchants, stay under each threshold | **only** cross-merchant features catch this |
| E9 | Cover traffic | run the attack *during* a flash sale | everything — the hardest case |

**The deliverable is a detection-floor chart per attack**: attack intensity on x, recall on y, three curves (Baseline A, Baseline B, Tyche), with the 0.5-recall crossing marked. This states plainly *where each system stops working*.

That is a far stronger result than a single F1. It says: here is what we catch, here is exactly what we miss, and here is what the relationship engine buys you. E8 in particular is what justifies cross-merchant features — nothing else detects it.

### 7.3 Documented real-world attack signatures

Encode observable signatures from public payment-industry sources — card testing / enumeration, BIN attacks, promo and referral abuse, refund and friendly-fraud waves, COD/RTO abuse — into matrix rows, with citations. **Defensive signatures only**: what the pattern *looks like in aggregate telemetry*, never how to execute it.

Cite Razorpay's own published documentation (disputes, chargeback types, refunds, security) for the loss taxonomy, and keep the §42 source discipline rigidly: separate Razorpay-published facts / external research / synthetic assumptions / Tyche's own results. Never blur them.

**Effort:** 7–9 days, and it can run in parallel with Phase 6.

---

## Module disposition

| Path | Action |
|---|---|
| `app/core/*` | **Keep** — config, db, ids, logging, metrics, redis all transfer unchanged |
| `app/api/deps.py`, `v1/health.py` | Keep |
| `app/api/v1/events.py` | Rewrite payloads (payment events, not agent actions) |
| `app/api/v1/risk.py` | Replace → `incidents.py` |
| `app/api/v1/cases.py` | Evolve → incident lifecycle (keep the lifecycle logic) |
| `app/schemas/enums.py` | Rewrite — drop `ActionType`/`ActorType`/`TrustTier`; add `WindowSize`, `IncidentStatus`, `ActionTier`, `ScenarioClass` |
| `app/schemas/events.py` | Rewrite per 1.3 |
| `app/schemas/entities.py` | Heavy edit — `Transaction` mostly survives; drop agent/session/delegation; add instrument metadata, geo, COD |
| `app/schemas/risk.py` | Rewrite → incident schema (§19) |
| `app/models/*` | Rewrite + new migration (six stores) |
| `app/features/context.py` | **Keep the pattern** (past-only, one-context-two-builders) — rewrite the content for windows |
| `app/features/online.py` | Rewrite to window aggregation; **keep the Redis discipline** (hot state as evidence, never as a feature) |
| `app/features/baselines.py` | Evolve → per-merchant seasonal baseline engine |
| `app/features/authorization.py` | **Delete** — delegation concept is gone |
| `app/features/{behavior,temporal,transaction}.py` | Rewrite as families A–J |
| `app/features/engine.py` | Keep the shape, repoint |
| `app/graph/*` | **Keep and extend** — `ClusterSummary` is already close to §16 |
| `app/intent/*` | Repurpose → `app/explain/` with the grounding guard |
| `app/risk/engine.py` | **Keep the degradation architecture**, repoint components |
| `app/risk/fusion.py` | Keep |
| `app/risk/rules.py` | Rewrite → Baseline A + hard signals |
| `app/risk/models.py` | Rewrite → window-level GBM |
| `app/risk/evidence.py` | Keep, extend with baseline-deviation evidence |
| `app/decision/policy.py` | Evolve → four tiers |
| `app/cases/service.py` | Evolve → incident manager |
| `app/audit/store.py` | Keep |
| `app/evaluation/metrics.py` | Keep, add incident-level + latency |
| `app/evaluation/dataset.py` | Rewrite → temporal split |
| `app/evaluation/detectors.py` | Rewrite → Baseline A/B/C |
| `app/evaluation/runner.py` | **Keep the protocol** (it is correct), repoint |
| `app/evaluation/report.py` | Keep, extend |
| `data/generators/*` | Rewrite — merchant timeline first (§14) |
| `tests/*` | Build from zero |

Roughly **60% rewrite, 30% keep, 10% delete**. The keeps are the load-bearing ones.

---

## Sequencing

```
Phase 0  Research matrix        3–4d   ████
Phase 1  Foundations            4–5d       █████
Phase 2  Data                   8–10d           ██████████   ← critical path
Phase 3  Features               6–8d                      ████████
Phase 4  Models                 6–7d                              ███████
Phase 5  Evaluation             5–6d                                     ██████
Phase 6  Serving                6–8d                                          ████████
Phase 7  Real threats/data      7–9d                              ███████████  (parallel from P4)
```

~6 weeks solo at a steady pace. Phase 2 is the critical path and the phase to protect — it decides whether every number after it means anything.

### If time is short

**Minimum defensible core** — cut to this, in priority order:

1. Phase 0 matrix (abbreviated — 10 scenarios, not 23)
2. Phase 2 generator with anti-leakage rules
3. Feature families A, B, C, I, J (skip E geographic, H payment-method-entropy)
4. Baselines A and B, plus Tyche
5. Leakage gates **G1, G2, G4, G5** (G5 is non-negotiable)
6. Incident-level metrics + hard-negative FP table
7. §27 killer experiment as the demo
8. One real dataset (**IEEE-CIS**) and one evasion sweep (**E2 dilution**)

Cut first: the dashboard (a notebook plus static charts is fine), the LLM explanation layer (templates work), cross-merchant features, G3, G6.

**Do not cut:** G5 (leave-one-scenario-out), the hard-negative FP table, or honest incident-level numbers. Those three are the entire credibility of the submission.

---

## Definition of done

The project is finished when it can answer, with evidence:

1. Given two identical 30→500 spikes, does Tyche separate them, and *why* (§27)?
2. What is the false-alert rate per merchant per day at the chosen operating point?
3. What is incident recall on an attack family the model never trained on (G5)?
4. Does the relationship engine beat contextual ML, and by how much (§26)?
5. At what attack intensity does each detector stop working (7.2)?
6. Do the relationship features carry signal on **real** fraud data (7.1)?
7. What does the merchant actually receive, and what can they do about it (§40)?

And the claims stay inside §33's bounds: not "detects all fraud", not "better than Razorpay" — but *"on our held-out incident benchmark and on lifted windows from IEEE-CIS, Tyche improved incident recall over the specified baselines while reducing hard-negative false positives, and here is exactly where it fails."*

That last clause is the one that wins.
