"""Human-readable evaluation report.

The report states what was measured, on what, and what it does not establish. Every number
comes from the run object; nothing here is written by hand.
"""

from __future__ import annotations

from app.schemas.evaluation import DetectorResult, EvaluationRunResponse, ThresholdPoint

DETECTOR_LABELS = {
    "rules": "Baseline 1 — static rules",
    "txn_ml": "Baseline 2 — transaction-only ML",
    "tyche": "Tyche — full agent + campaign context",
}


def _table(headers: list[str], rows: list[list[str]]) -> str:
    lines = ["| " + " | ".join(headers) + " |",
             "|" + "|".join("---" for _ in headers) + "|"]
    lines.extend("| " + " | ".join(row) + " |" for row in rows)
    return "\n".join(lines)


def _pct(value: float | None) -> str:
    return "—" if value is None else f"{value * 100:.1f}%"


def _num(value: float | None, digits: int = 3) -> str:
    return "—" if value is None else f"{value:.{digits}f}"


def _money(value: float | None) -> str:
    return "—" if value is None else f"₹{value:,.0f}"


def _by_split(results: list[DetectorResult], split: str) -> dict[str, DetectorResult]:
    return {r.detector: r for r in results if str(r.split) == split}


def _sweep_extract(points: list[ThresholdPoint], limit: int = 12) -> list[ThresholdPoint]:
    """A readable slice of the sweep: the best point per block threshold."""
    best: dict[float, ThresholdPoint] = {}
    for point in points:
        current = best.get(point.block_threshold)
        if current is None or point.expected_loss < current.expected_loss:
            best[point.block_threshold] = point
    ordered = [best[k] for k in sorted(best)]
    if len(ordered) <= limit:
        return ordered
    step = max(1, len(ordered) // limit)
    return ordered[::step][:limit]


def render_markdown(run: EvaluationRunResponse) -> str:
    summary = run.dataset_summary
    holdout = _by_split(run.results, "holdout")
    validation = _by_split(run.results, "validation")
    cost = run.cost_model
    sections: list[str] = []

    sections.append(
        f"""# Tyche — Evaluation Report

**Run ID:** `{run.run_id}`
**Dataset:** `{run.dataset_id}`
**Generated:** {run.completed_at.isoformat() if run.completed_at else "—"}

> **This is a research prototype evaluated on synthetic data.** Every number below was
> produced by a generator we wrote. It measures whether agent-behaviour and campaign
> context add information *on this benchmark*. It does not establish real-world performance,
> and it was not trained on or validated against any Razorpay data."""
    )

    # -- dataset -----------------------------------------------------------------------
    balance = summary.get("label_balance", {})
    hard = summary.get("hard_negatives", {})
    sections.append(
        f"""## 1. Dataset

| Property | Value |
|---|---|
| Transactions | {summary.get('transactions', 0):,} |
| Agent actions | {summary.get('actions', 0):,} |
| Sessions | {summary.get('sessions', 0):,} |
| Delegations | {summary.get('delegations', 0):,} |
| Episodes (split groups) | {summary.get('groups', 0):,} |
| Distinct campaigns | {summary.get('campaigns', 0):,} |
| Abusive transactions | {balance.get('abusive', 0):,} ({_pct(balance.get('abusive_rate'))}) |
| Hard negatives | {hard.get('transactions', 0):,} ({_pct(hard.get('share_of_legitimate'))} of legitimate traffic) |

### Composition by class

{_table(["Class", "Transactions"], [[k, f"{v:,}"] for k, v in sorted(summary.get('by_class', {}).items())])}

### Composition by scenario

{_table(["Scenario", "Transactions"], [[k, f"{v:,}"] for k, v in sorted(summary.get('by_scenario', {}).items())])}

Hard-negative scenarios — legitimate traffic deliberately built to trip naive rules:
{", ".join(f"`{s}`" for s in hard.get("scenarios", []))}."""
    )

    # -- methodology -------------------------------------------------------------------
    leakage = run.leakage_check
    sizes = leakage.get("split_sizes", {})
    sections.append(
        f"""## 2. Methodology

**Split.** {leakage.get('method', '—')} Splitting individual transactions would place the
same device farm on both sides of the wall and inflate every detector.

{_table(
    ["Split", "Transactions", "Groups", "Campaigns", "Abusive", "Hard negatives"],
    [[name, f"{s['transactions']:,}", f"{s['groups']:,}", str(s['campaigns']),
      f"{s['abusive']:,}", f"{s['hard_negatives']:,}"]
     for name, s in sizes.items()],
)}

**Leakage check:** `leakage_free = {leakage.get('leakage_free')}`

| Overlap | train↔validation | train↔holdout | validation↔holdout |
|---|---|---|---|
| Groups | {leakage.get('group_overlap', {}).get('train|validation')} | {leakage.get('group_overlap', {}).get('train|holdout')} | {leakage.get('group_overlap', {}).get('validation|holdout')} |
| Campaigns | {leakage.get('campaign_overlap', {}).get('train|validation')} | {leakage.get('campaign_overlap', {}).get('train|holdout')} | {leakage.get('campaign_overlap', {}).get('validation|holdout')} |
| Customers | {leakage.get('entity_overlap', {}).get('customer_id', {}).get('train|validation')} | {leakage.get('entity_overlap', {}).get('customer_id', {}).get('train|holdout')} | {leakage.get('entity_overlap', {}).get('customer_id', {}).get('validation|holdout')} |
| Devices | {leakage.get('entity_overlap', {}).get('device_id', {}).get('train|validation')} | {leakage.get('entity_overlap', {}).get('device_id', {}).get('train|holdout')} | {leakage.get('entity_overlap', {}).get('device_id', {}).get('validation|holdout')} |

Merchants, SKUs and coupons are shared global catalog entities and overlap by design.

All operating points below were selected on the validation split.

**Training protocol.** Population baselines fit on train only. Component models fit on
train. Fusion weights fit on *grouped out-of-fold* component predictions from train.
Operating points chosen on validation by minimum expected loss under a review-rate cap.
The holdout was scored once, with frozen thresholds, and never used for tuning.

**Positive prediction** means BLOCK *or* REVIEW: both stop the loss. Their very different
costs are handled in the expected-loss model rather than folded into precision."""
    )

    # -- results -----------------------------------------------------------------------
    def result_rows(results: dict[str, DetectorResult]) -> list[list[str]]:
        return [
            [
                DETECTOR_LABELS.get(name, name),
                _num(r.metrics.precision),
                _num(r.metrics.recall),
                _num(r.metrics.f1),
                _num(r.metrics.pr_auc),
                _pct(r.metrics.false_positive_rate),
                _money(r.loss.expected_loss),
            ]
            for name, r in results.items()
        ]

    headers = ["Detector", "Precision", "Recall", "F1", "PR-AUC", "FP rate", "Expected loss"]
    sections.append(
        f"""## 3. Results

### Holdout (frozen thresholds, scored once)

{_table(headers, result_rows(holdout))}

### Validation (used for threshold selection)

{_table(headers, result_rows(validation))}"""
    )

    # -- operating points and costs ----------------------------------------------------
    sections.append(
        f"""## 4. Decision mix and merchant cost (holdout)

{_table(
    ["Detector", "Review threshold", "Block threshold", "Allow", "Review", "Block",
     "Blocked legit GMV", "Prevented loss", "Expected loss"],
    [[DETECTOR_LABELS.get(name, name),
      _num(r.thresholds.get("review"), 2), _num(r.thresholds.get("block"), 2),
      _pct(r.loss.allow_rate), _pct(r.loss.review_rate), _pct(r.loss.block_rate),
      _money(r.loss.blocked_legitimate_gmv), _money(r.loss.prevented_loss),
      _money(r.loss.expected_loss)]
     for name, r in holdout.items()],
)}

**Cost assumptions** (synthetic, configurable, not sourced industry figures):

| Parameter | Value | Meaning |
|---|---|---|
| `fn_cost_multiplier` | {cost.fn_cost_multiplier if cost else '—'} | Merchant loss per missed abusive transaction, as a multiple of its amount |
| `chargeback_fee_flat` | {_money(cost.chargeback_fee_flat) if cost else '—'} | Flat dispute-handling fee per missed abuse |
| `fp_cost_multiplier` | {cost.fp_cost_multiplier if cost else '—'} | Lost margin/goodwill per wrongly blocked legitimate transaction |
| `review_cost_flat` | {_money(cost.review_cost_flat) if cost else '—'} | Analyst cost per manual review |

A reviewed transaction is modelled as caught: reviewed abuse counts as prevented loss plus
an analyst cost. That is an optimistic assumption about analyst effectiveness and it is
stated here rather than buried in the code."""
    )

    # -- hard negatives ----------------------------------------------------------------
    hard_rows: list[list[str]] = []
    for name, result in holdout.items():
        for slice_metrics in result.slices:
            if slice_metrics.slice_name in ("hard_negatives", "legit_agent", "legit_human"):
                hard_rows.append([
                    DETECTOR_LABELS.get(name, name),
                    slice_metrics.slice_name,
                    f"{slice_metrics.count:,}",
                    f"{slice_metrics.metrics.false_positives:,}",
                    _pct(slice_metrics.metrics.false_positive_rate),
                ])
    sections.append(
        f"""## 5. Hard negatives and legitimate automation (holdout)

This is the section that decides whether the system is safe to deploy. `hard_negatives` is
legitimate traffic engineered to look suspicious — flash-sale bursts, shared household
devices, enterprise bulk buyers, very fast legitimate agents, gateway-retry storms. Any flag
here is a false positive on a paying customer.

{_table(["Detector", "Slice", "Transactions", "False positives", "FP rate"], hard_rows)}"""
    )

    # -- recall on the target class ----------------------------------------------------
    abuse_rows: list[list[str]] = []
    for name, result in holdout.items():
        for slice_metrics in result.slices:
            if slice_metrics.slice_name in ("coordinated_abuse", "suspicious_automation"):
                abuse_rows.append([
                    DETECTOR_LABELS.get(name, name),
                    slice_metrics.slice_name,
                    f"{slice_metrics.count:,}",
                    _num(slice_metrics.metrics.recall),
                    f"{slice_metrics.metrics.false_negatives:,}",
                ])
    diagnostics = summary.get("diagnostics", {})
    lead_rows = [
        [DETECTOR_LABELS.get(name, name),
         str(d.get("lead_time_holdout", {}).get("campaigns_evaluated", "—")),
         str(d.get("lead_time_holdout", {}).get("campaigns_detected", "—")),
         _num(d.get("lead_time_holdout", {}).get("median_transactions_before_first_flag"), 1),
         _num(d.get("calibration_error_holdout"))]
        for name, d in diagnostics.items()
    ]
    sections.append(
        f"""## 6. Detection on the target loss class (holdout)

{_table(["Detector", "Slice", "Transactions", "Recall", "Missed"], abuse_rows)}

### Campaign detection lead time

Context windows are past-only, so the first transaction of a campaign has no cluster to
observe. This measures the cost of that honesty: how many transactions into a campaign the
first flag lands.

{_table(["Detector", "Campaigns", "Detected", "Median txns before first flag", "Calibration error"], lead_rows)}"""
    )

    # -- per-scenario ------------------------------------------------------------------
    tyche_holdout = holdout.get("tyche")
    if tyche_holdout:
        scenario_rows = [
            [
                s.slice_name.removeprefix("scenario:"),
                f"{s.count:,}",
                "abusive" if s.metrics.support_positive > 0 else "legitimate",
                _num(s.metrics.recall) if s.metrics.support_positive else "—",
                _pct(s.metrics.false_positive_rate) if s.metrics.support_negative else "—",
            ]
            for s in tyche_holdout.slices
            if s.slice_name.startswith("scenario:")
        ]
        sections.append(
            f"""## 7. Per-scenario behaviour — Tyche (holdout)

{_table(["Scenario", "Transactions", "Ground truth", "Recall", "FP rate"], scenario_rows)}"""
        )

    # -- threshold sweep ---------------------------------------------------------------
    sweep_sections = []
    for name, points in run.threshold_sweep.items():
        rows = [
            [_num(p.review_threshold, 2), _num(p.block_threshold, 2), _num(p.precision),
             _num(p.recall), _num(p.f1), _pct(p.false_positive_rate), _pct(p.review_rate),
             _money(p.blocked_legitimate_gmv), _money(p.prevented_loss), _money(p.expected_loss)]
            for p in _sweep_extract(points)
        ]
        sweep_sections.append(
            f"""### {DETECTOR_LABELS.get(name, name)}

{_table(["Review", "Block", "Precision", "Recall", "F1", "FP rate", "Review rate",
         "Blocked legit GMV", "Prevented loss", "Expected loss"], rows)}"""
        )
    sections.append(
        "## 8. Threshold sweep and expected-loss curve (validation)\n\n"
        "Best point per block threshold. The chosen operating point minimises expected loss "
        "subject to the review-rate cap.\n\n" + "\n\n".join(sweep_sections)
    )

    # -- fusion ------------------------------------------------------------------------
    weights = summary.get("fusion_weights", {})
    if weights:
        weight_rows = [[k, f"{v:+.3f}"] for k, v in weights.items()]
        sections.append(
            f"""## 9. Learned fusion weights

Logistic-regression coefficients over component scores, fitted on grouped out-of-fold
predictions from the training split. `avail_*` terms are the availability flags that let the
model treat a missing component as *unknown* rather than as zero risk.

{_table(["Fusion input", "Coefficient"], weight_rows)}

Intercept: `{_num(summary.get('fusion_intercept'))}`"""
        )

    # -- honest limitations ------------------------------------------------------------
    sections.append(
        """## 10. What this does and does not show

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
   approximated."""
    )

    return "\n\n".join(sections) + "\n"
