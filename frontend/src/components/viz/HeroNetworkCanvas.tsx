/** Hero visualisation: a payment stream in which a coordinated cluster forms.
 *
 * This is the product thesis rendered as motion. Diffuse points are ordinary
 * payment activity — independent, unrelated, spread out. A subset slowly
 * converges onto a few shared points and edges appear between them; once that
 * concentration passes a threshold the cluster is marked. Volume alone never
 * changes: the same number of points is on screen throughout. What changes is
 * *structure*, which is exactly what Veyra reasons about.
 *
 * Constraints honoured: single rAF loop, full GPU disposal on unmount, resize
 * handling, a static composed frame under prefers-reduced-motion, and a CSS-only
 * fallback when WebGL is unavailable.
 */

import { useEffect, useRef, useState } from 'react';
import * as THREE from 'three';

const POINT_COUNT = 620;
const RING_COUNT = 54;
const CYCLE_SECONDS = 15;

interface Props {
  height?: number | string;
  onPhaseChange?: (detected: boolean) => void;
}

export function HeroNetworkCanvas({ height = '100%', onPhaseChange }: Props) {
  const mountRef = useRef<HTMLDivElement | null>(null);
  const [webglFailed, setWebglFailed] = useState(false);
  const [detected, setDetected] = useState(false);
  const phaseRef = useRef(false);

  useEffect(() => {
    const mount = mountRef.current;
    if (!mount) return;

    const reduceMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;

    let renderer: THREE.WebGLRenderer;
    try {
      renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true, powerPreference: 'low-power' });
    } catch {
      setWebglFailed(true);
      return;
    }

    const width = mount.clientWidth || 800;
    const heightPx = mount.clientHeight || 520;

    renderer.setSize(width, heightPx);
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    mount.appendChild(renderer.domElement);

    const scene = new THREE.Scene();
    const camera = new THREE.PerspectiveCamera(52, width / heightPx, 0.1, 100);
    camera.position.set(0, 0, 15);

    // --- geometry ---------------------------------------------------------
    // `home` is where an ordinary transaction drifts; `ringTarget` is the
    // shared entity a coordinated attempt collapses onto.
    const positions = new Float32Array(POINT_COUNT * 3);
    const colors = new Float32Array(POINT_COUNT * 3);
    const home = new Float32Array(POINT_COUNT * 3);
    const ringTarget = new Float32Array(POINT_COUNT * 3);
    const drift = new Float32Array(POINT_COUNT);

    const hubs: THREE.Vector3[] = [
      new THREE.Vector3(2.6, 0.6, 0),
      new THREE.Vector3(3.9, -1.1, -1),
      new THREE.Vector3(1.9, -1.9, 0.7),
    ];

    const normalColor = new THREE.Color('#a78bfa');
    const quietColor = new THREE.Color('#4a3d6b');
    const alertColor = new THREE.Color('#ff2e4c');

    for (let i = 0; i < POINT_COUNT; i++) {
      const i3 = i * 3;
      const x = (Math.random() - 0.5) * 22;
      const y = (Math.random() - 0.5) * 12;
      const z = (Math.random() - 0.5) * 8;
      home[i3] = x;
      home[i3 + 1] = y;
      home[i3 + 2] = z;
      positions[i3] = x;
      positions[i3 + 1] = y;
      positions[i3 + 2] = z;

      const hub = hubs[i % hubs.length];
      ringTarget[i3] = hub.x + (Math.random() - 0.5) * 1.5;
      ringTarget[i3 + 1] = hub.y + (Math.random() - 0.5) * 1.5;
      ringTarget[i3 + 2] = hub.z + (Math.random() - 0.5) * 1.2;

      drift[i] = Math.random() * Math.PI * 2;

      const base = i < RING_COUNT ? normalColor : Math.random() > 0.6 ? normalColor : quietColor;
      colors[i3] = base.r;
      colors[i3 + 1] = base.g;
      colors[i3 + 2] = base.b;
    }

    const pointsGeom = new THREE.BufferGeometry();
    pointsGeom.setAttribute('position', new THREE.BufferAttribute(positions, 3));
    pointsGeom.setAttribute('color', new THREE.BufferAttribute(colors, 3));

    const pointsMat = new THREE.PointsMaterial({
      size: 0.13,
      vertexColors: true,
      transparent: true,
      opacity: 0.9,
      sizeAttenuation: true,
      depthWrite: false,
      blending: THREE.AdditiveBlending,
    });
    const points = new THREE.Points(pointsGeom, pointsMat);
    scene.add(points);

    // Edges only ever connect ring members to their hub — no fabricated links
    // between unrelated points.
    const edgePositions = new Float32Array(RING_COUNT * 6);
    const edgeGeom = new THREE.BufferGeometry();
    edgeGeom.setAttribute('position', new THREE.BufferAttribute(edgePositions, 3));
    const edgeMat = new THREE.LineBasicMaterial({
      color: new THREE.Color('#ff2e4c'),
      transparent: true,
      opacity: 0,
      depthWrite: false,
      blending: THREE.AdditiveBlending,
    });
    const edges = new THREE.LineSegments(edgeGeom, edgeMat);
    scene.add(edges);

    const posAttr = pointsGeom.getAttribute('position') as THREE.BufferAttribute;
    const colAttr = pointsGeom.getAttribute('color') as THREE.BufferAttribute;
    const edgeAttr = edgeGeom.getAttribute('position') as THREE.BufferAttribute;

    const tmp = new THREE.Color();

    /** progress: 0 = fully diffuse, 1 = fully converged. */
    function composeFrame(progress: number, t: number) {
      const eased = progress * progress * (3 - 2 * progress);

      for (let i = 0; i < POINT_COUNT; i++) {
        const i3 = i * 3;
        const wobble = Math.sin(t * 0.5 + drift[i]) * 0.16;

        if (i < RING_COUNT) {
          posAttr.array[i3] = home[i3] + (ringTarget[i3] - home[i3]) * eased + wobble;
          posAttr.array[i3 + 1] = home[i3 + 1] + (ringTarget[i3 + 1] - home[i3 + 1]) * eased + wobble;
          posAttr.array[i3 + 2] = home[i3 + 2] + (ringTarget[i3 + 2] - home[i3 + 2]) * eased;

          tmp.copy(normalColor).lerp(alertColor, Math.max(0, (eased - 0.45) / 0.55));
          colAttr.array[i3] = tmp.r;
          colAttr.array[i3 + 1] = tmp.g;
          colAttr.array[i3 + 2] = tmp.b;
        } else {
          // Ordinary traffic keeps drifting: volume is unchanged throughout.
          posAttr.array[i3] = home[i3] + Math.sin(t * 0.32 + drift[i]) * 0.42;
          posAttr.array[i3 + 1] = home[i3 + 1] + Math.cos(t * 0.26 + drift[i]) * 0.34;
          posAttr.array[i3 + 2] = home[i3 + 2] + wobble;
        }
      }
      posAttr.needsUpdate = true;
      colAttr.needsUpdate = true;

      for (let i = 0; i < RING_COUNT; i++) {
        const i3 = i * 3;
        const hub = hubs[i % hubs.length];
        const e6 = i * 6;
        edgeAttr.array[e6] = posAttr.array[i3];
        edgeAttr.array[e6 + 1] = posAttr.array[i3 + 1];
        edgeAttr.array[e6 + 2] = posAttr.array[i3 + 2];
        edgeAttr.array[e6 + 3] = hub.x;
        edgeAttr.array[e6 + 4] = hub.y;
        edgeAttr.array[e6 + 5] = hub.z;
      }
      edgeAttr.needsUpdate = true;
      edgeMat.opacity = Math.max(0, (eased - 0.35) / 0.65) * 0.5;

      const nowDetected = eased > 0.82;
      if (nowDetected !== phaseRef.current) {
        phaseRef.current = nowDetected;
        setDetected(nowDetected);
        onPhaseChange?.(nowDetected);
      }
    }

    let raf = 0;
    const start = performance.now();

    if (reduceMotion) {
      // One composed frame at the moment of detection — the story, without motion.
      composeFrame(0.95, 0);
      renderer.render(scene, camera);
    } else {
      const loop = () => {
        const elapsed = (performance.now() - start) / 1000;
        const cycle = (elapsed % CYCLE_SECONDS) / CYCLE_SECONDS;
        // Hold diffuse, converge, hold detected, release.
        const progress =
          cycle < 0.18 ? 0 : cycle < 0.55 ? (cycle - 0.18) / 0.37 : cycle < 0.86 ? 1 : 1 - (cycle - 0.86) / 0.14;

        composeFrame(Math.max(0, Math.min(1, progress)), elapsed);
        points.rotation.y = Math.sin(elapsed * 0.06) * 0.12;
        edges.rotation.y = points.rotation.y;
        renderer.render(scene, camera);
        raf = requestAnimationFrame(loop);
      };
      raf = requestAnimationFrame(loop);
    }

    const onResize = () => {
      const w = mount.clientWidth || 800;
      const h = mount.clientHeight || 520;
      renderer.setSize(w, h);
      camera.aspect = w / h;
      camera.updateProjectionMatrix();
    };
    const observer = new ResizeObserver(onResize);
    observer.observe(mount);

    return () => {
      cancelAnimationFrame(raf);
      observer.disconnect();
      pointsGeom.dispose();
      pointsMat.dispose();
      edgeGeom.dispose();
      edgeMat.dispose();
      renderer.dispose();
      if (renderer.domElement.parentNode === mount) mount.removeChild(renderer.domElement);
    };
  }, [onPhaseChange]);

  if (webglFailed) {
    return (
      <div
        style={{
          height,
          display: 'grid',
          placeItems: 'center',
          background:
            'radial-gradient(circle at 60% 45%, rgba(139,92,246,0.16), transparent 62%), var(--bg-sunken)',
          border: '1px solid var(--border-subtle)',
          borderRadius: 'var(--radius-xl)',
          color: 'var(--text-muted)',
          fontSize: 'var(--text-sm)',
          textAlign: 'center',
          padding: 'var(--sp-6)',
        }}
      >
        Transaction network visualisation unavailable — WebGL is not supported in this browser.
      </div>
    );
  }

  return (
    <div style={{ position: 'relative', height, width: '100%' }}>
      <div ref={mountRef} style={{ position: 'absolute', inset: 0 }} aria-hidden />
      <div
        aria-live="polite"
        style={{
          position: 'absolute',
          left: 'var(--sp-5)',
          bottom: 'var(--sp-5)',
          display: 'flex',
          alignItems: 'center',
          gap: 'var(--sp-2)',
          padding: '7px 13px',
          borderRadius: 999,
          background: detected ? 'var(--tier-restrict-wash)' : 'rgba(139,92,246,0.1)',
          border: `1px solid ${detected ? 'rgba(244,63,94,0.4)' : 'var(--accent-line)'}`,
          fontFamily: 'var(--font-mono)',
          fontSize: 'var(--text-xs)',
          letterSpacing: '0.1em',
          color: detected ? 'var(--tier-restrict)' : 'var(--accent-bright)',
          transition: 'all 0.5s var(--ease)',
          backdropFilter: 'blur(8px)',
        }}
      >
        <span
          style={{
            width: 6,
            height: 6,
            borderRadius: 999,
            background: 'currentColor',
            animation: 'veyra-pulse 1.6s ease-in-out infinite',
          }}
        />
        {detected ? 'COORDINATED ANOMALY DETECTED' : 'MONITORING PAYMENT ACTIVITY'}
      </div>
    </div>
  );
}
