/** Staged Pipeline Progress Component.
 *
 * Provides a 12-stage visual representation of the real multi-stage analysis pipeline.
 * Integrates directly with backend PipelineStage telemetry.
 *
 * Distinctly focused on visual analysis progression without exposing distracting
 * frontend/server timing implementation details during loading.
 */

import { CheckCircle2, Circle, Loader2, AlertCircle, MinusCircle } from 'lucide-react';
import type { PipelineStage, ServerTiming, StageStatus } from '../../api/types';

interface StagedPipelineProgressProps {
  running: boolean;
  backendCompleted?: boolean;
  activeStageIndex: number;
  stages?: PipelineStage[] | null;
  serverDurationMs?: number | null;
  timing?: ServerTiming | null;
  presentationElapsedMs?: number;
  targetPresentationMs?: number;
}

export const CANONICAL_STAGES = [
  { sequence: 1, id: 'generation', label: 'Generate synthetic traffic' },
  { sequence: 2, id: 'injection', label: 'Inject scenario' },
  { sequence: 3, id: 'windowing', label: 'Construct merchant-window' },
  { sequence: 4, id: 'baseline', label: 'Load model and historical baselines' },
  { sequence: 5, id: 'features', label: 'Extract contextual features' },
  { sequence: 6, id: 'graph', label: 'Construct entity graph' },
  { sequence: 7, id: 'deviation', label: 'Compute baseline deviations' },
  { sequence: 8, id: 'inference', label: 'Run model inference' },
  { sequence: 9, id: 'policy', label: 'Apply decision policy' },
  { sequence: 10, id: 'exposure', label: 'Estimate financial exposure' },
  { sequence: 11, id: 'forensics', label: 'Generate forensic explanation' },
  { sequence: 12, id: 'run_record', label: 'Store demo run record' },
];

function getStageContextMessage(index: number): string {
  if (index < 3) {
    return 'Preparing transaction context and constructing the analysis window.';
  }
  if (index < 6) {
    return 'Extracting behavioral signals and mapping entity relationships.';
  }
  if (index < 9) {
    return 'Evaluating deviations, risk signals, and decision policies.';
  }
  return 'Assessing potential exposure and generating forensic evidence.';
}

export function StagedPipelineProgress({
  running,
  activeStageIndex,
  stages,
  presentationElapsedMs = 0,
  targetPresentationMs = 25000,
}: StagedPipelineProgressProps) {
  // Use server stages if provided, otherwise fallback to canonical list
  const stagesToRender = (stages && stages.length > 0 ? stages : CANONICAL_STAGES).map(
    (stage, idx) => {
      const serverStage = stages?.find((s) => s.id === stage.id || s.sequence === idx + 1);
      let status: StageStatus = 'pending';

      if (!running) {
        status = serverStage?.status || 'completed';
      } else {
        if (idx < activeStageIndex) {
          status = 'completed';
        } else if (idx === activeStageIndex) {
          status = 'running';
        } else {
          status = 'pending';
        }
      }

      return {
        sequence: stage.sequence || idx + 1,
        id: stage.id,
        label: stage.label,
        status,
        duration_ms: (serverStage && (idx < activeStageIndex || !running)) ? serverStage.duration_ms : undefined,
        detail: serverStage?.detail,
      };
    },
  );

  return (
    <div
      style={{
        background: 'linear-gradient(180deg, rgba(10, 15, 30, 0.85) 0%, rgba(5, 8, 20, 0.95) 100%)',
        border: '1px solid rgba(59, 130, 246, 0.25)',
        borderRadius: 'var(--radius-md)',
        padding: 'var(--sp-5)',
        display: 'grid',
        gap: 'var(--sp-4)',
        boxShadow: '0 8px 32px rgba(0, 0, 0, 0.45)',
        position: 'relative',
        overflow: 'hidden',
      }}
    >
      {/* Subtle flowing top progress line while running */}
      {running && (
        <div
          style={{
            position: 'absolute',
            top: 0,
            left: 0,
            height: '2px',
            width: `${Math.min(100, (presentationElapsedMs / targetPresentationMs) * 100)}%`,
            background: 'linear-gradient(90deg, var(--accent-primary), var(--accent-bright))',
            boxShadow: '0 0 10px var(--accent-bright)',
            transition: 'width 0.1s linear',
          }}
        />
      )}

      {/* Header */}
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          flexWrap: 'wrap',
          gap: 12,
          paddingBottom: 12,
          borderBottom: '1px solid rgba(255, 255, 255, 0.07)',
        }}
      >
        <div>
          <div
            style={{
              fontFamily: 'var(--font-mono)',
              fontSize: '11px',
              fontWeight: 700,
              color: running ? 'var(--accent-bright)' : 'var(--color-safe)',
              letterSpacing: '0.08em',
              textTransform: 'uppercase',
              display: 'flex',
              alignItems: 'center',
              gap: 8,
            }}
          >
            {running ? (
              <>
                <Loader2 size={14} className="spin" />
                ANALYZING MERCHANT WINDOW…
              </>
            ) : (
              <>
                <CheckCircle2 size={14} />
                ANALYSIS COMPLETE
              </>
            )}
          </div>
          <p style={{ fontSize: 'var(--text-xs)', color: 'var(--text-secondary)', marginTop: 4, maxWidth: 640 }}>
            {running
              ? getStageContextMessage(activeStageIndex)
              : '12-stage forensic pipeline completed. All stages evaluated.'}
          </p>
        </div>

        {running && (
          <div
            style={{
              fontFamily: 'var(--font-mono)',
              fontSize: '11px',
              color: 'var(--text-muted)',
              letterSpacing: '0.05em',
              fontWeight: 600,
            }}
          >
            STAGE {Math.min(12, activeStageIndex + 1)} / 12
          </div>
        )}
      </div>

      {/* Stage Items Grid (12-stage execution trace) */}
      <div style={{ display: 'grid', gap: 6 }}>
        {stagesToRender.map((stage) => {
          const isDone = stage.status === 'completed';
          const isActive = stage.status === 'running';
          const isFailed = stage.status === 'failed';
          const isSkipped = stage.status === 'skipped';

          return (
            <div
              key={stage.id}
              style={{
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'space-between',
                padding: '7px 12px',
                borderRadius: 'var(--radius-sm)',
                background: isActive
                  ? 'rgba(59, 130, 246, 0.12)'
                  : isDone
                  ? 'rgba(255, 255, 255, 0.02)'
                  : 'transparent',
                border: isActive
                  ? '1px solid rgba(59, 130, 246, 0.45)'
                  : '1px solid transparent',
                boxShadow: isActive ? '0 0 14px rgba(59, 130, 246, 0.25)' : 'none',
                transition: 'all 0.2s ease',
              }}
            >
              <div style={{ display: 'flex', alignItems: 'center', gap: 10, minWidth: 0 }}>
                {/* Sequence number */}
                <span
                  style={{
                    fontFamily: 'var(--font-mono)',
                    fontSize: '10px',
                    fontWeight: 700,
                    color: isActive ? 'var(--accent-bright)' : isDone ? 'var(--color-safe)' : 'var(--text-muted)',
                    width: '18px',
                  }}
                >
                  {String(stage.sequence).padStart(2, '0')}
                </span>

                {/* Status icon */}
                {isDone && <CheckCircle2 size={15} color="var(--color-safe)" style={{ flexShrink: 0 }} />}
                {isActive && <Loader2 size={15} color="var(--accent-bright)" className="spin" style={{ flexShrink: 0 }} />}
                {isFailed && <AlertCircle size={15} color="var(--color-critical)" style={{ flexShrink: 0 }} />}
                {isSkipped && <MinusCircle size={15} color="var(--text-muted)" style={{ flexShrink: 0 }} />}
                {!isDone && !isActive && !isFailed && !isSkipped && (
                  <Circle size={15} color="var(--text-muted)" style={{ opacity: 0.35, flexShrink: 0 }} />
                )}

                <span
                  style={{
                    fontSize: 'var(--text-xs)',
                    fontWeight: isActive || isDone ? 600 : 400,
                    color: isDone ? 'var(--text-primary)' : isActive ? 'var(--accent-bright)' : 'var(--text-muted)',
                    whiteSpace: 'nowrap',
                    overflow: 'hidden',
                    textOverflow: 'ellipsis',
                  }}
                >
                  {stage.label}
                </span>

                {/* Optional detail chips */}
                {stage.detail && typeof stage.detail === 'object' && (
                  <span
                    style={{
                      fontSize: '10px',
                      color: 'var(--text-muted)',
                      fontFamily: 'var(--font-mono)',
                      background: 'rgba(255, 255, 255, 0.04)',
                      padding: '1px 6px',
                      borderRadius: 4,
                      marginLeft: 4,
                    }}
                  >
                    {formatStageDetail(stage.detail)}
                  </span>
                )}
              </div>

              {/* Stage duration or status indicator */}
              <div style={{ flexShrink: 0, marginLeft: 12 }}>
                {stage.duration_ms !== undefined ? (
                  <span
                    style={{
                      fontFamily: 'var(--font-mono)',
                      fontSize: '11px',
                      color: 'var(--text-secondary)',
                      fontWeight: 600,
                    }}
                  >
                    {stage.duration_ms < 1
                      ? `${(stage.duration_ms * 1000).toFixed(0)} µs`
                      : `${stage.duration_ms.toFixed(2)} ms`}
                  </span>
                ) : isActive ? (
                  <span
                    style={{
                      fontFamily: 'var(--font-mono)',
                      fontSize: '10px',
                      color: 'var(--accent-bright)',
                      textTransform: 'uppercase',
                      letterSpacing: '0.04em',
                    }}
                  >
                    running…
                  </span>
                ) : isSkipped ? (
                  <span style={{ fontSize: '10px', color: 'var(--text-muted)', textTransform: 'uppercase' }}>
                    skipped
                  </span>
                ) : null}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

function formatStageDetail(detail: Record<string, unknown>): string {
  if (detail.feature_values) return `${detail.feature_values} feature values`;
  if (detail.bipartite_gini !== undefined) return `Gini ${detail.bipartite_gini}`;
  if (detail.risk_score !== undefined) return `score ${detail.risk_score}`;
  if (detail.action_tier) return `${detail.action_tier}`;
  if (detail.model_name) return `${detail.model_name}`;
  if (detail.transactions_in_window) return `${detail.transactions_in_window} txns`;
  if (detail.at_risk_gmv) return `GMV ₹${detail.at_risk_gmv}`;
  if (detail.narrative_words) return `${detail.narrative_words} words`;
  if (detail.organic_transactions) return `${detail.organic_transactions} base txns`;
  return '';
}
