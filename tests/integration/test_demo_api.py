"""Demo simulation + synthetic data explorer, end to end (Part 7, A/B/D/E/F/J).

The load-bearing test in this file is `test_risk_score_is_not_derived_from_the_scenario_label`:
before this pass, `/v2/demo/simulate` computed its risk score from
`req.scenario_id in ATTACK_SCENARIO_SET`, so the "prediction" was a restatement of the
input. That test lies about the label and asserts the score does not move.
"""

from __future__ import annotations

import re
from datetime import datetime

import httpx
import pytest
from httpx import ASGITransport

from app.main import app

PAN_LIKE = re.compile(r"^\d{12,19}$")


@pytest.fixture(scope="module")
async def client():
    transport = ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://demotest", timeout=600.0
    ) as c:
        yield c


@pytest.fixture(scope="module")
async def attack_run(client):
    """One card-testing run, reused across assertions. Module-scoped because the first
    call pays the demo model's one-time fit."""
    resp = await client.post(
        "/v2/demo/simulate",
        json={"scenario_id": "card_testing_burst", "window_size": "5m", "seed": 42},
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


@pytest.mark.asyncio
async def test_risk_score_is_not_derived_from_the_scenario_label(client, monkeypatch, attack_run):
    """A: flipping the ground-truth label must not change the prediction.

    `ATTACK_SCENARIO_SET` is the exact set the old implementation branched on. If the
    score still depended on it, moving a scenario in or out would move the number.
    """
    import app.api.v2.demo as demo_module

    baseline_score = attack_run["risk_score"]

    # Lie: claim card_testing_burst is benign.
    monkeypatch.setattr(
        demo_module, "ATTACK_SCENARIO_SET", demo_module.ATTACK_SCENARIO_SET - {"card_testing_burst"}
    )
    resp = await client.post(
        "/v2/demo/simulate",
        json={"scenario_id": "card_testing_burst", "window_size": "5m", "seed": 42},
    )
    assert resp.status_code == 200
    lied = resp.json()

    assert lied["risk_score"] == pytest.approx(baseline_score, abs=1e-9), (
        "risk_score changed when only the ground-truth label changed — it is still "
        "label-derived rather than model-derived"
    )
    # The label itself is still reported, and now disagrees with the (unchanged) verdict.
    assert lied["ground_truth"]["scenario_is_labelled_attack"] is False


@pytest.mark.asyncio
async def test_scoring_calls_the_fitted_detector(client, monkeypatch):
    """B: the score is produced by DemoModelService.score(), on the extracted vector."""
    from app.serving import demo_model_service as dms

    service = dms.get_demo_model_service()
    service.ensure_trained()
    calls: list[list[dict]] = []
    original = service.score

    def spy(vectors):
        calls.append(vectors)
        return original(vectors)

    monkeypatch.setattr(service, "score", spy)

    resp = await client.post(
        "/v2/demo/simulate",
        json={"scenario_id": "flash_sale_spike", "window_size": "5m", "seed": 7},
    )
    assert resp.status_code == 200
    body = resp.json()

    assert calls, "DemoModelService.score was never called"
    assert len(calls[0]) == 1
    assert calls[0][0], "the detector was handed an empty feature vector"
    # The endpoint rounds to 6dp on the way out; compare against the same rounding.
    assert body["risk_score"] == pytest.approx(round(original(calls[0])[0], 6), abs=1e-9)
    assert body["run"]["model"]["model_name"] == "veyra_fusion_demo"


@pytest.mark.asyncio
async def test_run_metadata_declares_synthetic_provenance(attack_run):
    """D: provenance is explicit, not inferred."""
    provenance = attack_run["run"]["provenance"]
    assert provenance["data_source"] == "synthetic"
    assert provenance["generated_for"] == "demo_run"
    assert provenance["is_production_data"] is False
    assert "synthetic scenario label" in provenance["ground_truth_semantics"]


@pytest.mark.asyncio
async def test_stage_trace_is_measured_server_side(attack_run):
    """J: every declared stage carries a real measured duration."""
    stages = attack_run["stages"]
    ids = [s["id"] for s in stages]

    for required in (
        "generation",
        "injection",
        "windowing",
        "features",
        "graph",
        "inference",
        "policy",
        "exposure",
        "forensics",
    ):
        assert required in ids, f"missing stage {required}"

    assert all(s["duration_ms"] >= 0.0 for s in stages)
    assert all(s["status"] == "completed" for s in stages)
    assert any(s["duration_ms"] > 0.0 for s in stages), "no stage recorded a non-zero duration"
    assert attack_run["run"]["total_server_duration_ms"] > 0.0


@pytest.mark.asyncio
async def test_aggregate_metadata_is_present(attack_run):
    run = attack_run["run"]
    assert run["total_transactions"] > 0
    assert run["time_span_seconds"] >= 0
    assert run["window_size"] == "5m"
    assert run["feature_count"] > 0
    assert run["baselines_available"] is True
    assert run["entity_counts"]["devices"] >= 1
    assert run["model"]["training_windows"] > 0
    assert isinstance(run["model"]["trained_this_call"], bool)


@pytest.mark.asyncio
async def test_ground_truth_is_reported_but_labelled_as_such(attack_run):
    gt = attack_run["ground_truth"]
    assert gt["scenario_is_labelled_attack"] is True
    assert gt["abusive_transaction_count"] >= 0
    assert "not read when computing risk_score" in gt["note"]
    assert isinstance(attack_run["model_matches_ground_truth"], bool)


# --------------------------------------------------------------------- data explorer


@pytest.mark.asyncio
async def test_transaction_explorer_paginates(client, attack_run):
    """E: pagination is bounded and consistent."""
    run_id = attack_run["run"]["run_id"]

    resp = await client.get(f"/v2/demo/runs/{run_id}/transactions?page=1&page_size=5")
    assert resp.status_code == 200
    page = resp.json()

    assert page["page"] == 1
    assert page["page_size"] == 5
    assert len(page["items"]) <= 5
    assert page["total_transactions"] == attack_run["run"]["total_transactions"]
    assert page["provenance"]["data_source"] == "synthetic"


@pytest.mark.asyncio
async def test_page_size_is_capped(client, attack_run):
    """E: no request can pull an unbounded page."""
    run_id = attack_run["run"]["run_id"]
    resp = await client.get(f"/v2/demo/runs/{run_id}/transactions?page=1&page_size=100000")
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_no_raw_card_identifiers_are_exposed(client, attack_run):
    """F: nothing PAN-shaped, and no field named like a card number, reaches the client."""
    run_id = attack_run["run"]["run_id"]
    resp = await client.get(f"/v2/demo/runs/{run_id}/transactions?page=1&page_size=50")
    page = resp.json()

    banned_keys = {"pan", "card_number", "cardnumber", "cvv", "card"}
    for row in page["items"]:
        for key, value in row.items():
            assert key.lower() not in banned_keys, f"forbidden field {key} in explorer output"
            if isinstance(value, str):
                assert not PAN_LIKE.match(value), f"PAN-shaped value in field {key}"


@pytest.mark.asyncio
async def test_feature_explorer_groups_by_family(client, attack_run):
    run_id = attack_run["run"]["run_id"]
    resp = await client.get(f"/v2/demo/runs/{run_id}/features")
    assert resp.status_code == 200
    body = resp.json()

    assert body["model_feature_count"] > 0
    assert set(body["families"]).issubset(set("ABCDEFGHIJ"))
    sample = next(iter(body["families"].values()))[0]
    assert {"feature_id", "family", "value", "is_model_input"} <= set(sample)


@pytest.mark.asyncio
async def test_run_summary_reports_composition(client, attack_run):
    run_id = attack_run["run"]["run_id"]
    resp = await client.get(f"/v2/demo/runs/{run_id}/summary")
    assert resp.status_code == 200
    body = resp.json()

    assert body["total_transactions"] == body["abusive_transactions"] + body["benign_transactions"]
    assert body["provenance"]["is_production_data"] is False


@pytest.mark.asyncio
async def test_unknown_run_is_not_found(client):
    resp = await client.get("/v2/demo/runs/run_definitely_not_real/summary")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_unknown_scenario_is_rejected(client):
    resp = await client.post("/v2/demo/simulate", json={"scenario_id": "not_a_scenario"})
    assert resp.status_code == 400


# ------------------------------------------------- stage trace structure (Parts 1 & 2)


@pytest.mark.asyncio
async def test_stage_sequence_is_dense_and_ordered(attack_run):
    """Stages must be a real ordered trace: 1..N with no gaps, and each stage's own
    wall-clock window must not run backwards."""
    stages = attack_run["stages"]
    assert [s["sequence"] for s in stages] == list(range(1, len(stages) + 1))

    for s in stages:
        assert s["status"] in {"pending", "running", "completed", "failed", "skipped"}
        started = datetime.fromisoformat(s["started_at"].replace("Z", "+00:00"))
        ended = datetime.fromisoformat(s["ended_at"].replace("Z", "+00:00"))
        assert ended >= started, f"stage {s['id']} ends before it starts"

    # Execution order is chronological across the whole trace.
    starts = [datetime.fromisoformat(s["started_at"].replace("Z", "+00:00")) for s in stages]
    assert starts == sorted(starts), "stages are not in chronological order"


@pytest.mark.asyncio
async def test_backend_reports_real_time_not_padded_time(attack_run):
    """The backend must never inflate its own cost to make a UI feel busy.

    A warm demo run is milliseconds of work. If this ever creeps into seconds, something
    is sleeping or doing duplicate work — either way the number stops being a measurement.
    """
    timing = attack_run["run"]["timing"]
    assert timing["measurement"] == "time.perf_counter"
    assert timing["includes_frontend_presentation_time"] is False
    assert timing["stage_count"] == len(attack_run["stages"])

    total = attack_run["run"]["total_server_duration_ms"]
    assert total == timing["server_processing_ms"]
    assert total > 0.0

    # The sum of measured stages cannot exceed the measured total.
    assert sum(s["duration_ms"] for s in attack_run["stages"]) <= total + 1.0


@pytest.mark.asyncio
async def test_run_metadata_carries_the_request_that_produced_it(attack_run):
    """Part 3: the run block must be self-describing, so the UI never has to remember
    what it asked for in order to label what it got back."""
    run = attack_run["run"]
    assert run["scenario_id"] == "card_testing_burst"
    assert run["seed"] == 42
    assert run["intensity"] > 0
    assert run["window_size"] == "5m"
    assert run["total_entities"] == sum(run["entity_counts"].values())
    assert run["risk_score"] == attack_run["risk_score"]
    assert run["action_tier"] == attack_run["action_tier"]
    assert run["model"]["was_cached"] is not run["model"]["trained_this_call"]


# ------------------------------------------------------- entity summary (Part 5D)


@pytest.mark.asyncio
async def test_entity_summary_agrees_with_the_run_it_explains(client, attack_run):
    run_id = attack_run["run"]["run_id"]
    body = (await client.get(f"/v2/demo/runs/{run_id}/entities")).json()

    assert body["run_id"] == run_id
    assert body["counts"] == attack_run["run"]["entity_counts"]
    assert body["total_entities"] == sum(body["counts"].values())
    assert body["transactions"] == attack_run["run"]["total_transactions"]
    assert body["provenance"]["is_production_data"] is False


@pytest.mark.asyncio
async def test_run_detail_links_reach_every_sub_resource(client, attack_run):
    """A frontend should be able to navigate the explorer from the run document alone."""
    run_id = attack_run["run"]["run_id"]
    detail = (await client.get(f"/v2/demo/runs/{run_id}")).json()

    for name, url in detail["links"].items():
        resp = await client.get(url)
        assert resp.status_code == 200, f"link '{name}' -> {url} returned {resp.status_code}"
