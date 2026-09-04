/** Architecture.
 *
 * A walkable map of the real pipeline. Each stage names the module that
 * implements it and the ADR that decided it, so a technical reader can go from
 * this page straight to the code. Stage names match the `stages` array the API
 * returns for a live detection — nothing here is an invented layer.
 */

import { useState } from 'react';
import { ArrowRight, FileText, ShieldCheck } from 'lucide-react';
import { Badge, Card, SectionLabel } from '../components/ui';

interface Stage {
  id: string;
  index: string;
  name: string;
  oneLiner: string;
  module: string;
  adr?: string;
  purpose: string;
  inputs: string;
  outputs: string;
  why: string;
  tradeoff: string;
  boundary?: boolean;
}

const STAGES: Stage[] = [
  {
    id: 'ingestion',
    index: '01',
    name: 'Event ingestion',
    oneLiner: 'Accept transaction envelopes and persist them durably.',
    module: 'app/ingestion/service.py',
    purpose:
      'Takes payment events from the merchant and writes them to durable storage before any scoring happens, so a detection can always be reconstructed from what was actually received.',
    inputs: 'Transaction envelopes — amount, instrument token, device fingerprint, network address, outcome.',
    outputs: 'Persisted raw event rows, keyed by merchant and timestamp.',
    why: 'Scoring against an in-memory stream cannot be audited afterwards. Writing first means every incident has evidence that outlives the request.',
    tradeoff:
      'Durable writes dominate end-to-end latency — visible in the Performance Lab, where ingestion is most of the elapsed time and inference is a rounding error.',
  },
  {
    id: 'windows',
    index: '02',
    name: 'Temporal aggregation',
    oneLiner: 'Slice traffic into merchant-windows at four horizons.',
    module: 'app/windows.py',
    adr: 'ADR-001, ADR-002',
    purpose:
      'Groups events into the unit the system actually reasons about: one merchant over one window. The same traffic is cut at 1m, 5m, 15m and 1h.',
    inputs: 'Raw events for a merchant, plus a window size and end time.',
    outputs: 'A merchant-window: the ordered set of events strictly inside that horizon.',
    why: 'The detection unit is the merchant-window, not the individual transaction. Coordination is a property of a group, and a single payment carries no evidence of it.',
    tradeoff:
      'Multiple horizons cost more compute than one. It buys the ability to catch both a sharp burst and a slow ramp built specifically to stay under a short-window threshold.',
  },
  {
    id: 'baseline',
    index: '03',
    name: 'Historical baseline',
    oneLiner: 'Compare against this merchant at this hour of the week.',
    module: 'app/features/ (baselines)',
    adr: 'ADR-002',
    purpose:
      'Holds a per-merchant, per-hour-of-week expected median and variability for each feature, and measures how far the current window sits from it.',
    inputs: 'Historical windows for the merchant; the current feature vector.',
    outputs: 'Deviation in MAD units, plus a confidence level reflecting how much history backs it.',
    why: 'Busy is relative. A grocery merchant at Sunday noon and a gaming merchant at 3am have completely different normals, and a global threshold is wrong for both.',
    tradeoff:
      'Median absolute deviation resists having its notion of normal dragged along by a past attack, but it needs enough history to be meaningful — which is why confidence is reported rather than assumed.',
  },
  {
    id: 'features',
    index: '04',
    name: 'Contextual features',
    oneLiner: 'Compute 79 features across ten families.',
    module: 'app/features/engine.py',
    adr: 'ADR-004',
    purpose:
      'Turns a window into a feature vector: transaction rates, amount distributions, instrument novelty, decline velocity, entropy measures, account age, and more.',
    inputs: 'The merchant-window and its baseline.',
    outputs: 'A 79-dimension feature vector, family-tagged (A–J).',
    why: 'These are the quantities that separate a flash sale from card testing once volume is held constant.',
    tradeoff:
      'Downstream signals — chargebacks, confirmed fraud labels — are structurally barred from the feature set. They would raise offline scores and be unavailable at decision time, which is the classic leakage trap.',
  },
  {
    id: 'graph',
    index: '05',
    name: 'Entity graph',
    oneLiner: 'Link accounts, devices, instruments and networks.',
    module: 'app/graph/',
    purpose:
      'Builds a bipartite graph over the window connecting customers to the devices, payment instruments and network addresses they transacted through, then measures concentration and cluster size.',
    inputs: 'Events in the window, with their entity identifiers.',
    outputs: 'Nodes, edges, and cluster metrics such as largest connected component size.',
    why: 'Coordination is a shape, not a volume. Fifty transactions across fifty devices and fifty transactions across three devices look identical to a counter and nothing alike to a graph.',
    tradeoff:
      'Graph construction is per-window rather than a persistent global graph — cheaper and privacy-preserving, at the cost of not seeing rings that span windows.',
  },
  {
    id: 'fusion',
    index: '06',
    name: 'Fusion',
    oneLiner: 'Combine the signals into one calibrated score.',
    module: 'app/models_ml/fusion.py',
    purpose:
      'Weighs the volume, contextual and graph detectors into a single risk score for the window.',
    inputs: 'Feature vector, baseline deviations, graph metrics.',
    outputs: 'A risk score in [0, 1].',
    why: 'Each detector alone is either too blunt or too narrow. Volume flags every sale; graph signals alone miss attacks that are fast but not concentrated.',
    tradeoff:
      'Fusion is harder to explain than a single rule, which is why the forensic stage exists downstream — the score never ships without its evidence.',
  },
  {
    id: 'incident',
    index: '07',
    name: 'Incident detection',
    oneLiner: 'Persist a scored window worth acting on.',
    module: 'app/api/v2/incidents.py',
    purpose:
      'Turns a scored window that crosses the acting threshold into a durable incident record an analyst can retrieve, annotate and resolve.',
    inputs: 'Scored window, decision tier, evidence payload.',
    outputs: 'An incident with id, status, evidence and analyst notes.',
    why: 'A score that vanishes after the response is not operationally useful. Incidents give the merchant a queue and a history.',
    tradeoff:
      'Persisting incidents adds write load and retention questions, accepted because an alert nobody can revisit is an alert nobody can act on.',
  },
  {
    id: 'policy',
    index: '08',
    name: 'Decision policy',
    oneLiner: 'Map the score to one of four tiers.',
    module: 'app/decision/policy.py',
    adr: 'ADR-005, ADR-006',
    purpose:
      'Selects OBSERVE, ALERT, REVIEW or RESTRICT, and computes the financial exposure behind the recommendation.',
    inputs: 'Risk score, dominant scenario, merchant cost assumptions.',
    outputs: 'An action tier, a recommended defensive control, and an exposure breakdown.',
    why: 'Thresholds are chosen by expected loss, not by picking a round number. The cost of blocking a real customer and the cost of missing an attack are both declared constants.',
    tradeoff:
      'The system recommends and never automatically blocks. That deliberately leaves value on the table in exchange for never silently cutting off a merchant’s legitimate revenue on a model’s say-so.',
  },
  {
    id: 'forensics',
    index: '09',
    name: 'Forensic explanation',
    oneLiner: 'State why, in language a human can check.',
    module: 'app/explanations/generator.py',
    purpose:
      'Produces the narrative, the ranked feature deviations, and the entity-graph payload that justify the score.',
    inputs: 'Score, tier, feature deviations, graph, exposure.',
    outputs: 'A written summary plus structured evidence, exportable as Markdown or CSV.',
    why: 'An analyst has to be able to disagree with the model. That requires seeing the evidence, not just the number.',
    tradeoff:
      'Generated narrative can only describe what the features captured; it explains the model’s reasoning, and is not an independent investigation.',
  },
  {
    id: 'security',
    index: '10',
    name: 'Security boundary',
    oneLiner: 'Authenticate, scope to tenant, protect identifiers.',
    module: 'app/core/auth.py · app/core/crypto.py',
    purpose:
      'Resolves the authenticated principal, narrows every query to the merchants that principal may see, and tokenizes or encrypts sensitive identifiers at rest.',
    inputs: 'Credentials, requested merchant scope.',
    outputs: 'A principal with a resolved, non-wideable tenant scope.',
    why: 'Multi-tenant fraud data is exactly the data you cannot afford to leak between tenants.',
    tradeoff:
      'Scope resolution runs on every request rather than being cached per session — a small cost per call for the guarantee that a client-supplied merchant id can only ever narrow access.',
    boundary: true,
  },
];

export function ArchitecturePage() {
  const [activeId, setActiveId] = useState(STAGES[0].id);
  const active = STAGES.find((s) => s.id === activeId) ?? STAGES[0];

  return (
    <div className="container" style={{ padding: 'var(--sp-7) var(--sp-5) var(--sp-9)' }}>
      <header style={{ display: 'grid', gap: 'var(--sp-3)', maxWidth: 760, marginBottom: 'var(--sp-5)' }}>
        <SectionLabel>Architecture</SectionLabel>
        <h1 style={{ fontSize: 'var(--text-2xl)', fontWeight: 700 }}>How a transaction becomes a decision.</h1>
        <p style={{ fontSize: 'var(--text-md)', color: 'var(--text-secondary)', lineHeight: 1.65 }}>
          Ten stages, in the order they run. Select any one to see what it takes in, what it hands
          on, and the engineering tradeoff behind it.
        </p>
      </header>

      {/* Technical Honesty: Three Scoring Paths */}
      <div
        style={{
          background: 'var(--surface-1)',
          border: '1px solid rgba(59, 130, 246, 0.25)',
          borderRadius: 'var(--radius-md)',
          padding: '16px 20px',
          marginBottom: 'var(--sp-6)',
          display: 'grid',
          gap: 12,
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <ShieldCheck size={16} color="var(--accent-bright)" />
          <span style={{ fontFamily: 'var(--font-mono)', fontSize: '11px', fontWeight: 700, letterSpacing: '0.05em', color: 'var(--accent-bright)', textTransform: 'uppercase' }}>
            Technical Honesty: Three Distinct Scoring Paths
          </span>
        </div>

        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(240px, 1fr))', gap: 14, marginTop: 4 }}>
          <div style={{ background: 'rgba(255, 255, 255, 0.02)', padding: 12, borderRadius: 6, border: '1px solid rgba(255, 255, 255, 0.05)' }}>
            <div style={{ fontFamily: 'var(--font-mono)', fontSize: '11px', fontWeight: 700, color: 'var(--color-safe)' }}>
              1. LIVE PRODUCTION PATH
            </div>
            <div style={{ fontSize: '11px', color: 'var(--text-muted)', fontFamily: 'var(--font-mono)', marginTop: 2 }}>
              POST /v2/score-window
            </div>
            <p style={{ fontSize: '12px', color: 'var(--text-secondary)', marginTop: 6, lineHeight: 1.5 }}>
              Operates on persisted database events for a merchant, compares against 168-hour historical baselines, evaluates loss-minimizing thresholds, and persists alerts into the durable incident store (<code>app/serving/scoring_service.py</code>).
            </p>
          </div>

          <div style={{ background: 'rgba(255, 255, 255, 0.02)', padding: 12, borderRadius: 6, border: '1px solid rgba(255, 255, 255, 0.05)' }}>
            <div style={{ fontFamily: 'var(--font-mono)', fontSize: '11px', fontWeight: 700, color: 'var(--accent-bright)' }}>
              2. DEMO MODEL-BACKED PATH
            </div>
            <div style={{ fontSize: '11px', color: 'var(--text-muted)', fontFamily: 'var(--font-mono)', marginTop: 2 }}>
              POST /v2/demo/simulate
            </div>
            <p style={{ fontSize: '12px', color: 'var(--text-secondary)', marginTop: 6, lineHeight: 1.5 }}>
              Generates scenario traffic live, extracts features, and scores with a fitted <code>HistGradientBoostingClassifier</code> ensemble (<code>veyra_fusion_demo</code>). Holds results in a bounded in-memory store for synthetic inspection (<code>app/serving/demo_model_service.py</code>).
            </p>
          </div>

          <div style={{ background: 'rgba(255, 255, 255, 0.02)', padding: 12, borderRadius: 6, border: '1px solid rgba(255, 255, 255, 0.05)' }}>
            <div style={{ fontFamily: 'var(--font-mono)', fontSize: '11px', fontWeight: 700, color: 'var(--color-warning)' }}>
              3. OFFLINE EVALUATION PATH
            </div>
            <div style={{ fontSize: '11px', color: 'var(--text-muted)', fontFamily: 'var(--font-mono)', marginTop: 2 }}>
              app/evaluation/
            </div>
            <p style={{ fontSize: '12px', color: 'var(--text-secondary)', marginTop: 6, lineHeight: 1.5 }}>
              Batch evaluation harness over historical synthetic corpora. Measures ROC-AUC, PR-AUC, expected financial loss curves, and calibration across seed permutations without touching serving paths.
            </p>
          </div>
        </div>
      </div>

      {/* Demo execution trace: the 12 real, server-timed stages POST /v2/demo/simulate returns */}
      <div
        style={{
          background: 'var(--surface-1)',
          border: '1px solid var(--border-subtle)',
          borderRadius: 'var(--radius-md)',
          padding: '16px 20px',
          marginBottom: 'var(--sp-6)',
          display: 'grid',
          gap: 12,
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <ArrowRight size={16} color="var(--accent-bright)" />
          <span className="mono" style={{ fontSize: '11px', fontWeight: 700, letterSpacing: '0.05em', color: 'var(--accent-bright)', textTransform: 'uppercase' }}>
            Demo execution trace — 12 stages
          </span>
        </div>
        <p style={{ fontSize: '13px', color: 'var(--text-secondary)', lineHeight: 1.6, maxWidth: 720 }}>
          Every <code>POST /v2/demo/simulate</code> call returns a <code>stages</code> array: real,
          server-timed steps in the order they actually ran, each carrying a stable{' '}
          <code>id</code>, its <code>sequence</code>, a <code>duration_ms</code> measured with{' '}
          <code>time.perf_counter()</code>, and wall-clock <code>started_at</code>/<code>ended_at</code>{' '}
          stamps. This is the request-level execution trace for one detection run — a finer
          granularity than the ten module stages on the left, which describe the codebase, not one
          call.
        </p>
        <div style={{ overflowX: 'auto' }}>
          <table style={{ width: '100%', borderCollapse: 'collapse', minWidth: 640 }}>
            <thead>
              <tr>
                {['#', 'Stage id', 'What it does'].map((h) => (
                  <th
                    key={h}
                    className="eyebrow"
                    style={{ textAlign: 'left', padding: '6px 12px 6px 0', borderBottom: '1px solid var(--border-subtle)', fontSize: '10px', color: 'var(--text-muted)' }}
                  >
                    {h}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {[
                ['generation', 'Generate an hour of organic synthetic traffic for a fresh merchant profile.'],
                ['injection', 'Splice the chosen scenario recipe (attack or benign surge) into that traffic.'],
                ['windowing', 'Slice the merged stream to the requested window (1m/5m/15m/1h), past-only.'],
                ['baseline', 'Load the demo model and its frozen training-corpus baselines (cached after the first call).'],
                ['features', 'Extract families A–I over the window with FeatureEngine.'],
                ['graph', 'Build the bipartite entity graph and family-J concentration metrics.'],
                ['deviation', 'Compute MAD deviation twins against the frozen baselines.'],
                ['inference', 'Score model_features through the fitted VeyraFusionDetector.'],
                ['policy', 'Map the score to OBSERVE / ALERT / REVIEW / RESTRICT via DecisionPolicy.'],
                ['exposure', 'Estimate financial exposure from GMV, transaction count and the decided tier.'],
                ['forensics', 'Generate the narrative, ranked deviations and entity-graph payload.'],
                ['run_record', 'Store the run in the bounded in-memory run store for the Data Explorer.'],
              ].map(([id, desc], i) => (
                <tr key={id}>
                  <td className="mono" style={{ padding: '7px 12px 7px 0', borderBottom: '1px solid var(--border-subtle)', fontSize: '11px', color: 'var(--text-muted)' }}>
                    {String(i + 1).padStart(2, '0')}
                  </td>
                  <td className="mono" style={{ padding: '7px 12px 7px 0', borderBottom: '1px solid var(--border-subtle)', fontSize: '12px', color: 'var(--accent-bright)', whiteSpace: 'nowrap' }}>
                    {id}
                  </td>
                  <td style={{ padding: '7px 0', borderBottom: '1px solid var(--border-subtle)', fontSize: '12px', color: 'var(--text-secondary)', lineHeight: 1.55 }}>
                    {desc}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <p style={{ fontSize: '12px', color: 'var(--text-muted)', lineHeight: 1.6, marginTop: 2 }}>
          Each stage carries a <code>status</code> of <code>pending</code>, <code>running</code>,{' '}
          <code>completed</code>, <code>failed</code> or <code>skipped</code>; a finished response
          only ever contains <code>completed</code> (or <code>failed</code>, if a stage raised). The
          <em> ground-truth label</em> for the chosen scenario is read only after stage 8 has already
          produced a score — it populates the response's <code>ground_truth</code> block for
          comparison and is never an input to <code>inference</code>.
        </p>
      </div>

      <div
        className="veyra-split"
        style={{
          display: 'grid',
          gridTemplateColumns: 'minmax(250px, 330px) 1fr',
          gap: 'var(--sp-5)',
          alignItems: 'start',
        }}
      >
        {/* ---------------------------------------------------- stage rail */}
        <nav aria-label="Pipeline stages" style={{ display: 'grid', gap: 6 }}>
          {STAGES.map((stage, i) => {
            const selected = stage.id === activeId;
            return (
              <div key={stage.id} style={{ display: 'grid', gap: 6 }}>
                <button
                  onClick={() => setActiveId(stage.id)}
                  aria-current={selected ? 'true' : undefined}
                  style={{
                    display: 'grid',
                    gridTemplateColumns: '30px 1fr',
                    alignItems: 'center',
                    gap: 'var(--sp-3)',
                    textAlign: 'left',
                    padding: 'var(--sp-3)',
                    background: selected ? 'var(--surface-2)' : 'transparent',
                    border: `1px solid ${selected ? 'var(--accent-line)' : 'var(--border-subtle)'}`,
                    borderRadius: 'var(--radius)',
                    color: 'inherit',
                    transition: 'background 0.15s, border-color 0.15s',
                  }}
                >
                  <span
                    className="mono"
                    style={{
                      fontSize: 'var(--text-xs)',
                      color: selected ? 'var(--accent-bright)' : 'var(--text-muted)',
                    }}
                  >
                    {stage.index}
                  </span>
                  <span style={{ display: 'grid', gap: 2, minWidth: 0 }}>
                    <span
                      style={{
                        fontSize: 'var(--text-sm)',
                        fontWeight: selected ? 600 : 500,
                        color: selected ? 'var(--text-primary)' : 'var(--text-secondary)',
                      }}
                    >
                      {stage.name}
                    </span>
                    <span style={{ fontSize: 'var(--text-xs)', color: 'var(--text-muted)', lineHeight: 1.45 }}>
                      {stage.oneLiner}
                    </span>
                  </span>
                </button>
                {i < STAGES.length - 1 && (
                  <span
                    aria-hidden
                    style={{
                      justifySelf: 'start',
                      marginLeft: 21,
                      width: 1,
                      height: 10,
                      background: 'var(--border)',
                    }}
                  />
                )}
              </div>
            );
          })}
        </nav>

        {/* --------------------------------------------------- stage detail */}
        <Card style={{ display: 'grid', gap: 'var(--sp-5)', position: 'sticky', top: 'calc(var(--nav-h) + 16px)' }}>
          <div style={{ display: 'grid', gap: 'var(--sp-3)' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--sp-3)', flexWrap: 'wrap' }}>
              <span className="mono" style={{ fontSize: 'var(--text-sm)', color: 'var(--accent-bright)' }}>
                {active.index}
              </span>
              <h2 style={{ fontSize: 'var(--text-xl)' }}>{active.name}</h2>
              {active.boundary && (
                <Badge color="var(--accent-bright)" background="var(--accent-wash)">
                  <ShieldCheck size={12} /> Cross-cutting
                </Badge>
              )}
            </div>
            <p style={{ fontSize: 'var(--text-md)', color: 'var(--text-secondary)', lineHeight: 1.65 }}>
              {active.purpose}
            </p>
          </div>

          <div
            style={{
              display: 'grid',
              gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))',
              gap: 'var(--sp-4)',
              padding: 'var(--sp-4)',
              background: 'var(--bg-sunken)',
              borderRadius: 'var(--radius)',
              border: '1px solid var(--border-subtle)',
            }}
          >
            <div style={{ display: 'grid', gap: 6 }}>
              <span className="eyebrow">Inputs</span>
              <p style={{ fontSize: 'var(--text-sm)', color: 'var(--text-secondary)', lineHeight: 1.6 }}>
                {active.inputs}
              </p>
            </div>
            <div style={{ display: 'grid', gap: 6 }}>
              <span className="eyebrow" style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                <ArrowRight size={11} /> Outputs
              </span>
              <p style={{ fontSize: 'var(--text-sm)', color: 'var(--text-secondary)', lineHeight: 1.6 }}>
                {active.outputs}
              </p>
            </div>
          </div>

          <div style={{ display: 'grid', gap: 'var(--sp-2)' }}>
            <span className="eyebrow">Why it exists</span>
            <p style={{ fontSize: 'var(--text-sm)', color: 'var(--text-secondary)', lineHeight: 1.7 }}>
              {active.why}
            </p>
          </div>

          <div
            style={{
              display: 'grid',
              gap: 'var(--sp-2)',
              padding: 'var(--sp-4)',
              background: 'var(--accent-wash)',
              border: '1px solid var(--accent-line)',
              borderRadius: 'var(--radius)',
            }}
          >
            <span className="eyebrow" style={{ color: 'var(--accent-bright)' }}>
              Engineering tradeoff
            </span>
            <p style={{ fontSize: 'var(--text-sm)', color: 'var(--text-secondary)', lineHeight: 1.7 }}>
              {active.tradeoff}
            </p>
          </div>

          <div
            style={{
              display: 'flex',
              flexWrap: 'wrap',
              gap: 'var(--sp-3)',
              paddingTop: 'var(--sp-4)',
              borderTop: '1px solid var(--border-subtle)',
              alignItems: 'center',
            }}
          >
            <span className="eyebrow">Implemented in</span>
            <code
              className="mono"
              style={{
                fontSize: 'var(--text-xs)',
                color: 'var(--text-secondary)',
                background: 'var(--surface-2)',
                border: '1px solid var(--border-subtle)',
                borderRadius: 'var(--radius-sm)',
                padding: '3px 8px',
              }}
            >
              {active.module}
            </code>
            {active.adr && (
              <span
                style={{
                  display: 'inline-flex',
                  alignItems: 'center',
                  gap: 5,
                  fontSize: 'var(--text-xs)',
                  color: 'var(--text-muted)',
                }}
              >
                <FileText size={12} />
                {active.adr}
              </span>
            )}
          </div>
        </Card>
      </div>

      {/* Scale Lab: a separate pipeline, benchmark-environment measurements, not production capacity */}
      <div style={{ marginTop: 'var(--sp-7)', display: 'grid', gap: 'var(--sp-4)' }}>
        <header style={{ display: 'grid', gap: 6, maxWidth: 760 }}>
          <SectionLabel>Scale Lab</SectionLabel>
          <h2 style={{ fontSize: 'var(--text-xl)', fontWeight: 700 }}>
            A separate pipeline for one question: how does the system behave as workload grows?
          </h2>
          <p style={{ fontSize: 'var(--text-md)', color: 'var(--text-secondary)', lineHeight: 1.65 }}>
            Scale Lab (<code>POST /v2/demo/benchmarks</code>) does not run the Detection pipeline
            above at scale — it runs its own bounded, chunked benchmark against the real detector
            and the real database, and reports what it actually measured. Numbers describe this
            server, not a production deployment.
          </p>
        </header>

        <Card style={{ display: 'grid', gap: 'var(--sp-4)' }}>
          <div style={{ display: 'grid', gap: 'var(--sp-2)' }}>
            <span className="eyebrow">Benchmark lifecycle</span>
            <div style={{ display: 'grid', gap: 6 }}>
              {[
                ['Request validation', 'workload_size, duration_minutes, scenario_mix / fraud_ratio, benchmark_mode ("ingestion" or "pipeline") are validated; an experimental-tier request is refused outright if experimental benchmarks are disabled.'],
                ['Guardrail resolution', 'The requested workload is capped to the configured hard ceiling before anything runs. POST returns immediately with a run_id — the benchmark itself runs on a background worker.'],
                ['Chunked synthetic generation', 'Events are generated and persisted in bounded chunks (never the whole workload held in memory at once), split into legitimate and fraud traffic to match the requested mix.'],
                ['Ingestion measurement', 'Each chunk is written to the real database; generation, validation and persistence timing accumulate into the ingestion figures.'],
                ['Sampled computation (pipeline mode only)', 'A bounded sample of merchant-windows — not the whole workload — is run through feature extraction, entity graph construction and model inference, with per-window timing.'],
                ['Resource measurement', 'Peak traced Python heap (tracemalloc) and database file growth are measured across the run.'],
                ['Representative sampling', 'A bounded, reservoir-sampled set of legitimate, fraud and random transactions is retained as inspectable evidence — never the full generated workload.'],
                ['Cleanup', 'Every row the benchmark wrote is deleted before the result is returned, so a benchmark never leaves synthetic volume behind in the database.'],
                ['Result serialization', 'A structured result is written back to the run record, polled via progress and result endpoints until the run reaches a terminal status.'],
              ].map(([step, desc], i) => (
                <div
                  key={step}
                  style={{
                    display: 'grid',
                    gridTemplateColumns: '26px 200px 1fr',
                    gap: 'var(--sp-3)',
                    alignItems: 'baseline',
                    padding: '8px 0',
                    borderBottom: i < 8 ? '1px solid var(--border-subtle)' : 'none',
                  }}
                >
                  <span className="mono" style={{ fontSize: '11px', color: 'var(--text-muted)' }}>
                    {String(i + 1).padStart(2, '0')}
                  </span>
                  <span style={{ fontSize: '13px', fontWeight: 600, color: 'var(--text-primary)' }}>{step}</span>
                  <span style={{ fontSize: '13px', color: 'var(--text-secondary)', lineHeight: 1.6 }}>{desc}</span>
                </div>
              ))}
            </div>
          </div>
        </Card>

        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(260px, 1fr))', gap: 'var(--sp-4)' }}>
          <Card style={{ display: 'grid', gap: 8 }}>
            <span className="eyebrow" style={{ color: 'var(--accent-bright)' }}>Guardrails (configured)</span>
            <div style={{ display: 'grid', gap: 6, fontSize: '13px' }}>
              <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                <span style={{ color: 'var(--text-secondary)' }}>Hard event ceiling</span>
                <span className="mono" style={{ color: 'var(--text-primary)' }}>2,000,000</span>
              </div>
              <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                <span style={{ color: 'var(--text-secondary)' }}>Wall-clock budget</span>
                <span className="mono" style={{ color: 'var(--text-primary)' }}>120s</span>
              </div>
              <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                <span style={{ color: 'var(--text-secondary)' }}>Chunk size</span>
                <span className="mono" style={{ color: 'var(--text-primary)' }}>20,000 events</span>
              </div>
              <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                <span style={{ color: 'var(--text-secondary)' }}>Sampled windows (pipeline mode)</span>
                <span className="mono" style={{ color: 'var(--text-primary)' }}>150 max</span>
              </div>
              <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                <span style={{ color: 'var(--text-secondary)' }}>Concurrent benchmarks</span>
                <span className="mono" style={{ color: 'var(--text-primary)' }}>1</span>
              </div>
              <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                <span style={{ color: 'var(--text-secondary)' }}>Representative samples / bucket</span>
                <span className="mono" style={{ color: 'var(--text-primary)' }}>8</span>
              </div>
            </div>
            <p style={{ fontSize: '11px', color: 'var(--text-muted)', lineHeight: 1.5, marginTop: 4 }}>
              All configurable via <code>VEYRA_BENCHMARK_*</code> environment variables. A 100M
              request is capped to the ceiling before generation starts, and the wall-clock budget
              can stop it earlier still — a large request never freezes the server it runs on.
            </p>
          </Card>

          <Card style={{ display: 'grid', gap: 8 }}>
            <span className="eyebrow" style={{ color: 'var(--accent-bright)' }}>Completion statuses</span>
            <div style={{ display: 'grid', gap: 6, fontSize: '12.5px' }}>
              <div><code className="mono" style={{ color: 'var(--color-safe)' }}>completed</code> — the (possibly capped) target was fully processed.</div>
              <div><code className="mono" style={{ color: 'var(--color-warning)' }}>stopped_early</code> — the wall-clock budget expired first; figures cover only what ran.</div>
              <div><code className="mono" style={{ color: 'var(--accent-bright)' }}>capped</code> — the safety ceiling lowered the target, and that lowered target was reached.</div>
              <div><code className="mono" style={{ color: 'var(--color-critical)' }}>failed</code> — the run raised an exception.</div>
              <div><code className="mono" style={{ color: 'var(--color-critical)' }}>rejected</code> — refused before execution; nothing was generated.</div>
            </div>
            <p style={{ fontSize: '11px', color: 'var(--text-muted)', lineHeight: 1.5, marginTop: 4 }}>
              Precedence when more than one applies: <code>failed &gt; stopped_early &gt; capped &gt; completed</code>.
              A run that is both capped and cut off by the budget is reported <code>stopped_early</code>
              — it never reads as a plain completion.
            </p>
          </Card>
        </div>
      </div>
    </div>
  );
}
