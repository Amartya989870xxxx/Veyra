#!/usr/bin/env python3
"""Generate the deterministic synthetic benchmark.

    python scripts/generate_dataset.py --seed 42 --transactions 10000
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.core.config import get_settings  # noqa: E402
from app.core.logging import configure_logging  # noqa: E402
from data.generators.synthetic import (  # noqa: E402
    DEFAULT_COMPOSITION,
    GeneratorConfig,
    generate,
    save,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate the Veyra synthetic benchmark")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument(
        "--transactions", type=int, default=None,
        help="Approximate total; the class mix is scaled proportionally",
    )
    parser.add_argument("--duration-days", type=int, default=30)
    parser.add_argument("--out", default=None, help="Artifact directory")
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args()

    settings = get_settings()
    configure_logging(settings.log_level, "console")

    composition = dict(DEFAULT_COMPOSITION)
    if args.transactions:
        scale = args.transactions / sum(DEFAULT_COMPOSITION.values())
        composition = {k: max(1, int(v * scale)) for k, v in composition.items()}

    config = GeneratorConfig(
        seed=args.seed, composition=composition, duration_days=args.duration_days
    )
    dataset = generate(config)
    out_dir = args.out or str(Path(settings.artifact_dir) / "datasets")
    path = save(dataset, out_dir)

    if not args.quiet:
        manifest = dataset.manifest
        print(f"\nDataset written to {path}")
        print(json.dumps(
            {k: manifest[k] for k in ("dataset_id", "counts", "by_class", "label_balance",
                                      "hard_negatives")},
            indent=2,
        ))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
