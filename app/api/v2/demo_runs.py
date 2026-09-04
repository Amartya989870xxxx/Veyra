"""Synthetic data explorer for recent demo runs (Part 2).

Lets a reviewer page through the exact synthetic transaction stream and feature vector
behind a specific `/v2/demo/simulate` verdict, so the number on the Detection page can be
checked against its own inputs rather than taken on trust.

Bounded by construction:

- Only runs still held by `app/serving/demo_run_store.py` are reachable — the last
  `demo_run_store_max_runs` (default 20), each expiring after
  `demo_run_store_ttl_seconds` (default 30 minutes). Nothing is written to the database
  and nothing is written to disk.
- `page_size` is capped at `MAX_PAGE_SIZE`, so no request can pull a whole run in one go.
- A run belonging to another principal reads as 404, never 403 (same reasoning as
  `app/api/v2/incidents.py`).

Identifiers returned here are the generator's own synthetic fingerprints
(`instrument_fp`, `device_fp`, `ip_fp`). Veyra never holds a PAN — `app/schemas/entities.py`
rejects PAN-shaped fingerprints at ingest — so there is no card number to redact here;
`test_no_raw_card_identifiers_are_exposed` pins that.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query

from app.core.auth import AuthenticatedPrincipal, get_current_principal
from app.registry import load_features
from app.schemas.demo import (
    EntityCounts,
    EntitySummary,
    FeatureSummary,
    FeatureValue,
    RunDetail,
    RunLinks,
    RunRetention,
    RunSummary,
    TransactionPage,
    TransactionRow,
)
from app.serving.demo_run_store import DemoRunRecord, get_demo_run_store

router = APIRouter(prefix="/demo/runs", tags=["Demo Data Explorer"])

MAX_PAGE_SIZE = 200
DEFAULT_PAGE_SIZE = 50


def _load_run(run_id: str, principal: AuthenticatedPrincipal) -> DemoRunRecord:
    record = get_demo_run_store().get(run_id, principal)
    if record is None:
        raise HTTPException(
            status_code=404,
            detail=(
                f"Demo run '{run_id}' not found. Runs are held in memory only, bounded to "
                "the most recent runs and expiring after a short TTL — re-run the "
                "simulation to inspect a fresh one."
            ),
        )
    return record


def _entity_counts(record: DemoRunRecord) -> EntityCounts:
    evidence = record.feature_vector.evidence
    return EntityCounts(
        customers=int(evidence.get("B.unique_customers", 0)),
        devices=int(evidence.get("B.unique_devices", 0)),
        instruments=int(evidence.get("B.unique_instruments", 0)),
        ip_addresses=int(evidence.get("B.unique_ips", 0)),
    )


@router.get("/{run_id}/transactions", response_model=TransactionPage)
async def get_run_transactions(
    run_id: str,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE),
    principal: AuthenticatedPrincipal = Depends(get_current_principal),
) -> TransactionPage:
    """One page of the synthetic transactions that produced this run's verdict."""
    record = _load_run(run_id, principal)

    total = len(record.transactions)
    total_pages = max(1, (total + page_size - 1) // page_size)
    start = (page - 1) * page_size
    window = record.transactions[start : start + page_size]

    items = [
        TransactionRow(
            transaction_id=t.attempt.transaction_id,
            timestamp=t.attempt.timestamp,
            merchant_id=t.attempt.merchant_id,
            customer_id=t.attempt.customer_id,
            instrument_token=t.attempt.instrument_fp,
            device_id=t.attempt.device_fp,
            ip_token=t.attempt.ip_fp,
            amount=str(t.attempt.amount),
            currency=t.attempt.currency,
            outcome_status=t.outcome.status.value if t.outcome else None,
            outcome_failure_code=t.outcome.failure_code if t.outcome else None,
            ground_truth_is_abusive=t.is_abusive,
            ground_truth_is_spike=t.is_spike,
            ground_truth_scenario_id=t.scenario_id,
        )
        for t in window
    ]

    return TransactionPage(
        run_id=run_id,
        page=page,
        page_size=page_size,
        total_transactions=total,
        total_pages=total_pages,
        items=items,
    )


@router.get("/{run_id}/features", response_model=FeatureSummary)
async def get_run_features(
    run_id: str,
    principal: AuthenticatedPrincipal = Depends(get_current_principal),
) -> FeatureSummary:
    """The feature vector behind this run, grouped by family, with deviation twins
    attached to the raw feature they belong to."""
    record = _load_run(run_id, principal)
    registry = load_features()
    vector = record.feature_vector

    families: dict[str, list[FeatureValue]] = {}
    for feature_id, value in vector.all_features.items():
        if feature_id.endswith("_dev"):
            continue  # surfaced on its base feature below, not as a row of its own
        spec = registry.get(feature_id)
        if spec is None:
            continue
        families.setdefault(spec.family, []).append(
            FeatureValue(
                feature_id=feature_id,
                family=spec.family,
                value=float(value),
                deviation_mad=(
                    float(vector.all_features[f"{feature_id}_dev"])
                    if f"{feature_id}_dev" in vector.all_features
                    else None
                ),
                is_model_input=spec.is_model_input,
                is_evidence_only=spec.evidence_only,
            )
        )

    for rows in families.values():
        rows.sort(key=lambda r: r.feature_id)

    return FeatureSummary(
        run_id=run_id,
        families=dict(sorted(families.items())),
        model_feature_count=len(vector.model_features),
        evidence_feature_count=len(vector.evidence),
        baseline_confidence=vector.baseline_confidence.value,
    )


@router.get("/{run_id}/summary", response_model=RunSummary)
async def get_run_summary(
    run_id: str,
    principal: AuthenticatedPrincipal = Depends(get_current_principal),
) -> RunSummary:
    """Composition, time range and entity counts for one run's synthetic input."""
    record = _load_run(run_id, principal)
    timestamps = [t.attempt.timestamp for t in record.transactions]
    total = len(record.transactions)

    return RunSummary(
        run_id=run_id,
        scenario_id=record.scenario_id,
        window_size=record.window_size.value,
        window_end=record.window_end,
        total_transactions=total,
        abusive_transactions=record.abusive_count,
        benign_transactions=total - record.abusive_count,
        time_range_start=min(timestamps) if timestamps else record.window_end,
        time_range_end=max(timestamps) if timestamps else record.window_end,
        entity_counts=_entity_counts(record),
        action_tier=record.action_tier,
        risk_score=record.risk_score,
    )


@router.get("/{run_id}/entities", response_model=EntitySummary)
async def get_run_entities(
    run_id: str,
    principal: AuthenticatedPrincipal = Depends(get_current_principal),
) -> EntitySummary:
    """Who appeared in this run's window, and how concentrated the entity graph was.

    Every number here is read off the run's own feature vector — the same evidence
    features the detector saw — rather than recomputed, so the explorer cannot disagree
    with the verdict it is explaining.
    """
    record = _load_run(run_id, principal)
    counts = _entity_counts(record)
    features = record.feature_vector.all_features
    txns = len(record.transactions)

    return EntitySummary(
        run_id=run_id,
        counts=counts,
        total_entities=counts.total,
        transactions=txns,
        instruments_per_customer=(
            round(counts.instruments / counts.customers, 4) if counts.customers else None
        ),
        transactions_per_device=(round(txns / counts.devices, 4) if counts.devices else None),
        largest_cluster_volume_share=(
            round(float(features["J.largest_cluster_vol_share"]), 6)
            if "J.largest_cluster_vol_share" in features
            else None
        ),
        bipartite_gini=(
            round(float(features["J.bipartite_gini"]), 6)
            if "J.bipartite_gini" in features
            else None
        ),
    )


@router.get("/{run_id}", response_model=RunDetail)
async def get_run(
    run_id: str,
    principal: AuthenticatedPrincipal = Depends(get_current_principal),
) -> RunDetail:
    """Run metadata plus pointers to the sub-resources that hold its data."""
    record = _load_run(run_id, principal)
    store = get_demo_run_store()
    timestamps = [t.attempt.timestamp for t in record.transactions]

    return RunDetail(
        run_id=record.run_id,
        created_at=record.created_at,
        scenario_id=record.scenario_id,
        merchant_id=record.merchant_id,
        merchant_category=record.merchant_category,
        window_size=record.window_size.value,
        window_end=record.window_end,
        total_transactions=len(record.transactions),
        abusive_transactions=record.abusive_count,
        scenario_is_labelled_attack=record.is_labelled_attack,
        risk_score=record.risk_score,
        action_tier=record.action_tier,
        entity_counts=_entity_counts(record),
        time_range_start=min(timestamps) if timestamps else record.window_end,
        time_range_end=max(timestamps) if timestamps else record.window_end,
        entity_graph=record.entity_graph_payload,
        links=RunLinks(
            transactions=(
                f"/v2/demo/runs/{run_id}/transactions?page=1&page_size={DEFAULT_PAGE_SIZE}"
            ),
            features=f"/v2/demo/runs/{run_id}/features",
            summary=f"/v2/demo/runs/{run_id}/summary",
            entities=f"/v2/demo/runs/{run_id}/entities",
        ),
        retention=RunRetention(
            max_runs_retained=store.max_runs,
            ttl_seconds=store.ttl_seconds,
        ),
    )
