"""Deterministic synthetic benchmark generator.

Given the same ``GeneratorConfig`` this produces byte-identical output, which is what makes
the reproducibility test in ``tests/evaluation`` meaningful. The dataset ID is derived from
the config rather than the wall clock for the same reason.

Composition follows PRD §21.1 as a starting point (7000/1500/1000/500) and is adjustable.
Episode sizes vary, so class counts land near — not exactly on — their targets; the manifest
records what was actually produced rather than what was requested.
"""

from __future__ import annotations

import hashlib
import json
import random
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path

from data.generators.catalog import build_catalog
from data.generators.records import Episode, EpisodeContext, IdAllocator, dump_record
from data.generators.scenarios import HARD_NEGATIVE_SCENARIOS, SCENARIO_FAMILIES

GENERATOR_VERSION = "synthgen-v1"

# The PRD suggests 7000/1500/1000/500 as a starting point and says explicitly that these
# are starting values, not final truth. We raised the legitimate-agent share to 3500 after
# measuring that the original mix made `actor_type == AGENT` a near-perfect classifier: with
# 1500 legitimate agent transactions against 1500 abusive ones (all agent-driven), a model
# could reach PR-AUC 0.999 on that single field. That would validate exactly the premise
# this product rejects. At 3500, P(abusive | agent) is roughly 0.25 against a 0.15 base
# rate: informative, as it should be, but nowhere near decisive. A further ~40% of campaign
# episodes run headless (no agent identity at all), which puts abuse on both sides of the
# actor_type split. See docs/evaluation.md.
DEFAULT_COMPOSITION = {
    "LEGIT_HUMAN": 5000,
    "LEGIT_AGENT": 3500,
    "SUSPICIOUS_AUTOMATION": 1000,
    "COORDINATED_ABUSE": 500,
}


@dataclass
class GeneratorConfig:
    seed: int = 42
    composition: dict[str, int] = field(default_factory=lambda: dict(DEFAULT_COMPOSITION))
    start: str = "2026-02-01T00:00:00+00:00"
    duration_days: int = 30
    n_merchants: int = 60
    n_skus: int = 400
    n_coupons: int = 25

    def fingerprint(self) -> str:
        payload = json.dumps(
            {**asdict(self), "generator_version": GENERATOR_VERSION}, sort_keys=True
        )
        return hashlib.sha256(payload.encode()).hexdigest()

    @property
    def target_transactions(self) -> int:
        return sum(self.composition.values())


@dataclass
class GeneratedDataset:
    dataset_id: str
    config: GeneratorConfig
    episodes: list[Episode]
    manifest: dict

    @property
    def transactions(self):
        return [t for ep in self.episodes for t in ep.transactions]

    @property
    def actions(self):
        return [a for ep in self.episodes for a in ep.actions]

    @property
    def sessions(self):
        return [s for ep in self.episodes for s in ep.sessions]

    @property
    def delegations(self):
        return [d for ep in self.episodes for d in ep.delegations]


def _pick(rng: random.Random, family: list[tuple]) -> object:
    """Choose a scenario builder weighted by *episodes needed*, not by episodes picked.

    A registry entry is ``(builder, transaction_share, mean_episode_size)``. To hit a target
    transaction share, a scenario that emits 110 transactions per episode must be selected
    far less often than one that emits 3.
    """
    weights = [(fn, share / max(0.5, mean_size)) for fn, share, mean_size in family]
    total = sum(w for _, w in weights)
    roll = rng.uniform(0, total)
    upto = 0.0
    for fn, weight in weights:
        upto += weight
        if roll <= upto:
            return fn
    return weights[-1][0]


def generate(config: GeneratorConfig | None = None) -> GeneratedDataset:
    config = config or GeneratorConfig()
    rng = random.Random(config.seed)
    catalog = build_catalog(
        random.Random(config.seed ^ 0x5EED), config.n_merchants, config.n_skus, config.n_coupons
    )
    start = datetime.fromisoformat(config.start)
    if start.tzinfo is None:
        start = start.replace(tzinfo=timezone.utc)
    ctx = EpisodeContext(
        rng=rng, catalog=catalog, ids=IdAllocator(), start=start,
        horizon=timedelta(days=config.duration_days),
    )

    episodes: list[Episode] = []
    produced = {label: 0 for label in config.composition}

    # Generate class by class in a fixed order so the sequence of RNG draws is stable.
    for label in sorted(config.composition):
        target = config.composition[label]
        family = SCENARIO_FAMILIES[label]
        guard = 0
        while produced[label] < target:
            guard += 1
            if guard > target * 50 + 1000:  # pathological config; fail loudly
                raise RuntimeError(f"scenario family {label} failed to reach target {target}")
            builder = _pick(rng, family)
            episode = builder(ctx)
            if not episode.transactions:
                continue
            episodes.append(episode)
            produced[label] += len(episode.transactions)

    # Chronological order mirrors how a real event stream would arrive.
    episodes.sort(key=lambda ep: min(t.timestamp for t in ep.transactions))

    dataset_id = f"ds_{config.fingerprint()[:16]}"
    manifest = _build_manifest(dataset_id, config, episodes)
    return GeneratedDataset(dataset_id=dataset_id, config=config, episodes=episodes,
                            manifest=manifest)


def _build_manifest(dataset_id: str, config: GeneratorConfig, episodes: list[Episode]) -> dict:
    transactions = [t for ep in episodes for t in ep.transactions]
    by_class: dict[str, int] = {}
    by_scenario: dict[str, int] = {}
    for t in transactions:
        by_class[t.label_class] = by_class.get(t.label_class, 0) + 1
        by_scenario[t.scenario] = by_scenario.get(t.scenario, 0) + 1

    hard_negatives = sum(1 for t in transactions if t.hard_negative)
    abusive = sum(1 for t in transactions if t.is_abusive)
    gmv = sum(t.amount for t in transactions)

    return {
        "dataset_id": dataset_id,
        "generator_version": GENERATOR_VERSION,
        "config_fingerprint": config.fingerprint(),
        "config": asdict(config),
        "counts": {
            "transactions": len(transactions),
            "actions": sum(len(ep.actions) for ep in episodes),
            "sessions": sum(len(ep.sessions) for ep in episodes),
            "delegations": sum(len(ep.delegations) for ep in episodes),
            "episodes": len(episodes),
            "groups": len({ep.group_id for ep in episodes}),
            "campaigns": len({ep.campaign_id for ep in episodes if ep.campaign_id}),
            "customers": len({t.customer_id for t in transactions}),
            "agents": len({t.agent_id for t in transactions if t.agent_id}),
            "devices": len({t.device_id for t in transactions}),
            "networks": len({t.network_fingerprint for t in transactions}),
        },
        "by_class": dict(sorted(by_class.items())),
        "by_scenario": dict(sorted(by_scenario.items())),
        "hard_negatives": {
            "transactions": hard_negatives,
            "share_of_legitimate": round(
                hard_negatives / max(1, len(transactions) - abusive), 4
            ),
            "scenarios": sorted(HARD_NEGATIVE_SCENARIOS),
        },
        "label_balance": {
            "abusive": abusive,
            "legitimate": len(transactions) - abusive,
            "abusive_rate": round(abusive / max(1, len(transactions)), 4),
        },
        "gmv_total": round(gmv, 2),
        "window": {
            "start": config.start,
            "duration_days": config.duration_days,
        },
        "notes": (
            "Fully synthetic. No real customers, merchants, cards, tokens or personal data. "
            "Labels are ground truth from the generator and are never visible to a detector."
        ),
    }


# --------------------------------------------------------------------------------------
# persistence
# --------------------------------------------------------------------------------------

_FILES = {
    "transactions": "transactions.jsonl",
    "actions": "actions.jsonl",
    "sessions": "sessions.jsonl",
    "delegations": "delegations.jsonl",
}


def _write_jsonl(path: Path, records) -> str:
    digest = hashlib.sha256()
    with path.open("w", encoding="utf-8") as fh:
        for record in records:
            line = json.dumps(dump_record(record), sort_keys=True)
            fh.write(line + "\n")
            digest.update(line.encode())
    return digest.hexdigest()


def save(dataset: GeneratedDataset, out_dir: str | Path) -> Path:
    """Write the dataset to a versioned artifact directory. Returns the directory path."""
    root = Path(out_dir) / dataset.dataset_id
    root.mkdir(parents=True, exist_ok=True)

    checksums = {
        "transactions": _write_jsonl(root / _FILES["transactions"], dataset.transactions),
        "actions": _write_jsonl(root / _FILES["actions"], dataset.actions),
        "sessions": _write_jsonl(root / _FILES["sessions"], dataset.sessions),
        "delegations": _write_jsonl(root / _FILES["delegations"], dataset.delegations),
    }
    manifest = {
        **dataset.manifest,
        "files": _FILES,
        "checksums": checksums,
        "written_at": datetime.now(timezone.utc).isoformat(),
    }
    (root / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return root
