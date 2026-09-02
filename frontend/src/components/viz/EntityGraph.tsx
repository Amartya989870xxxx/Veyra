/** Entity relationship graph.
 *
 * Evolved from the original EntityGraphCanvas: same force-directed 2D canvas
 * approach (which is clearer here than 3D would be), restyled onto the Veyra
 * palette and given explanations a non-specialist can read.
 *
 * Everything drawn comes from the backend's `entity_graph` payload. Node degree
 * — the "shared by N attempts" figure — is counted from the real edge list, so
 * no relationship is invented for visual effect. If the backend sends an empty
 * graph, the component says so instead of drawing something.
 */

import { useEffect, useMemo, useRef, useState } from 'react';
import { Maximize2, ZoomIn, ZoomOut } from 'lucide-react';
import type { EntityEdge, EntityGraph as EntityGraphData, EntityNode } from '../../api/types';
import { EmptyState } from '../ui';

interface SimNode extends EntityNode {
  x: number;
  y: number;
  vx: number;
  vy: number;
  degree: number;
}

const TYPE_LABEL: Record<string, string> = {
  customer: 'Customer account',
  device: 'Device fingerprint',
  instrument: 'Payment instrument',
  ip: 'Network address',
};

const TYPE_COLOR: Record<string, string> = {
  customer: '#a78bfa',
  device: '#f5f3ff',
  instrument: '#fbbf24',
  ip: '#34d399',
};

const EDGE_LABEL: Record<string, string> = {
  used_device: 'transacted from this device',
  used_card: 'used this payment instrument',
  used_ip: 'connected from this network address',
};

/** The far end of an edge when the selected node is the customer. */
const COUNTERPART_NOUN: Record<string, string> = {
  used_device: 'devices',
  used_card: 'payment instruments',
  used_ip: 'network addresses',
};

export function EntityGraph({
  graph,
  concentrated = false,
  height = 460,
}: {
  graph: EntityGraphData | undefined;
  /** Whether the detection concentrated on a small entity cluster. Drives the
   *  hub highlight — sourced from the backend verdict, not guessed here. */
  concentrated?: boolean;
  height?: number;
}) {
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const nodesRef = useRef<SimNode[]>([]);
  const rafRef = useRef(0);
  const [selected, setSelected] = useState<SimNode | null>(null);
  const [zoom, setZoom] = useState(1);

  const { nodes, edges } = useMemo(() => {
    const rawNodes = graph?.nodes ?? [];
    const rawEdges = graph?.edges ?? [];
    const degree = new Map<string, number>();
    for (const e of rawEdges) {
      degree.set(e.source, (degree.get(e.source) ?? 0) + 1);
      degree.set(e.target, (degree.get(e.target) ?? 0) + 1);
    }
    return { nodes: rawNodes, edges: rawEdges, degreeMap: degree };
  }, [graph]);

  const degreeMap = useMemo(() => {
    const d = new Map<string, number>();
    for (const e of edges) {
      d.set(e.source, (d.get(e.source) ?? 0) + 1);
      d.set(e.target, (d.get(e.target) ?? 0) + 1);
    }
    return d;
  }, [edges]);

  const maxDegree = useMemo(
    () => (degreeMap.size ? Math.max(...degreeMap.values()) : 0),
    [degreeMap],
  );

  /** Plain-language breakdown of how the selected node is connected, grouped by
   *  the backend's edge type so the panel says "used this payment instrument"
   *  rather than surfacing `used_card` at the reader. */
  const selectedRelations = useMemo(() => {
    if (!selected) return [];
    const counts = new Map<string, number>();
    for (const e of edges) {
      if (e.source !== selected.id && e.target !== selected.id) continue;
      counts.set(e.type, (counts.get(e.type) ?? 0) + 1);
    }
    // The graph is bipartite: every edge joins a customer to a device,
    // instrument or address. So the far end is always an account unless the
    // selection *is* the account, which decides how the sentence reads.
    const fromCustomer = selected.type === 'customer';
    return [...counts.entries()]
      .sort((a, b) => b[1] - a[1])
      .map(([type, count]) => {
        if (fromCustomer) {
          const noun = COUNTERPART_NOUN[type] ?? 'connected entities';
          return `used ${count} ${count === 1 ? noun.replace(/s$/, '') : noun}`;
        }
        const verb = EDGE_LABEL[type] ?? type.replace(/_/g, ' ');
        return `${count} ${count === 1 ? 'account' : 'accounts'} ${verb}`;
      });
  }, [selected, edges]);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas || nodes.length === 0) return;

    const ctx = canvas.getContext('2d');
    if (!ctx) return;

    const reduceMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;

    const resize = () => {
      const dpr = Math.min(window.devicePixelRatio, 2);
      canvas.width = canvas.clientWidth * dpr;
      canvas.height = canvas.clientHeight * dpr;
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    };
    resize();

    const w = canvas.clientWidth;
    const h = canvas.clientHeight;

    // Cap the simulation: large windows can return thousands of nodes and the
    // canvas is unreadable long before that.
    const capped = nodes.slice(0, 220);
    const idSet = new Set(capped.map((n) => n.id));
    const cappedEdges = edges.filter((e) => idSet.has(e.source) && idSet.has(e.target)).slice(0, 400);

    const sim: SimNode[] = capped.map((n, i) => {
      const angle = (i / capped.length) * Math.PI * 2;
      const radius = Math.min(w, h) * 0.3;
      return {
        ...n,
        x: w / 2 + Math.cos(angle) * radius * (0.5 + Math.random() * 0.6),
        y: h / 2 + Math.sin(angle) * radius * (0.5 + Math.random() * 0.6),
        vx: 0,
        vy: 0,
        degree: degreeMap.get(n.id) ?? 0,
      };
    });
    nodesRef.current = sim;
    const byId = new Map(sim.map((n) => [n.id, n]));

    const step = () => {
      // Repulsion between nodes, attraction along real edges, gentle centring.
      for (let i = 0; i < sim.length; i++) {
        const a = sim[i];
        for (let j = i + 1; j < sim.length; j++) {
          const b = sim[j];
          const dx = b.x - a.x;
          const dy = b.y - a.y;
          const d2 = dx * dx + dy * dy || 1;
          if (d2 > 40000) continue;
          const force = 220 / d2;
          const fx = dx * force;
          const fy = dy * force;
          a.vx -= fx;
          a.vy -= fy;
          b.vx += fx;
          b.vy += fy;
        }
        a.vx += (w / 2 - a.x) * 0.0012;
        a.vy += (h / 2 - a.y) * 0.0012;
      }

      for (const e of cappedEdges) {
        const s = byId.get(e.source);
        const t = byId.get(e.target);
        if (!s || !t) continue;
        const dx = t.x - s.x;
        const dy = t.y - s.y;
        const dist = Math.hypot(dx, dy) || 1;
        const pull = (dist - 62) * 0.0055;
        const fx = (dx / dist) * pull;
        const fy = (dy / dist) * pull;
        s.vx += fx;
        s.vy += fy;
        t.vx -= fx;
        t.vy -= fy;
      }

      for (const n of sim) {
        n.vx *= 0.86;
        n.vy *= 0.86;
        n.x = Math.max(16, Math.min(w - 16, n.x + n.vx));
        n.y = Math.max(16, Math.min(h - 16, n.y + n.vy));
      }
    };

    const draw = () => {
      ctx.clearRect(0, 0, w, h);
      ctx.save();
      ctx.translate(w / 2, h / 2);
      ctx.scale(zoom, zoom);
      ctx.translate(-w / 2, -h / 2);

      for (const e of cappedEdges) {
        const s = byId.get(e.source);
        const t = byId.get(e.target);
        if (!s || !t) continue;
        const hot = concentrated && (s.degree > 2 || t.degree > 2);
        ctx.strokeStyle = hot ? 'rgba(244,63,94,0.34)' : 'rgba(139,92,246,0.16)';
        ctx.lineWidth = hot ? 1.1 : 0.7;
        ctx.beginPath();
        ctx.moveTo(s.x, s.y);
        ctx.lineTo(t.x, t.y);
        ctx.stroke();
      }

      for (const n of sim) {
        const shared = n.degree > 2;
        const r = 3.2 + Math.min(n.degree, 12) * 0.62;
        const color = concentrated && shared ? '#f43f5e' : TYPE_COLOR[n.type] ?? '#a7a0b5';

        if (shared) {
          ctx.beginPath();
          ctx.arc(n.x, n.y, r + 5, 0, Math.PI * 2);
          ctx.fillStyle = concentrated ? 'rgba(244,63,94,0.13)' : 'rgba(139,92,246,0.12)';
          ctx.fill();
        }

        ctx.beginPath();
        ctx.arc(n.x, n.y, r, 0, Math.PI * 2);
        ctx.fillStyle = color;
        ctx.fill();

        if (selected?.id === n.id) {
          ctx.beginPath();
          ctx.arc(n.x, n.y, r + 7, 0, Math.PI * 2);
          ctx.strokeStyle = '#f5f3ff';
          ctx.lineWidth = 1.6;
          ctx.stroke();
        }
      }
      ctx.restore();
    };

    let ticks = 0;
    const loop = () => {
      // Settle then stop: no runaway loop once the layout is stable.
      if (ticks < (reduceMotion ? 220 : 400)) {
        step();
        ticks++;
        draw();
        rafRef.current = requestAnimationFrame(loop);
      } else {
        draw();
      }
    };

    if (reduceMotion) {
      for (let i = 0; i < 220; i++) step();
      draw();
    } else {
      rafRef.current = requestAnimationFrame(loop);
    }

    const onResize = () => {
      resize();
      draw();
    };
    const ro = new ResizeObserver(onResize);
    ro.observe(canvas);

    return () => {
      cancelAnimationFrame(rafRef.current);
      ro.disconnect();
    };
  }, [nodes, edges, degreeMap, zoom, concentrated, selected]);

  const handleClick = (ev: React.MouseEvent<HTMLCanvasElement>) => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const rect = canvas.getBoundingClientRect();
    const w = canvas.clientWidth;
    const h = canvas.clientHeight;
    const px = (ev.clientX - rect.left - w / 2) / zoom + w / 2;
    const py = (ev.clientY - rect.top - h / 2) / zoom + h / 2;

    let closest: SimNode | null = null;
    let best = 18;
    for (const n of nodesRef.current) {
      const d = Math.hypot(n.x - px, n.y - py);
      if (d < best) {
        best = d;
        closest = n;
      }
    }
    setSelected(closest);
  };

  if (!graph || graph.nodes.length === 0) {
    return (
      <EmptyState
        title="No entity graph returned"
        detail="The backend did not include relationship data for this window. Run a detection to populate the entity network."
      />
    );
  }

  const truncated = graph.nodes.length > 220;

  return (
    <div style={{ display: 'grid', gap: 'var(--sp-4)' }}>
      <div
        style={{
          display: 'flex',
          flexWrap: 'wrap',
          alignItems: 'center',
          justifyContent: 'space-between',
          gap: 'var(--sp-3)',
        }}
      >
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 'var(--sp-4)' }}>
          {Object.entries(TYPE_LABEL).map(([type, label]) => (
            <span
              key={type}
              style={{ display: 'inline-flex', alignItems: 'center', gap: 7, fontSize: 'var(--text-xs)', color: 'var(--text-secondary)' }}
            >
              <span style={{ width: 8, height: 8, borderRadius: 999, background: TYPE_COLOR[type] }} />
              {label}
            </span>
          ))}
          {concentrated && (
            <span style={{ display: 'inline-flex', alignItems: 'center', gap: 7, fontSize: 'var(--text-xs)', color: 'var(--tier-restrict)' }}>
              <span style={{ width: 8, height: 8, borderRadius: 999, background: '#f43f5e' }} />
              Shared by several attempts
            </span>
          )}
        </div>
        <div style={{ display: 'flex', gap: 6 }}>
          <IconBtn label="Zoom out" onClick={() => setZoom((z) => Math.max(0.5, z - 0.2))}>
            <ZoomOut size={14} />
          </IconBtn>
          <IconBtn label="Reset zoom" onClick={() => setZoom(1)}>
            <Maximize2 size={14} />
          </IconBtn>
          <IconBtn label="Zoom in" onClick={() => setZoom((z) => Math.min(2.4, z + 0.2))}>
            <ZoomIn size={14} />
          </IconBtn>
        </div>
      </div>

      <canvas
        ref={canvasRef}
        onClick={handleClick}
        style={{
          width: '100%',
          height,
          display: 'block',
          background: 'var(--bg-sunken)',
          border: '1px solid var(--border-subtle)',
          borderRadius: 'var(--radius-lg)',
          cursor: 'crosshair',
        }}
      />

      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 'var(--sp-4)', alignItems: 'center', justifyContent: 'space-between' }}>
        <p style={{ fontSize: 'var(--text-sm)', color: 'var(--text-secondary)' }}>
          {selected ? (
            <>
              <strong style={{ color: 'var(--text-primary)' }}>{TYPE_LABEL[selected.type] ?? selected.type}</strong>{' '}
              <span className="mono" style={{ color: 'var(--text-muted)' }}>{selected.label}</span>
              {' — '}
              {selected.degree > 0
                ? `connected to ${selected.degree} other ${selected.degree === 1 ? 'entity' : 'entities'} in this window.`
                : 'no connections in this window.'}
              {selectedRelations.length > 0 && (
                <span style={{ color: 'var(--text-muted)' }}> {selectedRelations.join(' · ')}.</span>
              )}
              {selected.degree > 2 && selected.type === 'device' && ' Several accounts share this device.'}
            </>
          ) : (
            'Click any node to see how it is connected. Larger nodes are shared by more payment attempts.'
          )}
        </p>
        <span className="mono" style={{ fontSize: 'var(--text-xs)', color: 'var(--text-muted)' }}>
          {graph.total_nodes} nodes · {graph.total_edges} edges
          {truncated && ' · showing first 220'}
        </span>
      </div>

      {maxDegree > 0 && (
        <p style={{ fontSize: 'var(--text-xs)', color: 'var(--text-muted)', lineHeight: 1.6 }}>
          Independent shoppers produce a wide, loosely connected graph. Coordinated activity collapses onto a
          few shared devices or instruments — the most connected entity here appears in {maxDegree} relationships.
        </p>
      )}
    </div>
  );
}

function IconBtn({ children, label, onClick }: { children: React.ReactNode; label: string; onClick: () => void }) {
  return (
    <button
      type="button"
      aria-label={label}
      onClick={onClick}
      style={{
        display: 'inline-flex',
        alignItems: 'center',
        justifyContent: 'center',
        width: 30,
        height: 30,
        background: 'var(--surface-2)',
        border: '1px solid var(--border)',
        borderRadius: 'var(--radius-sm)',
        color: 'var(--text-secondary)',
      }}
    >
      {children}
    </button>
  );
}

export type { EntityEdge };
