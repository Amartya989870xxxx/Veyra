/** Detection pipeline stages, rendered from the backend's `stages` array.
 *
 * Stage names, descriptions, ordering and durations all come from the response.
 * Nothing is invented: if a stage carries no duration the cell shows an em dash
 * rather than a plausible-looking number, and the total is summed from what was
 * actually returned.
 */

import { Check } from 'lucide-react';
import type { ExecutionStage } from '../../api/types';
import { formatLatency, toNumber } from '../../lib/format';
import { EmptyState } from '../ui';

export function PipelineTimeline({
  stages,
  compact = false,
}: {
  stages: ExecutionStage[] | undefined;
  compact?: boolean;
}) {
  if (!stages || stages.length === 0) {
    return (
      <EmptyState
        title="No pipeline trace returned"
        detail="This response did not include stage timings. Run a detection to see the pipeline execute."
      />
    );
  }

  const durations = stages.map((s) => toNumber(s.duration_ms)).filter((n): n is number => n !== null);
  const total = durations.length ? durations.reduce((a, b) => a + b, 0) : null;
  const slowest = durations.length ? Math.max(...durations) : 0;

  return (
    <div style={{ display: 'grid', gap: compact ? 'var(--sp-2)' : 'var(--sp-3)' }}>
      {stages.map((stage) => {
        const ms = toNumber(stage.duration_ms);
        const share = ms !== null && slowest > 0 ? Math.max(0.04, ms / slowest) : 0;
        const done = String(stage.status).toUpperCase() === 'COMPLETED';

        return (
          <div
            key={stage.stage_number}
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
              {String(stage.stage_number).padStart(2, '0')}
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
                {done && <Check size={13} style={{ color: 'var(--tier-observe)', flexShrink: 0 }} />}
                <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                  {stage.name}
                </span>
              </div>
              {!compact && (
                <p style={{ marginTop: 3, fontSize: 'var(--text-xs)', color: 'var(--text-muted)', lineHeight: 1.5 }}>
                  {stage.description}
                </p>
              )}
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
        <span style={{ color: 'var(--text-secondary)' }}>Measured pipeline time</span>
        <span className="mono tabular" style={{ color: 'var(--accent-bright)', fontWeight: 600 }}>
          {formatLatency(total)}
        </span>
      </div>
      <p style={{ fontSize: 'var(--text-xs)', color: 'var(--text-muted)', lineHeight: 1.6 }}>
        Timings are measured server-side for this run on the project environment. They are not a
        Razorpay infrastructure benchmark.
      </p>
    </div>
  );
}
