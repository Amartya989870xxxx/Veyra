/** Detection Page.
 *
 * The interactive detection console. Picks a scenario, generates synthetic traffic,
 * and sends it through the live multi-stage Veyra detection pipeline.
 *
 * Exposes truthful data provenance, real stage execution telemetry, fitted model
 * score, decision policy tier, and an inspectable synthetic data explorer.
 */

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { ChevronRight, Info, Play, ShieldCheck } from 'lucide-react';
import { ApiError, api } from '../api/client';
import type {
  ScenarioSummary,
  SimulationReport,
  WindowSize,
} from '../api/types';
import { deriveEvidence } from '../lib/evidence';
import {
  formatCount,
  formatMoney,
  formatPercent,
  formatTimestamp,
  formatTimestampUtc,
} from '../lib/format';
import {
  MERCHANT_CATEGORIES,
  WINDOW_OPTIONS,
  humanizeControl,
  riskHeadline,
  riskLabel,
  tierColorVar,
  tierWashVar,
  windowLabel,
} from '../lib/scenarios';
import {
  Badge,
  Button,
  Card,
  Disclosure,
  EmptyState,
  ErrorState,
  InfoTip,
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
import { ProvenancePanel } from '../components/viz/ProvenancePanel';
import { StagedPipelineProgress } from '../components/viz/StagedPipelineProgress';
import { RunSummaryBanner } from '../components/viz/RunSummaryBanner';
import { SyntheticDataExplorer } from '../components/explorer/SyntheticDataExplorer';

const TABS = [
  { id: 'why', label: 'Why it was flagged' },
  { id: 'pipeline', label: 'Detection pipeline' },
  { id: 'explorer', label: 'Synthetic data explorer' },
  { id: 'graph', label: 'Entity network' },
  { id: 'baseline', label: 'Historical comparison' },
  { id: 'events', label: 'Transaction events' },
];

export function DetectionPage({
  initialScenario,
  onNavigateExplorer,
}: {
  initialScenario?: string;
  onNavigateExplorer?: (runId: string) => void;
}) {
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

  // Presentation & stage pacing
  const analysisRef = useRef<HTMLDivElement>(null);
  const [activeStageIndex, setActiveStageIndex] = useState(0);
  const [presentationElapsedMs, setPresentationElapsedMs] = useState(0);
  const [pendingReport, setPendingReport] = useState<SimulationReport | null>(null);
  const presentationTimerRef = useRef<number | null>(null);
  const pendingReportRef = useRef<SimulationReport | null>(null);

  const TARGET_PRESENTATION_MS = 25000;

  useEffect(() => {
    return () => {
      if (presentationTimerRef.current) {
        window.clearInterval(presentationTimerRef.current);
      }
    };
  }, []);

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
    // 1. Immediately enter loading state and clear previous result/error
    setRunning(true);
    setRunError(null);
    setResult(null);
    setPendingReport(null);
    pendingReportRef.current = null;
    setActiveStageIndex(0);
    setPresentationElapsedMs(0);

    // 2. PART 2: Immediately smooth scroll to analysis/progress section
    const prefersReducedMotion =
      typeof window !== 'undefined' &&
      window.matchMedia('(prefers-reduced-motion: reduce)').matches;

    setTimeout(() => {
      analysisRef.current?.scrollIntoView({
        behavior: prefersReducedMotion ? 'auto' : 'smooth',
        block: 'start',
      });
    }, 15);

    // 3. Start presentation elapsed timer (~11s target)
    const startTime = Date.now();
    if (presentationTimerRef.current) {
      window.clearInterval(presentationTimerRef.current);
    }

    presentationTimerRef.current = window.setInterval(() => {
      const elapsed = Date.now() - startTime;
      setPresentationElapsedMs(elapsed);

      // 12 stages across 11,000ms: ~916ms per stage
      const stageIdx = Math.min(11, Math.floor(elapsed / (TARGET_PRESENTATION_MS / 12)));
      setActiveStageIndex(stageIdx);

      // Check if presentation target has elapsed AND backend has returned
      if (elapsed >= TARGET_PRESENTATION_MS) {
        if (pendingReportRef.current) {
          if (presentationTimerRef.current) {
            window.clearInterval(presentationTimerRef.current);
            presentationTimerRef.current = null;
          }
          setResult(pendingReportRef.current);
          setRunning(false);
          setTab('why');
        }
      }
    }, 80);

    // 4. Issue backend simulation request
    try {
      const report = await api.runSimulation({
        scenario_id: scenarioId,
        merchant_category: category,
        intensity,
        window_size: windowSize,
        seed: 42,
      });
      pendingReportRef.current = report;
      setPendingReport(report);

      // If presentation duration already elapsed (e.g. cold start taking > 11s), reveal immediately
      const currentElapsed = Date.now() - startTime;
      if (currentElapsed >= TARGET_PRESENTATION_MS) {
        if (presentationTimerRef.current) {
          window.clearInterval(presentationTimerRef.current);
          presentationTimerRef.current = null;
        }
        setResult(report);
        setRunning(false);
        setTab('why');
      }
    } catch (e) {
      if (presentationTimerRef.current) {
        window.clearInterval(presentationTimerRef.current);
        presentationTimerRef.current = null;
      }
      setRunError(e as ApiError);
      setRunning(false);
      setResult(null);
      setPendingReport(null);
    }
  }, [scenarioId, category, intensity, windowSize]);

  const selectedScenario = scenarios?.find((s) => s.scenario_id === scenarioId);

  return (
    <div className="container-wide" style={{ padding: 'var(--sp-6) var(--sp-5) var(--sp-9)' }}>
      <div style={{ marginBottom: 'var(--sp-5)' }}>
        <SectionLabel>Detection console</SectionLabel>
        <h1 style={{ fontSize: 'var(--text-2xl)', marginTop: 6, fontWeight: 700 }}>
          Run a detection
        </h1>
        <p style={{ color: 'var(--text-secondary)', marginTop: 8, maxWidth: 720, fontSize: 'var(--text-md)' }}>
          Generate a synthetic window of merchant traffic and execute it through the full detection pipeline.
          Choose a scenario, then inspect the measured stage telemetry, fusion score, and evidence.
        </p>
      </div>

      <div className="veyra-detection-grid">
        {/* ------------------------------------------------ control rail */}
        <aside style={{ display: 'grid', gap: 'var(--sp-4)', alignContent: 'start' }}>
          <Card style={{ display: 'grid', gap: 'var(--sp-5)' }}>
            <Step n={1} title="Choose a scenario" hint="What kind of synthetic traffic to generate.">
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
                  <select
                    value={scenarioId}
                    onChange={(e) => setScenarioId(e.target.value)}
                    aria-label="Detection scenario"
                    style={selectStyle}
                  >
                    {scenarios.map((s) => (
                      <option key={s.scenario_id} value={s.scenario_id}>
                        {s.name} ({s.category})
                      </option>
                    ))}
                  </select>

                  {selectedScenario && (
                    <div
                      style={{
                        fontSize: 'var(--text-xs)',
                        color: selectedScenario.is_attack ? 'var(--tier-restrict)' : 'var(--tier-observe)',
                        display: 'flex',
                        alignItems: 'center',
                        gap: 6,
                      }}
                    >
                      <span
                        style={{
                          width: 6,
                          height: 6,
                          borderRadius: '50%',
                          background: selectedScenario.is_attack ? 'var(--tier-restrict)' : 'var(--tier-observe)',
                        }}
                      />
                      {selectedScenario.is_attack
                        ? 'Attack pattern — expected tier REVIEW or RESTRICT'
                        : 'Benign surge — expected tier OBSERVE'}
                    </div>
                  )}
                </div>
              )}
            </Step>

            <Step n={2} title="Merchant profile" hint="Category determines baseline volume and amount ranges.">
              <select
                value={category}
                onChange={(e) => setCategory(e.target.value)}
                aria-label="Merchant category"
                style={selectStyle}
              >
                {MERCHANT_CATEGORIES.map((c) => (
                  <option key={c.value} value={c.value}>
                    {c.label}
                  </option>
                ))}
              </select>
            </Step>

            <Step n={3} title="Traffic intensity" hint="Higher values scale the volume of injected attempts.">
              <div style={{ display: 'grid', gap: 8 }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 'var(--text-xs)' }}>
                  <span style={{ color: 'var(--text-muted)' }}>Multiplier</span>
                  <span className="mono" style={{ color: 'var(--accent-bright)', fontWeight: 600 }}>
                    {intensity.toFixed(1)}x
                  </span>
                </div>
                <input
                  type="range"
                  min={0.5}
                  max={3.0}
                  step={0.5}
                  value={intensity}
                  onChange={(e) => setIntensity(Number(e.target.value))}
                  aria-label="Traffic intensity"
                  style={{ width: '100%', accentColor: 'var(--accent)' }}
                />
                <div
                  style={{
                    display: 'flex',
                    justifyContent: 'space-between',
                    fontSize: '10px',
                    color: 'var(--text-muted)',
                  }}
                >
                  <span>0.5x (light)</span>
                  <span>1.0x (normal)</span>
                  <span>3.0x (heavy)</span>
                </div>
              </div>
            </Step>

            <Step n={4} title="Window horizon" hint="Temporal aggregation horizon for grouping events.">
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
                        cursor: 'pointer',
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
              {running ? 'Executing pipeline…' : 'Run detection'}
            </Button>
          </Card>

          <HonestyNote />
        </aside>

        {/* ------------------------------------------------------- results */}
        <main
          ref={analysisRef}
          style={{
            display: 'grid',
            gap: 'var(--sp-5)',
            alignContent: 'start',
            minWidth: 0,
            scrollMarginTop: 'calc(var(--nav-h) + 24px)',
          }}
        >
          {/* Staged Analysis Experience during in-flight run */}
          {running && (
            <StagedPipelineProgress
              running={true}
              backendCompleted={Boolean(pendingReport)}
              activeStageIndex={activeStageIndex}
              stages={pendingReport?.stages ?? null}
              serverDurationMs={
                pendingReport?.run?.total_server_duration_ms ??
                pendingReport?.run?.timing?.server_processing_ms ??
                null
              }
              timing={pendingReport?.run?.timing ?? null}
              presentationElapsedMs={presentationElapsedMs}
              targetPresentationMs={TARGET_PRESENTATION_MS}
            />
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
                description="Pick a scenario on the left and click 'Run detection'. Veyra will generate synthetic traffic, execute feature extraction & graph clustering, score it with the fitted fusion model, and explain the verdict."
                action={
                  <Button variant="primary" onClick={runDetection} icon={<Play size={15} />}>
                    Run detection
                  </Button>
                }
              />
            </Card>
          )}

          {!running && result && (
            <ResultView
              result={result}
              onTabChange={setTab}
              tab={tab}
              onNavigateExplorer={onNavigateExplorer}
            />
          )}
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

/** Honest architectural explanation of this demo path. */
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
        <Info size={14} style={{ color: 'var(--accent-bright)' }} />
        How to read this run
      </div>
      <p style={{ fontSize: 'var(--text-xs)', color: 'var(--text-secondary)', lineHeight: 1.65 }}>
        Traffic is generated on the server for the scenario you pick, then passed through the real pipeline —
        window slicing, feature extraction, baseline deviation, entity graph clustering, and scoring with the
        fitted fusion model (<code>veyra_fusion_demo</code>). The resulting score is evaluated by the expected-loss
        decision policy to produce the action tier and deterministic forensic explanation.
      </p>
    </div>
  );
}

function ResultView({
  result,
  tab,
  onTabChange,
  onNavigateExplorer,
}: {
  result: SimulationReport;
  tab: string;
  onTabChange: (t: string) => void;
  onNavigateExplorer?: (runId: string) => void;
}) {
  const tier = String(result.action_tier);
  const color = tierColorVar(tier);
  const wash = tierWashVar(tier);

  const totalTx = result.run?.total_transactions ?? result.total_transactions ?? 0;
  const windowSize = result.run?.window_size ?? result.window_size ?? '5m';

  const evidence = useMemo(
    () => deriveEvidence(result.features_summary, totalTx),
    [result.features_summary, totalTx],
  );
  const concentrated = (result.features_summary?.['J.largest_cluster_vol_share'] ?? 0) >= 0.3;

  return (
    <div style={{ display: 'grid', gap: 'var(--sp-5)' }}>
      {/* 1. Truthful Data Provenance Panel */}
      {result.run && (
        <ProvenancePanel run={result.run} scenarioName={result.scenario_name} />
      )}

      {/* 2. Run Summary Banner */}
      <RunSummaryBanner
        report={result}
        onExploreData={(id) => {
          onTabChange('explorer');
          onNavigateExplorer?.(id);
        }}
      />

      {/* 3. Verdict Card */}
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
              {formatCount(totalTx)} payment attempts · {windowLabel(windowSize)} window ·{' '}
              {formatMoney(result.financial_exposure?.at_risk_gmv)} attempted
            </p>
          </div>

          <div style={{ display: 'grid', gap: 'var(--sp-4)', alignContent: 'start', minWidth: 200 }}>
            <Stat
              label="Policy Decision"
              value={<span style={{ color }}>{tier}</span>}
              sub={result.recommended_defensive_control ? humanizeControl(result.recommended_defensive_control) : 'No defensive friction needed'}
            />
            <Stat
              label="Scenario"
              value={<span style={{ fontSize: 'var(--text-md)' }}>{result.scenario_name}</span>}
              sub={
                result.ground_truth?.scenario_is_labelled_attack || result.is_attack
                  ? 'Synthetic Ground Truth: Attack pattern'
                  : 'Synthetic Ground Truth: Legitimate surge'
              }
            />
          </div>
        </div>
      </Card>

      {/* 4. Financial Exposure Row */}
      <Card>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 'var(--sp-4)' }}>
          <SectionLabel>Estimated financial exposure</SectionLabel>
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

      {/* 5. Policy Panel */}
      <PolicyPanel result={result} tier={tier} color={color} wash={wash} />

      {/* 6. Multi-tab Evidence Inspector */}
      <Card padded={false}>
        <div style={{ padding: '0 var(--sp-5)' }}>
          <Tabs tabs={TABS} active={tab} onChange={onTabChange} />
        </div>
        <div id={`panel-${tab}`} role="tabpanel" aria-labelledby={`tab-${tab}`} style={{ padding: 'var(--sp-5)' }}>
          {tab === 'why' && <WhyFlagged result={result} evidence={evidence} />}
          {tab === 'pipeline' && <PipelineTimeline stages={result.stages} />}
          {tab === 'explorer' && <SyntheticDataExplorer runId={result.run?.run_id ?? null} />}
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
    </div>
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
          <SectionLabel>Recommended defensive control</SectionLabel>
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
            {['OBSERVE', 'ALERT', 'REVIEW', 'RESTRICT'].map((t) => {
              const active = t === tier;
              return (
                <div
                  key={t}
                  style={{
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'space-between',
                    padding: '6px 10px',
                    borderRadius: 5,
                    background: active ? wash : 'var(--surface-2)',
                    border: `1px solid ${active ? color : 'transparent'}`,
                    fontSize: '11px',
                    fontFamily: 'var(--font-mono)',
                    color: active ? color : 'var(--text-muted)',
                    fontWeight: active ? 700 : 500,
                  }}
                >
                  <span>{t}</span>
                  {active && <span>● CURRENT TIER</span>}
                </div>
              );
            })}
          </div>
        </div>
      </div>
    </Card>
  );
}

function WhyFlagged({ result, evidence }: { result: SimulationReport; evidence: ReturnType<typeof deriveEvidence> }) {
  const totalTx = result.run?.total_transactions ?? result.total_transactions ?? 0;
  const abusiveTx = result.ground_truth?.abusive_transaction_count ?? result.abusive_transactions ?? 0;
  const merchantId = result.run?.merchant_id ?? result.merchant_id ?? 'm_0001';
  const windowEnd = result.run?.window_end ?? result.window_end ?? '';
  const scenarioId = result.run?.scenario_id ?? result.scenario_id ?? '';

  return (
    <div style={{ display: 'grid', gap: 'var(--sp-5)' }}>
      <div>
        <h3 style={{ fontSize: 'var(--text-lg)', fontWeight: 700 }}>Why was this flagged?</h3>
        <p style={{ fontSize: 'var(--text-sm)', color: 'var(--text-secondary)', marginTop: 6 }}>
          Each point below is calculated from this window. Volume alone never decides the outcome.
        </p>
      </div>

      {evidence.length === 0 ? (
        <EmptyState title="No evidence returned" description="The response did not include feature values for this window." />
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

      <Disclosure summary="Technical details — full forensic explanation, feature ids and timestamps">
        <div style={{ display: 'grid', gap: 'var(--sp-4)' }}>
          <div>
            <div className="eyebrow" style={{ marginBottom: 10 }}>
              Forensic evidence dossier
            </div>
            <NarrativeTypewriter text={result.explanation} />
          </div>
          <div className="veyra-kv">
            <KV k="Merchant ID" v={merchantId} mono />
            <KV k="Window end (local)" v={formatTimestamp(windowEnd)} />
            <KV k="Window end (UTC)" v={formatTimestampUtc(windowEnd)} mono />
            <KV k="Scenario ID" v={scenarioId} mono />
            <KV k="Attempts in window" v={formatCount(totalTx)} />
            <KV k="Abusive attempts (generator truth)" v={formatCount(abusiveTx)} />
          </div>
        </div>
      </Disclosure>
    </div>
  );
}

function EventsTab({ result }: { result: SimulationReport }) {
  const csv = result.export_formats?.csv;
  const totalTx = result.run?.total_transactions ?? result.total_transactions ?? 0;

  if (!csv) {
    return <EmptyState title="No transaction sample returned" description="This response did not include a per-transaction breakdown." />;
  }
  const lines = csv.trim().split('\n');
  const header = lines[0]?.split(',') ?? [];
  const rows = lines.slice(1, 61).map((l) => l.split(','));

  return (
    <div style={{ display: 'grid', gap: 'var(--sp-3)' }}>
      <p style={{ fontSize: 'var(--text-sm)', color: 'var(--text-secondary)' }}>
        Individual synthetic payment attempts in this window. Showing the first {rows.length} of{' '}
        {formatCount(totalTx)}. Use the <strong>Synthetic data explorer</strong> tab for full paged inspection.
      </p>
      <div style={{ overflowX: 'auto', border: '1px solid var(--border-subtle)', borderRadius: 'var(--radius)' }}>
        <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 'var(--text-xs)', fontFamily: 'var(--font-mono)' }}>
          <thead>
            <tr>
              {header.map((h) => (
                <th
                  key={h}
                  style={{
                    padding: '8px 12px',
                    textAlign: 'left',
                    color: 'var(--text-muted)',
                    borderBottom: '1px solid var(--border-subtle)',
                    background: 'var(--surface-1)',
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
