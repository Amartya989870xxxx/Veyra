# Veyra

**Incident-level fraud spike intelligence for merchants.**
Research prototype — Razorpay AI Buildathon 2026, Track 02 (AI Risk Manager).

---

Veyra learns what normal payment behaviour looks like for a merchant across multiple
time windows, detects abnormal changes in **volume, composition and relationships**,
judges whether the change is consistent with coordinated abuse rather than legitimate
demand, estimates financial exposure, and produces an explainable risk incident.

The central principle:

> **A volume anomaly is evidence, not a verdict.**

A merchant going from 30 to 500 orders may be running a flash sale or may be under a
card-testing attack. The two look identical in volume and completely different in
composition and entity relationships. Telling them apart is the whole product.

## Status

| | |
|---|---|
| Phase | 0 — research matrix |
| Detection unit | `(merchant_id, window_size, window_end)` → incident |
| Previous version | tagged `v1-agent-commerce` (different problem; see roadmap) |

**This is a research prototype evaluated on synthetic data.** It does not replace, and
does not claim to outperform, any production payment-risk platform.

## Documentation

| Document | What it covers |
|---|---|
| [`docs/ROADMAP.md`](docs/ROADMAP.md) | The full build plan, phases 0–7 |
| [`research/matrix.yaml`](research/matrix.yaml) | The executable scenario matrix (phase 0) |
| [`docs/decisions/`](docs/decisions/) | Architecture decision records |
| [`docs/threat-model.md`](docs/threat-model.md) | Scope, taxonomy, and defence-only boundary |

## Defence only

Veyra is a **detection** system. It simulates attack patterns offline, in synthetic data,
in order to measure whether it can catch them. It contains no attack tooling: no
credential testing, no card-testing automation, no evasion infrastructure, nothing that
runs against a live system.

## Source discipline

Claims in this repository are labelled by origin: **Razorpay-published fact**,
**external research**, **synthetic benchmark assumption**, or **Veyra experimental
result**. Cost constants are assumptions we chose and document — never presented as
Razorpay economics.
