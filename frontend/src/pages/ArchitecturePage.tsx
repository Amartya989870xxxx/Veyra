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
      <header style={{ display: 'grid', gap: 'var(--sp-3)', maxWidth: 760, marginBottom: 'var(--sp-6)' }}>
        <SectionLabel>Architecture</SectionLabel>
        <h1 style={{ fontSize: 'var(--text-2xl)' }}>How a transaction becomes a decision.</h1>
        <p style={{ fontSize: 'var(--text-md)', color: 'var(--text-secondary)', lineHeight: 1.65 }}>
          Ten stages, in the order they run. Select any one to see what it takes in, what it hands
          on, and the engineering tradeoff behind it.
        </p>
      </header>

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
    </div>
  );
}
