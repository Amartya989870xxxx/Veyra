/** Product navigation.
 *
 * Five destinations, named for what they do rather than for internal machinery —
 * the previous build shipped "Foundry Home", "Manual & Guide" and "Real Stress
 * Test", none of which tell a first-time visitor anything.
 *
 * The API status pill is a live reading of GET /health, not decoration: if the
 * backend is down the user learns it here, before clicking Run detection and
 * hitting a failure.
 */

import { useEffect, useState } from 'react';
import { Menu, X } from 'lucide-react';
import { api } from '../../api/client';
import type { HealthResponse } from '../../api/types';
import { Button } from '../ui';

export type RouteId = 'overview' | 'detection' | 'performance' | 'architecture' | 'docs';

export const ROUTES: { id: RouteId; label: string }[] = [
  { id: 'overview', label: 'Overview' },
  { id: 'detection', label: 'Detection' },
  { id: 'performance', label: 'Performance' },
  { id: 'architecture', label: 'Architecture' },
  { id: 'docs', label: 'Documentation' },
];

export function TopNav({
  route,
  onNavigate,
}: {
  route: RouteId;
  onNavigate: (r: RouteId) => void;
}) {
  const [health, setHealth] = useState<HealthResponse | null>(null);
  const [healthFailed, setHealthFailed] = useState(false);
  const [mobileOpen, setMobileOpen] = useState(false);

  useEffect(() => {
    const controller = new AbortController();
    api
      .getHealth(controller.signal)
      .then((h) => {
        setHealth(h);
        setHealthFailed(false);
      })
      .catch(() => setHealthFailed(true));
    return () => controller.abort();
  }, []);

  const online = Boolean(health) && !healthFailed;

  return (
    <header
      style={{
        position: 'sticky',
        top: 0,
        zIndex: 100,
        height: 'var(--nav-h)',
        display: 'flex',
        alignItems: 'center',
        background: 'rgba(5, 4, 9, 0.66)',
        backdropFilter: 'blur(24px) saturate(150%)',
        WebkitBackdropFilter: 'blur(24px) saturate(150%)',
        borderBottom: '1px solid var(--border-subtle)',
      }}
    >
      <div
        className="container-wide"
        style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 'var(--sp-5)' }}
      >
        <button
          onClick={() => onNavigate('overview')}
          style={{
            display: 'flex',
            alignItems: 'center',
            gap: 10,
            background: 'none',
            border: 'none',
            padding: 0,
            color: 'var(--text-primary)',
          }}
          aria-label="Veyra home"
        >
          <span
            aria-hidden
            style={{
              display: 'grid',
              placeItems: 'center',
              width: 28,
              height: 28,
              borderRadius: 8,
              overflow: 'hidden',
              boxShadow: '0 0 16px rgba(59, 130, 246, 0.35)',
              border: '1px solid rgba(255, 255, 255, 0.12)',
            }}
          >
            <img src="/favicon-32x32.png" alt="Veyra logo" width={28} height={28} style={{ display: 'block', objectFit: 'cover' }} />
          </span>
          <span style={{ fontFamily: 'var(--font-display)', fontSize: 'var(--text-md)', fontWeight: 700, letterSpacing: '0.01em' }}>VEYRA</span>
        </button>

        <nav aria-label="Primary" className="veyra-desktop-nav" style={{ display: 'flex', gap: 2 }}>
          {ROUTES.map((r) => {
            const active = r.id === route;
            return (
              <button
                key={r.id}
                onClick={() => onNavigate(r.id)}
                aria-current={active ? 'page' : undefined}
                style={{
                  padding: '7px 13px',
                  background: active ? 'var(--surface-2)' : 'transparent',
                  border: '1px solid ' + (active ? 'var(--border)' : 'transparent'),
                  borderRadius: 'var(--radius-sm)',
                  color: active ? 'var(--text-primary)' : 'var(--text-secondary)',
                  fontSize: 'var(--text-sm)',
                  fontWeight: active ? 600 : 500,
                  transition: 'color 0.15s, background 0.15s',
                }}
              >
                {r.label}
              </button>
            );
          })}
        </nav>

        <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--sp-3)' }}>
          <span
            title={
              online
                ? `Veyra API reachable · environment: ${health?.environment}`
                : 'The Veyra API is not reachable from this browser.'
            }
            style={{
              display: 'inline-flex',
              alignItems: 'center',
              gap: 7,
              padding: '5px 11px',
              borderRadius: 999,
              border: '1px solid var(--glass-edge)',
              background: 'var(--glass)',
              fontFamily: 'var(--font-mono)',
              fontSize: 'var(--text-xs)',
              color: online ? 'var(--tier-observe)' : 'var(--tier-restrict)',
              whiteSpace: 'nowrap',
            }}
          >
            <span
              style={{
                width: 6,
                height: 6,
                borderRadius: 999,
                background: 'currentColor',
                animation: online ? 'veyra-pulse 2.2s ease-in-out infinite' : undefined,
              }}
            />
            {online ? `API · ${health?.environment ?? 'ok'}` : 'API offline'}
          </span>

          <div className="veyra-desktop-nav">
            <Button variant="primary" size="sm" onClick={() => onNavigate('detection')}>
              Run Detection
            </Button>
          </div>

          <button
            className="veyra-mobile-toggle"
            aria-label={mobileOpen ? 'Close menu' : 'Open menu'}
            aria-expanded={mobileOpen}
            onClick={() => setMobileOpen((o) => !o)}
            style={{
              display: 'none',
              background: 'var(--surface-2)',
              border: '1px solid var(--border)',
              borderRadius: 'var(--radius-sm)',
              padding: 6,
              color: 'var(--text-primary)',
            }}
          >
            {mobileOpen ? <X size={16} /> : <Menu size={16} />}
          </button>
        </div>
      </div>

      {mobileOpen && (
        <div
          style={{
            position: 'absolute',
            top: 'var(--nav-h)',
            left: 0,
            right: 0,
            background: 'rgba(11, 9, 18, 0.96)',
            backdropFilter: 'blur(24px)',
            borderBottom: '1px solid var(--border)',
            padding: 'var(--sp-3)',
            display: 'grid',
            gap: 4,
          }}
        >
          {ROUTES.map((r) => (
            <button
              key={r.id}
              onClick={() => {
                onNavigate(r.id);
                setMobileOpen(false);
              }}
              style={{
                textAlign: 'left',
                padding: 'var(--sp-3)',
                background: r.id === route ? 'var(--surface-2)' : 'transparent',
                border: 'none',
                borderRadius: 'var(--radius-sm)',
                color: r.id === route ? 'var(--text-primary)' : 'var(--text-secondary)',
                fontSize: 'var(--text-base)',
              }}
            >
              {r.label}
            </button>
          ))}
        </div>
      )}
    </header>
  );
}
