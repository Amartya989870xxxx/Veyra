"""Correctness tests for the evaluation window index (Phase 1 performance fix).

The index replaced a linear rescan of the whole transaction dataset per window. A
performance change to the code that decides *which transactions a model may see* is
exactly the kind of change that can silently leak the future, so these tests pin the
semantics rather than just the speed:

- equivalence to the previous linear-filter behaviour on a representative dataset
- the half-open boundary: a transaction at `window_end` must NOT be visible
- merchant isolation: one merchant's transactions never enter another's window
- chronological ordering of the returned slice
- determinism for a fixed seed
"""

from __future__ import annotations

import random
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from app.evaluation.indexing import TransactionWindowIndex
from app.schemas.entities import PaymentAttempt
from app.schemas.enums import PaymentMethod
from app.windows import WindowSize
from data.generators.timeline import AnnotatedTransaction

BASE = datetime(2026, 3, 2, 12, 0, 0, tzinfo=UTC)


def _txn(merchant_id: str, offset_seconds: float, idx: int = 0) -> AnnotatedTransaction:
    ts = BASE + timedelta(seconds=offset_seconds)
    return AnnotatedTransaction(
        attempt=PaymentAttempt(
            transaction_id=f"txn_{merchant_id}_{idx}_{offset_seconds}",
            merchant_id=merchant_id,
            customer_id=f"cus_{idx}",
            instrument_fp=f"if_{idx}",
            device_fp=f"dv_{idx}",
            amount=Decimal("100.00"),
            payment_method=PaymentMethod.CARD,
            timestamp=ts,
        ),
        outcome=None,
        scenario_id="normal_day",
        is_abusive=False,
        is_spike=False,
    )


def _linear_filter(transactions, merchant_id, start, end):
    """The exact pre-optimization implementation, kept here as the oracle."""
    return [
        t
        for t in transactions
        if t.attempt.merchant_id == merchant_id and start <= t.attempt.timestamp < end
    ]


def _representative_dataset(seed: int = 20260827):
    rng = random.Random(seed)
    txns = []
    for merchant_i in range(4):
        merchant_id = f"m_{merchant_i:03d}"
        for i in range(250):
            txns.append(_txn(merchant_id, rng.uniform(0.0, 7200.0), i))
    txns.sort(key=lambda t: t.attempt.timestamp)
    return txns


def test_index_matches_linear_filter_on_representative_dataset():
    """Equivalence: same transactions, same order, for every window across the dataset."""
    txns = _representative_dataset()
    index = TransactionWindowIndex(txns)

    checked_nonempty = 0
    for merchant_i in range(4):
        merchant_id = f"m_{merchant_i:03d}"
        for window_size in (WindowSize.M1, WindowSize.M5, WindowSize.M15, WindowSize.H1):
            for step in range(0, 120, 7):
                w_end = BASE + timedelta(seconds=60 * step)
                w_start = w_end - window_size.delta

                expected = _linear_filter(txns, merchant_id, w_start, w_end)
                actual = index.slice(merchant_id, w_start, w_end)

                assert [t.attempt.transaction_id for t in actual] == [
                    t.attempt.transaction_id for t in expected
                ]
                if expected:
                    checked_nonempty += 1

    assert checked_nonempty > 50, "test data did not exercise enough non-empty windows"


def test_no_transaction_outside_the_window_enters():
    """The half-open boundary [start, end): start is in, end belongs to the next window."""
    w_end = BASE + timedelta(seconds=300)
    w_start = w_end - WindowSize.M5.delta

    on_start = _txn("m_a", (w_start - BASE).total_seconds(), 1)
    inside = _txn("m_a", (w_start - BASE).total_seconds() + 10, 2)
    on_end = _txn("m_a", (w_end - BASE).total_seconds(), 3)
    after_end = _txn("m_a", (w_end - BASE).total_seconds() + 1, 4)
    before_start = _txn("m_a", (w_start - BASE).total_seconds() - 1, 5)

    index = TransactionWindowIndex([before_start, on_start, inside, on_end, after_end])
    got = {t.attempt.transaction_id for t in index.slice("m_a", w_start, w_end)}

    assert on_start.attempt.transaction_id in got
    assert inside.attempt.transaction_id in got
    assert on_end.attempt.transaction_id not in got, "transaction at window_end leaked the future in"
    assert after_end.attempt.transaction_id not in got
    assert before_start.attempt.transaction_id not in got


def test_merchant_isolation_in_window_slices():
    """A merchant's window must never contain another merchant's transactions."""
    w_end = BASE + timedelta(seconds=600)
    w_start = w_end - WindowSize.M15.delta

    mine = [_txn("m_mine", 100 + i, i) for i in range(20)]
    theirs = [_txn("m_theirs", 100 + i, i) for i in range(20)]
    index = TransactionWindowIndex(mine + theirs)

    got = index.slice("m_mine", w_start, w_end)
    assert got, "expected a non-empty slice for this fixture"
    assert all(t.attempt.merchant_id == "m_mine" for t in got)
    assert len(got) == len(mine)

    absent = index.slice("m_unknown_merchant", w_start, w_end)
    assert absent == []


def test_slice_is_chronologically_ordered():
    rng = random.Random(7)
    unsorted_txns = [_txn("m_a", rng.uniform(0, 600), i) for i in range(80)]
    index = TransactionWindowIndex(unsorted_txns)

    got = index.slice("m_a", BASE, BASE + timedelta(seconds=600))
    stamps = [t.attempt.timestamp for t in got]
    assert stamps == sorted(stamps)


def test_index_does_not_mutate_source_collection():
    rng = random.Random(11)
    txns = [_txn("m_a", rng.uniform(0, 600), i) for i in range(50)]
    original_order = [t.attempt.transaction_id for t in txns]

    TransactionWindowIndex(txns)

    assert [t.attempt.transaction_id for t in txns] == original_order


def test_index_is_deterministic_for_fixed_seed():
    a = TransactionWindowIndex(_representative_dataset(seed=99))
    b = TransactionWindowIndex(_representative_dataset(seed=99))
    w_end = BASE + timedelta(seconds=1800)
    for window_size in (WindowSize.M1, WindowSize.M5, WindowSize.H1):
        sl_a = a.slice("m_001", w_end - window_size.delta, w_end)
        sl_b = b.slice("m_001", w_end - window_size.delta, w_end)
        assert [t.attempt.transaction_id for t in sl_a] == [t.attempt.transaction_id for t in sl_b]


def test_empty_dataset_and_empty_windows():
    index = TransactionWindowIndex([])
    assert index.slice("m_a", BASE, BASE + timedelta(seconds=60)) == []
    assert index.merchant_ids == []

    index2 = TransactionWindowIndex([_txn("m_a", 10, 1)])
    far_future = BASE + timedelta(days=30)
    assert index2.slice("m_a", far_future, far_future + timedelta(seconds=60)) == []


@pytest.mark.parametrize("window_size", [WindowSize.M1, WindowSize.M5, WindowSize.M15, WindowSize.H1])
def test_label_lifter_bisect_matches_linear_scan(window_size):
    """The label lifter got the same bisect treatment; verify it lifts identically.

    Compares the optimized lifter against an independent linear recomputation of the
    same rule, so a boundary error in the bisect would show up as a label difference.
    """
    from data.generators.lifting import lift_labels_to_windows

    rng = random.Random(4242)
    txns = []
    for i in range(200):
        t = _txn("m_lift", rng.uniform(0, 3600), i)
        txns.append(
            AnnotatedTransaction(
                attempt=t.attempt,
                outcome=None,
                scenario_id="card_testing_burst" if i % 3 == 0 else "normal_day",
                is_abusive=i % 3 == 0,
                is_spike=i % 3 == 0,
            )
        )
    txns.sort(key=lambda t: t.attempt.timestamp)

    labels = lift_labels_to_windows(txns, merchant_id="m_lift", window_sizes=(window_size,))
    assert labels, "expected lifted labels"

    for lbl in labels:
        w_start = lbl.window_end - window_size.delta
        expected_in_window = [
            t for t in txns if w_start <= t.attempt.timestamp < lbl.window_end
        ]
        assert lbl.total_txns == len(expected_in_window)
        assert lbl.n_abusive == sum(1 for t in expected_in_window if t.is_abusive)
