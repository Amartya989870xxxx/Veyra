"""The Phase 0 gate, wired into pytest.

`research/validate.py` already runs in CI as its own job. It runs here too, in strict
mode, because a gate living only in a workflow file is a gate that stops being run the
moment someone works outside CI — and the matrix is the single source that drives the
generator, the feature registry and the evaluation slices. Drift there is silent.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.gate
def test_matrix_validates_strict() -> None:
    result = subprocess.run(
        [sys.executable, str(ROOT / "research" / "validate.py"), "--strict"],
        capture_output=True,
        text=True,
        cwd=ROOT,
    )
    assert result.returncode == 0, (
        "research matrix gate failed — the matrix and the feature registry have drifted.\n"
        f"{result.stdout}\n{result.stderr}"
    )


@pytest.mark.gate
def test_every_scenario_feature_resolves_in_the_registry() -> None:
    """C2, asserted directly rather than through the subprocess.

    Duplicated deliberately: this is the check that catches a typo propagating into the
    generator, and it should fail with a readable diff rather than a captured stdout
    blob.
    """
    yaml = pytest.importorskip("yaml")
    matrix = yaml.safe_load((ROOT / "research" / "matrix.yaml").read_text())
    registry = yaml.safe_load((ROOT / "research" / "features.yaml").read_text())

    known = {f["id"] for f in registry["features"]}
    dangling: dict[str, list[str]] = {}
    for scenario in matrix["scenarios"]:
        missing = [f for f in scenario.get("features") or [] if f not in known]
        if missing:
            dangling[scenario["id"]] = missing

    assert not dangling, f"matrix references features absent from the registry: {dangling}"
