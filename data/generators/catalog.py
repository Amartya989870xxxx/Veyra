"""Shared synthetic entity catalogs.

Merchants, SKUs and coupons are global by design: a merchant is not a label-bearing
entity, and sharing them across episodes is what makes the benchmark realistic. Customers,
agents, devices and networks are allocated per episode so that a train/test split by group
cannot leak an abusive entity into the evaluation half.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field

CATEGORIES = [
    "grocery",
    "food",
    "electronics",
    "fashion",
    "pharmacy",
    "travel",
    "gaming",
    "utilities",
    "alcohol",
    "gift_cards",
]

# Typical ticket size per category, in INR: (median, log-spread).
CATEGORY_PRICING: dict[str, tuple[float, float]] = {
    "grocery": (850.0, 0.55),
    "food": (420.0, 0.5),
    "electronics": (14500.0, 0.8),
    "fashion": (2200.0, 0.7),
    "pharmacy": (640.0, 0.6),
    "travel": (9800.0, 0.75),
    "gaming": (1500.0, 0.65),
    "utilities": (1200.0, 0.4),
    "alcohol": (1800.0, 0.5),
    "gift_cards": (2000.0, 0.6),
}

PAYMENT_METHODS = ["upi", "card_token", "netbanking", "wallet", "upi_reserve_pay"]


@dataclass(frozen=True)
class Merchant:
    merchant_id: str
    category: str
    is_known: bool


@dataclass(frozen=True)
class Sku:
    sku_id: str
    merchant_id: str
    category: str
    base_price: float
    is_hot: bool


@dataclass(frozen=True)
class Coupon:
    coupon_id: str
    value: float
    is_public: bool


@dataclass
class Catalog:
    merchants: list[Merchant] = field(default_factory=list)
    skus: list[Sku] = field(default_factory=list)
    coupons: list[Coupon] = field(default_factory=list)

    _by_category: dict[str, list[Merchant]] = field(default_factory=dict, repr=False)
    _skus_by_merchant: dict[str, list[Sku]] = field(default_factory=dict, repr=False)

    def index(self) -> None:
        self._by_category = {}
        for m in self.merchants:
            self._by_category.setdefault(m.category, []).append(m)
        self._skus_by_merchant = {}
        for s in self.skus:
            self._skus_by_merchant.setdefault(s.merchant_id, []).append(s)

    def merchants_in(self, category: str) -> list[Merchant]:
        return self._by_category.get(category, [])

    def skus_of(self, merchant_id: str) -> list[Sku]:
        return self._skus_by_merchant.get(merchant_id, [])

    def hot_skus(self) -> list[Sku]:
        return [s for s in self.skus if s.is_hot]

    def public_coupons(self) -> list[Coupon]:
        return [c for c in self.coupons if c.is_public]

    def private_coupons(self) -> list[Coupon]:
        return [c for c in self.coupons if not c.is_public]


def build_catalog(rng: random.Random, n_merchants: int, n_skus: int, n_coupons: int) -> Catalog:
    merchants: list[Merchant] = []
    for i in range(n_merchants):
        category = CATEGORIES[i % len(CATEGORIES)]
        merchants.append(
            Merchant(
                merchant_id=f"m_{i:04d}",
                category=category,
                # A minority of merchants are outside the customer's known set, which the
                # `known_or_approved` delegation policy is allowed to care about.
                is_known=rng.random() > 0.15,
            )
        )

    skus: list[Sku] = []
    for i in range(n_skus):
        merchant = merchants[i % len(merchants)]
        median, spread = CATEGORY_PRICING[merchant.category]
        price = round(median * (1.0 + rng.gauss(0, spread) * 0.35), 2)
        price = max(49.0, price)
        skus.append(
            Sku(
                sku_id=f"sku_{i:04d}",
                merchant_id=merchant.merchant_id,
                category=merchant.category,
                base_price=price,
                is_hot=rng.random() < 0.06,  # a handful of genuinely popular products
            )
        )

    coupons: list[Coupon] = []
    for i in range(n_coupons):
        coupons.append(
            Coupon(
                coupon_id=f"cpn_{i:03d}",
                value=round(rng.choice([50, 100, 150, 200, 300, 500]) * 1.0, 2),
                is_public=rng.random() < 0.6,
            )
        )

    catalog = Catalog(merchants=merchants, skus=skus, coupons=coupons)
    catalog.index()
    return catalog
