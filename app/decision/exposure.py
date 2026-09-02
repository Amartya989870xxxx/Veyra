"""Financial exposure model for Veyra v2 (Phase 4.3 & §22, §42).

Quantifies the true business cost of an incident to prioritize analyst queues by economic risk:
    Exposure = [At-Risk GMV * P(Loss)] + [n_txn * (chargeback_fee + fulfilment_cost + support_cost)] + promo_exposure

Every economic constant is labeled ASSUMPTION (§42) and printed next to its value.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

# Economic assumption constants (explicitly labeled ASSUMPTIONS per §42)
ASSUMED_CHARGEBACK_FEE_INR = Decimal("1500.00")   # Acquirer fee on dispute
ASSUMED_FULFILMENT_COST_INR = Decimal("120.00")   # Packaging, shipping, logistics
ASSUMED_SUPPORT_COST_INR = Decimal("50.00")       # Customer support ticket handling


@dataclass(frozen=True, slots=True)
class IncidentExposure:
    at_risk_gmv: Decimal
    p_loss: float
    direct_fraud_loss: Decimal
    operational_loss: Decimal
    promo_exposure: Decimal
    total_exposure: Decimal

    def to_dict(self) -> dict[str, str | float]:
        return {
            "at_risk_gmv": str(self.at_risk_gmv),
            "p_loss": self.p_loss,
            "direct_fraud_loss": str(self.direct_fraud_loss),
            "operational_loss": str(self.operational_loss),
            "promo_exposure": str(self.promo_exposure),
            "total_exposure": str(self.total_exposure),
        }


def compute_incident_exposure(
    at_risk_gmv: Decimal | float,
    n_txns: int,
    p_loss: float = 0.85,
    promo_exposure: Decimal | float = 0.0,
    chargeback_fee: Decimal = ASSUMED_CHARGEBACK_FEE_INR,
    fulfilment_cost: Decimal = ASSUMED_FULFILMENT_COST_INR,
    support_cost: Decimal = ASSUMED_SUPPORT_COST_INR,
) -> IncidentExposure:
    """Compute financial exposure for an incident."""
    gmv = Decimal(str(at_risk_gmv)) if not isinstance(at_risk_gmv, Decimal) else at_risk_gmv
    promo = Decimal(str(promo_exposure)) if not isinstance(promo_exposure, Decimal) else promo_exposure

    direct_fraud = gmv * Decimal(str(p_loss))
    per_txn_overhead = chargeback_fee + fulfilment_cost + support_cost
    operational = Decimal(n_txns) * per_txn_overhead

    total = direct_fraud + operational + promo

    return IncidentExposure(
        at_risk_gmv=gmv,
        p_loss=p_loss,
        direct_fraud_loss=direct_fraud.quantize(Decimal("0.01")),
        operational_loss=operational.quantize(Decimal("0.01")),
        promo_exposure=promo.quantize(Decimal("0.01")),
        total_exposure=total.quantize(Decimal("0.01")),
    )
