"""Evaluation report formatter for Veyra v2 benchmark results (Phase 5.2).

Produces structured comparative benchmark tables across Detectors A, B, and C:
- Window Metrics (PR-AUC, ROC-AUC, Brier score)
- Incident Metrics (Incident Recall, Precision, Detection Latency p50/p90)
- Operational Metrics (False Alerts/Merchant/Day, Hard-Negative FP Breakdown)
- Economic Risk & Cost Reduction
"""

from __future__ import annotations

from app.evaluation.runner import BenchmarkSuiteResults


def generate_evaluation_markdown_report(suite: BenchmarkSuiteResults) -> str:
    """Format benchmark suite results into structured Markdown report.

    Two credibility fixes from the production-hardening audit, both load-bearing for
    what this report is allowed to claim:

    1. Recall/precision/latency percentages are meaningless without their denominator.
       `n_ground_truth_attack_incidents` is printed next to every recall figure so a
       reader cannot mistake "3 out of 3" for a statistically powered result.
    2. Hard-negative FP counts are now sourced from `hard_negative_population`
       (windows that were *actually present* in TEST for that scenario). A scenario
       that never occurred in this run's TEST split is reported as "not present in
       test split", not as a silent "0" — the previous version of this function fell
       back to a hardcoded list of three scenario names whenever none were observed,
       printing "0 FPs" for scenarios that were never evaluated in that run at all.
    """
    res_a = suite.results_by_detector.get("volume_only")
    res_b = suite.results_by_detector.get("contextual_ml")
    res_c = suite.results_by_detector.get("veyra_fusion")

    md = []
    md.append("# Veyra v2 — Fraud Spike Benchmark Evaluation Report\n")
    md.append(f"**Merchants:** {suite.n_merchants} | **Test Windows:** {suite.n_test_windows}")
    md.append(f"**Test Period:** {suite.test_start.strftime('%Y-%m-%d %H:%M UTC')} to {suite.test_end.strftime('%Y-%m-%d %H:%M UTC')}")
    md.append(f"**Ground-truth attack incidents in TEST:** {suite.n_ground_truth_attack_incidents}\n")

    if suite.n_ground_truth_attack_incidents < 10:
        md.append(
            f"> **Sample-size caveat:** TEST contains only "
            f"{suite.n_ground_truth_attack_incidents} ground-truth attack incident"
            f"{'s' if suite.n_ground_truth_attack_incidents != 1 else ''}. Incident "
            "recall/precision below are computed over this count and are not "
            "statistically meaningful at this scale — treat them as a smoke test that "
            "the pipeline runs end to end, not as a measured detection rate. A larger, "
            "multi-seed benchmark is required before recall/precision numbers from this "
            "report should be cited as a performance claim.\n"
        )

    # Table 1: Model Comparison
    md.append("## 1. Comparative Detector Performance\n")
    md.append("| Detector | PR-AUC | Incident Recall | Latency p50 (min) | False Alerts / Merch / Day | Expected Loss (₹) |")
    md.append("|---|---|---|---|---|---|")

    for name, r in suite.results_by_detector.items():
        pr = f"{r.window_metrics.pr_auc:.3f}"
        n = suite.n_ground_truth_attack_incidents
        tp = r.incident_metrics.true_positive_count
        rec = f"{r.incident_metrics.incident_recall:.1%} ({tp}/{n})"
        lat = f"{r.incident_metrics.latency_p50_minutes:.1f}"
        fa = f"{r.false_alerts_per_merchant_day:.2f}"
        loss = f"₹{r.expected_financial_loss:,.2f}"
        md.append(f"| **{name}** | {pr} | {rec} | {lat} | {fa} | {loss} |")

    # Table 2: Hard-Negative False Positives
    md.append("\n## 2. Hard-Negative False Positive Separation Breakdown\n")
    md.append("| Legitimate Spike Scenario | Windows in TEST | Detector A (Volume) FPs | Detector B (Contextual) FPs | Detector C (Veyra) FPs |")
    md.append("|---|---|---|---|---|")

    scenarios = set(suite.hard_negative_population.keys())
    for r in suite.results_by_detector.values():
        scenarios.update(r.hard_negative_fp_counts.keys())

    if not scenarios:
        md.append("| *(no LEGIT_SPIKE-labelled windows occurred in this TEST split)* | 0 | — | — | — |")
    else:
        for sc in sorted(scenarios):
            population = suite.hard_negative_population.get(sc, 0)
            if population == 0:
                md.append(f"| `{sc}` | 0 | *not present in test split* | *not present in test split* | *not present in test split* |")
                continue
            fp_a = res_a.hard_negative_fp_counts.get(sc, 0) if res_a else 0
            fp_b = res_b.hard_negative_fp_counts.get(sc, 0) if res_b else 0
            fp_c = res_c.hard_negative_fp_counts.get(sc, 0) if res_c else 0
            md.append(f"| `{sc}` | {population} | {fp_a} | {fp_b} | **{fp_c}** |")

    # Section 3: Key Insights — reported honestly in whichever direction the numbers
    # actually point, not only when Veyra Fusion comes out ahead.
    md.append("\n## 3. Findings & Thesis Verification (§26–27)\n")
    if res_c and res_b and res_a:
        diff = (res_c.window_metrics.pr_auc - res_b.window_metrics.pr_auc) * 100.0
        if diff >= 0:
            md.append(
                f"- **Graph value add:** Veyra Fusion's PR-AUC ({res_c.window_metrics.pr_auc:.3f}) was "
                f"**+{diff:.1f} points** over Contextual ML ({res_b.window_metrics.pr_auc:.3f}), which excludes "
                "relationship/graph features. On this run, the graph features helped."
            )
        else:
            md.append(
                f"- **Graph value add — not observed on this run:** Veyra Fusion's PR-AUC "
                f"({res_c.window_metrics.pr_auc:.3f}) was **{diff:.1f} points below** Contextual ML "
                f"({res_b.window_metrics.pr_auc:.3f}), which excludes relationship/graph features entirely. "
                "The graph engine added complexity without a measured accuracy benefit here; do not claim "
                "the graph features improve detection until this reverses on a larger evaluation."
            )
        if res_a.false_alerts_per_merchant_day > res_c.false_alerts_per_merchant_day:
            md.append(f"- **Volume baseline defect:** Volume-only alerting generated **{res_a.false_alerts_per_merchant_day:.2f}** false alerts/merchant/day vs **{res_c.false_alerts_per_merchant_day:.2f}** with Veyra.")
        elif res_a.incident_metrics.incident_recall < res_c.incident_metrics.incident_recall:
            md.append(
                f"- **Volume baseline defect:** Volume-only recall was "
                f"{res_a.incident_metrics.incident_recall:.1%} "
                f"({res_a.incident_metrics.true_positive_count}/{suite.n_ground_truth_attack_incidents}) vs "
                f"Veyra's {res_c.incident_metrics.incident_recall:.1%} "
                f"({res_c.incident_metrics.true_positive_count}/{suite.n_ground_truth_attack_incidents}) — "
                "at this sample size this is one incident's outcome, not a rate."
            )

    return "\n".join(md)
