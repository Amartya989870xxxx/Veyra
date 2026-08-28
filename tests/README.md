# Test harness

Built in Phase 1, **before** the rewrite, for one reason: Phase 5's leakage gates *are*
tests. Written any later they become one-off scripts that get run once, produce a
screenshot, and quietly stop being run. A gate that is not in CI is not a gate.

## What belongs where

| Directory | Holds | The question it answers |
|---|---|---|
| `unit/` | feature functions, baseline maths, window arithmetic | is this function correct in isolation? |
| `integration/` | ingest → aggregate → score → incident, end to end | do the parts still fit together? |
| `evaluation/` | leakage gates G1–G6 | is the headline number real, or did we learn the generator? |
| `failure/` | degraded components, missing baselines, clock skew, duplicate events | what happens when something is broken or absent? |
| `property/` | hypothesis invariants on window and baseline arithmetic | is it correct for inputs nobody thought to write down? |

## Why property tests carry unusual weight here

The window aggregator is where off-by-one and boundary bugs corrupt every downstream
number **without raising**. An example-based test proves the case you thought of; a
property test searches for the case you didn't, and hypothesis shrinks the failure to a
minimal reproduction.

The three invariants worth asserting, from `docs/ROADMAP.md` §1.2:

1. the sum of 1m counts across an hour equals the 1h count — additivity
2. a window never sees an event at or after its own `window_end` — the past-only rule
3. baselines are invariant to the order events are inserted in — no hidden state

## Markers

- `slow` — long-running evaluation work; excluded from the default run
- `gate` — a leakage gate. **Never** skip, xfail or weaken one of these to make CI green.
  A failing gate is a finding, and the finding is the point.

## Running

```
pytest                    # everything except slow
pytest -m gate            # the leakage gates alone
pytest tests/property -v  # invariants, with hypothesis statistics
HYPOTHESIS_PROFILE=ci pytest tests/property   # 10x the examples
```
