"""Population baselines fitted on the training split only.

A feature like "amount relative to the typical amount in this category" needs a
population statistic. Computing it over the whole dataset would leak holdout information
into training, so baselines are fitted on train, persisted with the model, and applied
unchanged everywhere else.
"""

from __future__ import annotations

import json
import statistics
from collections import defaultdict
from dataclasses import asdict, dataclass, field
from pathlib import Path


@dataclass
class Baselines:
    category_amount_median: dict[str, float] = field(default_factory=dict)
    global_amount_median: float = 1000.0
    category_coupon_rate: dict[str, float] = field(default_factory=dict)
    fitted_on: int = 0
    version: str = "baselines-v1"

    def amount_median_for(self, category: str) -> float:
        return self.category_amount_median.get(category, self.global_amount_median)

    def coupon_rate_for(self, category: str) -> float:
        return self.category_coupon_rate.get(category, 0.1)

    @classmethod
    def fit(cls, records) -> Baselines:
        """Fit from any iterable of objects exposing ``merchant_category``/``amount``."""
        amounts: dict[str, list[float]] = defaultdict(list)
        coupons: dict[str, list[int]] = defaultdict(list)
        all_amounts: list[float] = []
        count = 0
        for record in records:
            category = record.merchant_category
            amount = float(record.amount)
            amounts[category].append(amount)
            all_amounts.append(amount)
            coupons[category].append(1 if getattr(record, "coupon_id", None) else 0)
            count += 1
        return cls(
            category_amount_median={
                c: statistics.median(v) for c, v in amounts.items() if v
            },
            global_amount_median=statistics.median(all_amounts) if all_amounts else 1000.0,
            category_coupon_rate={
                c: statistics.fmean(v) for c, v in coupons.items() if v
            },
            fitted_on=count,
        )

    def save(self, path: str | Path) -> None:
        Path(path).write_text(json.dumps(asdict(self), indent=2), encoding="utf-8")

    @classmethod
    def load(cls, path: str | Path) -> Baselines:
        return cls(**json.loads(Path(path).read_text(encoding="utf-8")))


DEFAULT_BASELINES = Baselines()
