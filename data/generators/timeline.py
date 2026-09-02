"""Normal background timeline simulation for Veyra v2 (Phase 2.1).

Simulates continuous organic merchant transaction streams driven by:
- 168-hour weekly seasonality (hour of week diurnal patterns and weekend factors)
- Non-homogeneous Poisson arrival processes with continuous exponential inter-arrival times
- Realistic organic success/failure outcomes, decline codes, and refund latencies
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Iterator

from app.schemas.entities import (
    Dispute,
    Geo,
    InstrumentMeta,
    OrderOutcome,
    PaymentAttempt,
    PaymentOutcome,
    Refund,
)
from data.generators.population import MerchantProfile
from app.schemas.enums import (
    DeclineSource,
    DisputeType,
    OrderStatus,
    PaymentMethod,
    PaymentStatus,
    RefundReason,
)

# 24-hour diurnal multipliers (midnight to 23:00)
DIURNAL_24H = (
    0.20, 0.12, 0.08, 0.05, 0.05, 0.08,  # 00:00 - 05:00 (trough)
    0.20, 0.45, 0.75, 1.05, 1.25, 1.35,  # 06:00 - 11:00 (morning ramp)
    1.40, 1.30, 1.20, 1.15, 1.10, 1.20,  # 12:00 - 17:00 (afternoon)
    1.45, 1.60, 1.70, 1.50, 1.10, 0.55,  # 18:00 - 23:00 (evening peak)
)

# Day of week multipliers: Monday (0) to Sunday (6)
DOW_MULTIPLIERS = (0.95, 0.98, 1.00, 1.02, 1.15, 1.25, 1.20)

ORGANIC_FAILURE_CODES = (
    ("INSUFFICIENT_FUNDS", DeclineSource.ISSUER, 0.45),
    ("INCORRECT_OTP", DeclineSource.ISSUER, 0.25),
    ("DO_NOT_HONOR", DeclineSource.ISSUER, 0.15),
    ("NETWORK_TIMEOUT", DeclineSource.GATEWAY, 0.10),
    ("ISSUER_UNAVAILABLE", DeclineSource.NETWORK, 0.05),
)


@dataclass(slots=True)
class AnnotatedTransaction:
    """One transaction emitted by the generator with ground-truth attribution."""

    attempt: PaymentAttempt
    outcome: PaymentOutcome
    refund: Refund | None = None
    dispute: Dispute | None = None
    order: OrderOutcome | None = None

    scenario_id: str = "normal_day"
    is_abusive: bool = False
    is_spike: bool = False


def hour_of_week_rate_multiplier(ts: datetime) -> float:
    """Compute seasonal rate multiplier for a timestamp in [0, 167] hour of week."""
    dow = ts.weekday()  # 0 = Monday, 6 = Sunday
    hour = ts.hour
    return DIURNAL_24H[hour] * DOW_MULTIPLIERS[dow]


def generate_organic_timeline(
    profile: MerchantProfile,
    start_time: datetime,
    duration: timedelta,
    seed: int = 42,
) -> list[AnnotatedTransaction]:
    """Generate a continuous timeline of normal organic transactions for a merchant."""
    rng = random.Random(seed)
    end_time = start_time + duration
    current_time = start_time

    transactions: list[AnnotatedTransaction] = []
    base_rate_per_sec = profile.hourly_baseline_txns / 3600.0
    # Rolling buffer of recently-seen (customer, device, ip, instrument) bundles,
    # so organic traffic can legitimately repeat an entity within a window.
    recent_entities: list[tuple] = []

    while current_time < end_time:
        rate_multiplier = hour_of_week_rate_multiplier(current_time)
        effective_rate = max(0.001, base_rate_per_sec * rate_multiplier)

        # Exponential inter-arrival time in seconds
        inter_arrival_sec = rng.expovariate(effective_rate)
        current_time += timedelta(seconds=inter_arrival_sec)
        if current_time >= end_time:
            break

        txn_id = f"txn_{profile.merchant.merchant_id}_{len(transactions)+1:06d}"
        order_id = f"ord_{profile.merchant.merchant_id}_{len(transactions)+1:06d}"

        # Sample entities from merchant's organic pool.
        #
        # A share of organic traffic reuses an entity bundle seen in the last few
        # minutes: the same shopper retrying a declined card or checking out a second
        # item, a household or office sharing a device behind one NAT address. Without
        # this, no legitimate window ever repeats a device, and `C.devices_per_txn` sits
        # at exactly 1.0 for over half of all legitimate windows while attacks sit near
        # 0.2 — a near-degenerate split that let a single feature separate fraud from
        # flash sales at ~0.997 AUC. Real legitimate traffic has a device-sharing tail;
        # its absence made the hard problem easy for reasons that would not survive
        # contact with production data.
        recent_bundle = None
        if recent_entities and rng.random() < 0.22:
            recent_bundle = recent_entities[-rng.randint(1, min(6, len(recent_entities)))]

        if recent_bundle is not None:
            cust_id, dev_id, ip_id, inst_fp, inst_meta = recent_bundle
        else:
            cust_id = profile.sample_customer(rng)
            dev_id = profile.sample_device(rng)
            ip_id = profile.sample_ip(rng)
            inst_fp, inst_meta = profile.sample_instrument(rng)
            recent_entities.append((cust_id, dev_id, ip_id, inst_fp, inst_meta))
            if len(recent_entities) > 40:
                recent_entities.pop(0)
        geo = profile.sample_geo(rng)
        method = profile.sample_payment_method(rng)
        amount = profile.sample_price(rng)

        is_cod = method == PaymentMethod.COD

        attempt = PaymentAttempt(
            transaction_id=txn_id,
            merchant_id=profile.merchant.merchant_id,
            customer_id=cust_id,
            order_id=order_id,
            instrument_fp=inst_fp,
            instrument_meta=inst_meta,
            device_fp=dev_id,
            ip_fp=ip_id,
            geo=geo,
            amount=amount,
            currency="INR",
            payment_method=method,
            is_cod=is_cod,
            attempt_number=1,
            timestamp=current_time,
        )

        # Organic payment outcome
        is_failure = rng.random() < profile.organic_decline_rate
        if is_failure:
            codes, sources, weights = zip(*ORGANIC_FAILURE_CODES)
            chosen_idx = rng.choices(range(len(codes)), weights=weights, k=1)[0]
            outcome = PaymentOutcome(
                transaction_id=txn_id,
                status=PaymentStatus.FAILED,
                decline_source=sources[chosen_idx],
                failure_code=codes[chosen_idx],
                timestamp=current_time + timedelta(seconds=rng.uniform(1.0, 5.0)),
            )
            order = None
            refund = None
            dispute = None
        else:
            outcome = PaymentOutcome(
                transaction_id=txn_id,
                status=PaymentStatus.CAPTURED,
                decline_source=DeclineSource.UNKNOWN,
                failure_code=None,
                timestamp=current_time + timedelta(seconds=rng.uniform(1.0, 4.0)),
            )

            # Order outcome
            order = OrderOutcome(
                order_id=order_id,
                merchant_id=profile.merchant.merchant_id,
                status=OrderStatus.DELIVERED,
                timestamp=current_time + timedelta(days=rng.uniform(1.0, 4.0)),
            )

            # Rare organic refund (~0.8%)
            if rng.random() < 0.008:
                refund = Refund(
                    refund_id=f"ref_{txn_id}",
                    transaction_id=txn_id,
                    amount=amount,
                    reason_code=RefundReason.CUSTOMER_REQUEST,
                    timestamp=current_time + timedelta(hours=rng.uniform(2.0, 48.0)),
                )
            else:
                refund = None

            # Extremely rare organic dispute (~0.05%)
            if rng.random() < 0.0005:
                dispute = Dispute(
                    dispute_id=f"dsp_{txn_id}",
                    transaction_id=txn_id,
                    dispute_type=DisputeType.FRAUD,
                    amount=amount,
                    days_after_transaction=rng.randint(14, 45),
                    timestamp=current_time + timedelta(days=rng.randint(14, 45)),
                )
            else:
                dispute = None

        transactions.append(
            AnnotatedTransaction(
                attempt=attempt,
                outcome=outcome,
                refund=refund,
                dispute=dispute,
                order=order,
                scenario_id="normal_day",
                is_abusive=False,
                is_spike=False,
            )
        )

    return transactions
