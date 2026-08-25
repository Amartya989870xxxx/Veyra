#!/usr/bin/env python3
"""Phase 0 gate: validate the research matrix against the feature registry.

The matrix is only worth writing as data if something enforces it. This script is that
something. It runs in CI and fails the build when the matrix and the registry drift apart,
or when a scenario is written in a way that cannot be evaluated honestly.

The checks, and why each exists:

  C1  every scenario declares what it is confusable with, and how to tell them apart
      -> a scenario without this is "volume anomaly treated as verdict" (brief §5)
  C2  every referenced feature resolves in the registry
      -> stops the matrix describing detection it has no features for
  C3  every confusable_with target is a scenario, or a declared external look-alike
      -> catches typos; forces out-of-scope look-alikes to be deliberate
  C4  confusion is symmetric
      -> if A hides behind B, the generator must build B too, or A is untestable
  C5  attacks declare an intensity range reaching a genuinely undetectable low end
      -> without this, recall measures our generator's generosity (brief §13)
  C6  attacks declare which features must NOT separate them alone
      -> the anti-leakage contract, per-scenario
  C7  downstream-only features appear only in retrospective scenarios
      -> disputes and RTO are label sources, never real-time features (brief §6.10)
  C8  every legitimate scenario is named by at least one attack
      -> an unreferenced hard negative is one nothing is actually tested against

Usage:  python research/validate.py [--strict]
        --strict promotes warnings to failures.
"""

from __future__ import annotations

import sys
from collections import defaultdict
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent
MATRIX = ROOT / "matrix.yaml"
REGISTRY = ROOT / "features.yaml"

errors: list[str] = []
warnings: list[str] = []


def err(scenario: str, msg: str) -> None:
    errors.append(f"  [{scenario}] {msg}")


def warn(scenario: str, msg: str) -> None:
    warnings.append(f"  [{scenario}] {msg}")


def main(strict: bool = False) -> int:
    matrix = yaml.safe_load(MATRIX.read_text())
    registry = yaml.safe_load(REGISTRY.read_text())

    features = {f["id"]: f for f in registry["features"]}
    downstream_only = {fid for fid, f in features.items() if f.get("downstream_only")}
    families = set(registry["families"])

    scenarios = {s["id"]: s for s in matrix["scenarios"]}
    external = set(matrix.get("external_lookalikes", {}))
    retrospective_metrics = {"retrospective_label_quality"}

    if len(scenarios) != len(matrix["scenarios"]):
        errors.append("  [matrix] duplicate scenario ids")

    # registry self-consistency
    for fid, f in features.items():
        if f["family"] not in families:
            errors.append(f"  [registry] {fid} declares unknown family {f['family']!r}")

    referenced: set[str] = set()
    named_as_lookalike: set[str] = defaultdict(set)
    named_as_lookalike = defaultdict(set)

    for sid, s in scenarios.items():
        is_attack = s["class"] in ("attack", "mixed")
        is_baseline = s.get("family") == "baseline"
        is_retrospective = bool(set(s.get("eval_metric", [])) & retrospective_metrics)

        # ---- C1 -------------------------------------------------------------------
        lookalikes = s.get("confusable_with") or []
        discriminator = (s.get("discriminator") or "").strip()
        if not lookalikes and not is_baseline:
            err(sid, "C1: confusable_with is empty (only the baseline reference class may be)")
        if not discriminator:
            err(sid, "C1: discriminator is missing")
        elif len(discriminator) < 120 and not is_baseline:
            warn(sid, f"C1: discriminator is only {len(discriminator)} chars"
                 " — likely too vague to test")

        # ---- C2 -------------------------------------------------------------------
        for fid in s.get("features") or []:
            referenced.add(fid)
            if fid not in features:
                err(sid, f"C2: references unknown feature {fid!r}")
        if not s.get("features") and not is_baseline:
            err(sid, "C2: declares no features")

        # ---- C3 -------------------------------------------------------------------
        for target in lookalikes:
            if target in scenarios:
                named_as_lookalike[target].add(sid)
            elif target not in external:
                err(sid, f"C3: confusable_with {target!r} is neither a scenario"
                    " nor a declared external look-alike")

        # ---- C5 / C6 --------------------------------------------------------------
        recipe = s.get("synthetic_recipe") or {}
        if is_attack and not is_retrospective:
            if not recipe.get("intensity_range"):
                err(sid, "C5: attack declares no intensity_range"
                    " — recall would measure generator generosity")
            if not recipe.get("forbid_single_feature_separability"):
                err(sid, "C6: attack declares no"
                    " forbid_single_feature_separability contract")

        # ---- C7 -------------------------------------------------------------------
        leaked = set(s.get("features") or []) & downstream_only
        if leaked and not is_retrospective:
            err(sid, f"C7: uses downstream-only feature(s) {sorted(leaked)}"
                " in a real-time scenario")

    # ---- C4 ------------------------------------------------------------------------
    for sid, s in scenarios.items():
        for target in s.get("confusable_with") or []:
            # The baseline reference class is confusable with everything by definition;
            # naming all 26 others back would say nothing.
            if scenarios.get(target, {}).get("family") == "baseline":
                continue
            if target in scenarios and sid not in (scenarios[target].get("confusable_with") or []):
                warn(sid, f"C4: claims confusion with {target!r},"
                     f" but {target!r} does not name it back")

    # ---- C8 ------------------------------------------------------------------------
    for sid, s in scenarios.items():
        if (s["class"] == "legitimate" and s.get("family") != "baseline"
                and not named_as_lookalike.get(sid)):
            warn(sid, "C8: no attack names this hard negative"
                 " — nothing is tested against it")

    # Evidence-only and downstream-only entries are unreferenced by design: the first are
    # for humans reading an incident, the second are label sources. Report them apart from
    # features that are genuinely defined and then never used.
    by_design = {fid for fid, f in features.items()
                 if f.get("evidence_only") or f.get("downstream_only")}
    unused = sorted(set(features) - referenced - by_design)
    unused_by_design = sorted((set(features) - referenced) & by_design)

    # ---- report --------------------------------------------------------------------
    print(f"scenarios         {len(scenarios)}")
    print(f"features declared {len(features)}   referenced {len(referenced)}"
          f"   unreferenced {len(unused)}")
    if unused:
        print(f"  UNUSED (defined but never referenced): {', '.join(unused)}")
    if unused_by_design:
        print(f"  unreferenced by design (evidence/label only): {', '.join(unused_by_design)}")

    if warnings:
        print(f"\nWARNINGS ({len(warnings)})")
        print("\n".join(warnings))
    if errors:
        print(f"\nERRORS ({len(errors)})")
        print("\n".join(errors))
        print("\nGATE: FAIL")
        return 1
    if warnings and strict:
        print("\nGATE: FAIL (strict — warnings promoted)")
        return 1
    print("\nGATE: PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main(strict="--strict" in sys.argv))
