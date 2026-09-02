/** Historical baseline comparison.
 *
 * Plots the backend's `top_feature_deviations` as distance from the merchant's
 * normal range. Every value shown is the raw `deviation_mad` returned by the
 * API; the bar length is the only derived quantity and it is a pure visual scale
 * over those values.
 */

import type { FeatureDeviation } from '../../api/types';
import { formatMad, formatNumber, humanizeFeatureId, toNumber } from '../../lib/format';
import { EmptyState, InfoTip } from '../ui';

const MAD_EXPLAINER =
  'MAD measures how far current behaviour sits from the merchant’s own historical distribution, ' +
  'using medians so a past attack cannot drag the definition of "normal" along with it.';

export function BaselineDeviation({
  deviations,
  limit = 6,
}: {
  deviations: FeatureDeviation[] | undefined;
  limit?: number;
}) {
  if (!deviations || deviations.length === 0) {
    return (
      <EmptyState
        title="No baseline comparison returned"
        detail="This response did not include feature deviations. Run a detection to compare against the merchant’s history."
      />
    );
  }

  const rows = deviations.slice(0, limit);
  const magnitudes = rows
    .map((d) => Math.abs(toNumber(d.deviation_mad) ?? 0))
    .filter((n) => Number.isFinite(n));
  const max = magnitudes.length ? Math.max(...magnitudes, 1) : 1;

  return (
    <div style={{ display: 'grid', gap: 'var(--sp-4)' }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--sp-2)' }}>
        <span className="eyebrow">Deviation from this merchant&rsquo;s normal range</span>
        <InfoTip text={MAD_EXPLAINER} />
      </div>

      <div style={{ display: 'grid', gap: 'var(--sp-3)' }}>
        {rows.map((d) => {
          const mad = toNumber(d.deviation_mad);
          const magnitude = mad === null ? 0 : Math.abs(mad);
          const pct = Math.min(100, (magnitude / max) * 100);
          const high = String(d.direction).toUpperCase() === 'HIGH';

          return (
            <div key={d.feature_id} style={{ display: 'grid', gap: 6 }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', gap: 'var(--sp-3)', alignItems: 'baseline' }}>
                <span style={{ fontSize: 'var(--text-sm)', color: 'var(--text-primary)' }}>
                  {humanizeFeatureId(d.feature_id)}
                </span>
                <span
                  className="mono tabular"
                  style={{ fontSize: 'var(--text-xs)', color: high ? 'var(--tier-review)' : 'var(--tier-alert)', whiteSpace: 'nowrap' }}
                >
                  {formatMad(mad)}
                </span>
              </div>

              {/* Normal range sits at the left; the bar is distance travelled from it. */}
              <div
                style={{
                  position: 'relative',
                  height: 8,
                  borderRadius: 999,
                  background: 'var(--surface-2)',
                  overflow: 'hidden',
                }}
              >
                <div
                  aria-hidden
                  style={{
                    position: 'absolute',
                    left: 0,
                    top: 0,
                    bottom: 0,
                    width: 26,
                    background: 'var(--tier-observe-wash)',
                    borderRight: '1px solid rgba(52,211,153,0.4)',
                  }}
                />
                <div
                  style={{
                    position: 'absolute',
                    left: 0,
                    top: 0,
                    bottom: 0,
                    width: `${pct}%`,
                    background: high
                      ? 'linear-gradient(90deg, var(--accent-dim), var(--tier-review))'
                      : 'linear-gradient(90deg, var(--accent-dim), var(--tier-alert))',
                    borderRadius: 999,
                  }}
                />
              </div>

              <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 'var(--text-xs)', color: 'var(--text-muted)' }}>
                <span>Normal range</span>
                <span className="mono">observed {formatNumber(d.raw_value)}</span>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
