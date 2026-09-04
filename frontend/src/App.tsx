/** Application shell.
 *
 * Routing is hash-based and hand-rolled — lightweight navigation keeps deep links,
 * browser history, and refresh working seamlessly.
 */

import { Suspense, lazy, useCallback, useEffect, useState } from 'react';
import { TopNav, type RouteId } from './components/nav/TopNav';
import { OverviewPage } from './pages/OverviewPage';
import { LoadingBlock } from './components/ui';
import './styles/global.css';

// Lazy-loaded routes
const DetectionPage = lazy(() => import('./pages/DetectionPage').then((m) => ({ default: m.DetectionPage })));
const PerformancePage = lazy(() => import('./pages/PerformancePage').then((m) => ({ default: m.PerformancePage })));
const DataExplorerPage = lazy(() => import('./pages/DataExplorerPage').then((m) => ({ default: m.DataExplorerPage })));
const ArchitecturePage = lazy(() => import('./pages/ArchitecturePage').then((m) => ({ default: m.ArchitecturePage })));
const DocumentationPage = lazy(() => import('./pages/DocumentationPage').then((m) => ({ default: m.DocumentationPage })));

const ROUTE_IDS: RouteId[] = [
  'overview',
  'detection',
  'scale_lab',
  'performance',
  'explorer',
  'architecture',
  'docs',
];

function routeFromHash(): RouteId {
  const raw = window.location.hash.replace(/^#\/?/, '').split('?')[0];
  if (raw === 'performance') return 'scale_lab';
  return (ROUTE_IDS as string[]).includes(raw) ? (raw as RouteId) : 'overview';
}

function runIdFromHash(): string | null {
  const parts = window.location.hash.split('?');
  if (parts.length > 1) {
    const params = new URLSearchParams(parts[1]);
    return params.get('run_id');
  }
  return null;
}

export default function App() {
  const [route, setRoute] = useState<RouteId>(routeFromHash);
  const [pendingScenario, setPendingScenario] = useState<string | undefined>();
  const [selectedRunId, setSelectedRunId] = useState<string | null>(runIdFromHash);

  useEffect(() => {
    const onHashChange = () => {
      setRoute(routeFromHash());
      const rId = runIdFromHash();
      if (rId) setSelectedRunId(rId);
    };
    window.addEventListener('hashchange', onHashChange);
    return () => window.removeEventListener('hashchange', onHashChange);
  }, []);

  const navigate = useCallback((next: RouteId, runId?: string) => {
    if (runId) {
      setSelectedRunId(runId);
      window.location.hash = `/${next}?run_id=${encodeURIComponent(runId)}`;
    } else {
      window.location.hash = `/${next}`;
    }
    setRoute(next === 'performance' ? 'scale_lab' : next);
    window.scrollTo({ top: 0, behavior: 'auto' });
  }, []);

  const runScenario = useCallback(
    (scenarioId: string) => {
      setPendingScenario(scenarioId);
      navigate('detection');
    },
    [navigate],
  );

  return (
    <>
      <a className="skip-link" href="#main">
        Skip to content
      </a>

      {/* Ambient colour field behind every page */}
      <div className="veyra-backdrop" aria-hidden>
        <span className="blob blob-1" />
        <span className="blob blob-2" />
        <span className="blob blob-3" />
        <span className="grain" />
      </div>

      <div className="veyra-shell">
        <TopNav route={route} onNavigate={navigate} />

        <main id="main">
          <Suspense
            fallback={
              <div className="container" style={{ padding: 'var(--sp-8) var(--sp-5)' }}>
                <LoadingBlock label="Loading…" rows={4} />
              </div>
            }
          >
            {route === 'overview' && <OverviewPage onNavigate={navigate} onRunScenario={runScenario} />}

            {route === 'detection' && (
              <DetectionPage
                key={pendingScenario ?? 'default'}
                initialScenario={pendingScenario}
                onNavigateExplorer={(runId) => navigate('explorer', runId)}
              />
            )}

            {(route === 'scale_lab' || route === 'performance') && <PerformancePage />}

            {route === 'explorer' && (
              <DataExplorerPage
                initialRunId={selectedRunId}
                onNavigateDetection={() => navigate('detection')}
              />
            )}

            {route === 'architecture' && <ArchitecturePage />}

            {route === 'docs' && <DocumentationPage />}
          </Suspense>
        </main>

        <footer
          className="veyra-no-print"
          style={{
            borderTop: '1px solid var(--border-subtle)',
            background: 'rgba(5, 4, 9, 0.55)',
            backdropFilter: 'blur(18px)',
            padding: 'var(--sp-7) 0',
            marginTop: 'var(--sp-9)',
          }}
        >
          <div
            className="container"
            style={{
              display: 'flex',
              flexWrap: 'wrap',
              justifyContent: 'space-between',
              alignItems: 'center',
              gap: 'var(--sp-4)',
              fontSize: 'var(--text-xs)',
              color: 'var(--text-muted)',
            }}
          >
            <div>
              <span style={{ fontFamily: 'var(--font-display)', fontWeight: 700, color: 'var(--text-primary)', letterSpacing: '0.04em' }}>
                VEYRA
              </span>{' '}
              · Quantitative Streaming Intelligence
            </div>

            <div style={{ display: 'flex', gap: 'var(--sp-4)' }}>
              <button
                onClick={() => navigate('detection')}
                style={{ background: 'none', border: 'none', color: 'inherit', cursor: 'pointer', padding: 0 }}
              >
                Detection Console
              </button>
              <button
                onClick={() => navigate('scale_lab')}
                style={{ background: 'none', border: 'none', color: 'inherit', cursor: 'pointer', padding: 0 }}
              >
                Scale Lab
              </button>
              <button
                onClick={() => navigate('explorer')}
                style={{ background: 'none', border: 'none', color: 'inherit', cursor: 'pointer', padding: 0 }}
              >
                Data Explorer
              </button>
              <button
                onClick={() => navigate('architecture')}
                style={{ background: 'none', border: 'none', color: 'inherit', cursor: 'pointer', padding: 0 }}
              >
                Architecture
              </button>
              <button
                onClick={() => navigate('docs')}
                style={{ background: 'none', border: 'none', color: 'inherit', cursor: 'pointer', padding: 0 }}
              >
                Docs
              </button>
            </div>
          </div>
        </footer>
      </div>
    </>
  );
}
