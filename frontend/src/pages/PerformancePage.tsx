/** Veyra Scale Lab.
 *
 * Measures how Veyra behaves under large synthetic workloads (100K to 100M events).
 * Exposes two distinct server-side scaling dimensions:
 *   1. Ingestion / Write Scale: Validate, fingerprint, and persist synthetic envelopes.
 *   2. Detection / Computation Scale: Contextual feature extraction, bipartite entity
 *      graph construction, and model inference on sampled merchant-windows.
 *
 * Every numeric field is measured server-side with time.perf_counter() or tracemalloc.
 * Sizes above the server's safety ceiling are capped and reported as capped —
 * never extrapolated or fabricated.
 *
 * Fully integrated with the latest nested BenchmarkResult schema and authoritative
 * status precedence: failed > stopped_early > capped > completed.
 */

import { useCallback, useEffect, useRef, useState } from 'react';
import {
  AlertTriangle,
  BarChart3,
  CheckCircle2,
  Flame,
  HelpCircle,
  Loader2,
  Play,
  Server,
  ShieldAlert,
  X,
  XCircle,
} from 'lucide-react';
import { ApiError, api } from '../api/client';
import type {
  BenchmarkCreateResponse,
  BenchmarkMode,
  BenchmarkPresetsResponse,
  BenchmarkProgress,
  BenchmarkResult,
  BenchmarkSampleTransaction,
  BenchmarkStatus,
  ScenarioMix,
  StressTestResult,
} from '../api/types';
import {
  Badge,
  Button,
  Card,
  EmptyState,
  ErrorState,
  LoadingBlock,
  SectionLabel,
  Stat,
} from '../components/ui';

export function PerformancePage() {
  // Preset definitions & guardrails from server
  const [presetData, setPresetData] = useState<BenchmarkPresetsResponse | null>(null);

  // Configuration controls
  const [selectedSize, setSelectedSize] = useState<number>(100_000);
  const [selectedMode, setSelectedMode] = useState<BenchmarkMode>('pipeline');
  const [selectedMix, setSelectedMix] = useState<ScenarioMix>('legit_90_fraud_10');
  const [durationMinutes, setDurationMinutes] = useState<number>(5.0);

  // Benchmark execution state
  const [activeRunId, setActiveRunId] = useState<string | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [isPolling, setIsPolling] = useState(false);
  const [progress, setProgress] = useState<BenchmarkProgress | null>(null);
  const [activeStage, setActiveStage] = useState<string>('QUEUED');
  const [runResult, setRunResult] = useState<BenchmarkResult | null>(null);
  const [runError, setRunError] = useState<string | null>(null);

  // Completed benchmark history for scaling visualization
  const [benchmarkHistory, setBenchmarkHistory] = useState<BenchmarkResult[]>([]);

  // Sub-view toggle: Workload Scaling vs Burst Stress Test
  const [activeTab, setActiveTab] = useState<'scale_lab' | 'burst_test'>('scale_lab');

  // Representative samples tab & detail drawer
  const [sampleTab, setSampleTab] = useState<'legitimate' | 'fraud' | 'random'>('legitimate');
  const [selectedTx, setSelectedTx] = useState<BenchmarkSampleTransaction | null>(null);

  // Burst test state
  const [burstCount, setBurstCount] = useState(500);
  const [burstRunning, setBurstRunning] = useState(false);
  const [burstResult, setBurstResult] = useState<StressTestResult | null>(null);
  const [burstError, setBurstError] = useState<ApiError | null>(null);

  const pollTimerRef = useRef<number | null>(null);

  // Load server-defined presets & guardrails
  const loadPresets = useCallback(async () => {
    try {
      const data = await api.getBenchmarkPresets();
      setPresetData(data);
    } catch {
      // Degrades gracefully to default presets
    }
  }, []);

  useEffect(() => {
    loadPresets();
  }, [loadPresets]);

  // Clean up polling timer on unmount
  useEffect(() => {
    return () => {
      if (pollTimerRef.current) window.clearTimeout(pollTimerRef.current);
    };
  }, []);

  const pollStatusRef = useRef<((runId: string) => Promise<void>) | null>(null);

  // Poll active benchmark
  const pollStatus = useCallback(
    async (runId: string) => {
      try {
        const progressRes = await api.getBenchmarkProgress(runId);
        if (progressRes.progress) {
          setProgress(progressRes.progress);
          setActiveStage(progressRes.progress.stage || 'RUNNING');
        }

        if (progressRes.finished) {
          setIsPolling(false);

          // Status precedence: failed > stopped_early > capped > completed
          if (
            progressRes.status === 'completed' ||
            progressRes.status === 'stopped_early' ||
            progressRes.status === 'capped'
          ) {
            const fullRun = await api.getBenchmark(runId);
            if (fullRun.result) {
              setRunResult(fullRun.result);
              setBenchmarkHistory((prev) => [fullRun.result!, ...prev]);
            } else if (fullRun.error) {
              setRunError(fullRun.error);
            }
          } else if (progressRes.status === 'rejected') {
            setRunError(
              'Experimental benchmark execution rejected (allow_experimental=false in server environment).'
            );
          } else {
            setRunError(progressRes.error || 'Benchmark execution failed.');
          }
        } else {
          // Schedule next poll
          pollTimerRef.current = window.setTimeout(() => pollStatusRef.current?.(runId), 1200);
        }
      } catch (err) {
        setIsPolling(false);
        setRunError((err as Error).message);
      }
    },
    []
  );

  useEffect(() => {
    pollStatusRef.current = pollStatus;
  }, [pollStatus]);

  // Trigger new benchmark
  const startBenchmark = useCallback(async () => {
    if (pollTimerRef.current) window.clearTimeout(pollTimerRef.current);
    setIsSubmitting(true);
    setRunError(null);
    setRunResult(null);
    setProgress(null);
    setActiveStage('INITIALIZING');

    try {
      const response: BenchmarkCreateResponse = await api.createBenchmark({
        workload_size: selectedSize,
        duration_minutes: durationMinutes,
        scenario_mix: selectedMix,
        benchmark_mode: selectedMode,
      });

      setActiveRunId(response.run_id);
      setIsSubmitting(false);
      setIsPolling(true);

      // Start polling
      pollTimerRef.current = window.setTimeout(() => pollStatus(response.run_id), 800);
    } catch (err) {
      setIsSubmitting(false);
      const apiErr = err as ApiError;
      if (apiErr.status === 403) {
        setRunError(
          apiErr.detail ||
            'Benchmark rejected: Experimental benchmarks are disabled in this environment (VEYRA_BENCHMARK_ALLOW_EXPERIMENTAL=false).'
        );
      } else {
        setRunError(apiErr.detail || (err as Error).message);
      }
    }
  }, [selectedSize, durationMinutes, selectedMix, selectedMode, pollStatus]);

  // Trigger quick burst test
  const runBurst = useCallback(async () => {
    setBurstRunning(true);
    setBurstError(null);
    try {
      const res = await api.runStressTest({
        scenario_id: 'card_testing_burst',
        burst_count: burstCount,
        merchant_category: 'electronics',
      });
      setBurstResult(res);
    } catch (err) {
      setBurstError(err as ApiError);
    } finally {
      setBurstRunning(false);
    }
  }, [burstCount]);

  const selectedPreset = presetData?.presets.find((p) => p.workload_size === selectedSize);
  const isExperimentalDisallowed =
    selectedPreset?.tier === 'experimental' &&
    presetData !== null &&
    !presetData.guardrails.allow_experimental;

  // Helper for rendering authoritative status badge
  const renderStatusBadge = (status: BenchmarkStatus, stopReason?: string | null) => {
    switch (status) {
      case 'completed':
        return (
          <span
            style={{
              display: 'inline-flex',
              alignItems: 'center',
              gap: 6,
              padding: '4px 8px',
              borderRadius: 4,
              fontSize: '11px',
              fontFamily: 'var(--font-mono)',
              fontWeight: 700,
              background: 'rgba(16, 185, 129, 0.15)',
              color: 'var(--color-safe)',
              border: '1px solid rgba(16, 185, 129, 0.35)',
            }}
          >
            <CheckCircle2 size={13} />
            COMPLETED
          </span>
        );
      case 'stopped_early':
        return (
          <span
            style={{
              display: 'inline-flex',
              alignItems: 'center',
              gap: 6,
              padding: '4px 8px',
              borderRadius: 4,
              fontSize: '11px',
              fontFamily: 'var(--font-mono)',
              fontWeight: 700,
              background: 'rgba(245, 158, 11, 0.15)',
              color: 'var(--color-warning)',
              border: '1px solid rgba(245, 158, 11, 0.35)',
            }}
          >
            <AlertTriangle size={13} />
            STOPPED EARLY
            {stopReason && (
              <span style={{ fontWeight: 500, opacity: 0.9 }}>
                ({stopReason.replace(/_/g, ' ')})
              </span>
            )}
          </span>
        );
      case 'capped':
        return (
          <span
            style={{
              display: 'inline-flex',
              alignItems: 'center',
              gap: 6,
              padding: '4px 8px',
              borderRadius: 4,
              fontSize: '11px',
              fontFamily: 'var(--font-mono)',
              fontWeight: 700,
              background: 'rgba(59, 130, 246, 0.15)',
              color: 'var(--accent-bright)',
              border: '1px solid rgba(59, 130, 246, 0.35)',
            }}
          >
            <ShieldAlert size={13} />
            CAPPED BY CEILING
          </span>
        );
      case 'rejected':
        return (
          <span
            style={{
              display: 'inline-flex',
              alignItems: 'center',
              gap: 6,
              padding: '4px 8px',
              borderRadius: 4,
              fontSize: '11px',
              fontFamily: 'var(--font-mono)',
              fontWeight: 700,
              background: 'rgba(255, 46, 76, 0.15)',
              color: 'var(--color-critical)',
              border: '1px solid rgba(255, 46, 76, 0.35)',
            }}
          >
            <XCircle size={13} />
            REJECTED
          </span>
        );
      case 'failed':
      default:
        return (
          <span
            style={{
              display: 'inline-flex',
              alignItems: 'center',
              gap: 6,
              padding: '4px 8px',
              borderRadius: 4,
              fontSize: '11px',
              fontFamily: 'var(--font-mono)',
              fontWeight: 700,
              background: 'rgba(255, 46, 76, 0.15)',
              color: 'var(--color-critical)',
              border: '1px solid rgba(255, 46, 76, 0.35)',
            }}
          >
            <XCircle size={13} />
            FAILED
          </span>
        );
    }
  };

  return (
    <div className="container-wide" style={{ padding: 'var(--sp-6) var(--sp-5) var(--sp-9)' }}>
      {/* Header */}
      <div style={{ marginBottom: 'var(--sp-5)' }}>
        <div
          style={{
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            flexWrap: 'wrap',
            gap: 12,
          }}
        >
          <div>
            <SectionLabel>Scale &amp; Resilience Lab</SectionLabel>
            <h1 style={{ fontSize: 'var(--text-2xl)', marginTop: 6, fontWeight: 700 }}>
              Veyra Scale Lab
            </h1>
            <p
              style={{
                color: 'var(--text-secondary)',
                marginTop: 8,
                maxWidth: 760,
                fontSize: 'var(--text-md)',
              }}
            >
              Measure ingestion throughput and pipeline computation across large synthetic workloads
              (100K to 100M events). Every measurement is strictly executed and timed server-side in
              this local benchmark environment.
            </p>
          </div>

          {/* Mode Tabs */}
          <div
            style={{
              display: 'flex',
              gap: 6,
              background: 'var(--surface-1)',
              padding: 4,
              borderRadius: 8,
              border: '1px solid var(--border)',
            }}
          >
            <button
              onClick={() => setActiveTab('scale_lab')}
              style={{
                padding: '6px 14px',
                borderRadius: 6,
                background: activeTab === 'scale_lab' ? 'var(--accent-wash)' : 'transparent',
                border: `1px solid ${activeTab === 'scale_lab' ? 'var(--accent)' : 'transparent'}`,
                color: activeTab === 'scale_lab' ? 'var(--accent-bright)' : 'var(--text-secondary)',
                fontSize: 'var(--text-xs)',
                fontWeight: 600,
                cursor: 'pointer',
              }}
            >
              Workload Scaling Lab
            </button>
            <button
              onClick={() => setActiveTab('burst_test')}
              style={{
                padding: '6px 14px',
                borderRadius: 6,
                background: activeTab === 'burst_test' ? 'var(--accent-wash)' : 'transparent',
                border: `1px solid ${activeTab === 'burst_test' ? 'var(--accent)' : 'transparent'}`,
                color: activeTab === 'burst_test' ? 'var(--accent-bright)' : 'var(--text-secondary)',
                fontSize: 'var(--text-xs)',
                fontWeight: 600,
                cursor: 'pointer',
              }}
            >
              Burst Injection Test
            </button>
          </div>
        </div>
      </div>

      {activeTab === 'scale_lab' ? (
        <div className="veyra-detection-grid">
          {/* ------------------------------------------------ Control Rail */}
          <aside style={{ display: 'grid', gap: 'var(--sp-4)', alignContent: 'start' }}>
            <Card style={{ display: 'grid', gap: 'var(--sp-5)' }}>
              {/* Step 1: Benchmark Mode */}
              <div>
                <div
                  style={{
                    fontSize: '11px',
                    color: 'var(--text-muted)',
                    textTransform: 'uppercase',
                    letterSpacing: '0.05em',
                    fontWeight: 700,
                  }}
                >
                  1. Benchmark Mode
                </div>
                <div style={{ display: 'grid', gap: 6, marginTop: 8 }}>
                  <button
                    onClick={() => setSelectedMode('pipeline')}
                    style={{
                      padding: '10px 12px',
                      borderRadius: 'var(--radius-sm)',
                      background:
                        selectedMode === 'pipeline' ? 'var(--accent-wash)' : 'var(--surface-2)',
                      border: `1px solid ${
                        selectedMode === 'pipeline' ? 'var(--accent)' : 'var(--border)'
                      }`,
                      textAlign: 'left',
                      cursor: 'pointer',
                    }}
                  >
                    <div
                      style={{
                        fontWeight: 600,
                        fontSize: 'var(--text-xs)',
                        color:
                          selectedMode === 'pipeline'
                            ? 'var(--accent-bright)'
                            : 'var(--text-primary)',
                      }}
                    >
                      DETECTION / COMPUTATION SCALE
                    </div>
                    <div style={{ fontSize: '11px', color: 'var(--text-muted)', marginTop: 2 }}>
                      Measures ingestion + contextual features, entity graphs &amp; model scoring on
                      sample windows.
                    </div>
                  </button>

                  <button
                    onClick={() => setSelectedMode('ingestion')}
                    style={{
                      padding: '10px 12px',
                      borderRadius: 'var(--radius-sm)',
                      background:
                        selectedMode === 'ingestion' ? 'var(--accent-wash)' : 'var(--surface-2)',
                      border: `1px solid ${
                        selectedMode === 'ingestion' ? 'var(--accent)' : 'var(--border)'
                      }`,
                      textAlign: 'left',
                      cursor: 'pointer',
                    }}
                  >
                    <div
                      style={{
                        fontWeight: 600,
                        fontSize: 'var(--text-xs)',
                        color:
                          selectedMode === 'ingestion'
                            ? 'var(--accent-bright)'
                            : 'var(--text-primary)',
                      }}
                    >
                      INGESTION / WRITE SCALE
                    </div>
                    <div style={{ fontSize: '11px', color: 'var(--text-muted)', marginTop: 2 }}>
                      Measures bulk generation, validation, fingerprinting, and persistence.
                    </div>
                  </button>
                </div>
              </div>

              {/* Step 2: Workload Size Presets */}
              <div>
                <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
                  <div
                    style={{
                      fontSize: '11px',
                      color: 'var(--text-muted)',
                      textTransform: 'uppercase',
                      letterSpacing: '0.05em',
                      fontWeight: 700,
                    }}
                  >
                    2. Workload Preset
                  </div>
                  {selectedPreset?.tier === 'experimental' && (
                    <span
                      style={{
                        fontSize: '10px',
                        color: 'var(--color-critical)',
                        fontWeight: 700,
                        background: 'rgba(255, 46, 76, 0.1)',
                        padding: '2px 6px',
                        borderRadius: 4,
                      }}
                    >
                      EXPERIMENTAL
                    </span>
                  )}
                </div>

                <div
                  style={{
                    display: 'grid',
                    gridTemplateColumns: 'repeat(5, 1fr)',
                    gap: 6,
                    marginTop: 8,
                  }}
                >
                  {(
                    presetData?.presets || [
                      {
                        workload_size: 100_000,
                        label: '100K',
                        tier: 'safe',
                        will_be_capped: false,
                        executed_size_if_requested: 100_000,
                      },
                      {
                        workload_size: 500_000,
                        label: '500K',
                        tier: 'safe',
                        will_be_capped: false,
                        executed_size_if_requested: 500_000,
                      },
                      {
                        workload_size: 1_000_000,
                        label: '1M',
                        tier: 'safe',
                        will_be_capped: false,
                        executed_size_if_requested: 1_000_000,
                      },
                      {
                        workload_size: 10_000_000,
                        label: '10M',
                        tier: 'extended',
                        will_be_capped: true,
                        executed_size_if_requested: 2_000_000,
                      },
                      {
                        workload_size: 100_000_000,
                        label: '100M',
                        tier: 'experimental',
                        will_be_capped: true,
                        executed_size_if_requested: 2_000_000,
                      },
                    ]
                  ).map((p) => {
                    const active = p.workload_size === selectedSize;
                    const isExp = p.tier === 'experimental';
                    return (
                      <button
                        key={p.workload_size}
                        onClick={() => setSelectedSize(p.workload_size)}
                        style={{
                          padding: '8px 4px',
                          borderRadius: 'var(--radius-sm)',
                          background: active ? 'var(--accent-wash)' : 'var(--surface-2)',
                          border: `1px solid ${
                            active
                              ? 'var(--accent)'
                              : isExp
                              ? 'rgba(255, 46, 76, 0.3)'
                              : 'var(--border)'
                          }`,
                          color: active
                            ? 'var(--accent-bright)'
                            : isExp
                            ? 'var(--color-critical)'
                            : 'var(--text-secondary)',
                          fontFamily: 'var(--font-mono)',
                          fontSize: 'var(--text-xs)',
                          fontWeight: 700,
                          cursor: 'pointer',
                        }}
                      >
                        {p.label}
                      </button>
                    );
                  })}
                </div>

                {/* Server Ceiling Notice */}
                {selectedPreset?.will_be_capped && (
                  <div
                    style={{
                      fontSize: '11px',
                      color: 'var(--color-critical)',
                      background: 'rgba(255, 46, 76, 0.08)',
                      border: '1px solid rgba(255, 46, 76, 0.2)',
                      borderRadius: 4,
                      padding: '6px 8px',
                      marginTop: 8,
                      lineHeight: 1.4,
                    }}
                  >
                    <strong>Safety Cap:</strong> Server ceiling is{' '}
                    {presetData?.guardrails.hard_cap_events.toLocaleString() || '2,000,000'} events
                    in this environment. Workload will execute at cap and report as capped.
                  </div>
                )}

                {/* Experimental Notice */}
                {isExperimentalDisallowed && (
                  <div
                    style={{
                      fontSize: '11px',
                      color: 'var(--color-warning)',
                      background: 'rgba(245, 158, 11, 0.08)',
                      border: '1px solid rgba(245, 158, 11, 0.2)',
                      borderRadius: 4,
                      padding: '6px 8px',
                      marginTop: 8,
                      lineHeight: 1.4,
                    }}
                  >
                    <strong>Experimental Execution Disabled:</strong> Server has{' '}
                    <code>allow_experimental=false</code>. Running 100M will be rejected with HTTP 403.
                  </div>
                )}
              </div>

              {/* Step 3: Workload Composition */}
              <div>
                <div
                  style={{
                    fontSize: '11px',
                    color: 'var(--text-muted)',
                    textTransform: 'uppercase',
                    letterSpacing: '0.05em',
                    fontWeight: 700,
                  }}
                >
                  3. Traffic Composition
                </div>
                <div style={{ display: 'grid', gap: 4, marginTop: 8 }}>
                  {(
                    presetData?.scenario_mixes || [
                      { id: 'all_legit', label: '100% Legitimate', fraud_ratio: 0.0 },
                      { id: 'legit_90_fraud_10', label: '90% Legitimate / 10% Fraud', fraud_ratio: 0.1 },
                      { id: 'mixed_50_50', label: '50% / 50%', fraud_ratio: 0.5 },
                      { id: 'fraud_90_legit_10', label: '10% Legitimate / 90% Fraud', fraud_ratio: 0.9 },
                      { id: 'all_fraud', label: '100% Fraud', fraud_ratio: 1.0 },
                    ]
                  ).map((mix) => {
                    const active = mix.id === selectedMix;
                    return (
                      <button
                        key={mix.id}
                        onClick={() => setSelectedMix(mix.id as ScenarioMix)}
                        style={{
                          padding: '6px 10px',
                          borderRadius: 4,
                          background: active ? 'var(--accent-wash)' : 'transparent',
                          border: `1px solid ${active ? 'var(--accent)' : 'transparent'}`,
                          color: active ? 'var(--accent-bright)' : 'var(--text-secondary)',
                          fontSize: 'var(--text-xs)',
                          textAlign: 'left',
                          cursor: 'pointer',
                        }}
                      >
                        {mix.label}
                      </button>
                    );
                  })}
                </div>
              </div>

              {/* Step 4: Time Horizon */}
              <div>
                <div
                  style={{
                    fontSize: '11px',
                    color: 'var(--text-muted)',
                    textTransform: 'uppercase',
                    letterSpacing: '0.05em',
                    fontWeight: 700,
                  }}
                >
                  4. Simulated Time Horizon
                </div>
                <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 6, marginTop: 8 }}>
                  {[5.0, 30.0].map((mins) => {
                    const active = durationMinutes === mins;
                    return (
                      <button
                        key={mins}
                        onClick={() => setDurationMinutes(mins)}
                        style={{
                          padding: '6px 10px',
                          borderRadius: 4,
                          background: active ? 'var(--accent-wash)' : 'var(--surface-2)',
                          border: `1px solid ${active ? 'var(--accent)' : 'var(--border)'}`,
                          color: active ? 'var(--accent-bright)' : 'var(--text-secondary)',
                          fontSize: 'var(--text-xs)',
                          fontWeight: 600,
                          cursor: 'pointer',
                        }}
                      >
                        {mins} minutes
                      </button>
                    );
                  })}
                </div>
              </div>

              {/* Action Button */}
              <Button
                variant="primary"
                size="lg"
                full
                loading={isSubmitting || isPolling}
                onClick={startBenchmark}
                icon={<Play size={16} />}
              >
                {isSubmitting
                  ? 'Queueing benchmark…'
                  : isPolling
                  ? 'Executing workload…'
                  : `Run Scale Benchmark (${selectedPreset?.label || '100K'})`}
              </Button>
            </Card>

            {/* Explanation Card */}
            <Card style={{ padding: 14 }}>
              <div style={{ display: 'flex', gap: 8, alignItems: 'flex-start' }}>
                <HelpCircle
                  size={15}
                  color="var(--accent-bright)"
                  style={{ flexShrink: 0, marginTop: 2 }}
                />
                <div style={{ fontSize: '11px', color: 'var(--text-muted)', lineHeight: 1.5 }}>
                  <strong style={{ color: 'var(--text-primary)' }}>
                    What does this benchmark mean?
                  </strong>
                  <p style={{ margin: '4px 0 6px' }}>
                    Veyra generates synthetic payment traffic and measures how the current
                    environment behaves as workload size increases. These measurements describe this
                    benchmark environment, not production capacity.
                  </p>
                  <p style={{ margin: '4px 0' }}>
                    • <strong>Detection computation</strong> is measured per merchant-window, not per transaction.
                  </p>
                  <p style={{ margin: '4px 0' }}>
                    • <strong>Ingestion throughput</strong> measures bulk generation, validation, and persistence.
                  </p>
                </div>
              </div>
            </Card>
          </aside>

          {/* ------------------------------------------------ Results / Execution View */}
          <main style={{ display: 'grid', gap: 'var(--sp-5)', alignContent: 'start', minWidth: 0 }}>
            {/* Live Progress Card */}
            {(isSubmitting || isPolling) && (
              <Card style={{ display: 'grid', gap: 14, padding: 20 }}>
                <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                    <Loader2 size={16} className="spin" color="var(--accent-bright)" />
                    <span
                      style={{
                        fontFamily: 'var(--font-mono)',
                        fontSize: 'var(--text-xs)',
                        fontWeight: 700,
                        color: 'var(--accent-bright)',
                      }}
                    >
                      {activeStage}: {progress ? `${progress.percent.toFixed(0)}%` : 'PREPARING'}
                    </span>
                  </div>

                  {activeRunId && (
                    <span
                      style={{
                        fontFamily: 'var(--font-mono)',
                        fontSize: '11px',
                        color: 'var(--text-muted)',
                      }}
                    >
                      ID: {activeRunId}
                    </span>
                  )}
                </div>

                {/* Progress bar */}
                <div
                  style={{
                    height: 6,
                    background: 'rgba(255, 255, 255, 0.08)',
                    borderRadius: 3,
                    overflow: 'hidden',
                  }}
                >
                  <div
                    style={{
                      height: '100%',
                      width: `${progress ? Math.min(100, Math.max(5, progress.percent)) : 10}%`,
                      background: 'var(--accent)',
                      transition: 'width 0.3s ease',
                    }}
                  />
                </div>

                <div
                  style={{
                    display: 'flex',
                    justifyContent: 'space-between',
                    fontSize: '11px',
                    color: 'var(--text-muted)',
                    fontFamily: 'var(--font-mono)',
                  }}
                >
                  <span>
                    Processed:{' '}
                    {progress?.events_processed.toLocaleString() ?? 0} /{' '}
                    {progress?.events_target.toLocaleString() ?? selectedSize.toLocaleString()}
                  </span>
                  <span>
                    Elapsed: {progress ? `${(progress.elapsed_ms / 1000).toFixed(1)}s` : '0.0s'}
                  </span>
                </div>

                {selectedSize >= 1_000_000 && (
                  <p
                    style={{
                      fontSize: '11px',
                      color: 'var(--text-muted)',
                      fontStyle: 'italic',
                      marginTop: 4,
                    }}
                  >
                    Large synthetic workload benchmark in progress. Multi-minute runs stream live
                    execution snapshots from the background worker.
                  </p>
                )}
              </Card>
            )}

            {/* Error State */}
            {runError && (
              <ErrorState
                title="Benchmark Execution Status"
                detail={runError}
                onRetry={startBenchmark}
              />
            )}

            {/* Empty State before any run */}
            {!isPolling && !runResult && !runError && (
              <Card style={{ padding: 'var(--sp-7)' }}>
                <EmptyState
                  title="Ready to benchmark workload"
                  description="Select a workload preset (100K to 100M events) and execution mode, then click 'Run Scale Benchmark' to measure throughput and computation scaling."
                />
              </Card>
            )}

            {/* Completed Benchmark Results Card */}
            {runResult && (
              <div style={{ display: 'grid', gap: 'var(--sp-4)' }}>
                {/* 1. WORKLOAD & AUTHORITATIVE STATUS */}
                <Card style={{ display: 'grid', gap: 16 }}>
                  <div
                    style={{
                      display: 'flex',
                      alignItems: 'center',
                      justifyContent: 'space-between',
                      flexWrap: 'wrap',
                      gap: 12,
                    }}
                  >
                    <div>
                      <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                        {renderStatusBadge(runResult.status, runResult.stop_reason)}
                        {runResult.capped && runResult.status !== 'capped' && (
                          <span
                            style={{
                              fontSize: '10px',
                              background: 'rgba(59, 130, 246, 0.15)',
                              color: 'var(--accent-bright)',
                              border: '1px solid rgba(59, 130, 246, 0.3)',
                              padding: '2px 6px',
                              borderRadius: 4,
                              fontWeight: 700,
                            }}
                          >
                            CAPPED AT CEILING ({runResult.capped_workload_size.toLocaleString()})
                          </span>
                        )}
                      </div>
                      <h2 style={{ fontSize: 'var(--text-lg)', fontWeight: 700, marginTop: 6 }}>
                        {runResult.traffic.generated_events.toLocaleString()} Synthetic Events Processed
                      </h2>
                      <div style={{ fontSize: '11px', color: 'var(--text-muted)', marginTop: 2 }}>
                        Requested: {runResult.requested_workload_size.toLocaleString()} · Actual:{' '}
                        {runResult.traffic.generated_events.toLocaleString()}
                        {runResult.stop_reason && ` · Reason: ${runResult.stop_reason.replace(/_/g, ' ')}`}
                      </div>
                    </div>

                    <div
                      style={{
                        fontFamily: 'var(--font-mono)',
                        fontSize: 'var(--text-xs)',
                        color: 'var(--text-muted)',
                        textAlign: 'right',
                      }}
                    >
                      <div>
                        Mode:{' '}
                        <strong style={{ color: 'var(--text-primary)' }}>
                          {runResult.benchmark_mode === 'pipeline'
                            ? 'DETECTION / COMPUTATION'
                            : 'INGESTION / WRITE'}
                        </strong>
                      </div>
                      <div style={{ marginTop: 2 }}>Mix: {runResult.scenario_mix}</div>
                    </div>
                  </div>

                  {/* 2. TRAFFIC COMPOSITION VISUAL */}
                  <div
                    style={{
                      padding: 14,
                      background: 'rgba(255, 255, 255, 0.02)',
                      borderRadius: 6,
                      border: '1px solid var(--border)',
                      display: 'grid',
                      gap: 8,
                    }}
                  >
                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                      <span
                        style={{
                          fontSize: '11px',
                          color: 'var(--text-muted)',
                          textTransform: 'uppercase',
                          fontWeight: 700,
                          letterSpacing: '0.04em',
                        }}
                      >
                        Measured Traffic Composition
                      </span>
                      <span
                        style={{
                          fontFamily: 'var(--font-mono)',
                          fontSize: '11px',
                          color: 'var(--text-secondary)',
                        }}
                      >
                        {runResult.traffic.generated_events.toLocaleString()} actual events
                      </span>
                    </div>

                    {/* Proportional Bar */}
                    {(() => {
                      const total = Math.max(1, runResult.traffic.generated_events);
                      const legitPct = (runResult.traffic.legitimate_events / total) * 100;
                      const fraudPct = (runResult.traffic.fraud_events / total) * 100;
                      return (
                        <div
                          style={{
                            height: 10,
                            borderRadius: 5,
                            overflow: 'hidden',
                            display: 'flex',
                            background: 'rgba(255, 255, 255, 0.05)',
                          }}
                        >
                          <div
                            style={{
                              width: `${legitPct}%`,
                              background: 'var(--color-safe)',
                              transition: 'width 0.3s ease',
                            }}
                            title={`Legitimate: ${runResult.traffic.legitimate_events.toLocaleString()} (${legitPct.toFixed(1)}%)`}
                          />
                          <div
                            style={{
                              width: `${fraudPct}%`,
                              background: 'var(--color-critical)',
                              transition: 'width 0.3s ease',
                            }}
                            title={`Fraud: ${runResult.traffic.fraud_events.toLocaleString()} (${fraudPct.toFixed(1)}%)`}
                          />
                        </div>
                      );
                    })()}

                    <div
                      style={{
                        display: 'flex',
                        justifyContent: 'space-between',
                        fontSize: '11px',
                        fontFamily: 'var(--font-mono)',
                        flexWrap: 'wrap',
                        gap: 8,
                      }}
                    >
                      <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                        <div
                          style={{
                            width: 8,
                            height: 8,
                            borderRadius: '50%',
                            background: 'var(--color-safe)',
                          }}
                        />
                        <span style={{ color: 'var(--text-primary)', fontWeight: 600 }}>
                          {runResult.traffic.legitimate_events.toLocaleString()} Legitimate
                        </span>
                        <span style={{ color: 'var(--text-muted)' }}>
                          (
                          {(
                            (runResult.traffic.legitimate_events /
                              Math.max(1, runResult.traffic.generated_events)) *
                            100
                          ).toFixed(1)}
                          %)
                        </span>
                      </div>

                      <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                        <div
                          style={{
                            width: 8,
                            height: 8,
                            borderRadius: '50%',
                            background: 'var(--color-critical)',
                          }}
                        />
                        <span style={{ color: 'var(--text-primary)', fontWeight: 600 }}>
                          {runResult.traffic.fraud_events.toLocaleString()} Fraud
                        </span>
                        <span style={{ color: 'var(--text-muted)' }}>
                          (
                          {(
                            (runResult.traffic.fraud_events /
                              Math.max(1, runResult.traffic.generated_events)) *
                            100
                          ).toFixed(1)}
                          %)
                        </span>
                      </div>

                      <div style={{ color: 'var(--text-muted)' }}>
                        Actual Fraud Ratio:{' '}
                        <strong style={{ color: 'var(--text-primary)' }}>
                          {runResult.traffic.actual_fraud_ratio !== null
                            ? `${(runResult.traffic.actual_fraud_ratio * 100).toFixed(1)}%`
                            : '—'}
                        </strong>{' '}
                        (requested:{' '}
                        {runResult.traffic.requested_fraud_ratio !== null
                          ? `${(runResult.traffic.requested_fraud_ratio * 100).toFixed(0)}%`
                          : '—'}
                        )
                      </div>
                    </div>
                  </div>

                  {/* Primary Stats Grid */}
                  <div
                    style={{
                      display: 'grid',
                      gridTemplateColumns: 'repeat(auto-fit, minmax(140px, 1fr))',
                      gap: 12,
                      paddingTop: 12,
                      borderTop: '1px solid rgba(255, 255, 255, 0.06)',
                    }}
                  >
                    <div>
                      <div
                        style={{
                          fontSize: '10px',
                          color: 'var(--text-muted)',
                          textTransform: 'uppercase',
                          letterSpacing: '0.04em',
                        }}
                      >
                        Ingestion Throughput
                      </div>
                      <div
                        style={{
                          fontFamily: 'var(--font-mono)',
                          fontSize: '18px',
                          fontWeight: 800,
                          color: 'var(--accent-bright)',
                          marginTop: 2,
                        }}
                      >
                        {runResult.ingestion.events_per_second
                          ? `${Math.round(runResult.ingestion.events_per_second).toLocaleString()} events/sec`
                          : '—'}
                      </div>
                      <div style={{ fontSize: '10px', color: 'var(--text-muted)', marginTop: 2 }}>
                        {runResult.ingestion.write_duration_ms
                          ? `${(runResult.ingestion.write_duration_ms / 1000).toFixed(2)}s write duration`
                          : ''}
                      </div>
                    </div>

                    <div>
                      <div
                        style={{
                          fontSize: '10px',
                          color: 'var(--text-muted)',
                          textTransform: 'uppercase',
                          letterSpacing: '0.04em',
                        }}
                      >
                        Total Pipeline Duration
                      </div>
                      <div
                        style={{
                          fontFamily: 'var(--font-mono)',
                          fontSize: '18px',
                          fontWeight: 800,
                          color: 'var(--text-primary)',
                          marginTop: 2,
                        }}
                      >
                        {(runResult.total_ms / 1000).toFixed(2)}s
                      </div>
                      <div style={{ fontSize: '10px', color: 'var(--text-muted)', marginTop: 2 }}>
                        Wall-clock perf_counter
                      </div>
                    </div>

                    <div>
                      <div
                        style={{
                          fontSize: '10px',
                          color: 'var(--text-muted)',
                          textTransform: 'uppercase',
                          letterSpacing: '0.04em',
                        }}
                      >
                        Peak Traced Python Heap
                      </div>
                      <div
                        style={{
                          fontFamily: 'var(--font-mono)',
                          fontSize: '18px',
                          fontWeight: 800,
                          color: 'var(--text-primary)',
                          marginTop: 2,
                        }}
                      >
                        {runResult.memory.peak_traced_python_heap_mb
                          ? `${runResult.memory.peak_traced_python_heap_mb.toFixed(1)} MB`
                          : '—'}
                      </div>
                      <div style={{ fontSize: '10px', color: 'var(--text-muted)', marginTop: 2 }}>
                        tracemalloc heap (not process RSS)
                      </div>
                    </div>

                    <div>
                      <div
                        style={{
                          fontSize: '10px',
                          color: 'var(--text-muted)',
                          textTransform: 'uppercase',
                          letterSpacing: '0.04em',
                        }}
                      >
                        Storage Growth
                      </div>
                      <div
                        style={{
                          fontFamily: 'var(--font-mono)',
                          fontSize: '18px',
                          fontWeight: 800,
                          color: 'var(--text-primary)',
                          marginTop: 2,
                        }}
                      >
                        {runResult.storage.storage_delta_mb
                          ? `+${runResult.storage.storage_delta_mb.toFixed(2)} MB`
                          : '—'}
                      </div>
                      <div style={{ fontSize: '10px', color: 'var(--text-muted)', marginTop: 2 }}>
                        SQLite delta before cleanup
                      </div>
                    </div>
                  </div>
                </Card>

                {/* 3. DETECTION COMPUTATION SCALE (if pipeline mode and computation metrics present) */}
                {runResult.computation && (
                  <Card style={{ display: 'grid', gap: 12 }}>
                    <div
                      style={{
                        display: 'flex',
                        alignItems: 'center',
                        justifyContent: 'space-between',
                        flexWrap: 'wrap',
                        gap: 8,
                      }}
                    >
                      <div>
                        <h3 style={{ fontSize: 'var(--text-sm)', fontWeight: 700 }}>
                          Merchant-Window Computation ({runResult.computation.sampled_windows} Sampled Windows)
                        </h3>
                        <p style={{ fontSize: '11px', color: 'var(--text-muted)', marginTop: 2 }}>
                          Detection computation is measured per merchant-window, not per transaction.
                        </p>
                      </div>

                      <div
                        style={{
                          fontFamily: 'var(--font-mono)',
                          fontSize: 'var(--text-sm)',
                          fontWeight: 700,
                          color: 'var(--accent-bright)',
                          background: 'rgba(59, 130, 246, 0.1)',
                          padding: '4px 10px',
                          borderRadius: 4,
                          border: '1px solid rgba(59, 130, 246, 0.25)',
                        }}
                      >
                        {runResult.computation.per_window_latency_ms.toFixed(1)} ms / merchant-window
                      </div>
                    </div>

                    <div style={{ overflowX: 'auto' }}>
                      <table
                        style={{
                          width: '100%',
                          borderCollapse: 'collapse',
                          fontSize: 'var(--text-xs)',
                          fontFamily: 'var(--font-mono)',
                        }}
                      >
                        <thead>
                          <tr
                            style={{
                              borderBottom: '1px solid var(--border)',
                              color: 'var(--text-muted)',
                              textAlign: 'left',
                            }}
                          >
                            <th style={{ padding: '8px 10px' }}>Computation Stage</th>
                            <th style={{ padding: '8px 10px' }}>Total Time</th>
                            <th style={{ padding: '8px 10px' }}>Cost Per Merchant-Window</th>
                            <th style={{ padding: '8px 10px' }}>Description</th>
                          </tr>
                        </thead>
                        <tbody>
                          <tr style={{ borderBottom: '1px solid rgba(255, 255, 255, 0.04)' }}>
                            <td style={{ padding: '8px 10px', fontWeight: 600, color: 'var(--text-primary)' }}>
                              Feature Extraction
                            </td>
                            <td style={{ padding: '8px 10px' }}>
                              {runResult.computation.feature_extraction_total_ms.toFixed(1)} ms
                            </td>
                            <td style={{ padding: '8px 10px', color: 'var(--accent-bright)', fontWeight: 600 }}>
                              {runResult.computation.feature_extraction_per_window_ms.toFixed(2)} ms / window
                            </td>
                            <td style={{ padding: '8px 10px', color: 'var(--text-secondary)' }}>
                              Statistical feature families A–I
                            </td>
                          </tr>
                          <tr style={{ borderBottom: '1px solid rgba(255, 255, 255, 0.04)' }}>
                            <td style={{ padding: '8px 10px', fontWeight: 600, color: 'var(--text-primary)' }}>
                              Entity Graph Construction
                            </td>
                            <td style={{ padding: '8px 10px' }}>
                              {runResult.computation.entity_graph_total_ms.toFixed(1)} ms
                            </td>
                            <td style={{ padding: '8px 10px', color: 'var(--accent-bright)', fontWeight: 600 }}>
                              {runResult.computation.entity_graph_per_window_ms.toFixed(2)} ms / window
                            </td>
                            <td style={{ padding: '8px 10px', color: 'var(--text-secondary)' }}>
                              Bipartite clustering &amp; Gini coefficient
                            </td>
                          </tr>
                          <tr style={{ borderBottom: '1px solid rgba(255, 255, 255, 0.04)' }}>
                            <td style={{ padding: '8px 10px', fontWeight: 600, color: 'var(--text-primary)' }}>
                              Model Inference (Scoring)
                            </td>
                            <td style={{ padding: '8px 10px' }}>
                              {runResult.computation.model_inference_total_ms.toFixed(1)} ms
                            </td>
                            <td style={{ padding: '8px 10px', color: 'var(--accent-bright)', fontWeight: 600 }}>
                              {runResult.computation.model_inference_per_window_ms.toFixed(2)} ms / window
                            </td>
                            <td style={{ padding: '8px 10px', color: 'var(--text-secondary)' }}>
                              Fitted fusion classifier score
                            </td>
                          </tr>
                        </tbody>
                      </table>
                    </div>
                  </Card>
                )}

                {/* 4. REPRESENTATIVE SYNTHETIC EVENTS (RESERVOIR SAMPLES) */}
                {runResult.samples && (
                  <Card style={{ display: 'grid', gap: 14 }}>
                    <div
                      style={{
                        display: 'flex',
                        alignItems: 'center',
                        justifyContent: 'space-between',
                        flexWrap: 'wrap',
                        gap: 10,
                      }}
                    >
                      <div>
                        <div
                          style={{
                            fontSize: '10px',
                            color: 'var(--text-muted)',
                            textTransform: 'uppercase',
                            letterSpacing: '0.04em',
                            fontWeight: 700,
                          }}
                        >
                          Workload Inspection
                        </div>
                        <h3 style={{ fontSize: 'var(--text-sm)', fontWeight: 700, marginTop: 2 }}>
                          Representative Synthetic Events
                        </h3>
                        <p style={{ fontSize: '11px', color: 'var(--text-secondary)', marginTop: 2 }}>
                          Representative samples from the synthetic benchmark workload (reservoir sampled).
                          Not the complete dataset.
                        </p>
                      </div>

                      {/* Filter Tabs */}
                      <div
                        style={{
                          display: 'flex',
                          gap: 6,
                          background: 'rgba(255, 255, 255, 0.03)',
                          padding: 3,
                          borderRadius: 6,
                          border: '1px solid var(--border)',
                        }}
                      >
                        {(['legitimate', 'fraud', 'random'] as const).map((tab) => {
                          const active = sampleTab === tab;
                          const count = runResult.samples[tab]?.length ?? 0;
                          return (
                            <button
                              key={tab}
                              onClick={() => setSampleTab(tab)}
                              style={{
                                padding: '4px 10px',
                                borderRadius: 4,
                                background: active ? 'var(--accent-wash)' : 'transparent',
                                border: `1px solid ${active ? 'var(--accent)' : 'transparent'}`,
                                color: active ? 'var(--accent-bright)' : 'var(--text-secondary)',
                                fontSize: '11px',
                                fontFamily: 'var(--font-mono)',
                                fontWeight: 700,
                                textTransform: 'uppercase',
                                cursor: 'pointer',
                              }}
                            >
                              {tab} ({count})
                            </button>
                          );
                        })}
                      </div>
                    </div>

                    {/* Sample Table */}
                    {runResult.samples[sampleTab]?.length === 0 ? (
                      <div
                        style={{
                          padding: 20,
                          textAlign: 'center',
                          color: 'var(--text-muted)',
                          fontSize: 'var(--text-xs)',
                        }}
                      >
                        No representative {sampleTab} samples available in this workload execution.
                      </div>
                    ) : (
                      <div style={{ overflowX: 'auto', maxHeight: 360, overflowY: 'auto' }}>
                        <table
                          style={{
                            width: '100%',
                            borderCollapse: 'collapse',
                            fontSize: '11px',
                            fontFamily: 'var(--font-mono)',
                          }}
                        >
                          <thead style={{ position: 'sticky', top: 0, background: 'var(--surface-1)', zIndex: 2 }}>
                            <tr
                              style={{
                                borderBottom: '1px solid var(--border)',
                                color: 'var(--text-muted)',
                                textAlign: 'left',
                              }}
                            >
                              <th style={{ padding: '6px 8px' }}>Transaction ID</th>
                              <th style={{ padding: '6px 8px' }}>Customer</th>
                              <th style={{ padding: '6px 8px' }}>Device</th>
                              <th style={{ padding: '6px 8px' }}>Instrument</th>
                              <th style={{ padding: '6px 8px' }}>Amount</th>
                              <th style={{ padding: '6px 8px' }}>Status</th>
                              <th style={{ padding: '6px 8px' }}>Ground Truth</th>
                            </tr>
                          </thead>
                          <tbody>
                            {runResult.samples[sampleTab].map((tx) => (
                              <tr
                                key={tx.transaction_id}
                                onClick={() => setSelectedTx(tx)}
                                style={{
                                  borderBottom: '1px solid rgba(255, 255, 255, 0.03)',
                                  cursor: 'pointer',
                                  transition: 'background 0.15s ease',
                                }}
                                onMouseEnter={(e) =>
                                  (e.currentTarget.style.background = 'rgba(255, 255, 255, 0.03)')
                                }
                                onMouseLeave={(e) =>
                                  (e.currentTarget.style.background = 'transparent')
                                }
                              >
                                <td style={{ padding: '6px 8px', fontWeight: 600, color: 'var(--accent-bright)' }}>
                                  {tx.transaction_id.slice(0, 16)}…
                                </td>
                                <td style={{ padding: '6px 8px', color: 'var(--text-secondary)' }}>
                                  {tx.customer_id ? tx.customer_id.slice(0, 12) : '—'}
                                </td>
                                <td style={{ padding: '6px 8px', color: 'var(--text-secondary)' }}>
                                  {tx.device_fingerprint ? tx.device_fingerprint.slice(0, 10) : '—'}
                                </td>
                                <td style={{ padding: '6px 8px', color: 'var(--text-secondary)' }}>
                                  {tx.instrument_fingerprint ? tx.instrument_fingerprint.slice(0, 12) : '—'}
                                </td>
                                <td style={{ padding: '6px 8px', fontWeight: 600, color: 'var(--text-primary)' }}>
                                  ₹{Number(tx.amount).toFixed(2)}
                                </td>
                                <td style={{ padding: '6px 8px' }}>
                                  <span
                                    style={{
                                      padding: '1px 5px',
                                      borderRadius: 3,
                                      fontSize: '9px',
                                      background:
                                        tx.outcome_status === 'CAPTURED'
                                          ? 'rgba(16, 185, 129, 0.15)'
                                          : 'rgba(239, 68, 68, 0.15)',
                                      color:
                                        tx.outcome_status === 'CAPTURED'
                                          ? 'var(--color-safe)'
                                          : 'var(--color-critical)',
                                    }}
                                  >
                                    {tx.outcome_status || 'UNKNOWN'}
                                  </span>
                                </td>
                                <td style={{ padding: '6px 8px' }}>
                                  <span
                                    style={{
                                      padding: '1px 5px',
                                      borderRadius: 3,
                                      fontSize: '9px',
                                      fontWeight: 700,
                                      background: tx.ground_truth_is_abusive
                                        ? 'rgba(255, 46, 76, 0.15)'
                                        : 'rgba(255, 255, 255, 0.05)',
                                      color: tx.ground_truth_is_abusive
                                        ? 'var(--color-critical)'
                                        : 'var(--text-muted)',
                                    }}
                                  >
                                    {tx.ground_truth_is_abusive ? 'FRAUD / ATTACK' : 'LEGITIMATE'}
                                  </span>
                                </td>
                              </tr>
                            ))}
                          </tbody>
                        </table>
                      </div>
                    )}
                  </Card>
                )}

                {/* 5. ENVIRONMENT & LIMITATIONS */}
                <Card style={{ display: 'grid', gap: 10 }}>
                  <h3
                    style={{
                      fontSize: 'var(--text-sm)',
                      fontWeight: 700,
                      display: 'flex',
                      alignItems: 'center',
                      gap: 6,
                    }}
                  >
                    <Server size={14} color="var(--accent-bright)" />
                    Benchmark Environment
                  </h3>
                  <div
                    style={{
                      display: 'grid',
                      gridTemplateColumns: 'repeat(auto-fit, minmax(160px, 1fr))',
                      gap: 10,
                      fontSize: '11px',
                      fontFamily: 'var(--font-mono)',
                    }}
                  >
                    <div>
                      <span style={{ color: 'var(--text-muted)' }}>Database:</span>{' '}
                      {runResult.environment.database} ({runResult.environment.database_url_scheme})
                    </div>
                    <div>
                      <span style={{ color: 'var(--text-muted)' }}>Python:</span>{' '}
                      {runResult.environment.python}
                    </div>
                    <div>
                      <span style={{ color: 'var(--text-muted)' }}>Platform:</span>{' '}
                      {runResult.environment.platform}
                    </div>
                    <div>
                      <span style={{ color: 'var(--text-muted)' }}>CPU Cores:</span>{' '}
                      {runResult.environment.cpu_count ?? 'N/A'}
                    </div>
                  </div>

                  {/* Limitations returned by server */}
                  {runResult.limitations && runResult.limitations.length > 0 && (
                    <div
                      style={{
                        marginTop: 8,
                        padding: 10,
                        background: 'rgba(255, 255, 255, 0.02)',
                        borderRadius: 6,
                        borderLeft: '2px solid var(--accent)',
                      }}
                    >
                      <div
                        style={{
                          fontSize: '10px',
                          color: 'var(--text-muted)',
                          textTransform: 'uppercase',
                          fontWeight: 700,
                        }}
                      >
                        Execution Limitations
                      </div>
                      <ul
                        style={{
                          margin: '4px 0 0',
                          paddingLeft: 16,
                          fontSize: '11px',
                          color: 'var(--text-secondary)',
                          lineHeight: 1.4,
                        }}
                      >
                        {runResult.limitations.map((lim, idx) => (
                          <li key={idx}>{lim}</li>
                        ))}
                      </ul>
                    </div>
                  )}

                  <p style={{ fontSize: '10px', color: 'var(--text-muted)', marginTop: 4 }}>
                    These measurements describe this benchmark environment, not production capacity.
                  </p>
                </Card>

                {/* 6. SCALING HISTORY COMPARISON */}
                {benchmarkHistory.length > 1 && (
                  <Card style={{ display: 'grid', gap: 12 }}>
                    <h3
                      style={{
                        fontSize: 'var(--text-sm)',
                        fontWeight: 700,
                        display: 'flex',
                        alignItems: 'center',
                        gap: 6,
                      }}
                    >
                      <BarChart3 size={14} color="var(--accent-bright)" />
                      Workload Scaling Comparison ({benchmarkHistory.length} runs recorded)
                    </h3>
                    <div style={{ overflowX: 'auto' }}>
                      <table
                        style={{
                          width: '100%',
                          borderCollapse: 'collapse',
                          fontSize: '11px',
                          fontFamily: 'var(--font-mono)',
                        }}
                      >
                        <thead>
                          <tr
                            style={{
                              borderBottom: '1px solid var(--border)',
                              color: 'var(--text-muted)',
                              textAlign: 'left',
                            }}
                          >
                            <th style={{ padding: '6px 8px' }}>Requested</th>
                            <th style={{ padding: '6px 8px' }}>Actual Events</th>
                            <th style={{ padding: '6px 8px' }}>Status</th>
                            <th style={{ padding: '6px 8px' }}>Mode</th>
                            <th style={{ padding: '6px 8px' }}>Ingestion (TPS)</th>
                            <th style={{ padding: '6px 8px' }}>Per-Window Cost</th>
                            <th style={{ padding: '6px 8px' }}>Peak Traced Heap</th>
                          </tr>
                        </thead>
                        <tbody>
                          {benchmarkHistory.map((h, i) => (
                            <tr
                              key={i}
                              style={{
                                borderBottom: '1px solid rgba(255, 255, 255, 0.03)',
                                opacity: h.status === 'completed' ? 1 : 0.85,
                              }}
                            >
                              <td style={{ padding: '6px 8px', fontWeight: 600 }}>
                                {h.requested_workload_size.toLocaleString()}
                              </td>
                              <td style={{ padding: '6px 8px' }}>
                                {h.traffic.generated_events.toLocaleString()}
                              </td>
                              <td style={{ padding: '6px 8px' }}>
                                {renderStatusBadge(h.status, h.stop_reason)}
                              </td>
                              <td style={{ padding: '6px 8px', color: 'var(--text-secondary)' }}>
                                {h.benchmark_mode}
                              </td>
                              <td
                                style={{
                                  padding: '6px 8px',
                                  color: 'var(--accent-bright)',
                                  fontWeight: 700,
                                }}
                              >
                                {h.ingestion.events_per_second
                                  ? `${Math.round(h.ingestion.events_per_second).toLocaleString()} TPS`
                                  : '—'}
                              </td>
                              <td style={{ padding: '6px 8px' }}>
                                {h.computation
                                  ? `${h.computation.per_window_latency_ms.toFixed(1)} ms/win`
                                  : '—'}
                              </td>
                              <td style={{ padding: '6px 8px' }}>
                                {h.memory.peak_traced_python_heap_mb
                                  ? `${h.memory.peak_traced_python_heap_mb.toFixed(1)} MB`
                                  : '—'}
                              </td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  </Card>
                )}
              </div>
            )}
          </main>
        </div>
      ) : (
        /* ------------------------------------------------ Burst Stress Test Sub-view */
        <div className="veyra-detection-grid">
          <aside style={{ display: 'grid', gap: 'var(--sp-4)', alignContent: 'start' }}>
            <Card style={{ display: 'grid', gap: 'var(--sp-4)' }}>
              <div>
                <div
                  style={{
                    fontSize: '11px',
                    color: 'var(--text-muted)',
                    textTransform: 'uppercase',
                    letterSpacing: '0.05em',
                    fontWeight: 700,
                  }}
                >
                  Burst Injection Size
                </div>
                <div
                  style={{
                    display: 'grid',
                    gridTemplateColumns: 'repeat(5, 1fr)',
                    gap: 6,
                    marginTop: 8,
                  }}
                >
                  {[250, 500, 1000, 2500, 5000].map((b) => (
                    <button
                      key={b}
                      onClick={() => setBurstCount(b)}
                      style={{
                        padding: '6px 4px',
                        borderRadius: 4,
                        background: burstCount === b ? 'var(--accent-wash)' : 'var(--surface-2)',
                        border: `1px solid ${burstCount === b ? 'var(--accent)' : 'var(--border)'}`,
                        color: burstCount === b ? 'var(--accent-bright)' : 'var(--text-secondary)',
                        fontFamily: 'var(--font-mono)',
                        fontSize: 'var(--text-xs)',
                        fontWeight: 700,
                        cursor: 'pointer',
                      }}
                    >
                      {b}
                    </button>
                  ))}
                </div>
              </div>

              <Button
                variant="primary"
                size="lg"
                full
                loading={burstRunning}
                onClick={runBurst}
                icon={<Flame size={16} />}
              >
                {burstRunning ? 'Injecting burst…' : `Inject ${burstCount} Events`}
              </Button>
            </Card>
          </aside>

          <main style={{ display: 'grid', gap: 'var(--sp-5)' }}>
            {burstRunning && (
              <Card>
                <LoadingBlock
                  label={`Injecting ${burstCount} events and timing pipeline…`}
                  rows={4}
                />
              </Card>
            )}

            {burstError && (
              <ErrorState
                title="Burst Injection Failed"
                detail={burstError.detail || burstError.message}
                onRetry={runBurst}
              />
            )}

            {!burstRunning && !burstResult && !burstError && (
              <Card style={{ padding: 'var(--sp-7)' }}>
                <EmptyState
                  title="No burst test executed"
                  description="Select a burst volume (250 to 5,000 events) and trigger an instant synchronous injection test."
                />
              </Card>
            )}

            {burstResult && (
              <Card style={{ display: 'grid', gap: 16 }}>
                <div
                  style={{
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'space-between',
                  }}
                >
                  <h3 style={{ fontSize: 'var(--text-md)', fontWeight: 700 }}>
                    Burst Test Results ({burstResult.burst_count} events)
                  </h3>
                  <Badge color="var(--color-safe)" background="rgba(16, 185, 129, 0.15)">
                    COMPLETED
                  </Badge>
                </div>

                <div
                  style={{
                    display: 'grid',
                    gridTemplateColumns: 'repeat(auto-fit, minmax(130px, 1fr))',
                    gap: 12,
                  }}
                >
                  <Stat
                    label="Burst Throughput"
                    value={`${Math.round(burstResult.throughput_tps).toLocaleString()} TPS`}
                    accent="var(--accent-bright)"
                  />
                  <Stat label="Total Wall Time" value={`${burstResult.total_time_ms.toFixed(1)} ms`} />
                  <Stat
                    label="Ingestion Time"
                    value={`${burstResult.ingestion_time_ms.toFixed(1)} ms`}
                  />
                  <Stat
                    label="Scoring Time"
                    value={`${burstResult.scoring_time_ms.toFixed(1)} ms`}
                  />
                </div>
              </Card>
            )}
          </main>
        </div>
      )}

      {/* Transaction Detail Drawer for Representative Samples */}
      {selectedTx && (
        <div
          style={{
            position: 'fixed',
            top: 0,
            right: 0,
            bottom: 0,
            width: 'min(480px, 90vw)',
            background: 'var(--surface-1)',
            borderLeft: '1px solid var(--border)',
            boxShadow: '-8px 0 30px rgba(0, 0, 0, 0.5)',
            zIndex: 9999,
            padding: 'var(--sp-5)',
            overflowY: 'auto',
            display: 'grid',
            gridTemplateRows: 'auto 1fr',
            gap: 16,
          }}
        >
          {/* Drawer Header */}
          <div
            style={{
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'space-between',
              paddingBottom: 12,
              borderBottom: '1px solid var(--border)',
            }}
          >
            <div>
              <div
                style={{
                  fontSize: '10px',
                  color: 'var(--text-muted)',
                  textTransform: 'uppercase',
                  letterSpacing: '0.04em',
                }}
              >
                Benchmark Reservoir Sample
              </div>
              <h3
                style={{
                  fontSize: 'var(--text-md)',
                  fontWeight: 700,
                  fontFamily: 'var(--font-mono)',
                  marginTop: 2,
                }}
              >
                {selectedTx.transaction_id}
              </h3>
            </div>
            <button
              onClick={() => setSelectedTx(null)}
              style={{
                background: 'rgba(255, 255, 255, 0.05)',
                border: '1px solid var(--border)',
                borderRadius: '50%',
                width: 32,
                height: 32,
                display: 'grid',
                placeItems: 'center',
                color: 'var(--text-primary)',
                cursor: 'pointer',
              }}
            >
              <X size={16} />
            </button>
          </div>

          {/* Drawer Body */}
          <div style={{ display: 'grid', gap: 14 }}>
            <div>
              <div style={{ fontSize: '10px', color: 'var(--text-muted)', textTransform: 'uppercase' }}>
                Timestamp
              </div>
              <div style={{ fontFamily: 'var(--font-mono)', fontSize: 'var(--text-xs)', marginTop: 3 }}>
                {new Date(selectedTx.timestamp).toUTCString()}
              </div>
            </div>

            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 10 }}>
              <div>
                <div style={{ fontSize: '10px', color: 'var(--text-muted)', textTransform: 'uppercase' }}>
                  Amount
                </div>
                <div
                  style={{
                    fontFamily: 'var(--font-mono)',
                    fontSize: 'var(--text-sm)',
                    fontWeight: 700,
                    marginTop: 3,
                  }}
                >
                  ₹{Number(selectedTx.amount).toFixed(2)} {selectedTx.currency}
                </div>
              </div>

              <div>
                <div style={{ fontSize: '10px', color: 'var(--text-muted)', textTransform: 'uppercase' }}>
                  Outcome Status
                </div>
                <div
                  style={{
                    fontFamily: 'var(--font-mono)',
                    fontSize: 'var(--text-xs)',
                    marginTop: 3,
                  }}
                >
                  {selectedTx.outcome_status || 'None'}
                </div>
              </div>
            </div>

            <div>
              <div style={{ fontSize: '10px', color: 'var(--text-muted)', textTransform: 'uppercase' }}>
                Ground Truth Label
              </div>
              <div style={{ marginTop: 4 }}>
                <span
                  style={{
                    display: 'inline-flex',
                    alignItems: 'center',
                    gap: 6,
                    padding: '3px 8px',
                    borderRadius: 4,
                    fontSize: '11px',
                    fontFamily: 'var(--font-mono)',
                    fontWeight: 700,
                    background: selectedTx.ground_truth_is_abusive
                      ? 'rgba(255, 46, 76, 0.15)'
                      : 'rgba(16, 185, 129, 0.15)',
                    color: selectedTx.ground_truth_is_abusive
                      ? 'var(--color-critical)'
                      : 'var(--color-safe)',
                    border: `1px solid ${
                      selectedTx.ground_truth_is_abusive
                        ? 'rgba(255, 46, 76, 0.35)'
                        : 'rgba(16, 185, 129, 0.35)'
                    }`,
                  }}
                >
                  {selectedTx.ground_truth_is_abusive ? 'ABUSIVE / FRAUD' : 'BENIGN / LEGITIMATE'}
                </span>
              </div>
            </div>

            <div>
              <div style={{ fontSize: '10px', color: 'var(--text-muted)', textTransform: 'uppercase' }}>
                Scenario ID
              </div>
              <div
                style={{
                  fontFamily: 'var(--font-mono)',
                  fontSize: 'var(--text-xs)',
                  color: 'var(--accent-bright)',
                  marginTop: 3,
                }}
              >
                {selectedTx.ground_truth_scenario_id || 'none'}
              </div>
            </div>

            {/* Entity Fingerprints */}
            <div
              style={{
                background: 'rgba(255, 255, 255, 0.02)',
                border: '1px solid var(--border)',
                borderRadius: 'var(--radius-sm)',
                padding: 12,
                display: 'grid',
                gap: 10,
              }}
            >
              <div
                style={{
                  fontSize: '10px',
                  color: 'var(--text-muted)',
                  textTransform: 'uppercase',
                  fontWeight: 700,
                }}
              >
                Entity Fingerprints (Synthetic Identity Nodes)
              </div>

              <div>
                <div style={{ fontSize: '10px', color: 'var(--text-muted)' }}>Customer ID</div>
                <div style={{ fontFamily: 'var(--font-mono)', fontSize: '11px' }}>
                  {selectedTx.customer_id || '—'}
                </div>
              </div>

              <div>
                <div style={{ fontSize: '10px', color: 'var(--text-muted)' }}>Device Fingerprint</div>
                <div style={{ fontFamily: 'var(--font-mono)', fontSize: '11px' }}>
                  {selectedTx.device_fingerprint || '—'}
                </div>
              </div>

              <div>
                <div style={{ fontSize: '10px', color: 'var(--text-muted)' }}>Instrument Fingerprint</div>
                <div style={{ fontFamily: 'var(--font-mono)', fontSize: '11px' }}>
                  {selectedTx.instrument_fingerprint || '—'}
                </div>
              </div>

              <div>
                <div style={{ fontSize: '10px', color: 'var(--text-muted)' }}>IP Fingerprint</div>
                <div style={{ fontFamily: 'var(--font-mono)', fontSize: '11px' }}>
                  {selectedTx.ip_fingerprint || '—'}
                </div>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
