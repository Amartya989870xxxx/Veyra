/** Detection console — the core product surface.
 *
 * Layout is a risk-operations console, not a marketing page: a control rail on
 * the left, the verdict and its evidence on the right. Every value rendered
 * comes from POST /v2/demo/simulate. There is no offline fallback; a failed call
 * shows an error with a retry, because a fabricated success is worse than a
 * visible failure.
 */

import { useCallback, useEffect, useMemo, useState } from 'react';
import { AlertTriangle, ChevronRight, Play, ShieldCheck } from 'lucide-react';
import { ApiError, api } from '../api/client';
import type { ScenarioSummary, SimulationReport, WindowSize } from '../api/types';
import { deriveEvidence } from '../lib/evidence';
import {
  formatCount,
  formatMoney,
  formatPercent,
  formatTimestamp,
  formatTimestampUtc,
  humanizeControl,
  windowLabel,
} from '../lib/format';
import {
  MERCHANT_CATEGORIES,
  TIER_COPY,
  TIER_ORDER,
  WINDOW_OPTIONS,
  riskHeadline,
  riskLabel,
  scenarioSummary,
  tierColorVar,
  tierWashVar,
} from '../lib/scenarios';
import {
  Badge,
  Button,
  Card,
  Disclosure,
  EmptyState,
  ErrorState,
  InfoTip,
  LoadingBlock,
  SectionLabel,
  Skeleton,
  Stat,
  Tabs,
} from '../components/ui';
import { EntityGraph } from '../components/viz/EntityGraph';
import { PipelineTimeline } from '../components/viz/PipelineTimeline';
import { BaselineDeviation } from '../components/viz/BaselineDeviation';
import { ReportExporter } from '../components/reporting/ReportExporter';
import { NarrativeTypewriter } from '../components/viz/NarrativeTypewriter';

const TABS = [
  { id: 'why', label: 'Why it was flagged' },
  { id: 'pipeline', label: 'Detection pipeline' },
  { id: 'graph', label: 'Entity network' },
  { id: 'baseline', label: 'Historical comparison' },
  { id: 'events', label: 'Transaction events' },
];

export function DetectionPage({ initialScenario }: { initialScenario?: string }) {
  const [scenarios, setScenarios] = useState<ScenarioSummary[] | null>(null);
  const [scenariosError, setScenariosError] = useState<ApiError | null>(null);

  const [scenarioId, setScenarioId] = useState(initialScenario ?? 'card_testing_burst');
  const [category, setCategory] = useState<string>('electronics');
  const [intensity, setIntensity] = useState(1.0);
  const [windowSize, setWindowSize] = useState<WindowSize>('5m');

  const [result, setResult] = useState<SimulationReport | null>(null);
  const [running, setRunning] = useState(false);
  const [runError, setRunError] = useState<ApiError | null>(null);
  const [tab, setTab] = useState('why');

  const loadScenarios = useCallback(() => {
    setScenariosError(null);
    api
      .listScenarios()
      .then(setScenarios)
      .catch((e: ApiError) => setScenariosError(e));
  }, []);

  useEffect(loadScenarios, [loadScenarios]);

  useEffect(() => {
    if (initialScenario) setScenarioId(initialScenario);
  }, [initialScenario]);

  const runDetection = useCallback(async () => {
    setRunning(true);
    setRunError(null);
    try {
      const report = await api.runSimulation({
        scenario_id: scenarioId,
        merchant_category: category,
        intensity,
        window_size: windowSize,
        seed: 42,
      });
      setResult(report);
      setTab('why');
    } catch (e) {
      setRunError(e as ApiError);
      setResult(null);
    } finally {
      setRunning(false);
    }
  }, [scenarioId, category, intensity, windowSize]);

  const selectedScenario = scenarios?.find((s) => s.scenario_id === scenarioId);

  return (
    <div className="container-wide" style={{ padding: 'var(--sp-6) var(--sp-5) var(--sp-9)' }}>
      <div style={{ marginBottom: 'var(--sp-5)' }}>
        <SectionLabel>Detection console</SectionLabel>
        <h1 style={{ fontSize: 'var(--text-2xl)', marginTop: 6 }}>Run a detection</h1>
        <p style={{ color: 'var(--text-secondary)', marginTop: 8, maxWidth: 720, fontSize: 'var(--text-md)' }}>
          Generate a window of merchant traffic and send it through the full detection pipeline. Choose a
          scenario, then read what Veyra concluded and why.
        </p>
      </div>

      <div className="veyra-detection-grid">
        {/* ------------------------------------------------ control rail */}
        <aside style={{ display: 'grid', gap: 'var(--sp-4)', alignContent: 'start' }}>
          <Card style={{ display: 'grid', gap: 'var(--sp-5)' }}>
            <Step n={1} title="Choose a scenario" hint="What kind of traffic to generate.">
              {scenariosError ? (
                <ErrorState
                  title="Could not load scenarios"
                  detail={scenariosError.detail || scenariosError.message}
                  onRetry={loadScenarios}
                />
              ) : !scenarios ? (
                <div style={{ display: 'grid', gap: 8 }}>
                  <Skeleton height={38} />
                  <Skeleton height={38} />
                </div>
              ) : (
                <div style={{ display: 'grid', gap: 8 }}>
                  <label htmlFor="scenario" className="sr-only">
                    Scenario
                  </label>
                  <select
                    id="scenario"
                    value={scenarioId}
                    onChange={(e) => setScenarioId(e.target.value)}
                    style={selectStyle}
                  >
                    <optgroup label="Attacks">
                      {scenarios
                        .filter((s) => s.is_attack)
                        .map((s) => (
                          <option key={s.scenario_id} value={s.scenario_id}>
                            {s.name}
                          </option>
                        ))}
                    </optgroup>
                    <optgroup label="Legitimate surges (should not be flagged)">
                      {scenarios
                        .filter((s) => !s.is_attack)
                        .map((s) => (
                          <option key={s.scenario_id} value={s.scenario_id}>
                            {s.name}
                          </option>
                        ))}
                    </optgroup>
                  </select>
                  <p style={{ fontSize: 'var(--text-xs)', color: 'var(--text-secondary)', lineHeight: 1.6 }}>
                    {scenarioSummary(scenarioId, selectedScenario?.name ?? scenarioId)}
                  </p>
                </div>
              )}
            </Step>

            <Step n={2} title="Merchant category" hint="Sets the baseline traffic profile and basket sizes.">
              <label htmlFor="category" className="sr-only">
                Merchant category
              </label>
              <select id="category" value={category} onChange={(e) => setCategory(e.target.value)} style={selectStyle}>
                {MERCHANT_CATEGORIES.map((c) => (
                  <option key={c.value} value={c.value}>
                    {c.label}
                  </option>
                ))}
              </select>
            </Step>

            <Step
              n={3}
              title="Intensity"
              hint="How aggressive the generated activity is. Lower values are deliberately harder to detect."
            >
              <div style={{ display: 'grid', gap: 8 }}>
                <input
                  type="range"
                  min={0.2}
                  max={3}
                  step={0.1}
                  value={intensity}
                  onChange={(e) => setIntensity(Number(e.target.value))}
                  aria-label="Intensity"
                  style={{ width: '100%', accentColor: 'var(--accent)' }}
                />
                <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 'var(--text-xs)', color: 'var(--text-muted)' }}>
                  <span>Subtle</span>
                  <span className="mono" style={{ color: 'var(--accent-bright)' }}>
                    {intensity.toFixed(1)}×
                  </span>
                  <span>Aggressive</span>
                </div>
              </div>
            </Step>

            <Step n={4} title="Scoring horizon" hint="The length of the traffic window Veyra scores.">
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 6 }}>
                {WINDOW_OPTIONS.map((w) => {
                  const active = w.value === windowSize;
                  return (
                    <button
                      key={w.value}
                      onClick={() => setWindowSize(w.value as WindowSize)}
                      title={w.hint}
                      aria-pressed={active}
                      style={{
                        padding: '8px 4px',
                        background: active ? 'var(--accent-wash)' : 'var(--surface-2)',
                        border: `1px solid ${active ? 'var(--accent)' : 'var(--border)'}`,
                        borderRadius: 'var(--radius-sm)',
                        color: active ? 'var(--accent-bright)' : 'var(--text-secondary)',
                        fontFamily: 'var(--font-mono)',
                        fontSize: 'var(--text-xs)',
                        fontWeight: 600,
                      }}
                    >
                      {w.value}
                    </button>
                  );
                })}
              </div>
              <p style={{ fontSize: 'var(--text-xs)', color: 'var(--text-muted)', marginTop: 8, lineHeight: 1.5 }}>
                {WINDOW_OPTIONS.find((w) => w.value === windowSize)?.hint}
              </p>
            </Step>

            <Button
              variant="primary"
              size="lg"
              full
              loading={running}
              onClick={runDetection}
              icon={<Play size={16} />}
            >
              {running ? 'Running detection…' : 'Run detection'}
            </Button>
          </Card>

          <HonestyNote />
        </aside>

        {/* ------------------------------------------------------- results */}
        <main style={{ display: 'grid', gap: 'var(--sp-5)', alignContent: 'start', minWidth: 0 }}>
          {running && (
            <Card>
              <LoadingBlock label="Generating traffic and scoring the window…" rows={4} />
            </Card>
          )}

          {!running && runError && (
            <ErrorState
              title={runError.isNetwork ? 'Detection engine unavailable' : 'Detection failed'}
              detail={
                runError.detail ||
                'The Veyra API did not return a result. Check that the backend is running and reachable.'
              }
              onRetry={runDetection}
            />
          )}

          {!running && !runError && !result && (
            <Card padded={false}>
              <EmptyState
                title="No detection run yet"
                detail="Pick a scenario on the left and select Run detection. Veyra will generate a window of traffic, score it, and explain the result."
                action={
                  <Button variant="primary" onClick={runDetection} icon={<Play size={15} />}>
                    Run detection
                  </Button>
                }
              />
            </Card>
          )}

          {!running && result && <ResultView result={result} onTabChange={setTab} tab={tab} />}
        </main>
      </div>
    </div>
  );
}

/* ------------------------------------------------------------------ parts */

const selectStyle: React.CSSProperties = {
  width: '100%',
  padding: '9px 11px',
  background: 'var(--surface-2)',
  border: '1px solid var(--border)',
  borderRadius: 'var(--radius-sm)',
  color: 'var(--text-primary)',
  fontSize: 'var(--text-sm)',
  fontFamily: 'inherit',
};

function Step({
  n,
  title,
  hint,
  children,
}: {
  n: number;
  title: string;
  hint: string;
  children: React.ReactNode;
}) {
  return (
    <div style={{ display: 'grid', gap: 'var(--sp-3)' }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--sp-2)' }}>
        <span
          aria-hidden
          className="mono"
          style={{
            display: 'grid',
            placeItems: 'center',
            width: 19,
            height: 19,
            borderRadius: 5,
            background: 'var(--accent-wash)',
            border: '1px solid var(--accent-line)',
            color: 'var(--accent-bright)',
            fontSize: 10,
            fontWeight: 600,
          }}
        >
          {n}
        </span>
        <span style={{ fontSize: 'var(--text-sm)', fontWeight: 600 }}>{title}</span>
        <InfoTip text={hint} />
      </div>
      {children}
    </div>
  );
}

/** Says plainly what this demo path is and is not. */
function HonestyNote() {
  return (
    <div
      style={{
        padding: 'var(--sp-4)',
        background: 'var(--surface-1)',
        border: '1px solid var(--border-subtle)',
        borderRadius: 'var(--radius)',
        display: 'grid',
        gap: 8,
      }}
    >
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 'var(--text-sm)', fontWeight: 600 }}>
        <AlertTriangle size={14} style={{ color: 'var(--tier-review)' }} />
        How to read this run
      </div>
      <p style={{ fontSize: 'var(--text-xs)', color: 'var(--text-secondary)', lineHeight: 1.65 }}>
        Traffic is generated on the server for the scenario you pick, then put through the real pipeline —
        window slicing, feature extraction, baseline comparison, entity graph, policy and explanation. The
        risk score on this demo route is produced by a deterministic scoring rule over those measured
        features, not by a trained model checkpoint, because no serving model is bundled with the
        prototype. The trained-model comparison lives in the offline benchmark on the Performance page.
      </p>
    </div>
  );
}

function ResultView({
  result,
  tab,
  onTabChange,
}: {
  result: SimulationReport;
  tab: string;
  onTabChange: (t: string) => void;
}) {
  const tier = String(result.action_tier);
  const color = tierColorVar(tier);
  const wash = tierWashVar(tier);
  const evidence = useMemo(
    () => deriveEvidence(result.features_summary, result.total_transactions),
    [result],
  );
  const concentrated = (result.features_summary?.['J.largest_cluster_vol_share'] ?? 0) >= 0.3;

  return (
    <>
      {/* ---------------------------------------------------- verdict */}
      <Card style={{ borderColor: `${color}44`, background: `linear-gradient(180deg, ${wash} 0%, var(--surface-1) 60%)` }}>
        <div style={{ display: 'flex', flexWrap: 'wrap', justifyContent: 'space-between', gap: 'var(--sp-5)' }}>
          <div style={{ minWidth: 260 }}>
            <Badge color={color} background={wash}>
              {riskLabel(tier)}
            </Badge>
            <div
              className="tabular"
              style={{ fontSize: 'var(--text-4xl)', fontWeight: 700, color, lineHeight: 1.05, marginTop: 'var(--sp-3)' }}
            >
              {formatPercent(result.risk_score)}
            </div>
            <p style={{ fontSize: 'var(--text-lg)', marginTop: 6, color: 'var(--text-primary)' }}>
              {riskHeadline(tier)}
            </p>
            <p style={{ fontSize: 'var(--text-sm)', color: 'var(--text-secondary)', marginTop: 'var(--sp-3)' }}>
              {formatCount(result.total_transactions)} payment attempts · {windowLabel(result.window_size)} window ·{' '}
              {formatMoney(result.financial_exposure?.at_risk_gmv)} attempted
            </p>
          </div>

          <div style={{ display: 'grid', gap: 'var(--sp-4)', alignContent: 'start', minWidth: 200 }}>
            <Stat label="Decision" value={<span style={{ color }}>{TIER_COPY[tier as keyof typeof TIER_COPY]?.label ?? tier}</span>} sub={TIER_COPY[tier as keyof typeof TIER_COPY]?.meaning} />
            <Stat
              label="Scenario"
              value={<span style={{ fontSize: 'var(--text-md)' }}>{result.scenario_name}</span>}
              sub={result.is_attack ? 'Generated as an attack' : 'Generated as legitimate traffic'}
            />
          </div>
        </div>
      </Card>

      {/* ------------------------------------------------- exposure row */}
      <Card>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 'var(--sp-4)' }}>
          <SectionLabel>Estimated exposure</SectionLabel>
          <InfoTip text="Cost constants are documented assumptions chosen for this project (ADR-005), not Razorpay economics." />
        </div>
        <div className="veyra-stat-row">
          <Stat label="Attempted GMV" value={formatMoney(result.financial_exposure?.at_risk_gmv)} />
          <Stat
            label="Potential direct loss"
            value={formatMoney(result.financial_exposure?.direct_fraud_loss)}
            sub={`assumes ${formatPercent(result.financial_exposure?.p_loss, 0)} loss rate`}
          />
          <Stat label="Operational impact" value={formatMoney(result.financial_exposure?.operational_loss)} sub="disputes, fulfilment, support" />
          <Stat label="Total exposure" value={formatMoney(result.financial_exposure?.total_exposure)} accent={color} />
        </div>
      </Card>

      {/* ----------------------------------------------------- policy */}
      <PolicyPanel result={result} tier={tier} color={color} wash={wash} />

      {/* ------------------------------------------------------- tabs */}
      <Card padded={false}>
        <div style={{ padding: '0 var(--sp-5)' }}>
          <Tabs tabs={TABS} active={tab} onChange={onTabChange} />
        </div>
        <div id={`panel-${tab}`} role="tabpanel" aria-labelledby={`tab-${tab}`} style={{ padding: 'var(--sp-5)' }}>
          {tab === 'why' && <WhyFlagged result={result} evidence={evidence} />}
          {tab === 'pipeline' && <PipelineTimeline stages={result.stages} />}
          {tab === 'graph' && <EntityGraph graph={result.entity_graph} concentrated={concentrated} />}
          {tab === 'baseline' && (
            <div style={{ display: 'grid', gap: 'var(--sp-5)' }}>
              <BaselineDeviation deviations={result.top_feature_deviations} />
              <Disclosure summary="All measured features for this window">
                <FeatureTable features={result.features_summary} />
              </Disclosure>
            </div>
          )}
          {tab === 'events' && <EventsTab result={result} />}
        </div>
      </Card>

      <ReportExporter report={result} />
    </>
  );
}

function PolicyPanel({
  result,
  tier,
  color,
  wash,
}: {
  result: SimulationReport;
  tier: string;
  color: string;
  wash: string;
}) {
  return (
    <Card>
      <div style={{ display: 'grid', gap: 'var(--sp-4)' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <ShieldCheck size={15} style={{ color }} />
          <SectionLabel>Recommended control</SectionLabel>
        </div>

        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 'var(--sp-5)', justifyContent: 'space-between' }}>
          <div style={{ maxWidth: 560 }}>
            <div style={{ fontSize: 'var(--text-lg)', fontWeight: 600, color }}>
              {humanizeControl(result.recommended_defensive_control)}
            </div>
            <p style={{ fontSize: 'var(--text-sm)', color: 'var(--text-secondary)', marginTop: 8, lineHeight: 1.65 }}>
              Veyra recommends controls; it does not decline payments automatically. Even at the highest tier the
              system suggests friction — a velocity cap or a step-up challenge — so a wrong call costs a moment of
              friction rather than a lost customer.
            </p>
          </div>

          <div style={{ display: 'grid', gap: 6, minWidth: 230 }}>
            {TIER_ORDER.map((t) => {
              const active = t === tier;
              return (
                <div
                  key={t}
                  style={{
                    display: 'flex',
                    alignItems: 'center',
                    gap: 'var(--sp-3)',
                    padding: '7px 11px',
                    borderRadius: 'var(--radius-sm)',
                    background: active ? wash : 'transparent',
                    border: `1px solid ${active ? `${color}55` : 'var(--border-subtle)'}`,
                  }}
                >
                  <span
                    style={{
                      width: 7,
                      height: 7,
                      borderRadius: 999,
                      background: active ? color : 'var(--surface-3)',
                      flexShrink: 0,
                    }}
                  />
                  <span style={{ fontSize: 'var(--text-sm)', fontWeight: active ? 600 : 500, color: active ? color : 'var(--text-secondary)' }}>
                    {TIER_COPY[t].label}
                  </span>
                  <span style={{ fontSize: 'var(--text-xs)', color: 'var(--text-muted)', marginLeft: 'auto', textAlign: 'right' }}>
                    {active ? 'selected' : ''}
                  </span>
                </div>
              );
            })}
          </div>
        </div>

        <p style={{ fontSize: 'var(--text-xs)', color: 'var(--text-muted)', lineHeight: 1.6, borderTop: '1px solid var(--border-subtle)', paddingTop: 'var(--sp-3)' }}>
          This prototype does not expose an endpoint that applies a control to live traffic, so no action is
          offered here. Analyst actions on stored incidents are supported by the API
          (<span className="mono">POST /v2/incidents/{'{id}'}/action</span>).
        </p>
      </div>
    </Card>
  );
}

function WhyFlagged({ result, evidence }: { result: SimulationReport; evidence: ReturnType<typeof deriveEvidence> }) {
  return (
    <div style={{ display: 'grid', gap: 'var(--sp-5)' }}>
      <div>
        <h3 style={{ fontSize: 'var(--text-lg)' }}>Why was this flagged?</h3>
        <p style={{ fontSize: 'var(--text-sm)', color: 'var(--text-secondary)', marginTop: 6 }}>
          Each point below is measured from this window. Volume alone never decides the outcome.
        </p>
      </div>

      {evidence.length === 0 ? (
        <EmptyState title="No evidence returned" detail="The response did not include feature values for this window." />
      ) : (
        <div style={{ display: 'grid', gap: 'var(--sp-3)' }}>
          {evidence.map((item) => {
            const tone =
              item.tone === 'risk'
                ? 'var(--tier-restrict)'
                : item.tone === 'benign'
                  ? 'var(--tier-observe)'
                  : 'var(--accent-bright)';
            return (
              <div
                key={item.id}
                style={{
                  display: 'grid',
                  gap: 6,
                  padding: 'var(--sp-4)',
                  background: 'var(--bg-sunken)',
                  border: '1px solid var(--border-subtle)',
                  borderLeft: `2px solid ${tone}`,
                  borderRadius: 'var(--radius)',
                }}
              >
                <div style={{ fontSize: 'var(--text-md)', fontWeight: 600, color: 'var(--text-primary)' }}>
                  {item.headline}
                </div>
                <p style={{ fontSize: 'var(--text-sm)', color: 'var(--text-secondary)', lineHeight: 1.65 }}>{item.why}</p>
                <p style={{ fontSize: 'var(--text-xs)', color: 'var(--text-muted)', lineHeight: 1.6 }}>{item.impact}</p>
              </div>
            );
          })}
        </div>
      )}

      <Disclosure summary="Technical details — full narrative, feature ids and timestamps">
        <div style={{ display: 'grid', gap: 'var(--sp-4)' }}>
          <div>
            <div className="eyebrow" style={{ marginBottom: 10 }}>
              Forensic analysis narrative
            </div>
            <NarrativeTypewriter text={result.explanation} />
          </div>
          <div className="veyra-kv">
            <KV k="Merchant" v={result.merchant_id} mono />
            <KV k="Window end (local)" v={formatTimestamp(result.window_end)} />
            <KV k="Window end (UTC)" v={formatTimestampUtc(result.window_end)} mono />
            <KV k="Scenario id" v={result.scenario_id} mono />
            <KV k="Attempts in window" v={formatCount(result.total_transactions)} />
            <KV k="Abusive attempts (generator truth)" v={formatCount(result.abusive_transactions)} />
          </div>
        </div>
      </Disclosure>
    </div>
  );
}

function EventsTab({ result }: { result: SimulationReport }) {
  const csv = result.export_formats?.csv;
  if (!csv) {
    return <EmptyState title="No transaction sample returned" detail="This response did not include a per-transaction breakdown." />;
  }
  const lines = csv.trim().split('\n');
  const header = lines[0]?.split(',') ?? [];
  const rows = lines.slice(1, 61).map((l) => l.split(','));

  return (
    <div style={{ display: 'grid', gap: 'var(--sp-3)' }}>
      <p style={{ fontSize: 'var(--text-sm)', color: 'var(--text-secondary)' }}>
        Individual payment attempts in this window, as returned by the API. Showing the first {rows.length} of{' '}
        {formatCount(result.total_transactions)}.
      </p>
      <div style={{ overflowX: 'auto', border: '1px solid var(--border-subtle)', borderRadius: 'var(--radius)' }}>
        <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 'var(--text-xs)' }}>
          <thead>
            <tr>
              {header.map((h) => (
                <th
                  key={h}
                  style={{
                    textAlign: 'left',
                    padding: '9px 12px',
                    background: 'var(--surface-2)',
                    borderBottom: '1px solid var(--border)',
                    color: 'var(--text-secondary)',
                    fontWeight: 600,
                    whiteSpace: 'nowrap',
                  }}
                >
                  {h.replace(/_/g, ' ')}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((cells, i) => (
              <tr key={i} style={{ background: i % 2 ? 'var(--bg-sunken)' : 'transparent' }}>
                {cells.map((c, j) => (
                  <td
                    key={j}
                    className="mono"
                    style={{
                      padding: '7px 12px',
                      borderBottom: '1px solid var(--border-subtle)',
                      color: c === 'True' ? 'var(--tier-restrict)' : 'var(--text-secondary)',
                      whiteSpace: 'nowrap',
                    }}
                  >
                    {c}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function FeatureTable({ features }: { features: Record<string, number> | undefined }) {
  const entries = Object.entries(features ?? {});
  if (entries.length === 0) return <p style={{ fontSize: 'var(--text-sm)', color: 'var(--text-muted)' }}>No features returned.</p>;
  return (
    <div className="veyra-kv">
      {entries.map(([k, v]) => (
        <KV key={k} k={k} v={typeof v === 'number' ? v.toFixed(4) : String(v)} mono />
      ))}
    </div>
  );
}

function KV({ k, v, mono }: { k: string; v: string; mono?: boolean }) {
  return (
    <div style={{ display: 'flex', justifyContent: 'space-between', gap: 'var(--sp-3)', padding: '6px 0', borderBottom: '1px solid var(--border-subtle)' }}>
      <span style={{ fontSize: 'var(--text-xs)', color: 'var(--text-muted)' }}>{k}</span>
      <span className={mono ? 'mono' : undefined} style={{ fontSize: 'var(--text-xs)', color: 'var(--text-secondary)', textAlign: 'right', wordBreak: 'break-all' }}>
        {v}
      </span>
    </div>
  );
}

export { ChevronRight };
