/** Application shell.
 *
 * Routing is hash-based and hand-rolled — five destinations do not justify a
 * router dependency, and the hash keeps the browser's back button, deep links
 * and refresh working. Scenario selection on the Overview page hands a scenario
 * id to the Detection console through `pendingScenario`, so "run this one" on
 * the landing page lands in the real product with the choice already made.
 */

import { Suspense, lazy, useCallback, useEffect, useState } from 'react';
import { TopNav, type RouteId } from './components/nav/TopNav';
import { OverviewPage } from './pages/OverviewPage';
import { LoadingBlock } from './components/ui';
import './styles/global.css';

// Overview is the entry point and stays in the main bundle. The other four are
// split, so arriving on #/detection never downloads the landing page's renderer.
const DetectionPage = lazy(() => import('./pages/DetectionPage').then((m) => ({ default: m.DetectionPage })));
const PerformancePage = lazy(() => import('./pages/PerformancePage').then((m) => ({ default: m.PerformancePage })));
const ArchitecturePage = lazy(() => import('./pages/ArchitecturePage').then((m) => ({ default: m.ArchitecturePage })));
const DocumentationPage = lazy(() => import('./pages/DocumentationPage').then((m) => ({ default: m.DocumentationPage })));

const ROUTE_IDS: RouteId[] = ['overview', 'detection', 'performance', 'architecture', 'docs'];

function routeFromHash(): RouteId {
  const raw = window.location.hash.replace(/^#\/?/, '').split('?')[0];
  return (ROUTE_IDS as string[]).includes(raw) ? (raw as RouteId) : 'overview';
}

export default function App() {
  const [route, setRoute] = useState<RouteId>(routeFromHash);
  const [pendingScenario, setPendingScenario] = useState<string | undefined>();

  useEffect(() => {
    const onHashChange = () => setRoute(routeFromHash());
    window.addEventListener('hashchange', onHashChange);
    return () => window.removeEventListener('hashchange', onHashChange);
  }, []);

  const navigate = useCallback((next: RouteId) => {
    window.location.hash = `/${next}`;
    setRoute(next);
    // A route change is a new page as far as the reader is concerned; the
    // Overview page manages its own in-page anchors.
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

      {/* Ambient colour field behind every page. Real element rather than a
          pseudo-element so its stacking order is explicit. */}
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
            // Remounting on scenario change lets the console start a fresh run
            // rather than merging a new selection into a previous result.
            <DetectionPage key={pendingScenario ?? 'default'} initialScenario={pendingScenario} />
          )}
          {route === 'performance' && <PerformancePage />}
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
        }}
      >
        <div
          className="container"
          style={{
            display: 'flex',
            flexWrap: 'wrap',
            gap: 'var(--sp-4)',
            alignItems: 'center',
            justifyContent: 'space-between',
          }}
        >
          <span style={{ fontSize: 'var(--text-xs)', color: 'var(--text-muted)', maxWidth: 620, lineHeight: 1.65 }}>
            Veyra — contextual fraud-spike detection. A research prototype evaluated on synthetic
            data; it holds no compliance certification and has not been validated against real
            payment traffic.
          </span>
          <nav aria-label="Footer" style={{ display: 'flex', gap: 'var(--sp-4)', flexWrap: 'wrap' }}>
            {ROUTE_IDS.map((id) => (
              <button
                key={id}
                onClick={() => navigate(id)}
                style={{
                  background: 'none',
                  border: 'none',
                  padding: 0,
                  fontSize: 'var(--text-xs)',
                  color: 'var(--text-secondary)',
                  textTransform: 'capitalize',
                }}
              >
                {id === 'docs' ? 'Documentation' : id}
              </button>
            ))}
          </nav>
        </div>
      </footer>
      </div>
    </>
  );
}
