"""Dataset loading and leakage-safe splitting.

The split is **by group, never by transaction**. A group is one generated episode: a
household, a flash sale, a device farm. Splitting individual transactions would put the
same device farm on both sides of the wall and every detector would look brilliant.

Groups are additionally stratified by ``(label_class, scenario)`` so each split gets a
spread of every scenario type. With ~30 campaigns in the default dataset, an unstratified
split can easily hand the holdout two campaign types and none of the others.
"""

from __future__ import annotations

import json
import random
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from app.schemas.enums import SplitName

TRAIN_FRACTION = 0.70
VALIDATION_FRACTION = 0.15
HOLDOUT_FRACTION = 0.15


@dataclass
class TxnRecord:
    """One benchmark transaction plus its ground-truth labels."""

    transaction_id: str
    merchant_id: str
    customer_id: str
    agent_id: str | None
    session_id: str | None
    delegation_id: str | None
    amount: float
    currency: str
    merchant_category: str
    sku_id: str | None
    quantity: int
    coupon_id: str | None
    coupon_value: float
    device_id: str
    network_fingerprint: str
    payment_method: str
    instrument_fingerprint: str
    retry_count: int
    status: str
    actor_type: str
    timestamp: datetime
    label_class: str
    is_abusive: bool
    scenario: str
    group_id: str
    campaign_id: str | None
    hard_negative: bool

    @classmethod
    def from_json(cls, raw: dict) -> TxnRecord:
        return cls(
            **{**raw, "timestamp": datetime.fromisoformat(raw["timestamp"])}
        )


@dataclass
class ActionRecord:
    action_id: str
    agent_id: str
    session_id: str
    sequence_number: int
    action_type: str
    tool_name: str | None
    timestamp: datetime
    merchant_id: str | None
    sku_id: str | None


@dataclass
class SessionRecord:
    session_id: str
    customer_id: str
    agent_id: str | None
    actor_type: str
    device_id: str
    network_fingerprint: str
    started_at: datetime
    ended_at: datetime | None


@dataclass
class DelegationRecord:
    delegation_id: str
    customer_id: str
    agent_id: str
    purpose: str
    max_amount: float
    currency: str
    allowed_categories: list[str]
    forbidden_categories: list[str]
    allowed_merchants: list[str]
    merchant_policy: str
    approval_required_above: float | None
    issued_at: datetime
    expires_at: datetime


@dataclass
class Dataset:
    dataset_id: str
    manifest: dict
    transactions: list[TxnRecord]
    actions_by_session: dict[str, list[ActionRecord]] = field(default_factory=dict)
    sessions: dict[str, SessionRecord] = field(default_factory=dict)
    delegations: dict[str, DelegationRecord] = field(default_factory=dict)
    path: Path | None = None

    def __post_init__(self) -> None:
        self.transactions.sort(key=lambda t: t.timestamp)

    @property
    def groups(self) -> list[str]:
        return sorted({t.group_id for t in self.transactions})

    def by_group(self) -> dict[str, list[TxnRecord]]:
        out: dict[str, list[TxnRecord]] = defaultdict(list)
        for t in self.transactions:
            out[t.group_id].append(t)
        return dict(out)

    def subset(self, transactions: list[TxnRecord]) -> Dataset:
        """A view over a subset of transactions that keeps all side tables intact.

        Side tables stay whole on purpose: at scoring time a detector is allowed to see the
        action trace of the transaction it is scoring. Ground-truth labels are what must not
        cross the split, and those live on the transaction.
        """
        return Dataset(
            dataset_id=self.dataset_id,
            manifest=self.manifest,
            transactions=list(transactions),
            actions_by_session=self.actions_by_session,
            sessions=self.sessions,
            delegations=self.delegations,
            path=self.path,
        )


def _iter_jsonl(path: Path):
    with path.open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                yield json.loads(line)


def _dt(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value) if value else None


def load_dataset(path: str | Path) -> Dataset:
    root = Path(path)
    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))

    transactions = [TxnRecord.from_json(raw) for raw in _iter_jsonl(root / "transactions.jsonl")]

    actions_by_session: dict[str, list[ActionRecord]] = defaultdict(list)
    for raw in _iter_jsonl(root / "actions.jsonl"):
        record = ActionRecord(**{**raw, "timestamp": _dt(raw["timestamp"])})
        actions_by_session[record.session_id].append(record)
    for series in actions_by_session.values():
        series.sort(key=lambda a: (a.sequence_number, a.timestamp))

    sessions = {}
    for raw in _iter_jsonl(root / "sessions.jsonl"):
        record = SessionRecord(
            **{**raw, "started_at": _dt(raw["started_at"]), "ended_at": _dt(raw["ended_at"])}
        )
        sessions[record.session_id] = record

    delegations = {}
    for raw in _iter_jsonl(root / "delegations.jsonl"):
        record = DelegationRecord(
            **{**raw, "issued_at": _dt(raw["issued_at"]), "expires_at": _dt(raw["expires_at"])}
        )
        delegations[record.delegation_id] = record

    return Dataset(
        dataset_id=manifest["dataset_id"],
        manifest=manifest,
        transactions=transactions,
        actions_by_session=dict(actions_by_session),
        sessions=sessions,
        delegations=delegations,
        path=root,
    )


def find_latest_dataset(artifact_dir: str | Path) -> Path | None:
    root = Path(artifact_dir)
    if not root.exists():
        return None
    candidates = [d for d in root.iterdir() if d.is_dir() and (d / "manifest.json").exists()]
    if not candidates:
        return None
    return max(candidates, key=lambda d: (d / "manifest.json").stat().st_mtime)


@dataclass
class SplitResult:
    train: Dataset
    validation: Dataset
    holdout: Dataset
    assignment: dict[str, str]
    leakage: dict[str, Any]

    def get(self, name: SplitName | str) -> Dataset:
        return {"train": self.train, "validation": self.validation, "holdout": self.holdout}[
            str(name)
        ]

    def summary(self) -> dict:
        return {
            name: {
                "transactions": len(ds.transactions),
                "groups": len({t.group_id for t in ds.transactions}),
                "campaigns": len({t.campaign_id for t in ds.transactions if t.campaign_id}),
                "abusive": sum(1 for t in ds.transactions if t.is_abusive),
                "hard_negatives": sum(1 for t in ds.transactions if t.hard_negative),
            }
            for name, ds in (
                ("train", self.train), ("validation", self.validation), ("holdout", self.holdout)
            )
        }


def split_dataset(dataset: Dataset, seed: int = 42) -> SplitResult:
    """Stratified group split into 70/15/15 train/validation/holdout.

    The holdout is never used for threshold or weight selection; that is enforced by the
    evaluation runner, which only ever passes ``validation`` to a tuner.
    """
    grouped = dataset.by_group()

    # Stratify on (class, scenario) so rare scenarios appear in every split.
    strata: dict[tuple[str, str], list[str]] = defaultdict(list)
    for group_id, txns in grouped.items():
        head = txns[0]
        strata[(head.label_class, head.scenario)].append(group_id)

    assignment: dict[str, str] = {}
    for stratum in sorted(strata):
        group_ids = sorted(strata[stratum])
        rng = random.Random(f"{seed}:{stratum}")
        rng.shuffle(group_ids)

        total = sum(len(grouped[g]) for g in group_ids)
        train_cap = total * TRAIN_FRACTION
        val_cap = total * (TRAIN_FRACTION + VALIDATION_FRACTION)
        running = 0
        for i, group_id in enumerate(group_ids):
            size = len(grouped[group_id])
            # Guarantee at least one group per split when the stratum has enough groups.
            if len(group_ids) >= 3 and i == len(group_ids) - 1:
                target = "holdout"
            elif len(group_ids) >= 3 and i == len(group_ids) - 2:
                target = "validation"
            elif running < train_cap:
                target = "train"
            elif running < val_cap:
                target = "validation"
            else:
                target = "holdout"
            assignment[group_id] = target
            running += size

    buckets: dict[str, list[TxnRecord]] = {"train": [], "validation": [], "holdout": []}
    for txn in dataset.transactions:
        buckets[assignment[txn.group_id]].append(txn)

    result = SplitResult(
        train=dataset.subset(buckets["train"]),
        validation=dataset.subset(buckets["validation"]),
        holdout=dataset.subset(buckets["holdout"]),
        assignment=assignment,
        leakage={},
    )
    result.leakage = check_leakage(result)
    return result


def check_leakage(split: SplitResult) -> dict[str, Any]:
    """Assert that no group or campaign straddles two splits; report entity overlap.

    Merchants, SKUs and coupons are shared global catalog entities and overlap by design.
    Customers, agents and devices are episode-scoped, so overlap there would be a real
    generator bug and is reported explicitly rather than silently tolerated.
    """
    splits = {"train": split.train, "validation": split.validation, "holdout": split.holdout}

    def collect(attr: str) -> dict[str, set]:
        return {
            name: {getattr(t, attr) for t in ds.transactions if getattr(t, attr) is not None}
            for name, ds in splits.items()
        }

    groups = collect("group_id")
    campaigns = collect("campaign_id")

    def overlaps(sets: dict[str, set]) -> dict[str, int]:
        return {
            f"{a}|{b}": len(sets[a] & sets[b])
            for a, b in (("train", "validation"), ("train", "holdout"), ("validation", "holdout"))
        }

    group_overlap = overlaps(groups)
    campaign_overlap = overlaps(campaigns)
    entity_overlap = {
        entity: overlaps(collect(entity))
        for entity in ("customer_id", "agent_id", "device_id", "network_fingerprint")
    }

    clean = (
        all(v == 0 for v in group_overlap.values())
        and all(v == 0 for v in campaign_overlap.values())
        and all(v == 0 for pair in entity_overlap.values() for v in pair.values())
    )
    return {
        "leakage_free": clean,
        "group_overlap": group_overlap,
        "campaign_overlap": campaign_overlap,
        "entity_overlap": entity_overlap,
        "shared_by_design": ["merchant_id", "sku_id", "coupon_id"],
        "split_sizes": split.summary(),
        "method": (
            "Stratified group split. Groups (generated episodes) are the atomic unit; "
            "stratification is on (label_class, scenario)."
        ),
    }
