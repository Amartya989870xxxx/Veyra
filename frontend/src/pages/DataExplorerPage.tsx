/** Data Explorer Page.
 *
 * Full-page view for forensic inspection of synthetic demo runs.
 * Lets a reviewer inspect transactions, ground-truth labels, and feature vectors.
 */

import { useState } from 'react';
import { Search, ArrowLeft } from 'lucide-react';
import { Button, Card, SectionLabel } from '../components/ui';
import { SyntheticDataExplorer } from '../components/explorer/SyntheticDataExplorer';

interface DataExplorerPageProps {
  initialRunId?: string | null;
  onNavigateDetection?: () => void;
}

export function DataExplorerPage({ initialRunId, onNavigateDetection }: DataExplorerPageProps) {
  const [inputRunId, setInputRunId] = useState(initialRunId || '');
  const [activeRunId, setActiveRunId] = useState<string | null>(initialRunId || null);

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (inputRunId.trim()) {
      setActiveRunId(inputRunId.trim());
    }
  };

  return (
    <div className="container-wide" style={{ padding: 'var(--sp-6) var(--sp-5) var(--sp-9)' }}>
      {/* Header */}
      <div style={{ marginBottom: 'var(--sp-5)' }}>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', flexWrap: 'wrap', gap: 12 }}>
          <div>
            <SectionLabel>Synthetic Dataset Inspector</SectionLabel>
            <h1 style={{ fontSize: 'var(--text-2xl)', marginTop: 6, fontWeight: 700 }}>
              Synthetic Data Explorer
            </h1>
            <p style={{ color: 'var(--text-secondary)', marginTop: 8, maxWidth: 760, fontSize: 'var(--text-md)' }}>
              Inspect the exact synthetic transactions, entity fingerprints, and feature values that produced a specific detection run.
              Bounded in-memory retention for reviewer auditing without sensitive payment data.
            </p>
          </div>

          {onNavigateDetection && (
            <Button
              variant="secondary"
              size="sm"
              onClick={onNavigateDetection}
              icon={<ArrowLeft size={14} />}
            >
              Back to Detection Console
            </Button>
          )}
        </div>
      </div>

      {/* Run Lookup Bar */}
      <Card style={{ marginBottom: 'var(--sp-5)', padding: '14px 18px' }}>
        <form onSubmit={handleSubmit} style={{ display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, flex: '1 1 300px' }}>
            <Search size={16} color="var(--text-muted)" />
            <input
              type="text"
              placeholder="Enter Run ID (e.g. run_01a067...)"
              value={inputRunId}
              onChange={(e) => setInputRunId(e.target.value)}
              style={{
                width: '100%',
                background: 'transparent',
                border: 'none',
                outline: 'none',
                color: 'var(--text-primary)',
                fontFamily: 'var(--font-mono)',
                fontSize: 'var(--text-sm)',
              }}
            />
          </div>

          <Button variant="primary" size="sm" type="submit">
            Inspect Run
          </Button>
        </form>
      </Card>

      {/* Explorer Component */}
      <SyntheticDataExplorer runId={activeRunId} />
    </div>
  );
}
