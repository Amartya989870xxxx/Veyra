/** Performance Lab.
 *
 * Measures how the detection pipeline behaves under a burst of traffic. Every
 * number on this page is returned by POST /v2/demo/stress-test — no timing is
 * taken in the browser, and nothing is extrapolated. The run is genuinely
 * executed against the backend, which is why it can take a few seconds.
 *
 * The honesty note is not boilerplate: these figures come from synthetic traffic
 * on whatever machine the API happens to be running on, and presenting them as
 * production capacity would be a fabricated claim.
 */

import { useCallback, useEffect, useRef, useState } from 'react';
import { Gauge, Info, Zap } from 'lucide-react';
import { ApiError, api } from '../api/client';
import type { ScenarioSummary, StressTestResult } from '../api/types';
import { formatCount, formatLatency, formatNumber, formatPercent, formatTps } from '../lib/format';
import { MERCHANT_CATEGORIES, riskLabel, scenarioSummary, tierColorVar, tierWashVar } from '../lib/scenarios';
import {
  Badge,
  Button,
  Card,
  EmptyState,
  ErrorState,
  InfoTip,
  LoadingBlock,
  SectionLabel,
  Stat,
} from '../components/ui';
import { PipelineTimeline } from '../components/viz/PipelineTimeline';

/** Backend clamps burst_count to 100..5000 (ScenarioStressRequest). Keeping the
 *  presets inside that range means the UI can never send a rejected request. */
const BURST_PRESETS = [250, 500, 1000, 2500, 5000];

export function PerformancePage() {
  const [scenarios, setScenarios] = useState<ScenarioSummary[] | null>(null);
  const [scenarioId, setScenarioId] = useState('card_testing_burst');
  const [category, setCategory] = useState('electronics');
  const [burstCount, setBurstCount] = useState(500);

  const [result, setResult] = useState<StressTestResult | null>(null);
  const [running, setRunning] = useState(false);
  const [error, setError] = useState<ApiError | null>(null);

  const abortRef = useRef<AbortController | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    api
      .listScenarios(controller.signal)
      .then(setScenarios)
      .catch(() => setScenarios([]));
    return () => controller.abort();
  }, []);

  // Any in-flight stress test is cancelled if the page unmounts, so a slow run
  // cannot resolve into an unmounted component.
  useEffect(() => () => abortRef.current?.abort(), []);

  const run = useCallback(async () => {
    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;

    setRunning(true);
    setError(null);
    try {
      const res = await api.runStressTest(
        { scenario_id: scenarioId, burst_count: burstCount, merchant_category: category },
        controller.signal,
      );
      setResult(res);
    } catch (err) {
      if (controller.signal.aborted) return;
      setError(
        err instanceof ApiError
          ? err
          : new ApiError('The stress test failed.', 0, String(err)),
      );
    } finally {
      if (!controller.signal.aborted) setRunning(false);
    }
  }, [scenarioId, burstCount, category]);

  const tier = result?.action_tier ?? '';

  return (
    <div className="container" style={{ padding: 'var(--sp-7) var(--sp-5) var(--sp-9)' }}>
      <header style={{ display: 'grid', gap: 'var(--sp-3)', maxWidth: 760, marginBottom: 'var(--sp-6)' }}>
        <SectionLabel>Performance Lab</SectionLabel>
        <h1 style={{ fontSize: 'var(--text-2xl)' }}>
          Measure the pipeline under burst traffic.
        </h1>
        <p style={{ fontSize: 'var(--text-md)', color: 'var(--text-secondary)', lineHeight: 1.65 }}>
          This injects a burst of transaction envelopes into the running backend and measures how
          long ingestion, feature extraction and scoring actually take. The request is real, so the
          wait is real.
        </p>
      </header>

      <div
        style={{
          display: 'grid',
          gridTemplateColumns: 'minmax(260px, 320px) 1fr',
          gap: 'var(--sp-5)',
          alignItems: 'start',
        }}
        className="veyra-split"
      >
        {/* ------------------------------------------------------ controls */}
        <Card style={{ display: 'grid', gap: 'var(--sp-5)', position: 'sticky', top: 'calc(var(--nav-h) + 16px)' }}>
          <div style={{ display: 'grid', gap: 'var(--sp-2)' }}>
            <h2 style={{ fontSize: 'var(--text-md)' }}>Configure the run</h2>
            <p style={{ fontSize: 'var(--text-xs)', color: 'var(--text-muted)', lineHeight: 1.6 }}>
              Traffic shape and volume to push through the pipeline.
            </p>
          </div>

          <label style={{ display: 'grid', gap: 'var(--sp-2)' }}>
            <span className="eyebrow">Traffic shape</span>
            <select
              value={scenarioId}
              onChange={(e) => setScenarioId(e.target.value)}
              disabled={running}
              style={selectStyle}
            >
              {(scenarios ?? []).map((s) => (
                <option key={s.scenario_id} value={s.scenario_id}>
                  {s.name}
                </option>
              ))}
              {!scenarios?.length && <option value="card_testing_burst">Card Testing Velocity Burst</option>}
            </select>
            <span style={{ fontSize: 'var(--text-xs)', color: 'var(--text-muted)', lineHeight: 1.55 }}>
              {scenarioSummary(scenarioId, scenarioId)}
            </span>
          </label>

          <label style={{ display: 'grid', gap: 'var(--sp-2)' }}>
            <span className="eyebrow">Merchant category</span>
            <select
              value={category}
              onChange={(e) => setCategory(e.target.value)}
              disabled={running}
              style={selectStyle}
            >
              {MERCHANT_CATEGORIES.map((c) => (
                <option key={c.value} value={c.value}>
                  {c.label}
                </option>
              ))}
            </select>
          </label>

          <div style={{ display: 'grid', gap: 'var(--sp-2)' }}>
            <span className="eyebrow" style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
              Burst size
              <InfoTip text="How many transaction envelopes are injected at once. Larger bursts spend proportionally more time in database ingestion." />
            </span>
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
              {BURST_PRESETS.map((n) => {
                const active = n === burstCount;
                return (
                  <button
                    key={n}
                    onClick={() => setBurstCount(n)}
                    disabled={running}
                    aria-pressed={active}
                    className="tabular"
                    style={{
                      padding: '7px 12px',
                      background: active ? 'var(--accent-wash)' : 'var(--surface-2)',
                      border: `1px solid ${active ? 'var(--accent-line)' : 'var(--border)'}`,
                      borderRadius: 'var(--radius-sm)',
                      color: active ? 'var(--accent-bright)' : 'var(--text-secondary)',
                      fontSize: 'var(--text-xs)',
                      fontWeight: 600,
                      opacity: running ? 0.55 : 1,
                    }}
                  >
                    {formatCount(n)}
                  </button>
                );
              })}
            </div>
          </div>

          <Button
            variant="primary"
            full
            loading={running}
            onClick={run}
            icon={<Zap size={16} />}
          >
            {running ? 'Running…' : 'Run stress test'}
          </Button>

          <p style={{ fontSize: 'var(--text-xs)', color: 'var(--text-muted)', lineHeight: 1.6 }}>
            Larger bursts take longer. The request stays open until the backend finishes.
          </p>
        </Card>

        {/* ------------------------------------------------------- results */}
        <div style={{ display: 'grid', gap: 'var(--sp-5)', minWidth: 0 }}>
          {error && (
            <ErrorState
              title={error.isNetwork ? 'Detection engine unavailable' : error.message}
              detail={error.detail || 'Could not reach the Veyra API. Check that the backend is running.'}
              onRetry={run}
            />
          )}

          {running && !result && (
            <Card>
              <LoadingBlock label={`Injecting ${formatCount(burstCount)} events and scoring the window…`} rows={4} />
            </Card>
          )}

          {!running && !result && !error && (
            <EmptyState
              title="No run yet"
              detail="Choose a burst size and run the test. Results appear here with the measured stage timings returned by the backend."
              action={<Button variant="primary" icon={<Zap size={15} />} onClick={run}>Run stress test</Button>}
            />
          )}

          {result && (
            <>
              <Card style={{ display: 'grid', gap: 'var(--sp-5)' }}>
                <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 'var(--sp-4)', flexWrap: 'wrap' }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--sp-3)' }}>
                    <Gauge size={18} style={{ color: 'var(--accent-bright)' }} />
                    <h2 style={{ fontSize: 'var(--text-md)' }}>Measured result</h2>
                  </div>
                  <div style={{ display: 'flex', gap: 'var(--sp-2)', flexWrap: 'wrap' }}>
                    <Badge
                      color={result.status === 'SUCCESS' ? 'var(--tier-observe)' : 'var(--tier-review)'}
                      background={result.status === 'SUCCESS' ? 'var(--tier-observe-wash)' : 'var(--tier-review-wash)'}
                    >
                      {result.status}
                    </Badge>
                    {tier && (
                      <Badge color={tierColorVar(tier)} background={tierWashVar(tier)}>
                        {tier}
                      </Badge>
                    )}
                  </div>
                </div>

                <div
                  style={{
                    display: 'grid',
                    gridTemplateColumns: 'repeat(auto-fit, minmax(150px, 1fr))',
                    gap: 'var(--sp-5)',
                  }}
                >
                  <Stat
                    label="Throughput"
                    value={formatTps(result.throughput_tps)}
                    sub="Events per second, end to end"
                    accent="var(--accent-bright)"
                  />
                  <Stat
                    label="End-to-end"
                    value={formatLatency(result.total_time_ms)}
                    sub={`For ${formatCount(result.burst_count)} events`}
                  />
                  <Stat
                    label="Events ingested"
                    value={formatCount(result.burst_count)}
                    sub="Written and scored"
                  />
                  <Stat
                    label="Risk score"
                    value={formatPercent(result.risk_score)}
                    sub={riskLabel(String(result.action_tier))}
                    accent={tierColorVar(String(result.action_tier))}
                  />
                  <Stat
                    label="Flagged in window"
                    value={formatCount(result.abusive_detected)}
                    sub="Transactions marked abusive"
                  />
                </div>
              </Card>

              <Card style={{ display: 'grid', gap: 'var(--sp-4)' }}>
                <div style={{ display: 'grid', gap: 4 }}>
                  <SectionLabel>Stage breakdown</SectionLabel>
                  <p style={{ fontSize: 'var(--text-sm)', color: 'var(--text-secondary)' }}>
                    Timings reported by the backend for this run.
                  </p>
                </div>
                <PipelineTimeline stages={result.stages} />

                <div
                  style={{
                    display: 'grid',
                    gridTemplateColumns: 'repeat(auto-fit, minmax(160px, 1fr))',
                    gap: 'var(--sp-4)',
                    paddingTop: 'var(--sp-4)',
                    borderTop: '1px solid var(--border-subtle)',
                  }}
                >
                  <Stat label="Ingestion" value={formatLatency(result.ingestion_time_ms)} />
                  <Stat label="Feature extraction" value={formatLatency(result.feature_time_ms)} />
                  <Stat label="Model inference" value={formatLatency(result.scoring_time_ms)} />
                </div>
              </Card>

              <Card style={{ display: 'grid', gap: 'var(--sp-3)' }}>
                <SectionLabel>What this test demonstrates</SectionLabel>
                <p style={{ fontSize: 'var(--text-sm)', color: 'var(--text-secondary)', lineHeight: 1.7 }}>
                  {formatCount(result.burst_count)} transaction envelopes were written to the
                  database, converted into features, and scored by the fusion model in a measured
                  end-to-end run of {formatLatency(result.total_time_ms)} —{' '}
                  {formatTps(result.throughput_tps)}. Ingestion accounts for{' '}
                  {formatNumber(
                    result.total_time_ms > 0
                      ? (result.ingestion_time_ms / result.total_time_ms) * 100
                      : 0,
                    0,
                  )}
                  % of that time, which is the expected shape: scoring is cheap, durable writes are not.
                </p>
                <p
                  style={{
                    display: 'flex',
                    gap: 'var(--sp-2)',
                    alignItems: 'flex-start',
                    fontSize: 'var(--text-xs)',
                    color: 'var(--text-muted)',
                    lineHeight: 1.65,
                  }}
                >
                  <Info size={13} style={{ flexShrink: 0, marginTop: 2 }} />
                  Benchmark results are measured on the project environment using controlled
                  synthetic traffic. They are not a production Razorpay infrastructure benchmark
                  and should not be read as capacity planning.
                </p>
              </Card>
            </>
          )}
        </div>
      </div>
    </div>
  );
}

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
