# Veyra — What's Left to Build

**Purpose of this document.** `ROADMAP.md` is the strategy: it argues *what* Veyra should
become and why the v1 framing had to be replaced. This document is the execution plan —
every phase and step that remains, what each one actually produces, and **why it exists at
all**. If a step here can't justify itself in a sentence, it shouldn't be in the build.

**Source of truth:** `Tyche_Fraud_Spike_Deep_Problem_Research.md` (the brief) → `docs/ROADMAP.md`
(strategy) → this file (execution).
**Written:** 2026-08-27

---

## The one-paragraph version

Veyra watches a merchant's payment stream and answers a question a per-transaction fraud
model structurally cannot: *has this merchant's payment **shape** changed in the last few
minutes, and does the change look coordinated or organic?* A flash sale and a card-testing
burst both look like "30 transactions/min → 500 transactions/min". Volume alone cannot tell
them apart. The **relationship structure underneath** the volume can — 500 transactions from
480 devices is a sale; 500 transactions from 12 devices is a ring. Everything below exists to
build that comparison honestly and then prove, with numbers we didn't choose in advance, how
well it works and exactly where it fails.

---

## Status legend

| | |
|---|---|
| ✅ | Done and committed |
| 🔨 | Next up |
| ⬜ | Not started |
| ⛔ | Blocking gate — nothing downstream is trustworthy until it passes |

---

## ✅ Phase 0 — The research matrix *(complete)*

**Why it existed.** §43 of the brief closes with an explicit instruction: *do not rebuild
until the research matrix is complete.* The reason is that every downstream artifact — the
generator, the feature list, the evaluation slices — is a projection of the same question
list. Write them independently and they drift; the generator grows a scenario the evaluator
never slices on, and nobody notices.

**What was built.** The matrix was made **executable** rather than prose, so drift becomes a
test failure instead of a discovery:

| File | What it is |
|---|---|
| `research/matrix.yaml` | 27 scenarios. Each carries the mechanism, observable signals, time scales, entity relationships, merchant loss, the scenarios it is `confusable_with`, the `discriminator` that separates them, a `synthetic_recipe` with an `intensity_range`, eval metrics, and a `real_data_proxy` |
| `research/features.yaml` | Feature families A–J, each feature tagged with `downstream_only`, `evidence_only`, `deviation_twin` |
| `research/validate.py` | The CI gate — eight checks, below |
| `docs/decisions/ADR-001..007` | The seven architectural decisions that are expensive to reverse |
| `docs/threat-model.md` | Attacker capabilities and the detection boundary |

**The two fields that carry the weight** are `confusable_with` and `discriminator`. A
scenario without a named look-alike is a scenario you cannot evaluate honestly — it's where
§5 ("a volume anomaly is evidence, not a verdict") stops being a slogan and becomes code.

**What `validate.py` enforces**, and why each check earns its place:

| | Check | Why |
|---|---|---|
| C1 | every scenario declares what it's confusable with, and how to tell them apart | without it, a scenario is a volume anomaly treated as a verdict (§5) |
| C2 | every referenced feature resolves in the registry | stops the matrix describing detection it has no features for |
| C3 | every `confusable_with` target is a scenario or a declared external look-alike | catches typos; forces out-of-scope look-alikes to be deliberate |
| C4 | confusion is **symmetric** | if A hides behind B, the generator must build B too — otherwise A is untestable |
| C5 | attacks declare an `intensity_range` reaching a genuinely undetectable low end | without it, recall measures our generator's generosity (§13) |
| C6 | attacks declare which features must **not** separate them alone | the anti-leakage contract, written per scenario |
| C7 | downstream-only features appear only in retrospective scenarios | disputes and RTO are label sources, never real-time features (§6.10) |
| C8 | every legitimate scenario is named by at least one attack | an unreferenced hard negative is one nothing is actually tested against |

**Gate status today:** `python3 research/validate.py` → **PASS**. 27 scenarios, 79 features
declared, 70 referenced by a scenario; the 9 unreferenced are evidence- or label-only by
design (raw counts, GMV, RTO rate, cluster density).

C4 and C8 are the two that keep the hard negatives honest: they make it impossible to write an
attack that hides behind a benign scenario the generator never builds, or to add a benign
scenario that no attack is ever tested against.

**Decisions now locked** (change these later and much of the build is invalidated):

- **ADR-001** — the scored unit is `(merchant_id, window_size, window_end)`, not a transaction
- **ADR-002** — detection windows 1m/5m/15m/1h on a 60s grid; baselines 24h/7d/28d; **24h is not a detection window** (a day-long alert is a post-mortem)
- **ADR-003** — window labels lifted by an explicit rule, with published sensitivity
- **ADR-004** — disputes/chargebacks/RTO are **label sources only**, structurally barred from features
- **ADR-005** — thresholds minimise **expected loss**, never F1
- **ADR-006** — four tiers (`OBSERVE/ALERT/REVIEW/RESTRICT`); the system **recommends**, never auto-blocks
- **ADR-007** — the generator is bound by a contract enforced in CI

---

## 🔨 Phase 1 — Foundations *(4–5 days)*

*Why the phase exists:* we're about to rewrite ~60% of an 11,000-line codebase. Doing that
without version control or a test harness is how a working system silently becomes a broken
one. This phase buys the safety net before the demolition starts.

### 1.1 Repository hygiene ✅ *(done)*

`git init`, three clean commits, `.gitignore` covering `*.db`, `artifacts/`, `reports/*.json`
and `data/real/`, the v1 state tagged `v1-agent-commerce`, and everything pushed to
`github.com/Amartya989870xxxx/Veyra_AI`.

**Why the tag matters:** v1's evaluation stays reproducible and citable as prior work. When
the report says "v2 scores lower than v1 *and that is the point*", the v1 number has to be
checkable, not just asserted.

### 1.2 ⛔ Test harness — before any rewrite

**What:** the five test trees, plus `pytest.ini`, fixtures, and CI wiring.

```
tests/unit/          feature functions, baseline maths, window arithmetic
tests/integration/   ingest → aggregate → score → incident, end to end
tests/evaluation/    leakage gates G1–G6 — these gate CI
tests/failure/       degraded components, missing baselines, clock skew, duplicate events
tests/property/      hypothesis-based invariants on the window aggregator
```

**Why first, not last.** Phase 5's leakage gates *are tests*. If the harness doesn't exist,
the gates get written as one-off scripts, run once, and quietly stop being run. A gate that
isn't in CI isn't a gate — it's a screenshot.

**Why property tests specifically.** The window aggregator is where off-by-one errors silently
corrupt every number downstream, and they never throw. Three invariants worth asserting with
generated inputs rather than hand-picked ones:

- the sum of 1m counts across an hour equals the 1h count
- no window ever sees an event at or after its own `window_end` *(this is the past-only rule, mechanised)*
- baselines are invariant to the order events are inserted in

**Done when:** `pytest` runs green on an empty-but-wired suite, in CI, on push.

### 1.3 Event schema — payment-centric

**What:** rewrite `app/schemas/events.py` and `enums.py`. Delete `ActionType`, `ActorType`,
`TrustTier`, `AgentSession`, `AgentDelegation`. Add:

```
PaymentAttemptEvent   merchant, customer, instrument_fp, instrument_meta(brand/type/issuer_country/bin_hash),
                      device_fp, ip_fp, geo(country/state/city), amount, currency,
                      payment_method, is_cod, coupon_id, order_id, ts
PaymentResultEvent    txn_id, status, failure_code, ts
RefundEvent           txn_id, amount, reason_code, ts
DisputeEvent          txn_id, dispute_type, ts          ← label source ONLY
OrderStatusEvent      order_id, status(SHIPPED/DELIVERED/RTO), ts
```

**Why the vocabulary change is not cosmetic.** v1's domain was agents, delegations and trust
tiers. That vocabulary can't express "this merchant's instrument cardinality grew 1:1 with
attempt count" — the concepts don't exist in it. The schema *is* the model of the problem.

**Why `DisputeEvent` gets a hard structural barrier (ADR-004).** A chargeback arrives 14–90
days after the payment. A model trained on `dispute_rate` scores beautifully offline and
cannot run in production, and the failure is **silent** — nothing errors, the metrics just
become fiction. So: `downstream_only: bool` on the field registry, and a unit test that fails
if any downstream field appears in a feature vector. This is the leak that's invisible in a
report and fatal in a live demo.

**Done when:** the downstream-leak test exists and fails when deliberately violated.

### 1.4 Storage model — six stores, six concerns

| Store | Holds | Note |
|---|---|---|
| `raw_events` | immutable normalised events | append-only, idempotent on `event_id` |
| `feature_store` | window aggregates per `(merchant, window, ts)` | the join key for everything |
| `baseline_store` | per-merchant expected behaviour + variability | versioned; refit on a schedule |
| `relationship_store` | entity-pair counters and degrees | TTL'd; the graph engine's persistence |
| `incident_store` | incidents, lifecycle, evidence | a first-class object, not a log line |
| `eval_store` | predictions, ground truth, run metadata | makes runs reproducible and diffable |

**Why six and not one.** Each has a different lifetime and mutability rule. `raw_events` is
append-only forever; `baseline_store` is versioned and refit; `relationship_store` expires.
Collapsing them means one retention policy for all, and the first thing lost is the ability to
say *"this incident was scored against baseline version 7, here it is."*

**Why `eval_store` earns its place:** without stored run metadata, "our PR-AUC improved" is
unfalsifiable. With it, two runs can be diffed.

New Alembic migration. **Do not migrate v1 data — regenerate.** The old rows describe agent
delegations; there is nothing in them worth carrying.

---

## ⬜ Phase 2 — Data ⛔ *(8–10 days — the critical path)*

*Why the phase exists:* this is the phase that decides whether every number in the project
means anything. v1 reported **F1 0.994 / PR-AUC 0.999** and that is not an achievement — it's
§13's diagnosis. The model learned the generator. Phase 2 is the fix, and it's the single
highest-leverage work in the build.

### 2.1 Generator v2 — normal first, injection second

**The v1 bug, precisely.** v1 built *episodes*: a scenario emitted a self-contained bundle of
transactions. So an episode's identity was recoverable from its own contents — the model
learned to recognise bundle boundaries, not abnormality. **No amount of careful splitting can
fix this**, because the leak is structural, not statistical.

**The v2 inversion (§14):**

```
1. Build a merchant population       size, category, geo mix, method mix, COD share, price distribution
2. Simulate normal timelines         for the full period, per merchant:
                                       seasonality (hour-of-day, day-of-week, festivals),
                                       trend, noise, organic customer arrival process
3. THEN inject scenarios             attacks and legitimate spikes are perturbations of a
                                     merchant's OWN ongoing stream, not appended bundles
4. Lift labels to windows            (§2.3 below)
```

**Why the ordering is the whole trick.** An injected attack now shares the merchant's normal
traffic, its customer pool, its amount distribution and its device population. There is no
bundle boundary left to recognise. The model has to find abnormality or find nothing.

### 2.2 Anti-leakage as a design constraint, not a review step

Five rules the generator is bound by (ADR-007), each closing a specific shortcut:

- **No sentinel values.** Every attack-injected variable is drawn from a distribution that
  *overlaps* the normal one. If card-testing amounts are exactly `₹1.00`, the model learns
  `amount == 1.00` and you have rebuilt §13's bad generator.
- **Attack intensity is a random variable**, sampled per incident across a wide range —
  *including intensities so low the attack is genuinely undetectable.* **Why:** if every
  attack in the test set is detectable, recall is a measure of the generator, not the model.
- **Every attack knob also fires under some benign scenario.** Retry storms raise decline
  rate. Subscription batches raise velocity. Household devices raise device reuse. Flash sales
  raise new-account rate. **Why:** this is what forces the model to use *combinations* instead
  of latching onto one telltale.
- **Attack traffic uses the merchant's own entity pools** where realistic — a compromised
  account is a *real* account with history, not a fresh id.
- **No global attacker signature.** Attack devices, IPs and instruments are drawn from the
  same fingerprint space as legitimate ones.

**Done when:** gate G1 (below) passes — no single feature separates the classes alone.

### 2.3 Label lifting — the rule that makes incidents scoreable

Truth arrives per transaction; the scored unit is a window (ADR-001). One rule, stated once,
applied to synthetic **and** real data alike:

```
window is POSITIVE  iff  n_abusive     >= K
                    and  abusive_share >= max(M, merchant_baseline_rate * 3)

default K = 5, M = 0.20
```

**Why publish a sensitivity table** for `K ∈ {3,5,10}` and `M ∈ {0.1,0.2,0.4}`: a result that
survives the label definition moving is a result. One that doesn't is an artifact of a
threshold — and we want to find that out before a judge does.

**Why three label classes, not two.** `LEGIT_SPIKE` is distinct from `NORMAL`. "Didn't fire on
a flash sale" and "didn't fire on a quiet Tuesday" are completely different achievements, and
collapsing them into one negative class hides **the only false-positive number that matters**.

### 2.4 Scenario library — build out all 27 matrix rows

- **Primary attacks:** card testing, BIN enumeration, distributed account abuse, device-farm
  rings, promo abuse, ATO waves, geo anomaly, payment-method shift, merchant compromise
- **Downstream:** refund abuse, dispute cohorts, COD/RTO abuse
- **Hard negatives:** flash sale, influencer campaign, product launch, festival, gateway retry
  storm, subscription batch, household devices, international expansion
- **Adversarial mixes:** a ring hidden inside a flash sale, low volume with extreme
  relationship density, simultaneous benign and malicious clusters, slow-ramp infiltration

**Why the hard negatives get equal engineering effort to the attacks:** they are the product.
Anyone can detect a spike. The entire claim of this project is *not firing* on the eight
benign scenarios that look identical to one.

---

## ⬜ Phase 3 — Features *(6–8 days)*

*Why the phase exists:* the features are where the brief's central thesis becomes computable.
Families A–I describe what the traffic looks like; family J describes **what shape it has** —
and J is the part a conventional fraud model doesn't have.

### 3.1 Feature registry driven by the matrix

```python
@feature(family="C", windows=["1m","5m","15m","1h"], downstream_only=False)
def instruments_per_txn(w: WindowAgg) -> float: ...
```

**Why a registry rather than a module of functions.** Four things come free and would
otherwise be manual and rotting: the leakage gate can enumerate every feature; the report can
group by family; the ADR-004 barrier is machine-enforceable; and a matrix row referencing a
feature that doesn't exist fails CI.

**Two implementation rules with reasons:**

- **Ratios over counts (§8C).** `unique_devices` doesn't transfer between a 50-order/day
  merchant and a 50,000-order/day one. `unique_devices / transactions` does. Raw counts stay
  in the registry tagged `evidence_only` — humans need them in the explanation; models mostly
  shouldn't consume them.
- **Every feature gets a deviation twin.** For `f`, also emit
  `f_dev = (f - baseline(f)) / robust_scale(f)`. The raw value answers *"what is it"*; the
  deviation answers *"is this abnormal **for this merchant**"* — and per §9 that second
  question is the one the model should mostly be asking.

### 3.2 Baseline engine

Per merchant, per feature, per window size, per hour-of-week:

```
expected     = robust location (median or EWMA)
variability  = robust scale   (MAD, not stddev)
deviation    = (observed - expected) / max(variability, floor)
```

**Why MAD and not standard deviation:** one prior spike poisons a stddev, which then widens
the "normal" band enough to hide the next spike. The metric that's supposed to detect attacks
would be desensitised by them.

**Why cold start needs a stated policy, not a default:** a merchant with under N days of
history falls back to a category-level population baseline and the incident records
`baseline_confidence: LOW`. Silently scoring a new merchant against six hours of history
produces confident nonsense.

**Why baselines fit on the training period only:** refitting across the full timeline is
temporal leakage — the baseline for a Tuesday would encode Wednesday's attack. It's the
easiest leak in the project to commit by accident, which is why G4 tests for it.

### 3.3 Relationship engine — the differentiator

`app/graph/networkx_engine.py` already computes something close to §16 (`ClusterSummary` has
entity counts, span, interarrival CV, concentration). **Extend, don't rewrite.** Add:

- **Per-window bipartite degree distributions** — accounts/device, devices/account,
  instruments/device, accounts/IP, addresses/account
- **Concentration measures** — Gini and entropy over each degree distribution. *Why:* "10
  devices serving 500 accounts" is a **shape**, and a count can't express it
- **In-window cluster extraction** — size, density, and what share of the window's volume the
  largest cluster carries
- **Cross-merchant** — entities appearing at N merchants in the same window (§6.8). *Why:*
  this is the **only** thing that catches evasion E8 (fan-out below every per-merchant threshold)
- **Novelty** — share of entities never seen in this merchant's history

All computed **past-only**, over the window plus a bounded lookback. v1 got this discipline
right; preserve it exactly.

---

## ⬜ Phase 4 — Models and decisions *(6–7 days)*

*Why the phase exists:* to answer the one question the project is actually built to answer —
**does the relationship engine earn its complexity?**

### 4.1 Three detectors, all tuned properly

| | What it is | What it proves |
|---|---|---|
| **A — volume only** | rolling z-score on transaction count, threshold tuned by expected loss | what "just alert on spikes" achieves. Expect a brutal hard-negative FP rate — **that is the point** |
| **B — contextual ML** | gradient boosting on families A–I. No relationship features, no cross-merchant | the honest strong baseline |
| **C — Veyra** | B + relationship/graph + multi-window fusion + cost-sensitive decisioning | the thesis |

**Why all three must be tuned properly (§26):** a strawman baseline is worse than no baseline
— it invalidates the comparison and any reviewer spots it immediately. **The experiment:**
does C beat B by enough to justify the relationship engine? Run the ablation, report it
truthfully. **If it doesn't, that is a finding worth presenting** — and it is worth far more
than a fabricated margin.

### 4.2 Decision layer — four tiers (ADR-006)

`OBSERVE` (logged, silent) → `ALERT` (notify) → `REVIEW` (analyst queue) → `RESTRICT`
(**recommend** a defensive control, one click to apply).

**Why recommend and never auto-block:** §20 argues against `risk > 0.5 → block` as an
architecture, and a student prototype silently declining live payments is indefensible
regardless. Thresholds chosen on **validation** by expected-loss minimisation under a
review-capacity cap — v1's `choose_operating_point` already does this correctly; keep it.

**Why a capacity cap is part of the objective:** an alerting system that generates more
reviews than a team can process has an effective precision of zero for everything past the
queue's depth.

### 4.3 Exposure model

```
exposure = at_risk_gmv * P(loss | incident_type)
         + n_txn * (chargeback_fee + fulfilment_cost + support_cost)
         + promo_exposure
```

**Why every constant is labelled ASSUMPTION and printed next to its value (§22, §42):** these
are our estimates, not Razorpay economics. Presenting invented constants as industry figures
is the fastest way to lose a technical audience, and the §42 source discipline — Razorpay
published facts / external research / synthetic assumptions / Veyra's own results, never
blurred — applies to every number in the report.

---

## ⬜ Phase 5 — Evaluation ⛔ *(5–6 days)*

*Why the phase exists:* it's the direct answer to §13 and to v1's 0.994. Everything here is
designed to make it **hard to fool ourselves**.

### 5.1 Splits — temporal, never random

```
[--------- TRAIN ---------][-- VAL --][-- TEST --]
 baselines fit here         thresholds  scored ONCE,
 models fit here            chosen here frozen
```

Plus **held-out merchants** inside the test period — *why:* it measures generalisation to a
merchant whose baseline was never learned, which is the actual deployment case. Plus
**held-out scenario variants** (see G5).

**Why random splits are disqualifying here:** a random split puts 11:59 in train and 12:00 in
test, and the same incident lands on both sides. The number that comes out is meaningless.

### 5.2 Metrics

**Window level:** PR-AUC as primary (§24 — accuracy is meaningless at these base rates),
precision/recall/F1 at the operating point, calibration error, reliability curve.

**Incident level — the headline.** Assembly and matching rules stated explicitly so they can't
be tuned after the fact:

- predicted incident = maximal run of flagged windows for a merchant, gap tolerance 2 windows
- match = any temporal overlap with a true incident, greedy one-to-one by earliest start
- extra predicted incidents overlapping an already-matched truth = false positives
- **detection latency** = `first_flag_time − true_incident_start`, reported p50/p90
- **missed-incident GMV** — recall weighted by money, not by count

**Operational:** false alerts per merchant per day — *the number that decides whether anyone
would actually run this* — alerts per analyst-hour, and hard-negative FP rate **broken out by
look-alike scenario**.

**Economic:** expected loss decomposed into FN and FP components, savings vs A and vs B.

### 5.3 ⛔ Leakage gates — CI tests that must pass

| Gate | Test | Pass condition |
|---|---|---|
| **G1** | univariate AUC of every single feature vs. the label | none > 0.90 alone, or investigate and justify |
| **G2** | retrain on shuffled labels | PR-AUC collapses to base rate ± 0.02 |
| **G3** | predict generator knobs from the feature vector | no label-determining parameter recoverable at R² > 0.8 |
| **G4** | split integrity | no merchant-window crosses splits; baselines provably fit on train only |
| **G5** | **leave-one-scenario-out** — train with `card_testing` entirely absent, test on it | recall > 0.5 |
| **G6** | **cross-generator** — train on Veyra's generator, test on PaySim/Sparkov lifted windows | report the PR-AUC drop; a large drop = generator overfit |

**Why G2 is worth the compute:** if PR-AUC stays high on shuffled labels, the model is reading
structure that correlates with the split rather than with the label. It's a two-line test that
catches a whole class of silent disasters.

**G5 is the most valuable single test in the project.** A real attacker does not use a
technique from your training set. Leave-one-scenario-out recall is the closest honest proxy
for *"would this catch something new"* — and reporting it, **even at a mediocre value**,
demonstrates more understanding than any headline F1.

---

## ⬜ Phase 6 — Serving *(6–8 days)*

*Why the phase exists:* an incident nobody can see, act on, or understand is not a product.
§40 asks what the merchant actually receives.

### 6.1 Incident manager

Correlate flagged windows across window sizes (a 1m and a 5m flag on the same merchant are
**one** incident), deduplicate, track `OPEN → ACKNOWLEDGED → CONFIRMED / DISMISSED → CLOSED`,
escalate severity as evidence accumulates. `app/cases/service.py` has the lifecycle bones.

**Why correlation isn't cosmetic:** without it, one attack produces four alerts per minute
across four window sizes, and the false-alert-per-day metric — the one that decides adoption —
becomes fiction.

### 6.2 Explanation layer — with a grounding guard

The LLM **explains evidence; it must not invent evidence.** Enforced mechanically, not by
prompt instruction:

1. the model receives a structured evidence object — only numbers already computed
2. it may not emit numerals absent from that object
3. a post-generation validator extracts every numeric token and asserts each appears in the
   evidence payload; on failure, fall back to a deterministic template

**Why a validator and not just a good prompt:** a hallucinated number in a fraud alert is
worse than no explanation at all — it's a confident false fact an analyst will act on. Prompt
instructions are a request; the validator is a guarantee.

`app/intent/` already has a provider abstraction with a null provider and timeout — repurpose
as `app/explain/`. The system must be fully functional with the LLM disabled **and must say so
when it is**. v1 does this correctly.

### 6.3 API and dashboard

```
POST  /api/v1/events                    ingest (batch)
GET   /api/v1/incidents                 list; filter by merchant/severity/status
GET   /api/v1/incidents/{id}            full incident: evidence, exposure, explanation
PATCH /api/v1/incidents/{id}            lifecycle transition
GET   /api/v1/merchants/{id}/baseline   current expected behaviour
GET   /api/v1/merchants/{id}/windows    window feature timeline (for the chart)
```

Dashboard, minimum viable: incident list by severity; per-incident timeline with the baseline
band and deviation overlaid; evidence table (observed vs expected vs deviation); the entity
cluster; exposure; the explanation.

**The chart that sells the entire project** is §27's killer experiment: **two spikes of
identical height, one green and one red, side by side**, with the feature panel underneath
showing exactly which signals separated them. Build that view first; everything else in the
dashboard is supporting cast.

---

## ⬜ Phase 7 — Real threats and real data *(7–9 days, parallel from Phase 4)*

*Why the phase exists:* this is what separates the project from a submission that only ever
tested against its own generator. It's also the part of your original request the brief covers
least. Three independent tracks.

### 7.1 Real datasets

No public dataset carries incident-level fraud-spike labels — every one needs the §2.3 label
lifting applied, and **being explicit about that limitation is part of the result.**

| Dataset | Real? | Entity/device signal | Role |
|---|---|---|---|
| **IEEE-CIS (Vesta)** | **real** | `DeviceInfo`, `DeviceType`, `id_12`–`id_38`, `card1`–`card6` | **primary real benchmark** — the only public real set with genuine relationship signal |
| **TalkingData** | **real** | `ip`, `device`, `os` (~185M rows) | velocity + relationship stress test at scale; click fraud, but real bot-farm burst structure |
| **Sparkov** | synthetic | `cc_num`, lat/long, native merchants | third-party generator — merchant-window native, so **G6 works directly** |
| **PaySim** | synthetic | `nameOrig`/`nameDest` graph | third-party generator, relationship test |
| **BankSim** | synthetic | customer, category | quick sanity check |
| **ULB creditcard.csv** | real but PCA'd | none | **weak** — temporal burst sanity only; no relationship features survive PCA |

**IEEE-CIS is the one to invest in.** Sort by `TransactionDT`; define pseudo-merchant segments
as `(ProductCD, addr1)`; build 1m/5m/15m/1h windows per segment; apply label lifting; then
check whether Veyra's **relationship** features carry real signal on real fraud.

**Why this is the strongest claim available to the project:** if device reuse, instrument
cardinality growth and degree concentration separate fraud on *Vesta's real transactions*,
then the thesis isn't an artifact of our own generator. Nothing else we can do carries that
weight.

**Licensing is not housekeeping.** Kaggle competition data requires accepting competition
rules, IEEE-CIS is research/non-commercial, none of it may be redistributed in the repo. Ship
**download scripts plus checksums**, never data. Cite every source.

### 7.2 Red-team suite — finding the detection floor

**Scope, explicitly:** defense-only, per §32. These are **offline evasion simulations against
our own detector** — synthetic traffic, our own generator, our own model. No live
infrastructure, no credential testing, nothing that runs against a real system.

Each evasion gets a knob, swept until detection fails:

| # | Evasion | Knob | Attacks which family |
|---|---|---|---|
| E1 | slow ramp | ramp over T ∈ 1–240 min | A (temporal), acceleration |
| E2 | dilution | attack share α ∈ 0.5%–50% of merchant traffic | B (volume), all deviations |
| E3 | device spread | devices per account d ∈ 1–∞ | F, J (relationship) |
| E4 | amount mimicry | draw amounts from the merchant's own history | D (monetary) |
| E5 | decline mimicry | pre-validate so decline rate stays normal | I (outcomes) |
| E6 | geo mimicry | match the merchant's own geo mix | E (geographic) |
| E7 | timing mimicry | inter-arrivals from the merchant's own process | A (temporal) |
| E8 | cross-merchant fan-out | spread over N merchants, stay under each threshold | **only** cross-merchant features catch this |
| E9 | cover traffic | run the attack *during* a flash sale | everything — the hardest case |

**The deliverable is a detection-floor chart per attack:** intensity on x, recall on y, three
curves (A, B, Veyra), with the 0.5-recall crossing marked.

**Why this beats a headline F1.** A single number says "we're good". A detection floor says
*here is what we catch, here is exactly what we miss, and here is what the relationship engine
buys you* — E8 in particular is the entire justification for cross-merchant features, since
nothing else detects it. Stating where a system stops working is the most credible thing a
technical report can do.

### 7.3 Documented real-world attack signatures

Encode observable signatures from public payment-industry sources — card testing/enumeration,
BIN attacks, promo and referral abuse, refund and friendly-fraud waves, COD/RTO abuse — into
matrix rows **with citations**. Defensive signatures only: what the pattern looks like in
aggregate telemetry, never how to execute it.

**Why citations matter here specifically:** it's the difference between "we imagined some
attacks" and "we implemented documented ones". Cite Razorpay's published documentation
(disputes, chargeback types, refunds, security) for the loss taxonomy.

---

## Sequencing and the critical path

```
Phase 0  Research matrix     ✅ done
Phase 1  Foundations         4–5d    █████
Phase 2  Data                8–10d        ██████████    ← critical path, protect it
Phase 3  Features            6–8d                   ████████
Phase 4  Models              6–7d                           ███████
Phase 5  Evaluation          5–6d                                  ██████
Phase 6  Serving             6–8d                                       ████████
Phase 7  Real threats/data   7–9d                           ███████████  (parallel from P4)
```

~6 weeks solo at a steady pace, ~60% rewrite / 30% keep / 10% delete. **Phase 2 is the phase to
protect** — it decides whether every number after it means anything.

**What survives from v1 unchanged** (the load-bearing keeps): `app/core/*` entirely; the
past-only, one-context-two-builders pattern in `app/features/context.py`; the Redis discipline
in `online.py` (hot state as evidence, never as a feature); the degradation architecture in
`app/risk/engine.py` (components degrade rather than substitute fake values); the evaluation
protocol in `runner.py`; and `choose_operating_point`. That discipline took real effort to get
right and would be stupid to throw away — the framing is being replaced, not the engineering.
Full file-by-file disposition is in `ROADMAP.md`.

---

## If time runs short

Cut to this, in priority order:

1. Phase 0 matrix ✅
2. Phase 2 generator with the anti-leakage rules
3. Feature families A, B, C, I, J *(skip E geographic, H payment-method entropy)*
4. Baselines A and B, plus Veyra
5. Leakage gates **G1, G2, G4, G5**
6. Incident-level metrics + the hard-negative FP table
7. §27 killer experiment as the demo
8. One real dataset (**IEEE-CIS**) and one evasion sweep (**E2 dilution**)

**Cut first:** the dashboard (a notebook plus static charts is fine), the LLM explanation layer
(templates work), cross-merchant features, G3, G6.

**Never cut:** G5, the hard-negative FP table, honest incident-level numbers. Those three *are*
the credibility of the submission.

---

## Definition of done

The project is finished when it can answer, with evidence:

1. Given two identical 30→500 spikes, does Veyra separate them, and **why** (§27)?
2. What is the false-alert rate per merchant per day at the chosen operating point?
3. What is incident recall on an attack family the model never trained on (G5)?
4. Does the relationship engine beat contextual ML, and by how much (§26)?
5. At what attack intensity does each detector stop working (7.2)?
6. Do the relationship features carry signal on **real** fraud data (7.1)?
7. What does the merchant actually receive, and what can they do about it (§40)?

And the claims stay inside §33's bounds — not *"detects all fraud"*, not *"better than
Razorpay"*, but:

> *On our held-out incident benchmark and on lifted windows from IEEE-CIS, Veyra improved
> incident recall over the specified baselines while reducing hard-negative false positives —
> and here is exactly where it fails.*

That last clause is the one that wins.

---

## A note on the numbers to expect

v1's F1 0.994 should be read as a **bug report**, not a benchmark. v2 will report materially
lower and more honest numbers, and the report should say so in those words. A PR-AUC in the
0.7–0.85 range on a leak-free generator, with a stated detection floor and an LOSO recall
figure, is a **stronger** result than 0.999 on a generator the model memorised — and it is the
only kind of result that survives someone looking closely.
