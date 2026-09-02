"""Merchant population and entity pool generators for Veyra v2 (Phase 2.1).

Defines realistic merchant behavioral profiles, size bands, payment mix distributions,
price curves, and pre-allocated entity pools (devices, instruments, IPs, accounts)
so that organic background traffic and injected scenarios draw from the same entity spaces (ADR-007).
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from typing import Sequence

from app.core.ids import new_id, stable_hash
from app.schemas.entities import Geo, InstrumentMeta, Merchant
from app.schemas.enums import InstrumentType, PaymentMethod

# Categories aligned with real payment volume in Indian commerce
CATEGORIES = (
    "electronics",
    "fashion_retail",
    "grocery_qcommerce",
    "digital_services",
    "gaming_entertainment",
    "travel_hospitality",
)

CARD_BRANDS = ("visa", "mastercard", "rupay", "amex")
BIN_PREFIXES = (
    "411111", "424242", "400000",  # Visa
    "510000", "520000", "555555",  # Mastercard
    "607000", "652100",            # RuPay
    "378282", "371449",            # Amex
)

MAJOR_INDIAN_CITIES = (
    Geo(country="IN", state="KA", city="Bengaluru"),
    Geo(country="IN", state="MH", city="Mumbai"),
    Geo(country="IN", state="DL", city="New Delhi"),
    Geo(country="IN", state="TG", city="Hyderabad"),
    Geo(country="IN", state="TN", city="Chennai"),
    Geo(country="IN", state="WB", city="Kolkata"),
    Geo(country="IN", state="MH", city="Pune"),
    Geo(country="IN", state="GJ", city="Ahmedabad"),
    Geo(country="IN", state="RJ", city="Jaipur"),
    Geo(country="IN", state="UP", city="Lucknow"),
)


@dataclass
class MerchantProfile:
    """Statistical and behavioral blueprint for a merchant."""

    merchant: Merchant
    hourly_baseline_txns: float
    avg_ticket_size: Decimal
    ticket_std_dev: Decimal
    payment_method_weights: dict[PaymentMethod, float]
    cod_eligible: bool
    cod_share: float
    on_file_rate: float
    organic_decline_rate: float

    # Entity pools (sized to merchant scale)
    customer_pool: list[str] = field(default_factory=list)
    device_pool: list[str] = field(default_factory=list)
    instrument_pool: list[InstrumentMeta] = field(default_factory=list)
    instrument_fp_pool: list[str] = field(default_factory=list)
    ip_pool: list[str] = field(default_factory=list)

    def sample_price(self, rng: random.Random) -> Decimal:
        """Sample transaction amount from log-normal price distribution."""
        mean = float(self.avg_ticket_size)
        std = float(self.ticket_std_dev)
        # Log-normal parameters
        mu = float(Decimal(str(mean)).ln())
        sigma = max(0.2, std / max(1.0, mean))
        val = rng.lognormvariate(mu, sigma)
        val = max(10.0, min(val, mean * 15.0))
        return Decimal(f"{val:.2f}")

    def sample_payment_method(self, rng: random.Random) -> PaymentMethod:
        methods = list(self.payment_method_weights.keys())
        weights = list(self.payment_method_weights.values())
        return rng.choices(methods, weights=weights, k=1)[0]

    def sample_geo(self, rng: random.Random) -> Geo:
        # 85% chance within primary Indian metros, 15% tier-2/3
        return rng.choice(MAJOR_INDIAN_CITIES)

    def sample_device(self, rng: random.Random) -> str:
        return rng.choice(self.device_pool)

    def sample_customer(self, rng: random.Random) -> str:
        return rng.choice(self.customer_pool)

    def sample_instrument(self, rng: random.Random) -> tuple[str, InstrumentMeta]:
        idx = rng.randrange(len(self.instrument_pool))
        return self.instrument_fp_pool[idx], self.instrument_pool[idx]

    def sample_ip(self, rng: random.Random) -> str:
        return rng.choice(self.ip_pool)


def create_entity_pools(
    merchant_id: str,
    n_customers: int,
    n_devices: int,
    n_instruments: int,
    n_ips: int,
    on_file_rate: float,
    seed: int = 42,
) -> tuple[list[str], list[str], list[InstrumentMeta], list[str], list[str]]:
    rng = random.Random(seed)

    customers = [f"cus_{merchant_id}_{i:05d}" for i in range(n_customers)]
    devices = [f"dv_{stable_hash(f'{merchant_id}:dev:{i}')[:12]}" for i in range(n_devices)]
    ips = [f"ip_{stable_hash(f'{merchant_id}:ip:{i}')[:12]}" for i in range(n_ips)]

    instruments: list[InstrumentMeta] = []
    instrument_fps: list[str] = []

    for i in range(n_instruments):
        brand = rng.choice(CARD_BRANDS)
        itype = InstrumentType.CREDIT if brand != "rupay" else InstrumentType.DEBIT
        bin_pfx = rng.choice(BIN_PREFIXES)
        bin_h = stable_hash(bin_pfx)[:12]
        is_on_file = rng.random() < on_file_rate

        meta = InstrumentMeta(
            brand=brand,
            instrument_type=itype,
            issuer_country="IN",
            bin_hash=f"bin_{bin_h}",
            is_on_file=is_on_file,
        )
        fp = f"if_{stable_hash(f'{merchant_id}:card:{i}')[:12]}"
        instruments.append(meta)
        instrument_fps.append(fp)

    return customers, devices, instruments, instrument_fps, ips


def generate_merchant_population(
    n_merchants: int = 10,
    seed: int = 42,
) -> list[MerchantProfile]:
    """Generate a diverse synthetic merchant population across sizes and categories."""
    rng = random.Random(seed)
    profiles: list[MerchantProfile] = []

    size_bands = (
        ("small", 15.0, 150, 120, 200, 100),       # ~15 txns/hr
        ("medium", 80.0, 800, 600, 1000, 500),     # ~80 txns/hr
        ("enterprise", 400.0, 4000, 3000, 5000, 2000),  # ~400 txns/hr
    )

    for i in range(n_merchants):
        m_id = f"m_{i+1:04d}"
        category = CATEGORIES[i % len(CATEGORIES)]
        size_name, base_txns, n_cust, n_dev, n_inst, n_ip = size_bands[i % len(size_bands)]

        # Category-specific ticket size and payment mix
        if category == "electronics":
            avg_ticket = Decimal("4500.00")
            ticket_std = Decimal("2500.00")
            pay_weights = {PaymentMethod.CARD: 0.50, PaymentMethod.UPI: 0.35, PaymentMethod.EMI: 0.15}
            cod_eligible = False
            cod_share = 0.0
            on_file = 0.15
        elif category == "grocery_qcommerce":
            avg_ticket = Decimal("450.00")
            ticket_std = Decimal("200.00")
            pay_weights = {PaymentMethod.UPI: 0.70, PaymentMethod.CARD: 0.20, PaymentMethod.WALLET: 0.10}
            cod_eligible = True
            cod_share = 0.20
            on_file = 0.40
        elif category == "fashion_retail":
            avg_ticket = Decimal("1850.00")
            ticket_std = Decimal("900.00")
            pay_weights = {PaymentMethod.UPI: 0.45, PaymentMethod.CARD: 0.40, PaymentMethod.COD: 0.15}
            cod_eligible = True
            cod_share = 0.25
            on_file = 0.25
        elif category == "digital_services":
            avg_ticket = Decimal("699.00")
            ticket_std = Decimal("300.00")
            pay_weights = {PaymentMethod.CARD: 0.55, PaymentMethod.UPI: 0.40, PaymentMethod.NETBANKING: 0.05}
            cod_eligible = False
            cod_share = 0.0
            on_file = 0.65
        else:
            avg_ticket = Decimal("1200.00")
            ticket_std = Decimal("600.00")
            pay_weights = {PaymentMethod.UPI: 0.50, PaymentMethod.CARD: 0.40, PaymentMethod.WALLET: 0.10}
            cod_eligible = True
            cod_share = 0.10
            on_file = 0.20

        custs, devs, insts, inst_fps, ips = create_entity_pools(
            merchant_id=m_id,
            n_customers=n_cust,
            n_devices=n_dev,
            n_instruments=n_inst,
            n_ips=n_ip,
            on_file_rate=on_file,
            seed=seed + i * 97,
        )

        merchant_obj = Merchant(
            merchant_id=m_id,
            name=f"Merchant {i+1} ({category})",
            category=category,
            home_country="IN",
            size_band=size_name,
            onboarded_at=datetime(2025, 1, 1, tzinfo=UTC),
        )

        profile = MerchantProfile(
            merchant=merchant_obj,
            hourly_baseline_txns=base_txns,
            avg_ticket_size=avg_ticket,
            ticket_std_dev=ticket_std,
            payment_method_weights=pay_weights,
            cod_eligible=cod_eligible,
            cod_share=cod_share,
            on_file_rate=on_file,
            organic_decline_rate=0.03,  # 3% organic baseline failure rate
            customer_pool=custs,
            device_pool=devs,
            instrument_pool=insts,
            instrument_fp_pool=inst_fps,
            ip_pool=ips,
        )
        profiles.append(profile)

    return profiles
