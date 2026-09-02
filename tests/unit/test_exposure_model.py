"""Unit tests for financial risk exposure calculations (Phase 4.3)."""

from __future__ import annotations

from decimal import Decimal
import pytest

from app.decision.exposure import (
    ASSUMED_CHARGEBACK_FEE_INR,
    ASSUMED_FULFILMENT_COST_INR,
    ASSUMED_SUPPORT_COST_INR,
    compute_incident_exposure,
)


def test_compute_incident_exposure_calculations():
    """Verify exposure model adds direct GMV loss, per-txn operations, and promo leakage."""
    at_risk_gmv = Decimal("100000.00")
    n_txns = 50
    p_loss = 0.80
    promo_exposure = Decimal("5000.00")

    exposure = compute_incident_exposure(
        at_risk_gmv=at_risk_gmv,
        n_txns=n_txns,
        p_loss=p_loss,
        promo_exposure=promo_exposure,
    )

    # Direct fraud = 100,000 * 0.80 = 80,000.00
    assert exposure.direct_fraud_loss == Decimal("80000.00")

    # Operational = 50 * (1500 + 120 + 50) = 50 * 1670 = 83,500.00
    per_txn_cost = ASSUMED_CHARGEBACK_FEE_INR + ASSUMED_FULFILMENT_COST_INR + ASSUMED_SUPPORT_COST_INR
    assert exposure.operational_loss == Decimal(50) * per_txn_cost

    # Total = 80,000 + 83,500 + 5,000 = 168,500.00
    assert exposure.total_exposure == Decimal("80000.00") + (Decimal(50) * per_txn_cost) + Decimal("5000.00")
