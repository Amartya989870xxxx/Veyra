/** Documentation.
 *
 * Developer-facing reference with two-layer structure:
 * 1. "IN SIMPLE TERMS" — clear, approachable explanation for non-technical reviewers.
 * 2. "TECHNICAL DETAILS" — rigorous engineering breakdown, schemas, and API contracts.
 *
 * Verified against active backend FastAPI routes (app/api/v2/ and app/main.py).
 */

import { useEffect, useState } from 'react';
import { API_BASE_URL } from '../api/client';
import { TIER_COPY, TIER_ORDER, WINDOW_OPTIONS } from '../lib/scenarios';
import { SectionLabel } from '../components/ui';

interface DocSection {
  id: string;
  title: string;
  body: React.ReactNode;
}

/* ------------------------------------------------------------- fragments */

function P({ children }: { children: React.ReactNode }) {
  return (
    <p style={{ fontSize: '15px', color: '#cbd5e1', lineHeight: 1.7 }}>
      {children}
    </p>
  );
}

function Code({ children }: { children: string }) {
  return (
    <pre
      style={{
        margin: 0,
        padding: 'var(--sp-4)',
        overflowX: 'auto',
        background: '#040711',
        border: '1px solid rgba(255, 255, 255, 0.08)',
        borderRadius: 'var(--radius)',
        fontFamily: 'var(--font-mono)',
        fontSize: '13px',
        lineHeight: 1.65,
        color: '#94a3b8',
      }}
    >
      <code>{children}</code>
    </pre>
  );
}

function Inline({ children }: { children: React.ReactNode }) {
  return (
    <code
      className="mono"
      style={{
        fontSize: '0.92em',
        color: '#60a5fa',
        background: 'rgba(37, 99, 235, 0.12)',
        borderRadius: 4,
        padding: '2px 6px',
      }}
    >
      {children}
    </code>
  );
}

function LayeredSection({
  simpleTerms,
  technicalDetails,
}: {
  simpleTerms: React.ReactNode;
  technicalDetails: React.ReactNode;
}) {
  return (
    <div style={{ display: 'grid', gap: 'var(--sp-4)' }}>
      {/* Layer 1: In Simple Terms */}
      <div
        style={{
          padding: '16px 20px',
          borderRadius: 'var(--radius)',
          background: 'rgba(16, 185, 129, 0.05)',
          border: '1px solid rgba(16, 185, 129, 0.22)',
        }}
      >
        <div
          style={{
            fontSize: '11px',
            fontFamily: 'var(--font-mono)',
            fontWeight: 700,
            letterSpacing: '0.08em',
            color: '#10b981',
            marginBottom: '8px',
            display: 'flex',
            alignItems: 'center',
            gap: '8px',
          }}
        >
          <span style={{ width: 6, height: 6, borderRadius: '50%', background: '#10b981' }} />
          IN SIMPLE TERMS
        </div>
        <div style={{ fontSize: '15px', color: '#f1f5f9', lineHeight: 1.65 }}>
          {simpleTerms}
        </div>
      </div>

      {/* Layer 2: Technical Details */}
      <div
        style={{
          padding: '20px 22px',
          borderRadius: 'var(--radius)',
          background: 'var(--bg-sunken)',
          border: '1px solid var(--border-subtle)',
        }}
      >
        <div
          style={{
            fontSize: '11px',
            fontFamily: 'var(--font-mono)',
            fontWeight: 700,
            letterSpacing: '0.08em',
            color: '#94a3b8',
            marginBottom: '14px',
            display: 'flex',
            alignItems: 'center',
            gap: '8px',
          }}
        >
          <span style={{ width: 6, height: 6, borderRadius: '50%', background: '#3b82f6' }} />
          TECHNICAL DETAILS
        </div>
        <div style={{ display: 'grid', gap: 'var(--sp-3)' }}>
          {technicalDetails}
        </div>
      </div>
    </div>
  );
}

function EndpointTable({ rows }: { rows: { method: string; path: string; note: string }[] }) {
  return (
    <div style={{ overflowX: 'auto' }}>
      <table style={{ width: '100%', borderCollapse: 'collapse', minWidth: 520 }}>
        <thead>
          <tr>
            {['Method', 'Path', 'Purpose'].map((h) => (
              <th
                key={h}
                className="eyebrow"
                style={{ textAlign: 'left', padding: '8px 12px 8px 0', borderBottom: '1px solid var(--border)', fontSize: '11px', color: '#64748b' }}
              >
                {h}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={`${r.method} ${r.path}`}>
              <td style={{ padding: '10px 12px 10px 0', borderBottom: '1px solid var(--border-subtle)', verticalAlign: 'top' }}>
                <span
                  className="mono"
                  style={{
                    fontSize: '12px',
                    fontWeight: 700,
                    color: r.method === 'GET' ? 'var(--tier-observe)' : '#f93f28',
                  }}
                >
                  {r.method}
                </span>
              </td>
              <td
                className="mono"
                style={{
                  padding: '10px 12px 10px 0',
                  borderBottom: '1px solid var(--border-subtle)',
                  fontSize: '12px',
                  color: 'var(--text-primary)',
                  verticalAlign: 'top',
                  whiteSpace: 'nowrap',
                }}
              >
                {r.path}
              </td>
              <td
                style={{
                  padding: '10px 0',
                  borderBottom: '1px solid var(--border-subtle)',
                  fontSize: '13px',
                  color: '#94a3b8',
                  lineHeight: 1.6,
                  verticalAlign: 'top',
                }}
              >
                {r.note}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/* -------------------------------------------------------------- sections */

function buildSections(): DocSection[] {
  return [
    {
      id: 'getting-started',
      title: 'Getting started',
      body: (
        <LayeredSection
          simpleTerms="Veyra runs as a Python FastAPI backend that inspects payment streams, accompanied by a React dashboard for live simulation and forensic inspection."
          technicalDetails={
            <>
              <P>
                The frontend holds no detection or ML logic; if the backend is unreachable, the console displays an explicit connection error rather than fabricating offline results.
              </P>
              <Code>{`# backend (from the repository root)
python -m uvicorn app.main:app --port 8008

# frontend (from frontend/ directory)
cd frontend
npm install
npm run dev`}</Code>
              <P>
                The frontend defaults to <Inline>{API_BASE_URL}</Inline>. Set <Inline>VITE_API_BASE_URL</Inline> in <Inline>frontend/.env</Inline> to target a remote staging instance.
              </P>
            </>
          }
        />
      ),
    },
    {
      id: 'how-detection-works',
      title: 'How detection works',
      body: (
        <LayeredSection
          simpleTerms="Instead of scoring one payment at a time in isolation, Veyra groups attempts over short time windows (e.g. 5 minutes) to see if hundreds of attempts are coordinating together like an attack ring."
          technicalDetails={
            <>
              <P>
                The fundamental unit of detection is the <strong>merchant-window</strong>: one merchant's traffic over a configured temporal horizon. A single payment carries no evidence that it belongs to an automated distributed ring.
              </P>
              <P>
                A window is evaluated by three specialized detectors fused into one probability:
                1. <strong>Volume Detector (A)</strong>: Evaluates velocity against historical expected traffic.
                2. <strong>Contextual Detector (B)</strong>: Analyzes 79 streaming feature metrics across amount entropy, decline velocity, and novelty.
                3. <strong>Entity Graph Detector (C)</strong>: Computes degree Gini concentration across connected bipartite clusters.
              </P>
              <P>
                Four sliding horizons are scored simultaneously: {WINDOW_OPTIONS.map((w) => w.label).join(', ')}. Sudden card-testing bursts trigger in 1m windows, while slow distributed ramps emerge in 1h windows.
              </P>
            </>
          }
        />
      ),
    },
    {
      id: 'detection-pipeline',
      title: 'Detection pipeline',
      body: (
        <LayeredSection
          simpleTerms="Every scenario you run goes through the same 12 real steps, in the same order, and the site shows you exactly how long each one actually took on the server."
          technicalDetails={
            <>
              <P>
                <Inline>POST /v2/demo/simulate</Inline> returns a <Inline>stages</Inline> array — one
                entry per real unit of server-side work, in execution order. Each entry carries a
                stable <Inline>id</Inline>, a 1-based <Inline>sequence</Inline>, a{' '}
                <Inline>status</Inline>, a <Inline>duration_ms</Inline> measured with{' '}
                <Inline>time.perf_counter()</Inline> around that specific unit of work, and wall-clock{' '}
                <Inline>started_at</Inline>/<Inline>ended_at</Inline> timestamps. Nothing here is
                estimated: a stage that did not run does not appear.
              </P>
              <Code>{`generation → injection → windowing → baseline
  → features → graph → deviation → inference
  → policy → exposure → forensics → run_record`}</Code>
              <P>
                <strong>Stage status</strong> is one of <Inline>pending</Inline>,{' '}
                <Inline>running</Inline>, <Inline>completed</Inline>, <Inline>failed</Inline> or{' '}
                <Inline>skipped</Inline>. A finished response only ever contains{' '}
                <Inline>completed</Inline> stages, or a <Inline>failed</Inline> one if something
                raised — the other two states exist so a client can model the same 12-stage list
                while a run is still in flight.
              </P>
              <P>
                <strong>Timing semantics.</strong> Every duration in the response is genuine
                backend processing time. The run also reports a <Inline>timing</Inline> block —{' '}
                <Inline>server_processing_ms</Inline>, the measurement method, and an explicit{' '}
                <Inline>includes_frontend_presentation_time: false</Inline> — so a client integrating
                against this API never has to guess whether a number includes anything beyond
                server work. A cold process pays a one-time model fit (visible as an outsized{' '}
                <Inline>baseline</Inline> stage on the first call after startup); every call after
                that completes in single-digit to low double-digit milliseconds.
              </P>
            </>
          }
        />
      ),
    },
    {
      id: 'synthetic-provenance',
      title: 'Synthetic data & provenance',
      body: (
        <LayeredSection
          simpleTerms="Everything you see in a demo run is generated fresh and clearly marked as synthetic. The scenario's own label (attack or benign) is shown for comparison, but it is never what produces the risk score — the score always comes from the model actually scoring the generated data."
          technicalDetails={
            <>
              <P>
                Every demo response carries a <Inline>provenance</Inline> block:
              </P>
              <Code>{`{
  "data_source": "synthetic",
  "generated_for": "demo_run",
  "is_production_data": false,
  "ground_truth_semantics": "..."
}`}</Code>
              <P>
                <strong>Model output vs. synthetic ground truth.</strong>{' '}
                <Inline>risk_score</Inline> is the output of{' '}
                <Inline>DemoModelService.score()</Inline> — a real fitted{' '}
                <Inline>VeyraFusionDetector</Inline> — run on the extracted feature vector.{' '}
                <Inline>ground_truth.scenario_is_labelled_attack</Inline> is a separate field: the
                synthetic generator's own label for the scenario you picked, read only{' '}
                <em>after</em> scoring is complete, and used solely to populate that comparison
                field and <Inline>model_matches_ground_truth</Inline>. It is structurally
                impossible for the label to influence the score, because the code that computes{' '}
                <Inline>risk_score</Inline> never reads it.
              </P>
              <P>
                The demo model itself is trained on a synthetic corpus generated from a fixed
                historical window that ends before any demo request's window begins, so a demo run
                can never be scored by a model that was trained on that exact traffic.
              </P>
            </>
          }
        />
      ),
    },
    {
      id: 'historical-baselines',
      title: 'Historical baselines',
      body: (
        <LayeredSection
          simpleTerms="Veyra learns what normal payment traffic looks like for each specific merchant for every hour of the week, so a busy Friday night isn't mistaken for a cyberattack."
          technicalDetails={
            <>
              <P>
                Every feature carries a per-merchant, per-hour-of-week baseline: an expected median and variability figure. Deviation is reported in <strong>MAD (Median Absolute Deviation)</strong> units rather than standard deviations.
              </P>
              <P>
                <strong>Mathematical Rationale</strong>: The standard deviation has a 0% breakdown point—ingesting a single past attack of 1,000 requests permanently inflates variance, rendering future attacks invisible. MAD possesses a 50% breakdown point, resisting outlier poisoning.
              </P>
              <Code>{`GET ${API_BASE_URL}/v2/merchants/{merchant_id}/baselines

# Returns stored hour-of-week profiles:
# { merchant_id, total_baselines, baselines: [
#     { feature_id, window_size, hour_of_week,
#       expected_median, variability_mad, confidence, sample_count } ] }`}</Code>
            </>
          }
        />
      ),
    },
    {
      id: 'contextual-detection',
      title: 'Contextual detection',
      body: (
        <LayeredSection
          simpleTerms="Veyra checks dozens of patterns beyond volume: whether payment amounts are random or fixed, whether failure codes look like bank errors or invalid card guesses, and how many new card numbers appear."
          technicalDetails={
            <>
              <P>
                Each window is reduced to 79 streaming features across ten families (Families A through J): transaction rates, amount entropy, card novelty share, decline velocity, Shannon failure entropy, and graph cluster metrics.
              </P>
              <P>
                <strong>Anti-Leakage Barrier (ADR-004)</strong>: Chargebacks, chargeback dispute statuses, and post-facto fraud labels are strictly barred from the feature extraction horizon. They exist purely as evaluation ground truth. The automated assertion <Inline>assert_no_downstream()</Inline> crashes the pipeline if any post-facto signal enters a feature vector.
              </P>
            </>
          }
        />
      ),
    },
    {
      id: 'entity-intelligence',
      title: 'Entity intelligence',
      body: (
        <LayeredSection
          simpleTerms="Veyra draws a web connecting accounts, cards, devices, and IP addresses. If 500 orders come from 500 different phones, it looks like a real sale; if 500 orders come from 3 phones, it's an emulator farm."
          technicalDetails={
            <>
              <P>
                Events in a window are linked into a bipartite graph over four entity types: Customer Accounts, Device Fingerprints, Instrument Tokens, and IP subnets. Edges record that an account transacted through a device or used an instrument.
              </P>
              <P>
                The graph engine operates in linear <Inline>O(V + E)</Inline> time per window, computing the degree distribution Gini coefficient and identifying the largest connected component. A high Gini coefficient (&gt; 0.70) indicates extreme entity reuse typical of card testing and botnet operations.
              </P>
            </>
          }
        />
      ),
    },
    {
      id: 'risk-decisions',
      title: 'Risk decisions',
      body: (
        <LayeredSection
          simpleTerms="Instead of simply blocking payments (which risks stopping real customers), Veyra uses four calibrated tiers from quiet monitoring to targeted friction challenges."
          technicalDetails={
            <>
              <P>
                Under <strong>ADR-006</strong>, the policy maps fused fraud probabilities to four discrete operating tiers based on expected loss optimization:
              </P>
              <div style={{ display: 'grid', gap: 'var(--sp-2)' }}>
                {TIER_ORDER.map((tier) => (
                  <div
                    key={tier}
                    style={{
                      display: 'grid',
                      gridTemplateColumns: '96px 1fr',
                      gap: 'var(--sp-3)',
                      alignItems: 'baseline',
                      padding: 'var(--sp-3)',
                      background: '#040711',
                      border: '1px solid var(--border-subtle)',
                      borderRadius: 'var(--radius-sm)',
                    }}
                  >
                    <span
                      className="mono"
                      style={{ fontSize: '12px', fontWeight: 700, color: `var(--tier-${tier.toLowerCase()})` }}
                    >
                      {tier}
                    </span>
                    <span style={{ fontSize: '13px', color: '#cbd5e1', lineHeight: 1.6 }}>
                      {TIER_COPY[tier].meaning}
                    </span>
                  </div>
                ))}
              </div>
              <P>
                Veyra recommends controls (e.g. rate-limiting specific device clusters or triggering step-up 3DS auth) rather than permanently shutting down checkout endpoints.
              </P>
            </>
          }
        />
      ),
    },
    {
      id: 'api-integration',
      title: 'API integration',
      body: (
        <LayeredSection
          simpleTerms="The API provides clean endpoints to simulate scenarios, run stress tests, query incidents, and retrieve merchant baselines."
          technicalDetails={
            <>
              <P>
                All application endpoints are versioned under <Inline>/v2</Inline>. The frontend communicates through the typed client in <Inline>src/api/client.ts</Inline>.
              </P>
              <EndpointTable
                rows={[
                  { method: 'GET', path: '/health', note: 'Liveness and environment status.' },
                  { method: 'GET', path: '/v2/demo/scenarios', note: 'List all supported attack and benign surge scenarios.' },
                  { method: 'POST', path: '/v2/demo/simulate', note: 'Generate, score and store one demo run: full 12-stage trace, verdict and forensic evidence.' },
                  { method: 'POST', path: '/v2/demo/stress-test', note: 'Small fixed-size burst probe, timed server-side.' },
                  { method: 'GET', path: '/v2/demo/runs/{run_id}', note: 'Metadata, entity graph and links for one stored demo run.' },
                  { method: 'GET', path: '/v2/demo/runs/{run_id}/transactions', note: 'Paginated synthetic transactions behind a run (page_size capped at 200).' },
                  { method: 'GET', path: '/v2/demo/runs/{run_id}/features', note: 'Full feature vector for a run, grouped by family, with baseline deviations.' },
                  { method: 'GET', path: '/v2/demo/runs/{run_id}/summary', note: 'Composition, time range and entity counts for a run.' },
                  { method: 'GET', path: '/v2/demo/runs/{run_id}/entities', note: 'Entity topology metrics: counts, ratios, cluster concentration, bipartite Gini.' },
                  { method: 'GET', path: '/v2/demo/benchmarks/presets', note: 'Workload presets, tiers, configured guardrails.' },
                  { method: 'POST', path: '/v2/demo/benchmarks', note: 'Queue a Scale Lab benchmark; returns immediately with a run_id.' },
                  { method: 'GET', path: '/v2/demo/benchmarks/{run_id}/progress', note: 'Cheap polling target for an in-flight benchmark.' },
                  { method: 'GET', path: '/v2/demo/benchmarks/{run_id}', note: 'Full benchmark run, including the result once terminal.' },
                  { method: 'GET', path: '/v2/demo/benchmarks', note: 'Recent benchmark runs held in the bounded registry.' },
                  { method: 'POST', path: '/v2/score-window', note: 'Score a merchant-window on ingested live stream.' },
                  { method: 'GET', path: '/v2/incidents', note: 'Query stored incidents filtered by merchant and status.' },
                  { method: 'GET', path: '/v2/incidents/{id}', note: 'Retrieve incident dossier with full entity graph.' },
                  { method: 'POST', path: '/v2/incidents/{id}/action', note: 'Acknowledge, mitigate, or resolve an incident.' },
                  { method: 'GET', path: '/v2/merchants/{id}/baselines', note: 'Retrieve historical 168h MAD baseline distributions.' },
                ]}
              />
              <P>Example simulation invocation:</P>
              <Code>{`curl -X POST ${API_BASE_URL}/v2/demo/simulate \\
  -H 'Content-Type: application/json' \\
  -d '{
    "scenario_id": "card_testing_burst",
    "merchant_category": "electronics",
    "intensity": 1.0,
    "window_size": "5m",
    "seed": 42
  }'`}</Code>
            </>
          }
        />
      ),
    },
    {
      id: 'data-explorer',
      title: 'Synthetic Data Explorer',
      body: (
        <LayeredSection
          simpleTerms="Every demo run keeps its underlying synthetic transactions, features and entity graph available for a short while, so you can check exactly what data produced a verdict — not just the final number."
          technicalDetails={
            <>
              <P>
                Runs are held in a <strong>bounded, in-memory, per-process store</strong> — never
                written to disk or the operational database. At most 20 recent runs are retained,
                each expiring after 30 minutes, evicted oldest-first. A run belonging to another
                principal reads as <Inline>404</Inline>, never <Inline>403</Inline>, so a{' '}
                <Inline>run_id</Inline> cannot be used to probe another principal's activity.
              </P>
              <P>
                <Inline>GET /v2/demo/runs/&#123;run_id&#125;/transactions</Inline> pages the exact
                synthetic transactions behind a run: <Inline>?page=1&amp;page_size=50</Inline>,
                capped at a hard maximum of <strong>200</strong> per page — a larger request is
                rejected, not silently truncated. Every row carries a synthetic ground-truth flag
                and never a raw card number: Veyra rejects PAN-shaped identifiers at ingest, so
                there is nothing of that shape to redact here.
              </P>
              <P>
                <Inline>GET /v2/demo/runs/&#123;run_id&#125;/features</Inline> returns the full
                feature vector grouped by family, with each baseline-deviation twin attached to the
                raw feature it belongs to. <Inline>GET /v2/demo/runs/&#123;run_id&#125;/summary</Inline>{' '}
                returns composition (legitimate vs. abusive counts), time range and entity counts.
              </P>
              <P>
                <strong>Entity topology.</strong>{' '}
                <Inline>GET /v2/demo/runs/&#123;run_id&#125;/entities</Inline> reports customer,
                device, instrument and IP counts for the run, derived ratios (
                <Inline>instruments_per_customer</Inline>, <Inline>transactions_per_device</Inline>
                ), and the two Family-J concentration metrics computed by the entity graph engine:{' '}
                <Inline>largest_cluster_volume_share</Inline> and <Inline>bipartite_gini</Inline>.
                Every number is read directly off the run's own feature vector — the explorer cannot
                disagree with the verdict it explains.
              </P>
            </>
          }
        />
      ),
    },
    {
      id: 'scale-lab',
      title: 'Scale Lab',
      body: (
        <LayeredSection
          simpleTerms="The Scale Lab runs a real, bounded stress test against the system — generating and processing tens of thousands to millions of synthetic events — and reports exactly what happened, including when a run stops early or gets capped for safety."
          technicalDetails={
            <>
              <P>
                <Inline>POST /v2/demo/benchmarks</Inline> accepts a <Inline>workload_size</Inline>{' '}
                (1,000 to 100,000,000), a <Inline>duration_minutes</Inline> span, a{' '}
                <Inline>scenario_mix</Inline> or explicit <Inline>fraud_ratio</Inline>, and a{' '}
                <Inline>benchmark_mode</Inline> of <Inline>ingestion</Inline> (write-scale only) or{' '}
                <Inline>pipeline</Inline> (write-scale plus a sampled detection pass). It returns{' '}
                <strong>immediately</strong> with a <Inline>run_id</Inline> — a benchmark runs on a
                background worker so the caller never holds a connection open for a
                multi-hundred-thousand-event run. Poll{' '}
                <Inline>GET /v2/demo/benchmarks/&#123;run_id&#125;/progress</Inline> for a cheap
                status/stage snapshot, and{' '}
                <Inline>GET /v2/demo/benchmarks/&#123;run_id&#125;</Inline> for the full result once
                terminal.
              </P>
              <P>
                <strong>Completion statuses.</strong> A run reports exactly one of:
              </P>
              <div style={{ display: 'grid', gap: 6 }}>
                {[
                  ['completed', '#10b981', 'The (possibly capped) target was fully processed.'],
                  ['stopped_early', '#f59e0b', 'The wall-clock budget expired first — figures cover only the events that actually ran, never scaled up to the target.'],
                  ['capped', '#3b82f6', 'The safety ceiling lowered the target below what was requested, and that lowered target was reached.'],
                  ['failed', '#f93f28', 'The run raised an exception; error carries the detail.'],
                  ['rejected', '#f93f28', 'Refused before execution — nothing was generated. Currently the path for an experimental-tier (>10M) request when experimental benchmarks are disabled.'],
                ].map(([status, color, desc]) => (
                  <div
                    key={status}
                    style={{
                      display: 'grid',
                      gridTemplateColumns: '130px 1fr',
                      gap: 'var(--sp-3)',
                      padding: '8px 12px',
                      background: '#040711',
                      border: '1px solid var(--border-subtle)',
                      borderRadius: 'var(--radius-sm)',
                    }}
                  >
                    <span className="mono" style={{ fontSize: '12px', fontWeight: 700, color: color as string }}>
                      {status}
                    </span>
                    <span style={{ fontSize: '13px', color: '#cbd5e1', lineHeight: 1.6 }}>{desc}</span>
                  </div>
                ))}
              </div>
              <P>
                Precedence when more than one condition applies:{' '}
                <Inline>failed &gt; stopped_early &gt; capped &gt; completed</Inline>. A run that is
                both capped by the ceiling and then cut off by the wall-clock budget is reported{' '}
                <Inline>stopped_early</Inline> — it is never described as a successful completion.
                When set, <Inline>stop_reason</Inline> is currently always{' '}
                <Inline>wall_clock_budget_exceeded</Inline>; three further values (
                <Inline>safety_ceiling_reached</Inline>, <Inline>persistence_unavailable</Inline>,{' '}
                <Inline>internal_error</Inline>) are reserved in the schema for guardrail paths the
                current runner does not yet exercise.
              </P>
              <P>
                <strong>Result structure.</strong> <Inline>result</Inline> is nested by concern, and
                every group states its own unit:
              </P>
              <Code>{`result.traffic       requested / generated / processed events,
                      measured legitimate/fraud counts, actual_fraud_ratio
result.ingestion     events_persisted, write_duration_ms,
                      events_per_second   ← write throughput, NOT latency
result.computation   sampled_windows, per_window_latency_ms
                      ← cost per merchant-window, NOT per transaction
                      (null in ingestion mode)
result.memory        peak_traced_python_heap_mb
                      ← tracemalloc heap, NOT process RSS
result.storage       storage_delta_mb  ← SQLite file growth
result.samples       bounded legitimate / fraud / random
                      transaction samples (reservoir-sampled)
result.environment   database, python, platform, cpu_count
result.limitations   plain-language notes on capping,
                      early stops, or unreachable traffic mixes`}</Code>
              <P>
                <strong>Traffic composition is measured, not assumed.</strong>{' '}
                <Inline>traffic.legitimate_events</Inline> and <Inline>traffic.fraud_events</Inline>{' '}
                are counted from each generated transaction's own label; if a run stops early, those
                counts cover only the events that actually generated — nothing is scaled up to the
                request.
              </P>
              <P>
                <strong>Representative samples.</strong> A result carries a bounded set of
                transactions (8 per bucket by default) drawn by reservoir sampling across the whole
                run rather than "the first N generated" — which would only show the opening moments
                of one merchant's traffic. The full generated workload is never returned.
              </P>
              <P>
                <strong>Guardrails.</strong> <Inline>GET /v2/demo/benchmarks/presets</Inline> reports
                this server's configured ceilings directly, so a client never has to hardcode them:
              </P>
              <Code>{`hard_cap_events        2,000,000   events/run, absolute ceiling
max_seconds            120         wall-clock budget/run
chunk_size             20,000      events generated & persisted per chunk
max_sample_windows     150         merchant-windows sampled in pipeline mode
sample_rows_per_bucket 8           representative transactions per bucket
concurrent_jobs        1           benchmarks run one at a time
allow_experimental     true/false  gates >10M workloads (HTTP 403 when false)`}</Code>
              <P>
                Events are generated and persisted in bounded chunks — never materialized as one
                Python list — so a workload well beyond the ceiling cannot exhaust memory even
                before the ceiling engages. Every workload preset is classified by tier:{' '}
                <strong>safe</strong> (100K–1M), <strong>extended</strong> (10M), or{' '}
                <strong>experimental</strong> (100M) — and every run's rows are deleted from the
                database before the result is returned.
              </P>
            </>
          }
        />
      ),
    },
    {
      id: 'data-privacy',
      title: 'Data privacy & security',
      body: (
        <LayeredSection
          simpleTerms="Veyra protects customer privacy by never storing credit card numbers, tokenizing identifiers with cryptography, and isolating each merchant's data."
          technicalDetails={
            <>
              <P>
                <strong>Zero PAN Storage</strong>: Raw 16-digit credit card numbers and CVVs are never persisted. Payment instruments are tokenized via salted HMAC-SHA256 blind indexing (<Inline>ins_tok_...</Inline>).
              </P>
              <P>
                <strong>PII Encryption</strong>: Customer personal data (emails, names, phone numbers) is encrypted at rest using AES-GCM-256 with unique 12-byte initialization vectors per record.
              </P>
              <P>
                <strong>Row-Level Tenant Isolation</strong>: Database queries strictly enforce <Inline>where(Table.merchant_id == authenticated_merchant)</Inline> to prevent cross-tenant data exposure.
              </P>
              <P>
                <strong>Fail-Closed Secrets</strong>: In a production profile, the backend validates cryptographic peppers on startup and terminates if required keys are missing or insecure.
              </P>
            </>
          }
        />
      ),
    },
    {
      id: 'evaluation-methodology',
      title: 'Evaluation methodology',
      body: (
        <LayeredSection
          simpleTerms="Veyra is tested against both cyberattacks and tricky normal situations (like flash sales) to prove it doesn't cause false alarms."
          technicalDetails={
            <>
              <P>
                The evaluation harness tests across synthetic episode streams generated from reproducible seeds.
              </P>
              <P>
                <strong>Hard Negatives</strong>: The suite explicitly includes legitimate lookalikes: midnight flash sales, gateway retry storms, bulk renewals, and family device sharing. Naive velocity rules score poorly on these tests by design.
              </P>
              <P>
                <strong>Zero Target Leakage Verification</strong>: Evaluated using strict episode splitting where historical training partitions are insulated from test periods by frozen holdout boundaries.
              </P>
            </>
          }
        />
      ),
    },
    {
      id: 'limitations',
      title: 'System limitations',
      body: (
        <LayeredSection
          simpleTerms="Veyra is a working research prototype evaluated on synthetic scenarios; it is not yet tested on live banking rails or certified for PCI-DSS compliance."
          technicalDetails={
            <>
              <P>Important engineering boundaries:</P>
              <ul style={{ display: 'grid', gap: '10px', margin: 0, paddingLeft: '1.2rem', color: '#cbd5e1', fontSize: '14px', lineHeight: 1.65 }}>
                <li>All evaluation figures derive from controlled synthetic data generators; no live bank production records were analyzed.</li>
                <li>Entity graphs are constructed per temporal window; syndicates spreading transactions over days without shared window presence require multi-window graph stitching.</li>
                <li>Baselines require historical depth; newly onboarded merchants fall back to category medians with lower confidence ratings.</li>
                <li>Scale Lab throughput reflects local execution against SQLite on this server, not distributed cloud infrastructure — the results describe this environment, not production capacity.</li>
                <li>At the default 120-second wall-clock budget, workloads at or above roughly 500K events typically report <Inline>stopped_early</Inline> rather than <Inline>completed</Inline> on this machine; the figures returned are honest for the events that actually ran.</li>
                <li>The demo scoring model is intentionally small — trained on one merchant profile over one week, so a browser click does not wait minutes for a fit — and does not carry the statistical power of the offline evaluation harness in <Inline>scripts/run_experiment.py</Inline>. Demo verdicts illustrate the pipeline; published benchmark numbers are the evaluation to cite.</li>
                <li>Veyra provides decision recommendations; automated payment blocking must be configured and governed by merchant risk policies.</li>
                <li>Veyra holds no formal PCI-DSS, SOC 2, or card network certification.</li>
              </ul>
            </>
          }
        />
      ),
    },
  ];
}

/* ------------------------------------------------------------------ page */

export function DocumentationPage() {
  const sections = buildSections();
  const [activeId, setActiveId] = useState(sections[0].id);

  useEffect(() => {
    const observer = new IntersectionObserver(
      (entries) => {
        const visible = entries
          .filter((e) => e.isIntersecting)
          .sort((a, b) => a.boundingClientRect.top - b.boundingClientRect.top);
        if (visible[0]) setActiveId(visible[0].target.id);
      },
      { rootMargin: '-80px 0px -70% 0px' },
    );

    sections.forEach((s) => {
      const el = document.getElementById(s.id);
      if (el) observer.observe(el);
    });

    return () => observer.disconnect();
  }, [sections]);

  const scrollTo = (id: string) => {
    const el = document.getElementById(id);
    if (!el) return;
    const top = el.getBoundingClientRect().top + window.scrollY - 84;
    window.scrollTo({ top, behavior: 'smooth' });
  };

  return (
    <div className="container" style={{ padding: 'var(--sp-7) var(--sp-5) var(--sp-9)' }}>
      <header style={{ display: 'grid', gap: 'var(--sp-3)', maxWidth: 760, marginBottom: 'var(--sp-6)' }}>
        <SectionLabel>Developer documentation</SectionLabel>
        <h1 style={{ fontFamily: 'var(--font-display)', fontSize: 'var(--text-3xl)', fontWeight: 700 }}>
          Veyra Technical Reference
        </h1>
        <p style={{ fontSize: '17px', color: '#cbd5e1', lineHeight: 1.65 }}>
          Architectural contracts, feature definitions, and integration reference. Structured in two layers: plain-language concepts for rapid evaluation, followed by engineering specifications.
        </p>
      </header>

      <div
        style={{
          display: 'grid',
          gridTemplateColumns: 'minmax(200px, 240px) 1fr',
          gap: 'var(--sp-6)',
          alignItems: 'start',
        }}
        className="veyra-docs-grid"
      >
        {/* Sticky side nav */}
        <nav
          aria-label="Documentation sections"
          style={{
            position: 'sticky',
            top: 'calc(var(--nav-h) + 20px)',
            display: 'grid',
            gap: 4,
            paddingRight: 'var(--sp-3)',
            borderRight: '1px solid var(--border-subtle)',
          }}
        >
          {sections.map((s) => {
            const active = s.id === activeId;
            return (
              <button
                key={s.id}
                onClick={() => scrollTo(s.id)}
                style={{
                  textAlign: 'left',
                  padding: '7px 12px',
                  background: active ? 'rgba(37, 99, 235, 0.1)' : 'transparent',
                  border: 'none',
                  borderLeft: active ? '2px solid #3b82f6' : '2px solid transparent',
                  borderRadius: '0 var(--radius-sm) var(--radius-sm) 0',
                  color: active ? '#ffffff' : '#94a3b8',
                  fontSize: '13px',
                  fontWeight: active ? 600 : 400,
                  transition: 'color 0.15s, background 0.15s',
                  cursor: 'pointer',
                }}
              >
                {s.title}
              </button>
            );
          })}
        </nav>

        {/* Section bodies */}
        <div style={{ display: 'grid', gap: 'var(--sp-7)' }}>
          {sections.map((s) => (
            <section key={s.id} id={s.id} style={{ display: 'grid', gap: 'var(--sp-4)', scrollMarginTop: 96 }}>
              <h2
                style={{
                  fontFamily: 'var(--font-display)',
                  fontSize: '24px',
                  fontWeight: 700,
                  color: '#ffffff',
                  paddingBottom: '8px',
                  borderBottom: '1px solid rgba(255, 255, 255, 0.08)',
                }}
              >
                {s.title}
              </h2>
              {s.body}
            </section>
          ))}
        </div>
      </div>
    </div>
  );
}
