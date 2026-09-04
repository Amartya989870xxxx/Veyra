/** Run Summary Banner.
 *
 * Shows what the system actually executed:
 * - Visibly separated MODEL OUTPUT vs SYNTHETIC GROUND TRUTH (Part 8)
 * - Clear distinction between SERVER WORK and ANALYSIS PRESENTATION (Part 4)
 * - Fitted model name & version (veyra_fusion_demo vdemo-1)
 * - Evaluated decision policy tier and recommended defensive control
 * - Quick inspection link to the Synthetic Data Explorer
 */

import { Cpu, Search, Database } from 'lucide-react';
import type { SimulationReport } from '../../api/types';
import { tierColorVar, tierWashVar } from '../../lib/scenarios';
import { Button } from '../ui';

interface RunSummaryBannerProps {
  report: SimulationReport;
  onExploreData?: (runId: string) => void;
}

export function RunSummaryBanner({ report, onExploreData }: RunSummaryBannerProps) {
  const run = report.run;
  const gt = report.ground_truth;
  const tierColor = tierColorVar(report.action_tier);
  const tierWash = tierWashVar(report.action_tier);

  const serverMs =
    run?.total_server_duration_ms ??
    run?.timing?.server_processing_ms ??
    report.stages?.reduce((acc, s) => acc + (s.duration_ms || 0), 0) ??
    0;

  return (
    <div
      style={{
        background: 'var(--surface-1)',
        border: '1px solid var(--border)',
        borderRadius: 'var(--radius-md)',
        padding: '18px 20px',
        display: 'grid',
        gap: 16,
      }}
    >
      {/* Top headline line */}
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          flexWrap: 'wrap',
          gap: 12,
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: 12, flexWrap: 'wrap' }}>
          <span
            style={{
              display: 'inline-flex',
              alignItems: 'center',
              gap: 6,
              padding: '4px 10px',
              borderRadius: 6,
              background: tierWash,
              border: `1px solid ${tierColor}`,
              color: tierColor,
              fontFamily: 'var(--font-mono)',
              fontSize: 'var(--text-xs)',
              fontWeight: 700,
              letterSpacing: '0.04em',
            }}
          >
            ACTION TIER: {report.action_tier}
          </span>

          {/* Model info badge */}
          {run?.model && (
            <span
              style={{
                display: 'inline-flex',
                alignItems: 'center',
                gap: 6,
                background: 'rgba(59, 130, 246, 0.08)',
                border: '1px solid rgba(59, 130, 246, 0.25)',
                padding: '3px 8px',
                borderRadius: 5,
                fontSize: '11px',
                color: 'var(--accent-bright)',
                fontFamily: 'var(--font-mono)',
              }}
            >
              <Cpu size={12} />
              {run.model.model_name}
              <span style={{ color: 'var(--text-muted)' }}>v{run.model.model_version}</span>
            </span>
          )}
        </div>

        {/* Action Button to inspect in explorer */}
        {run?.run_id && onExploreData && (
          <Button
            variant="secondary"
            size="sm"
            onClick={() => onExploreData(run.run_id)}
            icon={<Search size={14} />}
          >
            Inspect in Synthetic Data Explorer
          </Button>
        )}
      </div>

      {/* Part 8: VISIBLY SEPARATED MODEL OUTPUT vs GROUND TRUTH */}
      <div
        style={{
          display: 'grid',
          gridTemplateColumns: 'repeat(auto-fit, minmax(280px, 1fr))',
          gap: 14,
        }}
      >
        {/* Box 1: Model Output */}
        <div
          style={{
            background: 'rgba(255, 255, 255, 0.02)',
            border: '1px solid rgba(255, 255, 255, 0.07)',
            borderRadius: 'var(--radius-sm)',
            padding: '14px 16px',
            display: 'grid',
            gap: 10,
          }}
        >
          <div style={{ display: 'flex', alignItems: 'center', gap: 6, borderBottom: '1px solid rgba(255, 255, 255, 0.05)', paddingBottom: 8 }}>
            <Cpu size={14} color="var(--accent-bright)" />
            <span style={{ fontFamily: 'var(--font-mono)', fontSize: '11px', fontWeight: 700, letterSpacing: '0.05em', color: 'var(--accent-bright)', textTransform: 'uppercase' }}>
              MODEL OUTPUT (Fitted Ensemble)
            </span>
          </div>

          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 10 }}>
            <div>
              <div style={{ fontSize: '10px', color: 'var(--text-muted)', textTransform: 'uppercase' }}>
                Fusion Risk Score
              </div>
              <div style={{ fontFamily: 'var(--font-mono)', fontSize: '18px', fontWeight: 800, color: 'var(--text-primary)', marginTop: 2 }}>
                {(report.risk_score * 100).toFixed(1)}%
              </div>
              <div style={{ fontSize: '11px', color: 'var(--text-muted)', fontFamily: 'var(--font-mono)' }}>
                {report.risk_score.toFixed(4)}
              </div>
            </div>

            <div>
              <div style={{ fontSize: '10px', color: 'var(--text-muted)', textTransform: 'uppercase' }}>
                Policy Decision
              </div>
              <div style={{ fontFamily: 'var(--font-mono)', fontSize: '15px', fontWeight: 700, color: tierColor, marginTop: 2 }}>
                {report.action_tier}
              </div>
              <div style={{ fontSize: '10px', color: 'var(--text-muted)', marginTop: 2 }}>
                {report.recommended_defensive_control ? report.recommended_defensive_control.replace(/^RECOMMEND_/, '') : 'No action'}
              </div>
            </div>
          </div>
        </div>

        {/* Box 2: Synthetic Ground Truth */}
        <div
          style={{
            background: 'rgba(255, 255, 255, 0.02)',
            border: '1px solid rgba(255, 255, 255, 0.07)',
            borderRadius: 'var(--radius-sm)',
            padding: '14px 16px',
            display: 'grid',
            gap: 10,
          }}
        >
          <div style={{ display: 'flex', alignItems: 'center', gap: 6, borderBottom: '1px solid rgba(255, 255, 255, 0.05)', paddingBottom: 8 }}>
            <Database size={14} color="var(--color-warning)" />
            <span style={{ fontFamily: 'var(--font-mono)', fontSize: '11px', fontWeight: 700, letterSpacing: '0.05em', color: 'var(--color-warning)', textTransform: 'uppercase' }}>
              SYNTHETIC GROUND TRUTH
            </span>
          </div>

          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 10 }}>
            <div>
              <div style={{ fontSize: '10px', color: 'var(--text-muted)', textTransform: 'uppercase' }}>
                Scenario Label
              </div>
              <div
                style={{
                  fontFamily: 'var(--font-mono)',
                  fontSize: '14px',
                  fontWeight: 700,
                  marginTop: 2,
                  color: gt?.scenario_is_labelled_attack ? 'var(--color-critical)' : 'var(--color-safe)',
                }}
              >
                {gt?.scenario_is_labelled_attack ? 'Attack Scenario' : 'Benign Scenario'}
              </div>
              <div style={{ fontSize: '11px', color: 'var(--text-muted)' }}>
                {gt ? `${gt.abusive_transaction_count} of ${gt.total_transaction_count} abusive` : 'N/A'}
              </div>
            </div>

            <div>
              <div style={{ fontSize: '10px', color: 'var(--text-muted)', textTransform: 'uppercase' }}>
                Model / Truth Alignment
              </div>
              <div
                style={{
                  fontFamily: 'var(--font-mono)',
                  fontSize: '13px',
                  fontWeight: 600,
                  marginTop: 2,
                  color: report.model_matches_ground_truth ? 'var(--color-safe)' : 'var(--text-secondary)',
                }}
              >
                {report.model_matches_ground_truth ? '✓ Aligned' : '○ Independent'}
              </div>
              <div style={{ fontSize: '10px', color: 'var(--text-muted)', marginTop: 2 }}>
                Ground truth is never read by model
              </div>
            </div>
          </div>
        </div>
      </div>

      {/* Part 4: Metrics Row with SERVER PROCESSING vs PRESENTATION TIME */}
      <div
        style={{
          display: 'grid',
          gridTemplateColumns: 'repeat(auto-fit, minmax(130px, 1fr))',
          gap: 12,
          paddingTop: 12,
          borderTop: '1px solid rgba(255, 255, 255, 0.06)',
        }}
      >
        <div>
          <div style={{ fontSize: '10px', color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.04em' }}>
            Synthetic Events
          </div>
          <div style={{ fontFamily: 'var(--font-mono)', fontSize: 'var(--text-sm)', fontWeight: 700, marginTop: 3 }}>
            {run?.total_transactions ?? report.total_transactions} txns
          </div>
          <div style={{ fontSize: '10px', color: 'var(--text-muted)', marginTop: 1 }}>
            window: {run?.window_size ?? report.window_size}
          </div>
        </div>

        <div>
          <div style={{ fontSize: '10px', color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.04em' }}>
            Extracted Features
          </div>
          <div style={{ fontFamily: 'var(--font-mono)', fontSize: 'var(--text-sm)', fontWeight: 700, marginTop: 3 }}>
            {run?.feature_count ?? Object.keys(report.features_summary || {}).length} features
          </div>
          <div style={{ fontSize: '10px', color: 'var(--text-muted)', marginTop: 1 }}>
            Families A–J + deviations
          </div>
        </div>

        <div>
          <div style={{ fontSize: '10px', color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.04em' }}>
            Entities Observed
          </div>
          <div style={{ fontFamily: 'var(--font-mono)', fontSize: 'var(--text-sm)', fontWeight: 700, marginTop: 3 }}>
            {run?.entity_counts
              ? `${run.entity_counts.customers + run.entity_counts.devices + run.entity_counts.instruments} total`
              : `${report.entity_graph?.total_nodes ?? 0} nodes`}
          </div>
          <div style={{ fontSize: '10px', color: 'var(--text-muted)', marginTop: 1 }}>
            {run?.entity_counts
              ? `${run.entity_counts.devices} dev · ${run.entity_counts.instruments} inst`
              : `${report.entity_graph?.total_edges ?? 0} edges`}
          </div>
        </div>

        <div>
          <div style={{ fontSize: '10px', color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.04em' }}>
            Server Processing
          </div>
          <div
            style={{
              fontFamily: 'var(--font-mono)',
              fontSize: 'var(--text-sm)',
              fontWeight: 700,
              marginTop: 3,
              color: 'var(--accent-bright)',
            }}
          >
            {serverMs.toFixed(2)} ms
          </div>
          <div style={{ fontSize: '10px', color: 'var(--text-muted)', marginTop: 1 }}>
            time.perf_counter()
          </div>
        </div>

        <div>
          <div style={{ fontSize: '10px', color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.04em' }}>
            Analysis Presentation
          </div>
          <div
            style={{
              fontFamily: 'var(--font-mono)',
              fontSize: 'var(--text-sm)',
              fontWeight: 700,
              marginTop: 3,
              color: 'var(--text-secondary)',
            }}
          >
            ~25.0 s
          </div>
          <div style={{ fontSize: '10px', color: 'var(--text-muted)', marginTop: 1 }}>
            Review pacing
          </div>
        </div>
      </div>

      {/* Part 4 Explanation Note */}
      <div
        style={{
          fontSize: '11px',
          color: 'var(--text-secondary)',
          background: 'rgba(255, 255, 255, 0.02)',
          borderLeft: '2px solid var(--accent-bright)',
          padding: '8px 12px',
          lineHeight: 1.5,
          borderRadius: '0 4px 4px 0',
        }}
      >
        <span style={{ fontWeight: 600, color: 'var(--text-primary)' }}>Timing transparency: </span>
        Server processing completed in {serverMs.toFixed(2)} ms. The interface keeps the 12-stage pipeline visible briefly (~25s) so each stage can be observed without flashing past.
      </div>
    </div>
  );
}
