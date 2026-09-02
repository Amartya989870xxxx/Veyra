/** Incident report export.
 *
 * Every format here is backed by something real. `markdown` and `csv` are
 * produced server-side and arrive inside the response's `export_formats`; JSON
 * is the verbatim API response serialised. A format is only offered if the data
 * behind it actually exists on the current report, so the UI can never advertise
 * a download it cannot produce.
 *
 * PDF is deliberately the browser's own print pipeline rather than a bundled
 * renderer: it always reflects exactly what is on screen, and print styles in
 * global.css strip the chrome.
 */

import { useState } from 'react';
import { Check, Download, FileCode2, FileText, Printer, Table2 } from 'lucide-react';
import type { SimulationReport } from '../../api/types';
import { SectionLabel } from '../ui';

type FormatId = 'markdown' | 'csv' | 'json' | 'pdf';

interface ExportFormat {
  id: FormatId;
  label: string;
  detail: string;
  icon: React.ReactNode;
  /** Produces the file, or null for actions that are not downloads. */
  build: () => { content: string; filename: string; mime: string } | null;
}

function timestampSlug(): string {
  return new Date().toISOString().replace(/[:.]/g, '-').slice(0, 19);
}

export function ReportExporter({ report }: { report: SimulationReport }) {
  const [done, setDone] = useState<FormatId | null>(null);

  const base = `veyra_${report.merchant_id}_${report.scenario_id}_${timestampSlug()}`;
  const markdown = report.export_formats?.markdown;
  const csv = report.export_formats?.csv;

  const formats: ExportFormat[] = [];

  if (markdown) {
    formats.push({
      id: 'markdown',
      label: 'Incident report',
      detail: 'Markdown narrative, generated server-side',
      icon: <FileText size={17} style={{ color: 'var(--accent-bright)' }} />,
      build: () => ({ content: markdown, filename: `${base}.md`, mime: 'text/markdown' }),
    });
  }

  if (csv) {
    formats.push({
      id: 'csv',
      label: 'Transaction rows',
      detail: 'CSV of the events in this window',
      icon: <Table2 size={17} style={{ color: 'var(--tier-observe)' }} />,
      build: () => ({ content: csv, filename: `${base}.csv`, mime: 'text/csv' }),
    });
  }

  formats.push({
    id: 'json',
    label: 'Raw response',
    detail: 'The complete API payload, unmodified',
    icon: <FileCode2 size={17} style={{ color: 'var(--tier-review)' }} />,
    build: () => ({
      content: JSON.stringify(report, null, 2),
      filename: `${base}.json`,
      mime: 'application/json',
    }),
  });

  formats.push({
    id: 'pdf',
    label: 'Print / PDF',
    detail: 'Opens your browser print dialog',
    icon: <Printer size={17} style={{ color: 'var(--text-secondary)' }} />,
    build: () => null,
  });

  function handleExport(format: ExportFormat) {
    const file = format.build();

    if (!file) {
      window.print();
    } else {
      const blob = new Blob([file.content], { type: file.mime });
      const url = URL.createObjectURL(blob);
      const anchor = document.createElement('a');
      anchor.href = url;
      anchor.download = file.filename;
      document.body.appendChild(anchor);
      anchor.click();
      document.body.removeChild(anchor);
      URL.revokeObjectURL(url);
    }

    setDone(format.id);
    window.setTimeout(() => setDone((current) => (current === format.id ? null : current)), 2600);
  }

  return (
    <section className="veyra-no-print" style={{ display: 'grid', gap: 'var(--sp-4)' }}>
      <div style={{ display: 'grid', gap: 4 }}>
        <SectionLabel>Export</SectionLabel>
        <p style={{ fontSize: 'var(--text-sm)', color: 'var(--text-secondary)', maxWidth: 620 }}>
          Exports contain this run's data exactly as the API returned it — nothing is
          re-computed in the browser.
        </p>
      </div>

      <div
        style={{
          display: 'grid',
          gridTemplateColumns: 'repeat(auto-fit, minmax(212px, 1fr))',
          gap: 'var(--sp-3)',
        }}
      >
        {formats.map((format) => {
          const complete = done === format.id;
          return (
            <button
              key={format.id}
              type="button"
              onClick={() => handleExport(format)}
              style={{
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'space-between',
                gap: 'var(--sp-3)',
                padding: 'var(--sp-3) var(--sp-4)',
                textAlign: 'left',
                background: 'var(--surface-1)',
                border: '1px solid var(--border-subtle)',
                borderRadius: 'var(--radius)',
                color: 'var(--text-primary)',
                transition: 'border-color 0.15s var(--ease), background 0.15s var(--ease)',
              }}
              onMouseEnter={(e) => {
                e.currentTarget.style.borderColor = 'var(--accent-line)';
                e.currentTarget.style.background = 'var(--surface-2)';
              }}
              onMouseLeave={(e) => {
                e.currentTarget.style.borderColor = 'var(--border-subtle)';
                e.currentTarget.style.background = 'var(--surface-1)';
              }}
            >
              <span style={{ display: 'flex', alignItems: 'center', gap: 'var(--sp-3)', minWidth: 0 }}>
                {format.icon}
                <span style={{ display: 'grid', gap: 2, minWidth: 0 }}>
                  <span style={{ fontSize: 'var(--text-sm)', fontWeight: 600 }}>{format.label}</span>
                  <span style={{ fontSize: 'var(--text-xs)', color: 'var(--text-muted)' }}>
                    {format.detail}
                  </span>
                </span>
              </span>
              {complete ? (
                <Check size={16} style={{ color: 'var(--tier-observe)', flexShrink: 0 }} />
              ) : (
                <Download size={15} style={{ color: 'var(--text-muted)', flexShrink: 0 }} />
              )}
            </button>
          );
        })}
      </div>
    </section>
  );
}
