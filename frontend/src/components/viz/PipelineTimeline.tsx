/** Detection pipeline stages, rendered from the backend's real `stages` telemetry.
 *
 * Stage names, descriptions, ordering and measured durations all come directly from the
 * server response (app/schemas/demo.py PipelineStage).
 * Nothing is invented: if a stage carries no duration the cell shows an em dash
 * rather than a plausible-looking number, and the total is summed from what was
 * actually measured server-side.
 */

import { CheckCircle2 } from 'lucide-react';
import type { ExecutionStage, PipelineStage } from '../../api/types';
import { formatLatency, toNumber } from '../../lib/format';
import { EmptyState } from '../ui';

export type AnyStage = (PipelineStage | ExecutionStage) & {
  stage_number?: number;
  id?: string;
  name?: string;
  label?: string;
  description?: string;
  duration_ms: number;
  status: string;
  details?: Record<string, unknown>;
  detail?: Record<string, unknown> | null;
};

export function PipelineTimeline({
  stages,
  compact = false,
}: {
  stages: AnyStage[] | undefined;
  compact?: boolean;
}) {
  if (!stages || stages.length === 0) {
    return (
      <EmptyState
        title="No pipeline trace returned"
        description="This response did not include stage timings. Run a detection to see the pipeline execute."
      />
    );
  }

  const durations = stages.map((s) => toNumber(s.duration_ms)).filter((n): n is number => n !== null);
  const total = durations.length ? durations.reduce((a, b) => a + b, 0) : null;
  const slowest = durations.length ? Math.max(...durations) : 0;

  return (
    <div style={{ display: 'grid', gap: compact ? 'var(--sp-2)' : 'var(--sp-3)' }}>
      {stages.map((stage, idx) => {
        const ms = toNumber(stage.duration_ms);
        const share = ms !== null && slowest > 0 ? Math.max(0.04, ms / slowest) : 0;
        const done = String(stage.status).toUpperCase() === 'COMPLETED';
        const stageNum = stage.stage_number !== undefined ? stage.stage_number : idx + 1;
        const title = stage.name || stage.label || stage.id || `Stage ${stageNum}`;
        const detailObj = stage.detail || stage.details;

        return (
          <div
            key={stage.id || stageNum}
            style={{
              display: 'grid',
              gridTemplateColumns: compact ? '28px 1fr 76px' : '34px 1fr 92px',
              alignItems: 'center',
              gap: 'var(--sp-3)',
              padding: compact ? 'var(--sp-2) var(--sp-3)' : 'var(--sp-3) var(--sp-4)',
              background: 'var(--surface-1)',
              border: '1px solid var(--border-subtle)',
              borderRadius: 'var(--radius)',
            }}
          >
            <span className="mono" style={{ fontSize: 'var(--text-xs)', color: 'var(--text-muted)' }}>
              {String(stageNum).padStart(2, '0')}
            </span>

            <div style={{ minWidth: 0 }}>
              <div
                style={{
                  display: 'flex',
                  alignItems: 'center',
                  gap: 'var(--sp-2)',
                  fontSize: 'var(--text-sm)',
                  fontWeight: 500,
                  color: 'var(--text-primary)',
                }}
              >
                {done && <CheckCircle2 size={14} style={{ color: 'var(--color-safe)', flexShrink: 0 }} />}
                <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                  {title}
                </span>
              </div>
              {stage.description ? (
                <p style={{ marginTop: 3, fontSize: 'var(--text-xs)', color: 'var(--text-muted)', lineHeight: 1.5 }}>
                  {stage.description}
                </p>
              ) : detailObj && Object.keys(detailObj).length > 0 ? (
                <p style={{ marginTop: 3, fontSize: '11px', color: 'var(--text-muted)', fontFamily: 'var(--font-mono)' }}>
                  {Object.entries(detailObj)
                    .map(([k, v]) => `${k}: ${v}`)
                    .join(' · ')}
                </p>
              ) : null}
              <div
                style={{
                  marginTop: 7,
                  height: 2,
                  borderRadius: 2,
                  background: 'var(--surface-3)',
                  overflow: 'hidden',
                }}
              >
                <div
                  style={{
                    height: '100%',
                    width: `${share * 100}%`,
                    background: 'linear-gradient(90deg, var(--accent-dim), var(--accent-bright))',
                    borderRadius: 2,
                  }}
                />
              </div>
            </div>

            <span
              className="mono tabular"
              style={{ fontSize: 'var(--text-xs)', color: 'var(--text-secondary)', textAlign: 'right' }}
            >
              {formatLatency(stage.duration_ms)}
            </span>
          </div>
        );
      })}

      <div
        style={{
          display: 'flex',
          justifyContent: 'space-between',
          padding: 'var(--sp-3) var(--sp-4)',
          borderTop: '1px solid var(--border-subtle)',
          fontSize: 'var(--text-sm)',
        }}
      >
        <span style={{ color: 'var(--text-secondary)' }}>Total measured server time</span>
        <span className="mono tabular" style={{ color: 'var(--accent-bright)', fontWeight: 600 }}>
          {formatLatency(total)}
        </span>
      </div>
      <p style={{ fontSize: 'var(--text-xs)', color: 'var(--text-muted)', lineHeight: 1.6 }}>
        Timings are measured server-side via time.perf_counter() for this run in this benchmark environment.
      </p>
    </div>
  );
}
