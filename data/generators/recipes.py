"""Scenario injection recipes for the 27 matrix rows in Veyra v2 (Phase 2.4).

Every scenario injects perturbed transactions into a merchant's continuous timeline.
Anti-leakage contracts (ADR-007):
- No sentinel values (amounts, failure codes, and timestamps draw from continuous overlapping distributions).
- Attack intensity is a random variable across a wide range (including low intensities where recall is expected to degrade).
- Attacks draw from the merchant's own entity space (devices, customer IDs, IPs) where realistic.
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Callable

from app.core.ids import stable_hash
from app.schemas.entities import (
    Geo,
    InstrumentMeta,
    PaymentAttempt,
    PaymentOutcome,
)
from app.schemas.enums import (
    DeclineSource,
    InstrumentType,
    PaymentMethod,
    PaymentStatus,
)
from data.generators.population import MAJOR_INDIAN_CITIES, MerchantProfile
from data.generators.timeline import AnnotatedTransaction


ATTACK_DECLINE_CODES = (
    ("INVALID_CARD_NUMBER", DeclineSource.ISSUER, 0.40),
    ("INCORRECT_CVV", DeclineSource.ISSUER, 0.30),
    ("DO_NOT_HONOR", DeclineSource.ISSUER, 0.20),
    ("PICKUP_CARD", DeclineSource.ISSUER, 0.10),
)


def _sample_decline(rng: random.Random, weights: tuple[tuple[str, DeclineSource, float], ...]):
    """Draw a (failure_code, decline_source) pair from a weighted distribution.

    Several scenarios previously hard-coded a single failure code for every declined
    attempt, which drove `I.decline_code_entropy` to exactly 0.0 in ~56% of attack
    windows — a constant that appears almost nowhere else and is therefore a generator
    fingerprint rather than a behavioural signal. Real issuers return a spread of codes
    even within one attack.
    """
    codes, sources, w = zip(*weights)
    idx = rng.choices(range(len(codes)), weights=w, k=1)[0]
    return codes[idx], sources[idx]


CARD_TESTING_DECLINES = (
    ("INVALID_CARD_NUMBER", DeclineSource.ISSUER, 0.35),
    ("INCORRECT_CVV", DeclineSource.ISSUER, 0.25),
    ("DO_NOT_HONOR", DeclineSource.ISSUER, 0.20),
    ("EXPIRED_CARD", DeclineSource.ISSUER, 0.12),
    ("PICKUP_CARD", DeclineSource.ISSUER, 0.08),
)

RING_DECLINES = (
    ("SUSPECTED_FRAUD", DeclineSource.ISSUER, 0.40),
    ("DO_NOT_HONOR", DeclineSource.ISSUER, 0.25),
    ("LOST_OR_STOLEN", DeclineSource.ISSUER, 0.20),
    ("INSUFFICIENT_FUNDS", DeclineSource.ISSUER, 0.15),
)


@dataclass
class ScenarioInjectionSpec:
    scenario_id: str
    is_attack: bool
    is_spike: bool
    default_duration_min: int
    recipe_fn: Callable


def inject_card_testing_burst(
    profile: MerchantProfile,
    start_time: datetime,
    rng: random.Random,
    intensity: float = 1.0,
) -> list[AnnotatedTransaction]:
    """Card testing burst: high velocity probe of stolen card numbers."""
    duration_min = rng.randint(5, 20)
    end_time = start_time + timedelta(minutes=duration_min)

    # Intensity scales attempt count from low (subtle 30 txns) to high (400 txns)
    n_attempts = int(max(15, rng.randint(40, 250) * intensity))
    txns: list[AnnotatedTransaction] = []

    # Attacker operates from 1-3 devices and 1-4 proxy IPs
    n_attacker_devices = rng.randint(1, 3)
    attacker_devices = [f"dv_att_{stable_hash(f'att_dev_{i}_{start_time.isoformat()}')[:10]}" for i in range(n_attacker_devices)]
    attacker_ips = [f"ip_proxy_{stable_hash(f'att_ip_{i}_{start_time.isoformat()}')[:10]}" for i in range(2)]

    time_step_sec = (duration_min * 60.0) / max(1, n_attempts)
    current_time = start_time

    for i in range(n_attempts):
        current_time += timedelta(seconds=rng.uniform(0.1, time_step_sec * 1.5))
        if current_time >= end_time:
            current_time = end_time - timedelta(seconds=1)

        txn_id = f"txn_ct_{start_time.strftime('%H%M')}_{i:04d}"
        dev = rng.choice(attacker_devices)
        ip = rng.choice(attacker_ips)

        # Stolen card numbers: novel instrument fingerprints
        inst_fp = f"if_stolen_{stable_hash(f'card_{i}_{start_time.isoformat()}')[:12]}"
        inst_meta = InstrumentMeta(
            brand=rng.choice(("visa", "mastercard")),
            instrument_type=InstrumentType.CREDIT,
            issuer_country=rng.choice(("IN", "US", "GB", "SG")),
            bin_hash=f"bin_{stable_hash(str(i % 5))[:8]}",
            is_on_file=False,
        )

        # Micro authorization amount: ₹1.00 to ₹99.00 (within normal tail)
        amount = Decimal(f"{rng.uniform(1.0, 99.0):.2f}")

        attempt = PaymentAttempt(
            transaction_id=txn_id,
            merchant_id=profile.merchant.merchant_id,
            customer_id=profile.sample_customer(rng),
            instrument_fp=inst_fp,
            instrument_meta=inst_meta,
            device_fp=dev,
            ip_fp=ip,
            geo=profile.sample_geo(rng),
            amount=amount,
            currency="INR",
            payment_method=PaymentMethod.CARD,
            is_cod=False,
            attempt_number=1,
            timestamp=current_time,
        )

        # 85-95% failure rate (issuer declines)
        is_failure = rng.random() < 0.90
        if is_failure:
            codes, sources, weights = zip(*ATTACK_DECLINE_CODES)
            idx = rng.choices(range(len(codes)), weights=weights, k=1)[0]
            outcome = PaymentOutcome(
                transaction_id=txn_id,
                status=PaymentStatus.FAILED,
                decline_source=sources[idx],
                failure_code=codes[idx],
                timestamp=current_time + timedelta(seconds=rng.uniform(0.5, 2.0)),
            )
        else:
            outcome = PaymentOutcome(
                transaction_id=txn_id,
                status=PaymentStatus.AUTHORIZED,
                decline_source=DeclineSource.UNKNOWN,
                failure_code=None,
                timestamp=current_time + timedelta(seconds=rng.uniform(0.5, 2.0)),
            )

        txns.append(
            AnnotatedTransaction(
                attempt=attempt,
                outcome=outcome,
                scenario_id="card_testing_burst",
                is_abusive=True,
                is_spike=True,
            )
        )

    return txns


def inject_bin_enumeration_attack(
    profile: MerchantProfile,
    start_time: datetime,
    rng: random.Random,
    intensity: float = 1.0,
) -> list[AnnotatedTransaction]:
    """BIN enumeration attack: systematic probing of consecutive card ranges in 1 BIN."""
    duration_min = rng.randint(10, 30)
    n_attempts = int(max(20, rng.randint(60, 300) * intensity))
    txns: list[AnnotatedTransaction] = []

    # One targeted BIN range
    # Per-episode identities. These were previously global constants derived from fixed
    # strings, so every BIN-enumeration episode in every split shared one device and one
    # BIN — an identity a model could latch onto instead of the behaviour.
    episode_salt = f"{start_time.isoformat()}_{rng.random()}"
    target_bin_hash = f"bin_enum_{stable_hash('target_bin_range_' + episode_salt)[:8]}"
    attacker_dev = f"dv_bot_{stable_hash('botnet_master_' + episode_salt)[:10]}"
    attacker_ip = f"ip_bot_{stable_hash('botnet_ip_' + episode_salt)[:10]}"

    time_step_sec = (duration_min * 60.0) / max(1, n_attempts)
    current_time = start_time

    for i in range(n_attempts):
        current_time += timedelta(seconds=rng.uniform(0.1, time_step_sec * 1.5))
        txn_id = f"txn_bin_{start_time.strftime('%H%M')}_{i:04d}"

        inst_fp = f"if_enum_{target_bin_hash}_{i:04d}"
        inst_meta = InstrumentMeta(
            brand="visa",
            instrument_type=InstrumentType.CREDIT,
            issuer_country="IN",
            bin_hash=target_bin_hash,
            is_on_file=False,
        )

        amount = Decimal(f"{rng.uniform(10.0, 150.0):.2f}")
        attempt = PaymentAttempt(
            transaction_id=txn_id,
            merchant_id=profile.merchant.merchant_id,
            customer_id=profile.sample_customer(rng),
            instrument_fp=inst_fp,
            instrument_meta=inst_meta,
            device_fp=attacker_dev,
            ip_fp=attacker_ip,
            geo=profile.sample_geo(rng),
            amount=amount,
            currency="INR",
            payment_method=PaymentMethod.CARD,
            is_cod=False,
            attempt_number=1,
            timestamp=current_time,
        )

        is_failure = rng.random() < 0.92
        code, source = _sample_decline(rng, CARD_TESTING_DECLINES)
        outcome = PaymentOutcome(
            transaction_id=txn_id,
            status=PaymentStatus.FAILED if is_failure else PaymentStatus.AUTHORIZED,
            decline_source=source if is_failure else DeclineSource.UNKNOWN,
            failure_code=code if is_failure else None,
            timestamp=current_time + timedelta(seconds=1.0),
        )

        txns.append(
            AnnotatedTransaction(
                attempt=attempt,
                outcome=outcome,
                scenario_id="bin_enumeration_attack",
                is_abusive=True,
                is_spike=True,
            )
        )

    return txns


def inject_device_farm_ring(
    profile: MerchantProfile,
    start_time: datetime,
    rng: random.Random,
    intensity: float = 1.0,
) -> list[AnnotatedTransaction]:
    """Device farm / emulator ring: many fresh accounts operating through 2-4 devices."""
    duration_min = rng.randint(15, 45)
    n_attempts = int(max(20, rng.randint(50, 200) * intensity))
    txns: list[AnnotatedTransaction] = []

    episode_salt = stable_hash(f"farm_{start_time.isoformat()}_{rng.random()}")[:8]
    devices = [f"dv_farm_{episode_salt}_{i:02d}" for i in range(rng.randint(2, 4))]
    current_time = start_time
    time_step_sec = (duration_min * 60.0) / max(1, n_attempts)

    for i in range(n_attempts):
        current_time += timedelta(seconds=rng.uniform(0.5, time_step_sec * 1.5))
        txn_id = f"txn_farm_{i:04d}"
        cust_id = f"cus_farm_synth_{i:04d}"  # 100% account novelty
        dev = rng.choice(devices)
        inst_fp = f"if_farm_{i:04d}"
        inst_meta = InstrumentMeta(brand="mastercard", instrument_type=InstrumentType.DEBIT, is_on_file=False)

        attempt = PaymentAttempt(
            transaction_id=txn_id,
            merchant_id=profile.merchant.merchant_id,
            customer_id=cust_id,
            instrument_fp=inst_fp,
            instrument_meta=inst_meta,
            device_fp=dev,
            ip_fp=f"ip_farm_{rng.randint(1, 10)}",
            geo=profile.sample_geo(rng),
            amount=profile.sample_price(rng),
            payment_method=PaymentMethod.CARD,
            timestamp=current_time,
        )
        code, source = _sample_decline(rng, RING_DECLINES)
        outcome = PaymentOutcome(
            transaction_id=txn_id,
            status=PaymentStatus.CAPTURED if rng.random() < 0.60 else PaymentStatus.FAILED,
            decline_source=source,
            failure_code=code,
            timestamp=current_time + timedelta(seconds=1.5),
        )
        txns.append(
            AnnotatedTransaction(
                attempt=attempt, outcome=outcome, scenario_id="device_farm_ring", is_abusive=True, is_spike=True
            )
        )

    return txns


def inject_promo_coupon_harvesting(
    profile: MerchantProfile,
    start_time: datetime,
    rng: random.Random,
    intensity: float = 1.0,
) -> list[AnnotatedTransaction]:
    """Promo abuse: automated single-use discount harvesting."""
    duration_min = rng.randint(10, 30)
    n_attempts = int(max(15, rng.randint(40, 150) * intensity))
    txns: list[AnnotatedTransaction] = []
    coupon_id = "WELCOME500_HARVEST"
    current_time = start_time
    time_step_sec = (duration_min * 60.0) / max(1, n_attempts)

    for i in range(n_attempts):
        current_time += timedelta(seconds=rng.uniform(0.2, time_step_sec * 1.5))
        txn_id = f"txn_promo_{i:04d}"
        cust_id = f"cus_new_promo_{i:04d}"
        inst_fp, inst_meta = profile.sample_instrument(rng)

        attempt = PaymentAttempt(
            transaction_id=txn_id,
            merchant_id=profile.merchant.merchant_id,
            customer_id=cust_id,
            instrument_fp=inst_fp,
            instrument_meta=inst_meta,
            device_fp=f"dv_promo_{i % 3}",
            ip_fp=f"ip_promo_{i % 5}",
            geo=profile.sample_geo(rng),
            # Just above the discount threshold, but jittered: a fixed 501.00 on every
            # attempt drove amount variance and entropy to exactly zero.
            amount=Decimal(f"{rng.uniform(501.0, 585.0):.2f}"),
            coupon_id=coupon_id,
            payment_method=PaymentMethod.UPI,
            timestamp=current_time,
        )
        outcome = PaymentOutcome(
            transaction_id=txn_id,
            status=PaymentStatus.CAPTURED,
            timestamp=current_time + timedelta(seconds=1.0),
        )
        txns.append(
            AnnotatedTransaction(
                attempt=attempt, outcome=outcome, scenario_id="promo_coupon_harvesting", is_abusive=True, is_spike=True
            )
        )

    return txns


# =================================================================================
# HARD NEGATIVES — Legitimate traffic surges (getting these wrong is unacceptable)
# =================================================================================

def inject_flash_sale_spike(
    profile: MerchantProfile,
    start_time: datetime,
    rng: random.Random,
    intensity: float = 1.0,
) -> list[AnnotatedTransaction]:
    """Legitimate flash sale surge: massive volume spike from authentic, independent buyers."""
    duration_min = rng.randint(15, 60)
    # 10x to 30x normal volume
    n_attempts = int(max(50, profile.hourly_baseline_txns * rng.uniform(8.0, 20.0) * (duration_min / 60.0)))
    txns: list[AnnotatedTransaction] = []
    current_time = start_time
    time_step_sec = (duration_min * 60.0) / max(1, n_attempts)

    # Share of the surge that is *returning* buyers, reusing entities the merchant has
    # already seen. A real flash sale is a mix; the previous version gave every buyer a
    # brand-new device, card and IP, producing a perfect 1:1 entity-to-transaction
    # mapping found nowhere in real traffic.
    #
    # That constant was the single largest artifact in this generator. It made
    # `C.devices_per_txn` / `F.device_reuse_rate` separate flash sales from attacks at
    # ~0.997 single-feature AUC — the exact discrimination Veyra claims is hard became
    # trivially easy, because legitimate traffic was defined to sit at one extreme of
    # the feature and attacks at the other. Drawing part of the surge from the
    # merchant's own entity pools (ADR-007) makes device reuse a distribution instead
    # of a constant, so the detector has to use structure rather than read one column.
    returning_share = rng.uniform(0.35, 0.70)

    for i in range(n_attempts):
        current_time += timedelta(seconds=rng.uniform(0.05, time_step_sec * 1.5))
        txn_id = f"txn_sale_{i:05d}"
        order_id = f"ord_sale_{i:05d}"

        if rng.random() < returning_share:
            # Returning buyer: known account, known device, card on file.
            cust_id = profile.sample_customer(rng)
            dev_id = profile.sample_device(rng)
            ip_id = profile.sample_ip(rng)
            inst_fp, inst_meta = profile.sample_instrument(rng)
        else:
            # New buyer acquired by the sale.
            cust_id = f"cus_organic_{i:05d}"
            dev_id = f"dv_organic_{i:05d}"
            ip_id = f"ip_organic_{i:05d}"
            inst_fp = f"if_organic_{i:05d}"
            inst_meta = InstrumentMeta(
                brand=rng.choice(("visa", "mastercard", "rupay")),
                instrument_type=InstrumentType.DEBIT,
            )

        attempt = PaymentAttempt(
            transaction_id=txn_id,
            merchant_id=profile.merchant.merchant_id,
            customer_id=cust_id,
            order_id=order_id,
            instrument_fp=inst_fp,
            instrument_meta=inst_meta,
            device_fp=dev_id,
            ip_fp=ip_id,
            geo=profile.sample_geo(rng),
            amount=profile.sample_price(rng),
            payment_method=profile.sample_payment_method(rng),
            timestamp=current_time,
        )

        # High organic success rate (~92-96%)
        is_failure = rng.random() < 0.05
        outcome = PaymentOutcome(
            transaction_id=txn_id,
            status=PaymentStatus.FAILED if is_failure else PaymentStatus.CAPTURED,
            decline_source=DeclineSource.ISSUER if is_failure else DeclineSource.UNKNOWN,
            failure_code="INSUFFICIENT_FUNDS" if is_failure else None,
            timestamp=current_time + timedelta(seconds=rng.uniform(1.0, 3.0)),
        )

        txns.append(
            AnnotatedTransaction(
                attempt=attempt,
                outcome=outcome,
                scenario_id="flash_sale_spike",
                is_abusive=False,  # Legitimate hard negative!
                is_spike=True,
            )
        )

    return txns


def inject_gateway_retry_storm(
    profile: MerchantProfile,
    start_time: datetime,
    rng: random.Random,
    intensity: float = 1.0,
) -> list[AnnotatedTransaction]:
    """Gateway retry storm: payment aggregator timeout causing customer retry spikes."""
    duration_min = rng.randint(10, 25)
    n_customers = rng.randint(20, 60)
    txns: list[AnnotatedTransaction] = []
    current_time = start_time

    for c in range(n_customers):
        cust_id = profile.sample_customer(rng)
        dev_id = profile.sample_device(rng)
        inst_fp, inst_meta = profile.sample_instrument(rng)
        amount = profile.sample_price(rng)

        # 3 to 6 retry attempts per customer
        n_retries = rng.randint(3, 6)
        c_time = current_time + timedelta(seconds=rng.uniform(0, 300))

        for attempt_no in range(1, n_retries + 1):
            c_time += timedelta(seconds=rng.uniform(5.0, 35.0))
            txn_id = f"txn_retry_{c:03d}_{attempt_no}"
            attempt = PaymentAttempt(
                transaction_id=txn_id,
                merchant_id=profile.merchant.merchant_id,
                customer_id=cust_id,
                instrument_fp=inst_fp,
                instrument_meta=inst_meta,
                device_fp=dev_id,
                ip_fp=profile.sample_ip(rng),
                geo=profile.sample_geo(rng),
                amount=amount,
                payment_method=PaymentMethod.UPI,
                attempt_number=attempt_no,
                timestamp=c_time,
            )

            # Gateway timeout failures on early attempts, success on final attempt
            is_final = attempt_no == n_retries
            outcome = PaymentOutcome(
                transaction_id=txn_id,
                status=PaymentStatus.CAPTURED if is_final else PaymentStatus.FAILED,
                decline_source=DeclineSource.GATEWAY if not is_final else DeclineSource.UNKNOWN,
                failure_code="GATEWAY_TIMEOUT" if not is_final else None,
                timestamp=c_time + timedelta(seconds=2.0),
            )

            txns.append(
                AnnotatedTransaction(
                    attempt=attempt,
                    outcome=outcome,
                    scenario_id="gateway_retry_storm",
                    is_abusive=False,  # Legitimate hard negative!
                    is_spike=True,
                )
            )

    return txns


def inject_subscription_renewal_batch(
    profile: MerchantProfile,
    start_time: datetime,
    rng: random.Random,
    intensity: float = 1.0,
) -> list[AnnotatedTransaction]:
    """Subscription batch: automatic scheduled recurring payments (100% card on file)."""
    n_subscriptions = rng.randint(100, 400)
    txns: list[AnnotatedTransaction] = []
    current_time = start_time
    base = profile.avg_ticket_size
    plan_tiers = [
        (base * Decimal("0.5")).quantize(Decimal("0.01")),
        base.quantize(Decimal("0.01")),
        (base * Decimal("1.8")).quantize(Decimal("0.01")),
        (base * Decimal("3.0")).quantize(Decimal("0.01")),
    ]

    for i in range(n_subscriptions):
        # Dispatched in a tight window of 2-5 minutes
        txn_time = current_time + timedelta(seconds=rng.uniform(0.0, 180.0))
        txn_id = f"txn_sub_{i:04d}"
        cust_id = profile.sample_customer(rng)
        inst_fp, inst_meta = profile.sample_instrument(rng)

        # Card-on-file flag is strictly TRUE for subscription renewals
        on_file_meta = InstrumentMeta(
            brand=inst_meta.brand,
            instrument_type=inst_meta.instrument_type,
            issuer_country=inst_meta.issuer_country,
            bin_hash=inst_meta.bin_hash,
            is_on_file=True,
        )

        attempt = PaymentAttempt(
            transaction_id=txn_id,
            merchant_id=profile.merchant.merchant_id,
            customer_id=cust_id,
            instrument_fp=inst_fp,
            instrument_meta=on_file_meta,
            device_fp=None,  # Server-to-server batch (no browser device)
            ip_fp=None,
            geo=Geo(country="IN"),
            # Plan tiers rather than one price: a single amount for every renewal put
            # amount entropy at exactly 0 for this hard negative too.
            amount=plan_tiers[i % len(plan_tiers)],
            payment_method=PaymentMethod.CARD,
            timestamp=txn_time,
        )
        outcome = PaymentOutcome(
            transaction_id=txn_id,
            status=PaymentStatus.CAPTURED if rng.random() < 0.95 else PaymentStatus.FAILED,
            decline_source=DeclineSource.ISSUER,
            failure_code="INSUFFICIENT_FUNDS",
            timestamp=txn_time + timedelta(seconds=0.5),
        )

        txns.append(
            AnnotatedTransaction(
                attempt=attempt,
                outcome=outcome,
                scenario_id="subscription_renewal_batch",
                is_abusive=False,  # Legitimate hard negative!
                is_spike=True,
            )
        )

    return txns


def inject_ring_under_flash_sale(
    profile: MerchantProfile,
    start_time: datetime,
    rng: random.Random,
    intensity: float = 1.0,
) -> list[AnnotatedTransaction]:
    """E1: Adversarial fraud ring operating underneath genuine flash sale surge."""
    # 1. Benign flash sale background (80% of volume)
    benign_txns = inject_flash_sale_spike(profile, start_time, rng, intensity=intensity)
    # 2. Fraud ring foreground (20% of volume)
    fraud_txns = inject_card_testing_burst(profile, start_time, rng, intensity=intensity * 0.5)
    combined: list[AnnotatedTransaction] = []
    for t in benign_txns + fraud_txns:
        combined.append(
            AnnotatedTransaction(
                attempt=t.attempt,
                outcome=t.outcome,
                refund=t.refund,
                dispute=t.dispute,
                order=t.order,
                scenario_id="ring_under_flash_sale",
                is_abusive=t.is_abusive,
                is_spike=t.is_spike,
            )
        )
    combined.sort(key=lambda t: t.attempt.timestamp)
    return combined


def inject_slow_ramp_infiltration(
    profile: MerchantProfile,
    start_time: datetime,
    rng: random.Random,
    intensity: float = 1.0,
) -> list[AnnotatedTransaction]:
    """E2: Gradual volume increase over 60m designed to evade acceleration triggers."""
    txns: list[AnnotatedTransaction] = []
    duration_min = 60
    # Ramp rate: starts with 1 txn/min, increases linearly to 10 txn/min
    attacker_dev = f"dv_stealth_{rng.randint(100, 999)}"
    attacker_ip = f"ip_stealth_{rng.randint(100, 999)}"

    for minute in range(duration_min):
        n_minute_txns = int(1 + (minute / 6.0) * intensity)
        for i in range(n_minute_txns):
            t_offset = minute * 60 + rng.uniform(0.0, 59.0)
            txn_time = start_time + timedelta(seconds=t_offset)
            txn_id = f"txn_ramp_{minute:02d}_{i:02d}"
            inst_fp, inst_meta = profile.sample_instrument(rng)
            attempt = PaymentAttempt(
                transaction_id=txn_id,
                merchant_id=profile.merchant.merchant_id,
                customer_id=f"cus_ramp_{rng.randint(1, 20)}",
                instrument_fp=inst_fp,
                instrument_meta=inst_meta,
                device_fp=attacker_dev,
                ip_fp=attacker_ip,
                amount=profile.sample_price(rng),
                payment_method=PaymentMethod.CARD,
                timestamp=txn_time,
            )
            code, source = _sample_decline(rng, RING_DECLINES)
            outcome = PaymentOutcome(
                transaction_id=txn_id,
                status=PaymentStatus.CAPTURED if rng.random() < 0.40 else PaymentStatus.FAILED,
                decline_source=source,
                failure_code=code,
                timestamp=txn_time + timedelta(seconds=1.0),
            )
            txns.append(AnnotatedTransaction(attempt=attempt, outcome=outcome, scenario_id="slow_ramp_infiltration", is_abusive=True, is_spike=True))

    return txns


def inject_low_volume_relationship_anomaly(
    profile: MerchantProfile,
    start_time: datetime,
    rng: random.Random,
    intensity: float = 1.0,
) -> list[AnnotatedTransaction]:
    """E4: High graph entity concentration with low volume (sub-volume z-score threshold)."""
    txns: list[AnnotatedTransaction] = []
    n_txns = rng.randint(6, 12)  # Low volume
    shared_device = f"dv_lowvol_{rng.randint(100, 999)}"
    shared_ip = f"ip_lowvol_{rng.randint(100, 999)}"

    for i in range(n_txns):
        txn_time = start_time + timedelta(seconds=rng.uniform(0.0, 300.0))
        txn_id = f"txn_lowvol_{i:02d}"
        inst_fp, inst_meta = profile.sample_instrument(rng)
        attempt = PaymentAttempt(
            transaction_id=txn_id,
            merchant_id=profile.merchant.merchant_id,
            customer_id=f"cus_ring_{i:02d}",
            instrument_fp=inst_fp,
            instrument_meta=inst_meta,
            device_fp=shared_device,
            ip_fp=shared_ip,
            amount=profile.avg_ticket_size,
            payment_method=PaymentMethod.CARD,
            timestamp=txn_time,
        )
        code, source = _sample_decline(rng, RING_DECLINES)
        outcome = PaymentOutcome(
            transaction_id=txn_id,
            status=PaymentStatus.FAILED if rng.random() < 0.70 else PaymentStatus.CAPTURED,
            decline_source=source,
            failure_code=code,
            timestamp=txn_time + timedelta(seconds=1.0),
        )
        txns.append(AnnotatedTransaction(attempt=attempt, outcome=outcome, scenario_id="low_volume_relationship_anomaly", is_abusive=True, is_spike=False))

    return txns


def inject_card_testing_low_value(
    profile: MerchantProfile,
    start_time: datetime,
    rng: random.Random,
    intensity: float = 1.0,
) -> list[AnnotatedTransaction]:
    """E6: Card testing with micro-amounts (₹5–₹45) to evade value checks."""
    txns: list[AnnotatedTransaction] = []
    n_probes = int(rng.randint(25, 60) * intensity)
    dev_fp = f"dv_micro_{rng.randint(100, 999)}"

    for i in range(n_probes):
        txn_time = start_time + timedelta(seconds=rng.uniform(0.0, 300.0))
        txn_id = f"txn_micro_{i:03d}"
        inst_fp, inst_meta = profile.sample_instrument(rng)
        micro_amount = Decimal(f"{rng.uniform(5.0, 45.0):.2f}")
        attempt = PaymentAttempt(
            transaction_id=txn_id,
            merchant_id=profile.merchant.merchant_id,
            customer_id=f"cus_micro_{i:03d}",
            instrument_fp=inst_fp,
            instrument_meta=inst_meta,
            device_fp=dev_fp,
            amount=micro_amount,
            payment_method=PaymentMethod.CARD,
            timestamp=txn_time,
        )
        code, source = _sample_decline(rng, CARD_TESTING_DECLINES)
        outcome = PaymentOutcome(
            transaction_id=txn_id,
            status=PaymentStatus.FAILED if rng.random() < 0.85 else PaymentStatus.CAPTURED,
            decline_source=source,
            failure_code=code,
            timestamp=txn_time + timedelta(seconds=1.0),
        )
        txns.append(AnnotatedTransaction(attempt=attempt, outcome=outcome, scenario_id="card_testing_low_value", is_abusive=True, is_spike=True))

    return txns


# Master registry of scenario injection functions
SCENARIO_RECIPES: dict[str, Callable] = {
    "card_testing_burst": inject_card_testing_burst,
    "bin_enumeration_attack": inject_bin_enumeration_attack,
    "device_farm_ring": inject_device_farm_ring,
    "promo_coupon_harvesting": inject_promo_coupon_harvesting,
    "flash_sale_spike": inject_flash_sale_spike,
    "gateway_retry_storm": inject_gateway_retry_storm,
    "subscription_renewal_batch": inject_subscription_renewal_batch,
    "ring_under_flash_sale": inject_ring_under_flash_sale,
    "slow_ramp_infiltration": inject_slow_ramp_infiltration,
    "low_volume_relationship_anomaly": inject_low_volume_relationship_anomaly,
    "card_testing_low_value": inject_card_testing_low_value,
}

