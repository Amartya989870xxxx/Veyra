/** Data Provenance Panel.
 *
 * Clearly discloses the origin and synthetic nature of data used for a detection run.
 * Styled as a clean, high-precision technical panel rather than an alarming warning banner.
 */

import { Database, ShieldCheck, Cpu, Clock, Layers } from 'lucide-react';
import type { DemoRunMeta } from '../../api/types';

interface ProvenancePanelProps {
  run: DemoRunMeta;
  scenarioName?: string;
}

export function ProvenancePanel({ run, scenarioName }: ProvenancePanelProps) {
  const prov = run.provenance;

  return (
    <div
      style={{
        background: 'linear-gradient(180deg, rgba(15, 23, 42, 0.6) 0%, rgba(10, 15, 30, 0.4) 100%)',
        border: '1px solid rgba(59, 130, 246, 0.2)',
        borderRadius: 'var(--radius-md)',
        padding: '14px 18px',
        display: 'grid',
        gap: 12,
        boxShadow: '0 4px 20px -4px rgba(0, 0, 0, 0.4)',
      }}
    >
      {/* Top Banner Row */}
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          flexWrap: 'wrap',
          gap: 12,
          paddingBottom: 10,
          borderBottom: '1px solid rgba(255, 255, 255, 0.06)',
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
          <span
            style={{
              display: 'inline-flex',
              alignItems: 'center',
              gap: 6,
              background: 'rgba(59, 130, 246, 0.12)',
              border: '1px solid rgba(59, 130, 246, 0.3)',
              borderRadius: 5,
              padding: '3px 8px',
              color: 'var(--accent-bright)',
              fontFamily: 'var(--font-mono)',
              fontSize: '11px',
              fontWeight: 700,
              letterSpacing: '0.04em',
              textTransform: 'uppercase',
            }}
          >
            <Database size={12} />
            SYNTHETIC DATA
          </span>
          <span style={{ fontSize: 'var(--text-xs)', color: 'var(--text-secondary)' }}>
            Generated live for this demo run
          </span>
        </div>

        <div style={{ display: 'flex', alignItems: 'center', gap: 14, flexWrap: 'wrap' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 'var(--text-xs)' }}>
            <span style={{ color: 'var(--text-muted)' }}>PRODUCTION DATA:</span>
            <span
              style={{
                color: prov?.is_production_data ? 'var(--color-warning)' : 'var(--color-safe)',
                fontWeight: 600,
                display: 'inline-flex',
                alignItems: 'center',
                gap: 4,
              }}
            >
              <ShieldCheck size={13} />
              {prov?.is_production_data ? 'Yes' : 'No (Zero Production PII)'}
            </span>
          </div>

          <div style={{ fontSize: 'var(--text-xs)', color: 'var(--text-muted)' }}>
            RUN ID:{' '}
            <code
              style={{
                fontFamily: 'var(--font-mono)',
                color: 'var(--text-secondary)',
                fontSize: '11px',
              }}
            >
              {run.run_id}
            </code>
          </div>
        </div>
      </div>

      {/* Metadata Grid */}
      <div
        style={{
          display: 'grid',
          gridTemplateColumns: 'repeat(auto-fit, minmax(130px, 1fr))',
          gap: 12,
        }}
      >
        <div>
          <div style={{ fontSize: '10px', color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.05em' }}>
            Scenario
          </div>
          <div style={{ fontSize: 'var(--text-xs)', fontWeight: 600, color: 'var(--text-primary)', marginTop: 2 }}>
            {scenarioName || run.scenario_id}
          </div>
        </div>

        <div>
          <div style={{ fontSize: '10px', color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.05em' }}>
            Merchant Category
          </div>
          <div style={{ fontSize: 'var(--text-xs)', fontWeight: 600, color: 'var(--text-primary)', marginTop: 2, textTransform: 'capitalize' }}>
            {run.merchant_category}
          </div>
        </div>

        <div>
          <div style={{ fontSize: '10px', color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.05em' }}>
            Window Horizon
          </div>
          <div style={{ fontSize: 'var(--text-xs)', fontWeight: 600, color: 'var(--text-primary)', marginTop: 2, display: 'flex', alignItems: 'center', gap: 4 }}>
            <Clock size={12} style={{ color: 'var(--text-muted)' }} />
            {run.window_size} ({run.time_span_seconds ? `${Math.round(run.time_span_seconds)}s span` : 'bounded'})
          </div>
        </div>

        <div>
          <div style={{ fontSize: '10px', color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.05em' }}>
            Synthetic Events
          </div>
          <div style={{ fontSize: 'var(--text-xs)', fontWeight: 600, color: 'var(--text-primary)', marginTop: 2 }}>
            {run.total_transactions} txns ({run.feature_count} features)
          </div>
        </div>

        <div>
          <div style={{ fontSize: '10px', color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.05em' }}>
            Fitted Model
          </div>
          <div style={{ fontSize: 'var(--text-xs)', fontWeight: 600, color: 'var(--text-primary)', marginTop: 2, display: 'flex', alignItems: 'center', gap: 4 }}>
            <Cpu size={12} style={{ color: 'var(--text-muted)' }} />
            {run.model.model_name} <span style={{ color: 'var(--text-muted)', fontSize: '10px' }}>({run.model.model_version})</span>
          </div>
        </div>

        <div>
          <div style={{ fontSize: '10px', color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.05em' }}>
            Entities Observed
          </div>
          <div style={{ fontSize: 'var(--text-xs)', fontWeight: 600, color: 'var(--text-primary)', marginTop: 2, display: 'flex', alignItems: 'center', gap: 4 }}>
            <Layers size={12} style={{ color: 'var(--text-muted)' }} />
            {run.entity_counts.customers} cus · {run.entity_counts.devices} dev · {run.entity_counts.instruments} inst
          </div>
        </div>
      </div>
    </div>
  );
}
