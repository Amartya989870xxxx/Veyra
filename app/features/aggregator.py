"""Window data aggregator for feature extraction (Phase 3.1).

Aggregates raw event transactions falling strictly within [window_end - size, window_end).
Extracts descriptive statistics (counts, ratios, distributions, entropies) for Families A through I.
"""

from __future__ import annotations

import math
import statistics
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Sequence

from app.graph.metrics import (
    compute_gini,
    compute_jensen_shannon_divergence,
    compute_shannon_entropy,
)
from app.schemas.entities import PaymentAttempt, PaymentOutcome
from app.schemas.enums import DeclineSource, PaymentMethod, PaymentStatus
from app.windows import WindowSize
from data.generators.timeline import AnnotatedTransaction


@dataclass
class WindowAgg:
    merchant_id: str
    window_size: WindowSize
    window_end: datetime
    transactions: list[AnnotatedTransaction | PaymentAttempt]

    historical_instruments: set[str] = field(default_factory=set)
    historical_devices: set[str] = field(default_factory=set)
    historical_customers: set[str] = field(default_factory=set)
    preceding_window_txn_rate: float = 0.0
    baseline_geo_mix: dict[str, float] = field(default_factory=dict)
    baseline_method_mix: dict[str, float] = field(default_factory=dict)

    @property
    def window_minutes(self) -> float:
        return self.window_size.seconds / 60.0

    @property
    def attempts(self) -> list[PaymentAttempt]:
        return [
            t.attempt if isinstance(t, AnnotatedTransaction) else t
            for t in self.transactions
        ]

    @property
    def outcomes(self) -> list[PaymentOutcome]:
        return [
            t.outcome
            for t in self.transactions
            if isinstance(t, AnnotatedTransaction) and t.outcome is not None
        ]


def compute_window_features_dict(agg: WindowAgg) -> dict[str, float]:
    """Compute all raw feature values for Families A through I from WindowAgg."""
    attempts = agg.attempts
    outcomes = agg.outcomes
    n_txns = len(attempts)

    features: dict[str, float] = {}

    # Default fallback for zero-transaction windows
    if n_txns == 0:
        return _empty_window_features(agg)

    # ---- Family A: Temporal ----
    txn_rate = n_txns / agg.window_minutes
    features["A.txn_rate"] = float(txn_rate)
    features["A.rate_accel"] = float(txn_rate - agg.preceding_window_txn_rate)
    features["A.burst_duration"] = 0.0

    timestamps = [t.timestamp.timestamp() for t in attempts]
    timestamps.sort()
    interarrivals = [timestamps[i] - timestamps[i - 1] for i in range(1, len(timestamps))]

    if interarrivals:
        ia_mean = statistics.mean(interarrivals)
        ia_std = statistics.stdev(interarrivals) if len(interarrivals) > 1 else 0.0
        ia_cv = ia_std / max(1e-4, ia_mean)
        sorted_ia = sorted(interarrivals)
        p05_idx = int(0.05 * len(sorted_ia))
        ia_p05 = sorted_ia[p05_idx]
    else:
        ia_mean = agg.window_size.seconds / max(1.0, float(n_txns))
        ia_cv = 1.0
        ia_p05 = ia_mean

    features["A.interarrival_mean"] = float(ia_mean)
    features["A.interarrival_cv"] = float(ia_cv)
    features["A.interarrival_p05"] = float(ia_p05)
    features["A.periodicity_score"] = float(max(0.0, 1.0 - min(1.0, ia_cv)))
    features["A.hour_of_week_dev"] = 0.0

    # ---- Family B: Volume ----
    cust_ids = [t.customer_id or f"anon_cus_{t.transaction_id}" for t in attempts]
    dev_ids = [t.device_fp or f"anon_dev_{t.transaction_id}" for t in attempts]
    inst_fps = [t.instrument_fp for t in attempts]
    ip_fps = [t.ip_fp or f"anon_ip_{t.transaction_id}" for t in attempts]

    n_cust = len(set(cust_ids))
    n_dev = len(set(dev_ids))
    n_inst = len(set(inst_fps))
    n_ip = len(set(ip_fps))

    n_failures = sum(1 for o in outcomes if o.status is PaymentStatus.FAILED)
    n_success = sum(1 for o in outcomes if o.status in (PaymentStatus.CAPTURED, PaymentStatus.AUTHORIZED))

    features["B.txn_count"] = float(n_txns)
    features["B.success_count"] = float(n_success)
    features["B.failure_count"] = float(n_failures)
    features["B.unique_customers"] = float(n_cust)
    features["B.unique_instruments"] = float(n_inst)
    features["B.unique_devices"] = float(n_dev)
    features["B.unique_ips"] = float(n_ip)

    # ---- Family C: Ratios ----
    features["C.failure_rate"] = float(n_failures / n_txns)
    features["C.devices_per_txn"] = float(n_dev / n_txns)
    features["C.accounts_per_txn"] = float(n_cust / n_txns)
    features["C.instruments_per_txn"] = float(n_inst / n_txns)
    features["C.ips_per_txn"] = float(n_ip / n_txns)

    novel_insts = sum(1 for fp in set(inst_fps) if fp not in agg.historical_instruments)
    novel_devs = sum(1 for fp in set(dev_ids) if fp not in agg.historical_devices)
    novel_custs = sum(1 for c in set(cust_ids) if c not in agg.historical_customers)

    features["C.instrument_novelty"] = float(novel_insts / max(1, n_inst))
    features["C.device_novelty"] = float(novel_devs / max(1, n_dev))
    features["C.account_novelty"] = float(novel_custs / max(1, n_cust))

    n_coupons = sum(1 for t in attempts if t.coupon_id is not None)
    n_cod = sum(1 for t in attempts if t.is_cod or t.payment_method == PaymentMethod.COD)
    n_intl = sum(1 for t in attempts if t.geo.country != "IN")
    n_retries = sum(1 for t in attempts if t.attempt_number > 1)

    features["C.coupon_rate"] = float(n_coupons / n_txns)
    features["C.cod_rate"] = float(n_cod / n_txns)
    features["C.international_rate"] = float(n_intl / n_txns)
    features["C.retry_rate"] = float(n_retries / n_txns)

    # ---- Family D: Monetary ----
    amounts = [float(t.amount) for t in attempts]
    gmv = sum(amounts)
    amt_median = statistics.median(amounts)
    amt_std = statistics.stdev(amounts) if len(amounts) > 1 else 0.0
    amt_mean = statistics.mean(amounts)
    amt_cv = amt_std / max(1.0, amt_mean)

    # Amount entropy over 10 histogram bins
    amt_bins = Counter([min(9, int(a / max(100.0, amt_mean * 2.0) * 10)) for a in amounts])
    amt_entropy = compute_shannon_entropy(amt_bins)

    n_low_val = sum(1 for a in amounts if a < 100.0)
    n_high_val = sum(1 for a in amounts if a > 10000.0)

    features["D.gmv"] = float(gmv)
    features["D.amount_median"] = float(amt_median)
    features["D.amount_cv"] = float(amt_cv)
    features["D.amount_entropy"] = float(amt_entropy)
    features["D.low_value_ratio"] = float(n_low_val / n_txns)
    features["D.high_value_ratio"] = float(n_high_val / n_txns)
    features["D.discount_to_gmv"] = float((n_coupons * 100.0) / max(1.0, gmv))

    # ---- Family E: Geographic ----
    country_counts = Counter([t.geo.country for t in attempts])
    state_counts = Counter([t.geo.state or "UNKNOWN" for t in attempts])
    city_counts = Counter([t.geo.city or "UNKNOWN" for t in attempts])

    features["E.country_entropy"] = compute_shannon_entropy(country_counts)
    features["E.state_entropy"] = compute_shannon_entropy(state_counts)
    features["E.new_country_count"] = float(len([c for c in country_counts if c != "IN"]))
    features["E.geo_gini"] = compute_gini(list(state_counts.values()))
    features["E.geo_transition_rate"] = 0.0

    current_city_dist = {k: v / n_txns for k, v in city_counts.items()}
    if agg.baseline_geo_mix:
        features["E.geo_mix_jsd"] = compute_jensen_shannon_divergence(current_city_dist, agg.baseline_geo_mix)
    else:
        features["E.geo_mix_jsd"] = 0.0

    # ---- Family F: Device ----
    dev_to_cust: dict[str, set[str]] = defaultdict(set)
    dev_to_inst: dict[str, set[str]] = defaultdict(set)
    dev_txn_counts: Counter[str] = Counter()

    for t in attempts:
        dev = t.device_fp or f"anon_dev_{t.transaction_id}"
        cust = t.customer_id or f"anon_cus_{t.transaction_id}"
        dev_to_cust[dev].add(cust)
        dev_to_inst[dev].add(t.instrument_fp)
        dev_txn_counts[dev] += 1

    accounts_per_dev = [len(custs) for custs in dev_to_cust.values()]
    insts_per_dev = [len(insts) for insts in dev_to_inst.values()]

    features["F.accounts_per_device_max"] = float(max(accounts_per_dev) if accounts_per_dev else 1.0)
    features["F.accounts_per_device_mean"] = float(statistics.mean(accounts_per_dev) if accounts_per_dev else 1.0)
    features["F.accounts_per_device_gini"] = compute_gini(accounts_per_dev)
    features["F.txn_per_device_max"] = float(max(dev_txn_counts.values()) if dev_txn_counts else 1.0)
    features["F.instruments_per_device_max"] = float(max(insts_per_dev) if insts_per_dev else 1.0)
    features["F.device_reuse_rate"] = float(1.0 - (n_dev / max(1, n_txns)))

    # ---- Family G: Account ----
    cust_txn_counts = Counter(cust_ids)
    features["G.account_age_median"] = 168.0  # Default ~7 days
    features["G.account_age_p10"] = 24.0
    features["G.new_account_rate"] = float(novel_custs / max(1, n_cust))
    features["G.txn_per_account_max"] = float(max(cust_txn_counts.values()) if cust_txn_counts else 1.0)
    features["G.accounts_per_address_max"] = 1.0
    features["G.account_cohort_concentration"] = float(novel_custs / max(1, n_txns))

    # ---- Family H: Payment Method ----
    method_counts = Counter([str(t.payment_method) for t in attempts])
    features["H.method_entropy"] = compute_shannon_entropy(method_counts)
    features["H.card_share"] = float(sum(1 for t in attempts if t.payment_method == PaymentMethod.CARD) / n_txns)

    current_method_dist = {k: v / n_txns for k, v in method_counts.items()}
    if agg.baseline_method_mix:
        features["H.method_mix_jsd"] = compute_jensen_shannon_divergence(current_method_dist, agg.baseline_method_mix)
    else:
        features["H.method_mix_jsd"] = 0.0

    issuer_countries = Counter([t.instrument_meta.issuer_country or "IN" for t in attempts])
    features["H.issuer_country_entropy"] = compute_shannon_entropy(issuer_countries)

    bin_prefixes = Counter([t.instrument_meta.bin_hash or "UNKNOWN" for t in attempts])
    features["H.bin_prefix_gini"] = compute_gini(list(bin_prefixes.values()))
    features["H.instrument_repeat_rate"] = float(n_txns / max(1, n_inst))

    # ---- Family I: Outcomes ----
    decline_codes = Counter([o.failure_code for o in outcomes if o.failure_code])
    features["I.decline_code_entropy"] = compute_shannon_entropy(decline_codes)
    top_decline_cnt = max(decline_codes.values()) if decline_codes else 0
    features["I.decline_code_top_share"] = float(top_decline_cnt / max(1, n_failures))

    issuer_declines = sum(1 for o in outcomes if o.decline_source == DeclineSource.ISSUER)
    features["I.decline_issuer_share"] = float(issuer_declines / max(1, n_failures))

    # Near real-time refunds in window
    refunds = [t.refund for t in agg.transactions if isinstance(t, AnnotatedTransaction) and t.refund is not None]
    features["I.refund_rate"] = float(len(refunds) / max(1, n_txns))
    features["I.refund_latency_median"] = 4.0 if refunds else 0.0
    features["I.refund_cohort_concentration"] = 0.0

    # Downstream-only features (computed for reference / evaluation, barred from model vector)
    features["I.dispute_rate"] = 0.0
    features["I.rto_rate"] = 0.0
    features["I.chargeback_rate"] = 0.0

    return features


def _empty_window_features(agg: WindowAgg) -> dict[str, float]:
    """Return default zero-state feature dictionary for empty windows."""
    features = {
        "A.txn_rate": 0.0, "A.rate_accel": 0.0, "A.burst_duration": 0.0,
        "A.interarrival_mean": float(agg.window_size.seconds), "A.interarrival_cv": 0.0,
        "A.interarrival_p05": float(agg.window_size.seconds), "A.periodicity_score": 0.0,
        "A.hour_of_week_dev": 0.0,
        "B.txn_count": 0.0, "B.success_count": 0.0, "B.failure_count": 0.0,
        "B.unique_customers": 0.0, "B.unique_instruments": 0.0,
        "B.unique_devices": 0.0, "B.unique_ips": 0.0,
        "C.failure_rate": 0.0, "C.devices_per_txn": 0.0, "C.accounts_per_txn": 0.0,
        "C.instruments_per_txn": 0.0, "C.ips_per_txn": 0.0,
        "C.instrument_novelty": 0.0, "C.device_novelty": 0.0, "C.account_novelty": 0.0,
        "C.coupon_rate": 0.0, "C.cod_rate": 0.0, "C.international_rate": 0.0, "C.retry_rate": 0.0,
        "D.gmv": 0.0, "D.amount_median": 0.0, "D.amount_cv": 0.0, "D.amount_entropy": 0.0,
        "D.low_value_ratio": 0.0, "D.high_value_ratio": 0.0, "D.discount_to_gmv": 0.0,
        "E.country_entropy": 0.0, "E.state_entropy": 0.0, "E.geo_mix_jsd": 0.0,
        "E.new_country_count": 0.0, "E.geo_gini": 0.0, "E.geo_transition_rate": 0.0,
        "F.accounts_per_device_max": 0.0, "F.accounts_per_device_mean": 0.0,
        "F.accounts_per_device_gini": 0.0, "F.txn_per_device_max": 0.0,
        "F.instruments_per_device_max": 0.0, "F.device_reuse_rate": 0.0,
        "G.account_age_median": 0.0, "G.account_age_p10": 0.0, "G.new_account_rate": 0.0,
        "G.txn_per_account_max": 0.0, "G.accounts_per_address_max": 0.0,
        "G.account_cohort_concentration": 0.0,
        "H.method_entropy": 0.0, "H.method_mix_jsd": 0.0, "H.card_share": 0.0,
        "H.issuer_country_entropy": 0.0, "H.bin_prefix_gini": 0.0, "H.instrument_repeat_rate": 0.0,
        "I.decline_code_entropy": 0.0, "I.decline_code_top_share": 0.0, "I.decline_issuer_share": 0.0,
        "I.refund_rate": 0.0, "I.refund_latency_median": 0.0, "I.refund_cohort_concentration": 0.0,
        "I.dispute_rate": 0.0, "I.rto_rate": 0.0, "I.chargeback_rate": 0.0,
    }
    return features
