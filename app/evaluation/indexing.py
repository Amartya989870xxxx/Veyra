"""Merchant/time index for window feature extraction (evaluation performance).

The evaluation runner and the label lifter both need the same thing thousands of times:
"give me this merchant's transactions inside ``[start, end)``". Both previously answered
it by scanning the *entire* dataset once per window, which is
``O(n_windows x n_transactions)`` — for a 3-merchant/4-day run that is ~69,000 windows
against tens of thousands of transactions, and it is why larger experiments were not
runnable at all.

This module answers the same question in ``O(log n + k)`` per window by grouping once by
merchant and binary-searching a sorted timestamp list.

**The half-open rule is the whole point.** ``bisect_left`` on both bounds reproduces
``start <= ts < end`` exactly: the left bound admits a transaction landing precisely on
``start``, the right bound excludes one landing precisely on ``end``, which is the
past-only barrier from ``app/windows.py`` expressed as slice arithmetic. Getting the
right bound wrong (``bisect_right``) would silently pull one future instant into every
window — no error, just quietly leaked features.
"""

from __future__ import annotations

from bisect import bisect_left
from collections import defaultdict
from datetime import datetime
from typing import Sequence

from data.generators.timeline import AnnotatedTransaction


class TransactionWindowIndex:
    """Immutable (merchant_id, time-range) index over a transaction collection.

    Does not mutate or take ownership of the source sequence: transactions are grouped
    into new lists and the originals are never reordered in place.
    """

    __slots__ = ("_by_merchant", "_timestamps")

    def __init__(self, transactions: Sequence[AnnotatedTransaction]) -> None:
        grouped: dict[str, list[AnnotatedTransaction]] = defaultdict(list)
        for txn in transactions:
            grouped[txn.attempt.merchant_id].append(txn)

        self._by_merchant: dict[str, list[AnnotatedTransaction]] = {}
        self._timestamps: dict[str, list[datetime]] = {}
        for merchant_id, items in grouped.items():
            # Stable sort: for an already chronological source (which is what the
            # pipeline produces) this preserves the exact order the previous linear
            # filter returned, so feature inputs are unchanged, not merely equivalent.
            ordered = sorted(items, key=lambda t: t.attempt.timestamp)
            self._by_merchant[merchant_id] = ordered
            self._timestamps[merchant_id] = [t.attempt.timestamp for t in ordered]

    def slice(
        self,
        merchant_id: str,
        start: datetime,
        end: datetime,
    ) -> list[AnnotatedTransaction]:
        """Transactions for ``merchant_id`` with ``start <= timestamp < end``."""
        ordered = self._by_merchant.get(merchant_id)
        if not ordered:
            return []

        stamps = self._timestamps[merchant_id]
        lo = bisect_left(stamps, start)
        hi = bisect_left(stamps, end)  # strict upper bound — never bisect_right here
        return ordered[lo:hi]

    @property
    def merchant_ids(self) -> list[str]:
        return sorted(self._by_merchant.keys())

    def count_for_merchant(self, merchant_id: str) -> int:
        return len(self._by_merchant.get(merchant_id, ()))
