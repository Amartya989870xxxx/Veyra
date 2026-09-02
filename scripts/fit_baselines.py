#!/usr/bin/env python3
"""Fit 168-hour median/MAD baselines from a merchant's past traffic and persist them.

This is the offline half of the MAD contract, and the piece that was missing: the
`baseline_store` table, its repository and the `/v2/merchants/{id}/baselines` endpoint
all existed, but nothing ever wrote a row, so online scoring always found an empty store
and every deviation twin silently degraded to its raw feature value.

    past traffic (strictly before --as-of)
            |
            v
    window features  ->  fit median/MAD per (merchant, feature, window_size, hour_of_week)
            |
            v
    freeze: stamp fit_period_start / fit_period_end on every profile
            |
            v
    baseline_store  ->  ScoringService loads and applies unchanged

Temporal rule: only windows ending at or before `--as-of` are consumed. Nothing from the
scoring period can influence the parameters used to score it. Re-run this job
periodically to refresh baselines; each run re-fits from history only and bumps nothing
forward in time on its own.

Usage:
    PYTHONPATH=. python scripts/fit_baselines.py --days 14 [--as-of 2026-03-08T00:00:00Z]
"""

from __future__ import annotations

import argparse
import asyncio
from datetime import UTC, datetime, timedelta

from app.core.db import session_scope
from app.evaluation.indexing import TransactionWindowIndex
from app.features.baselines import baseline_rows_from_engine, fit_baselines_from_window_history
from app.features.engine import FeatureEngine
from app.models.repositories import BaselineStoreRepository, RawEventsRepository
from app.schemas.entities import PaymentAttempt
from app.windows import WindowSize, align_to_grid, grid_points
from decimal import Decimal


async def _load_attempts(session, merchant_id: str, start: datetime, end: datetime):
    rows = await RawEventsRepository.list_events_for_merchant(
        session=session, merchant_id=merchant_id, start_ts=start, end_ts=end
    )
    attempts = []
    for row in rows:
        payload = row.payload or {}
        attempts.append(
            PaymentAttempt(
                transaction_id=payload.get("transaction_id", row.event_id),
                merchant_id=merchant_id,
                customer_id=payload.get("customer_id"),
                instrument_fp=payload.get("instrument_fp", "if_unknown"),
                device_fp=payload.get("device_fp"),
                ip_fp=payload.get("ip_fp"),
                amount=Decimal(str(payload.get("amount", 0.0))),
                currency=payload.get("currency", "INR"),
                timestamp=row.timestamp,
            )
        )
    return attempts


async def fit_and_store(
    merchant_id: str,
    as_of: datetime,
    days: int,
    window_sizes: tuple[WindowSize, ...] = (WindowSize.M5, WindowSize.M15),
) -> int:
    """Fit baselines from `[as_of - days, as_of)` and write them to `baseline_store`."""
    as_of = align_to_grid(as_of)
    history_start = as_of - timedelta(days=days)

    async with session_scope() as session:
        attempts = await _load_attempts(session, merchant_id, history_start, as_of)
        if not attempts:
            print(f"  {merchant_id}: no history in window — nothing to fit")
            return 0

        # Wrap in the same index the evaluation path uses so window slicing semantics
        # (half-open, merchant-scoped) are identical to scoring.
        class _Wrapped:
            def __init__(self, attempt):
                self.attempt = attempt

        index = TransactionWindowIndex([_Wrapped(a) for a in attempts])
        engine = FeatureEngine()

        history_records = []
        for window_size in window_sizes:
            for w_end in grid_points(history_start + window_size.delta, as_of):
                w_txns = index.slice(merchant_id, w_end - window_size.delta, w_end)
                if not w_txns:
                    continue
                vec = engine.extract_window_features(
                    merchant_id=merchant_id,
                    window_size=window_size,
                    window_end=w_end,
                    transactions=[w.attempt for w in w_txns],
                )
                history_records.append(
                    {
                        "merchant_id": merchant_id,
                        "window_size": window_size.value,
                        "window_end": w_end,
                        "features": {k: v for k, v in vec.all_features.items() if not k.endswith("_dev")},
                    }
                )

        if not history_records:
            print(f"  {merchant_id}: no non-empty windows — nothing to fit")
            return 0

        fitted = fit_baselines_from_window_history(history_records)
        rows = baseline_rows_from_engine(fitted)
        for row_kwargs in rows:
            await BaselineStoreRepository.save_baseline(session=session, **row_kwargs)

        print(
            f"  {merchant_id}: fitted {len(rows):,} baseline profiles from "
            f"{len(history_records):,} windows ({history_start.date()} -> {as_of.date()})"
        )
        return len(rows)


async def main_async(args) -> int:
    as_of = (
        datetime.fromisoformat(args.as_of.replace("Z", "+00:00"))
        if args.as_of
        else datetime.now(UTC)
    )

    merchant_ids = [m.strip() for m in args.merchants.split(",") if m.strip()]
    print(f"Fitting baselines as-of {as_of.isoformat()} from {args.days} days of history")
    total = 0
    for merchant_id in merchant_ids:
        total += await fit_and_store(merchant_id, as_of, args.days)
    print(f"total profiles written: {total:,}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--merchants", required=True, help="comma-separated merchant ids")
    parser.add_argument("--days", type=int, default=14, help="days of history to fit on")
    parser.add_argument("--as-of", default=None, help="ISO timestamp; history strictly before this")
    args = parser.parse_args()
    return asyncio.run(main_async(args))


if __name__ == "__main__":
    raise SystemExit(main())
