/** Overview Page — Final Frontend Polish Pass.
 *
 * Implements:
 * 1. Grounded, problem-focused messaging ("See coordinated fraud before it becomes loss").
 * 2. Comfortable, legible typography across all laptops and screens.
 * 3. Restrained, calm fintech visual identity (no generic AI neon glow).
 * 4. Product-relevant 3D Hero visualization (HeroNetworkCanvas) showing payment cluster formation.
 * 5. Interactive "Same spike. Different conclusion." story contrasting legitimate flash sales vs card testing.
 * 6. Strict metric integrity — zero fabricated numbers, zero unsupported "100% Zero Leakage" absolute claims.
 */

import { Suspense, lazy, useState } from 'react';
import {
  ArrowRight,
  CheckCircle2,
  Clock,
  Cpu,
  Layers,
  ShieldCheck,
  Users,
  Video,
} from 'lucide-react';
import type { RouteId } from '../components/nav/TopNav';

const HeroNetworkCanvas = lazy(() =>
  import('../components/viz/HeroNetworkCanvas').then((m) => ({ default: m.HeroNetworkCanvas })),
);

/** The final, permanent Veyra product walkthrough video: https://youtu.be/ldEY9BxSoCs
 *
 * Hardcoded so the walkthrough works in every environment — local dev, preview and
 * production — with zero required deployment configuration. `VITE_WALKTHROUGH_VIDEO_ID`
 * (see `frontend/.env.example`) remains a supported override for swapping the video
 * without a code change, but Vercel needs no environment variable set for this to work.
 */
const CANONICAL_WALKTHROUGH_VIDEO_ID = 'ldEY9BxSoCs';
const WALKTHROUGH_VIDEO_ID: string =
  (import.meta.env.VITE_WALKTHROUGH_VIDEO_ID as string | undefined)?.trim() ||
  CANONICAL_WALKTHROUGH_VIDEO_ID;

interface OverviewPageProps {
  onNavigate: (route: RouteId) => void;
  onRunScenario: (scenarioId: string) => void;
}

export function OverviewPage({ onNavigate, onRunScenario }: OverviewPageProps) {
  // "Same spike. Different conclusion." interactive scenario toggle
  const [activeStory, setActiveStory] = useState<'flash_sale' | 'card_testing'>('flash_sale');

  // Audience tab state
  const [activeAudienceTab, setActiveAudienceTab] = useState<number>(0);

  // FAQ accordion state
  const [openFaq, setOpenFaq] = useState<number | null>(0);

  const audienceTabs = [
    {
      id: 'gateways',
      title: 'Payment Gateways & Aggregators',
      badge: 'HIGH-THROUGHPUT INFRASTRUCTURE',
      headline: 'Detect distributed card testing before downstream processor fines hit',
      description:
        'When stolen card dumps are tested across hundreds of merchant endpoints, traditional single-event filters pass each low-value authorization. Veyra evaluates streaming velocity across merchant windows, isolating automated bot networks without blocking legitimate shoppers.',
      metricLabel: 'Evaluated Benchmark Mitigation',
      metricVal: 'Card Testing Defense',
      features: [
        'Evaluated on 60-second temporal windows with past-only scoring boundaries',
        'Shannon Failure Entropy separates bank outages from automated decline storms',
        'Entity cluster rate-limiting without degrading real shopper authorization rates',
      ],
      scenarioId: 'card_testing_burst',
      ctaText: 'Test Card-Testing Defense',
    },
    {
      id: 'd2c',
      title: 'High-Growth D2C & Commerce',
      badge: 'PRESERVE LEGITIMATE REVENUE',
      headline: 'Protect flash sales and product launches from false declines',
      description:
        'During an organic midnight drop, naive fraud engines mistake eager human shoppers for an attack. Veyra’s 168-hour seasonal MAD baselines and bipartite graph engine verify entity diversity, preventing costly false blocks on your highest-grossing hours.',
      metricLabel: 'Flash-Sale Hard Negative',
      metricVal: '0.0% False Blocks',
      features: [
        '168-Hour Diurnal MAD Baselines prevent Friday night revenue drops',
        'Bipartite Graph Gini separates 500 shoppers from 500 fake accounts on 2 devices',
        'Protects coupon and discount budgets against voucher harvesting swarms',
      ],
      scenarioId: 'flash_sale_spike',
      ctaText: 'Test Flash Sale Hard-Negative',
    },
    {
      id: 'risk-teams',
      title: 'Risk & Fraud Engineering',
      badge: 'EXPLAINABLE RISK INTELLIGENCE',
      headline: 'Forensic incident dossiers with verifiable temporal leakage gates',
      description:
        'Eliminate alert fatigue. Every flagged incident synthesizes a transparent, plain-language forensic narrative contrasting observed metrics against historical baselines, paired with exportable PDF, Markdown, JSON, and CSV audit evidence.',
      metricLabel: 'Investigation Readiness',
      metricVal: 'Instant Dossier',
      features: [
        'ADR-004 Downstream Barrier prevents post-facto dispute label leakage',
        'ADR-006 4-Tier Decision Policy (OBSERVE, ALERT, REVIEW, RESTRICT)',
        'One-click export to PDF dossiers, Markdown summaries, JSON vectors, and CSV streams',
      ],
      scenarioId: 'device_farm_ring',
      ctaText: 'Test Device Farm Detection',
    },
    {
      id: 'vulcan',
      title: 'Agentic Commerce (Razorpay Vulcan)',
      badge: 'AUTONOMOUS AGENT RISK VERIFICATION',
      headline: 'Pre-flight risk verification for autonomous AI buyer swarms',
      description:
        'As autonomous procurement agents transact across agentic payment rails, malicious actors deploy headless bot swarms to deplete inventory. Veyra verifies AI agent behavior against legitimate entropy distributions, securing agentic checkouts seamlessly.',
      metricLabel: 'Throughput Tested',
      metricVal: '2,000+ TPS',
      features: [
        'Pre-flight risk verification for agentic API payment intents',
        'Decouples rogue emulator swarms from authenticated procurement agents',
        'Zero-friction pass-through for legitimate one-click autonomous transactions',
      ],
      scenarioId: 'ring_under_flash_sale',
      ctaText: 'Test Vulcan Co-Defense',
    },
  ];

  const faqs = [
    {
      q: 'How does Veyra separate legitimate flash sales from coordinated attacks?',
      a: 'During both an attack and a flash sale, transaction volume spikes drastically. Veyra inspects orthogonal dimensions: in a legitimate flash sale, attempts originate from thousands of distinct, unlinked devices with normal failure rates (<6%) and high amount entropy. In an attack, attempts originate from clustered device emulators or proxy pools with high failure rates (>80%) and low entropy. Veyra fuses these signals to score flash sales in Tier OBSERVE (0% false blocks on evaluated tests) and attacks in Tier RESTRICT.',
    },
    {
      q: 'What is Median Absolute Deviation (MAD) and why is it used instead of standard deviation?',
      a: 'The arithmetic mean and standard deviation have a 0% breakdown point: a single past attack of 1,000 transactions inflates standard deviation so heavily that future attacks appear normal (outlier poisoning). MAD calculates the median of deviations from the median, possessing a 50% breakdown point. It ensures that historical attacks do not desensitize the merchant baseline for that specific hour of the week.',
    },
    {
      q: 'How does Veyra achieve sustained throughput in benchmark tests?',
      a: 'Veyra utilizes single-pass in-memory vector aggregations (WindowAgg), linear-time O(V+E) bipartite connected component graph extraction, and quantized HistGradientBoosting decision trees. This avoids expensive ad-hoc SQL joins or global graph traversals during online scoring.',
    },
    {
      q: 'How does Veyra address data leakage in machine learning (ADR-004)?',
      a: 'Chargebacks and dispute outcomes arrive 14 to 60 days after payment. If an offline model trains on future dispute labels, it creates artificial accuracy that collapses in production. Veyra enforces a strict past-only horizon [T - WindowSize, T) with automated CI assertion gates (assert_no_downstream) that fail the build if post-facto signals enter a feature vector.',
    },
    {
      q: 'How are customer identifiers and card data handled?',
      a: 'Veyra never stores raw credit card PANs or CVVs. Payment instruments are tokenized into deterministic salted hashes via HMAC-SHA256 blind indexing (ins_tok_...). Customer PII is encrypted at rest using AES-GCM-256 with unique 12-byte initialization vectors per record, and all database queries enforce row-level tenant isolation.',
    },
    {
      q: 'What are the four operational decision tiers in ADR-006?',
      a: 'Veyra avoids binary blocking to prevent catastrophic revenue loss. Tiers are: 1. OBSERVE (p < 0.35, silent telemetry), 2. ALERT (0.35 <= p < 0.60, merchant notification), 3. REVIEW (0.60 <= p < 0.85, queued for human fraud analyst), and 4. RESTRICT (p >= 0.85, recommends targeted velocity caps, CAPTCHA challenges, or coupon pauses without dropping live payments).',
    },
  ];

  return (
    <div style={{ background: '#060913', color: '#ffffff', overflowX: 'hidden' }}>
      {/* -------------------------------------------------------------
          HERO SECTION: Focused Problem Statement + Product-Relevant 3D Visual
      -------------------------------------------------------------- */}
      <section
        style={{
          position: 'relative',
          padding: 'clamp(48px, 7vw, 84px) 0 clamp(40px, 5vw, 64px)',
          background:
            'radial-gradient(ellipse 70% 50% at 50% -10%, rgba(30, 58, 138, 0.28) 0%, rgba(6, 9, 19, 0) 80%)',
          overflow: 'hidden',
          borderBottom: '1px solid rgba(255, 255, 255, 0.07)',
        }}
      >
        <div className="container" style={{ position: 'relative', zIndex: 10 }}>
          <div
            style={{
              display: 'grid',
              gridTemplateColumns: 'repeat(auto-fit, minmax(320px, 1fr))',
              gap: 'clamp(32px, 5vw, 56px)',
              alignItems: 'center',
            }}
          >
            {/* Left: Grounded Problem Statement & CTAs */}
            <div style={{ textAlign: 'left', maxWidth: '620px' }}>
              {/* Eyebrow Pill */}
              <div
                style={{
                  display: 'inline-flex',
                  alignItems: 'center',
                  gap: '8px',
                  padding: '5px 12px',
                  borderRadius: '999px',
                  background: 'rgba(255, 255, 255, 0.05)',
                  border: '1px solid rgba(255, 255, 255, 0.1)',
                  fontSize: '12px',
                  fontWeight: 600,
                  color: '#94a3b8',
                  letterSpacing: '0.04em',
                  marginBottom: '20px',
                }}
              >
                <span
                  style={{
                    width: '6px',
                    height: '6px',
                    borderRadius: '50%',
                    background: '#f93f28',
                    boxShadow: '0 0 8px #f93f28',
                  }}
                />
                [ CONTEXTUAL FRAUD DETECTION ]
              </div>

              {/* Master Headline (Problem-First) */}
              <h1
                style={{
                  fontFamily: 'var(--font-display)',
                  fontSize: 'clamp(34px, 4.4vw, 54px)',
                  fontWeight: 700,
                  lineHeight: 1.15,
                  letterSpacing: '-0.02em',
                  color: '#ffffff',
                  marginBottom: '20px',
                }}
              >
                See coordinated fraud before it becomes loss.
              </h1>

              {/* Supporting Copy (Readable, Clear, Non-Hyperbolic) */}
              <p
                style={{
                  fontSize: '17px',
                  lineHeight: 1.65,
                  color: '#cbd5e1',
                  marginBottom: '32px',
                  fontWeight: 400,
                }}
              >
                Veyra analyzes transaction behavior across time, historical merchant patterns, and connected entities to detect coordinated payment attacks that simple volume rules confuse with legitimate traffic spikes.
              </p>

              {/* CTAs */}
              <div style={{ display: 'flex', gap: '14px', flexWrap: 'wrap', marginBottom: '32px' }}>
                <button
                  onClick={() => onNavigate('detection')}
                  style={{
                    background: '#f93f28',
                    border: 'none',
                    color: '#ffffff',
                    padding: '13px 26px',
                    borderRadius: '8px',
                    fontSize: '14px',
                    fontWeight: 700,
                    boxShadow: '0 4px 20px rgba(249, 63, 40, 0.35)',
                    display: 'inline-flex',
                    alignItems: 'center',
                    gap: '8px',
                    cursor: 'pointer',
                    transition: 'transform 0.15s ease, filter 0.15s ease',
                  }}
                  onMouseEnter={(e) => {
                    e.currentTarget.style.transform = 'translateY(-2px)';
                    e.currentTarget.style.filter = 'brightness(1.1)';
                  }}
                  onMouseLeave={(e) => {
                    e.currentTarget.style.transform = 'none';
                    e.currentTarget.style.filter = 'none';
                  }}
                >
                  Open Detection Console <ArrowRight size={15} />
                </button>

                <button
                  onClick={() => onNavigate('performance')}
                  style={{
                    background: 'rgba(255, 255, 255, 0.05)',
                    border: '1px solid rgba(255, 255, 255, 0.14)',
                    color: '#ffffff',
                    padding: '13px 22px',
                    borderRadius: '8px',
                    fontSize: '14px',
                    fontWeight: 600,
                    cursor: 'pointer',
                    display: 'inline-flex',
                    alignItems: 'center',
                    gap: '8px',
                    transition: 'background 0.15s ease, border-color 0.15s ease',
                  }}
                  onMouseEnter={(e) => {
                    e.currentTarget.style.background = 'rgba(255, 255, 255, 0.09)';
                    e.currentTarget.style.borderColor = 'rgba(255, 255, 255, 0.25)';
                  }}
                  onMouseLeave={(e) => {
                    e.currentTarget.style.background = 'rgba(255, 255, 255, 0.05)';
                    e.currentTarget.style.borderColor = 'rgba(255, 255, 255, 0.14)';
                  }}
                >
                  <Cpu size={15} color="#94a3b8" /> Performance Lab
                </button>
              </div>

              {/* Grounded Metadata Pill */}
              <div
                style={{
                  display: 'inline-flex',
                  alignItems: 'center',
                  gap: '12px',
                  fontSize: '13px',
                  color: '#94a3b8',
                  padding: '8px 14px',
                  borderRadius: '6px',
                  background: 'rgba(255, 255, 255, 0.02)',
                  border: '1px solid rgba(255, 255, 255, 0.06)',
                }}
              >
                <span style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
                  <Clock size={13} color="#3b82f6" /> 60s Past-Only Windows
                </span>
                <span>•</span>
                <span style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
                  <ShieldCheck size={13} color="#10b981" /> 168h Seasonal Baselines
                </span>
              </div>
            </div>

            {/* Right: Product-Relevant 3D Visual (HeroNetworkCanvas) */}
            <div
              style={{
                position: 'relative',
                height: '460px',
                borderRadius: '16px',
                border: '1px solid rgba(255, 255, 255, 0.09)',
                background: '#070b18',
                overflow: 'hidden',
                boxShadow: '0 20px 60px rgba(0, 0, 0, 0.65)',
              }}
            >
              {/* Caption Header */}
              <div
                style={{
                  position: 'absolute',
                  top: '16px',
                  left: '16px',
                  right: '16px',
                  zIndex: 2,
                  display: 'flex',
                  justifyContent: 'space-between',
                  alignItems: 'center',
                }}
              >
                <span
                  style={{
                    fontSize: '11px',
                    fontFamily: 'var(--font-mono)',
                    color: '#64748b',
                    letterSpacing: '0.04em',
                  }}
                >
                  STREAM TOPOLOGY METAPHOR
                </span>
                <span
                  style={{
                    fontSize: '11px',
                    fontFamily: 'var(--font-mono)',
                    color: '#94a3b8',
                  }}
                >
                  620 NODES // 3 HUBS
                </span>
              </div>

              {/* Three.js Canvas */}
              <Suspense
                fallback={
                  <div
                    style={{
                      height: '100%',
                      display: 'grid',
                      placeItems: 'center',
                      color: '#64748b',
                      fontSize: '13px',
                    }}
                  >
                    Initializing stream visualizer…
                  </div>
                }
              >
                <HeroNetworkCanvas height="100%" />
              </Suspense>
            </div>
          </div>
        </div>
      </section>

      {/* -------------------------------------------------------------
          PROBLEM 5: INTERACTIVE "SAME SPIKE, DIFFERENT CONCLUSION" STORY
      -------------------------------------------------------------- */}
      <section
        style={{
          padding: 'clamp(60px, 8vw, 100px) 0',
          background: '#040711',
          borderBottom: '1px solid rgba(255, 255, 255, 0.06)',
        }}
      >
        <div className="container">
          <div style={{ textAlign: 'center', maxWidth: '760px', margin: '0 auto 48px' }}>
            <div
              style={{
                fontSize: '12px',
                fontFamily: 'var(--font-mono)',
                color: '#3b82f6',
                letterSpacing: '0.08em',
                textTransform: 'uppercase',
                marginBottom: '10px',
                fontWeight: 600,
              }}
            >
              [ THE CORE DETECTION THESIS ]
            </div>
            <h2
              style={{
                fontFamily: 'var(--font-display)',
                fontSize: 'clamp(28px, 4vw, 44px)',
                fontWeight: 700,
                color: '#ffffff',
                letterSpacing: '-0.02em',
                marginBottom: '14px',
              }}
            >
              Same spike. Different conclusion.
            </h2>
            <p style={{ color: '#94a3b8', fontSize: '16px', lineHeight: 1.65 }}>
              A naive detector sees only "transaction volume is 10× above normal" and blocks traffic indiscriminately. Veyra looks underneath the volume to separate organic sales from malicious rings.
            </p>

            {/* Interactive Story Toggle */}
            <div
              style={{
                display: 'inline-flex',
                gap: '8px',
                padding: '6px',
                borderRadius: '8px',
                background: 'rgba(255, 255, 255, 0.04)',
                border: '1px solid rgba(255, 255, 255, 0.08)',
                marginTop: '28px',
              }}
            >
              <button
                onClick={() => setActiveStory('flash_sale')}
                style={{
                  padding: '9px 18px',
                  borderRadius: '6px',
                  fontSize: '13px',
                  fontWeight: 600,
                  cursor: 'pointer',
                  border: 'none',
                  background: activeStory === 'flash_sale' ? '#10b981' : 'transparent',
                  color: activeStory === 'flash_sale' ? '#ffffff' : '#94a3b8',
                  transition: 'all 0.15s ease',
                }}
              >
                Scenario A: Legitimate Flash Sale
              </button>
              <button
                onClick={() => setActiveStory('card_testing')}
                style={{
                  padding: '9px 18px',
                  borderRadius: '6px',
                  fontSize: '13px',
                  fontWeight: 600,
                  cursor: 'pointer',
                  border: 'none',
                  background: activeStory === 'card_testing' ? '#f93f28' : 'transparent',
                  color: activeStory === 'card_testing' ? '#ffffff' : '#94a3b8',
                  transition: 'all 0.15s ease',
                }}
              >
                Scenario B: Coordinated Card Testing
              </button>
            </div>
          </div>

          {/* Interactive Contrast Card */}
          <div
            style={{
              maxWidth: '960px',
              margin: '0 auto',
              background: '#080c1a',
              border: `1px solid ${activeStory === 'flash_sale' ? 'rgba(16, 185, 129, 0.3)' : 'rgba(249, 63, 40, 0.3)'}`,
              borderRadius: '16px',
              padding: 'clamp(28px, 4vw, 44px)',
              boxShadow: '0 20px 50px rgba(0, 0, 0, 0.5)',
              transition: 'border-color 0.3s ease',
            }}
          >
            {activeStory === 'flash_sale' ? (
              <div>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '20px', flexWrap: 'wrap', gap: '12px' }}>
                  <div>
                    <span style={{ fontSize: '11px', fontFamily: 'var(--font-mono)', color: '#10b981', fontWeight: 700, letterSpacing: '0.08em' }}>
                      [ HARD NEGATIVE // BENIGN VOLUME SURGE ]
                    </span>
                    <h3 style={{ fontFamily: 'var(--font-display)', fontSize: '24px', fontWeight: 700, marginTop: '4px' }}>
                      Midnight Marketing Drop
                    </h3>
                  </div>
                  <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                    <span style={{ fontSize: '12px', color: '#94a3b8' }}>Naive Detector:</span>
                    <span style={{ fontSize: '12px', padding: '4px 8px', borderRadius: '4px', background: 'rgba(239, 68, 68, 0.15)', color: '#ef4444', fontWeight: 600 }}>
                      FALSE ALARM (BLOCKED)
                    </span>
                    <span style={{ fontSize: '12px', color: '#94a3b8', marginLeft: '8px' }}>Veyra:</span>
                    <span style={{ fontSize: '12px', padding: '4px 8px', borderRadius: '4px', background: 'rgba(16, 185, 129, 0.15)', color: '#10b981', fontWeight: 600 }}>
                      TIER OBSERVE (PASSED)
                    </span>
                  </div>
                </div>

                <p style={{ color: '#cbd5e1', fontSize: '15px', lineHeight: 1.65, marginBottom: '28px' }}>
                  A surge of 500 orders arrives in 2 minutes following an influencer campaign. Volume is 12× normal baseline, but Veyra looks at underlying dimensions:
                </p>

                <div
                  style={{
                    display: 'grid',
                    gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))',
                    gap: '16px',
                    marginBottom: '32px',
                  }}
                >
                  <div style={{ padding: '16px', borderRadius: '8px', background: 'rgba(255, 255, 255, 0.03)', border: '1px solid rgba(255, 255, 255, 0.06)' }}>
                    <div style={{ fontSize: '11px', color: '#64748b', textTransform: 'uppercase' }}>Entity Diversity</div>
                    <div style={{ fontSize: '16px', fontWeight: 700, color: '#ffffff', marginTop: '4px' }}>482 Unique Devices</div>
                    <div style={{ fontSize: '12px', color: '#10b981', marginTop: '2px' }}>Gini concentration &lt; 0.18</div>
                  </div>

                  <div style={{ padding: '16px', borderRadius: '8px', background: 'rgba(255, 255, 255, 0.03)', border: '1px solid rgba(255, 255, 255, 0.06)' }}>
                    <div style={{ fontSize: '11px', color: '#64748b', textTransform: 'uppercase' }}>Failure Rate</div>
                    <div style={{ fontSize: '16px', fontWeight: 700, color: '#ffffff', marginTop: '4px' }}>4.2% Decline Rate</div>
                    <div style={{ fontSize: '12px', color: '#10b981', marginTop: '2px' }}>Normal bank response codes</div>
                  </div>

                  <div style={{ padding: '16px', borderRadius: '8px', background: 'rgba(255, 255, 255, 0.03)', border: '1px solid rgba(255, 255, 255, 0.06)' }}>
                    <div style={{ fontSize: '11px', color: '#64748b', textTransform: 'uppercase' }}>Amount Dispersion</div>
                    <div style={{ fontSize: '16px', fontWeight: 700, color: '#ffffff', marginTop: '4px' }}>High Amount Entropy</div>
                    <div style={{ fontSize: '12px', color: '#10b981', marginTop: '2px' }}>Varied organic carts (₹499–₹3,200)</div>
                  </div>
                </div>

                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: '16px', borderTop: '1px solid rgba(255, 255, 255, 0.06)', paddingTop: '20px' }}>
                  <span style={{ fontSize: '13px', color: '#94a3b8' }}>
                    Outcome: 0% false declines on real customers during critical revenue hours.
                  </span>
                  <button
                    onClick={() => onRunScenario('flash_sale_spike')}
                    style={{
                      background: 'transparent',
                      border: '1px solid #10b981',
                      color: '#10b981',
                      padding: '10px 18px',
                      borderRadius: '6px',
                      fontSize: '13px',
                      fontWeight: 600,
                      cursor: 'pointer',
                      display: 'inline-flex',
                      alignItems: 'center',
                      gap: '6px',
                    }}
                  >
                    Run Flash Sale in Console <ArrowRight size={14} />
                  </button>
                </div>
              </div>
            ) : (
              <div>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '20px', flexWrap: 'wrap', gap: '12px' }}>
                  <div>
                    <span style={{ fontSize: '11px', fontFamily: 'var(--font-mono)', color: '#f93f28', fontWeight: 700, letterSpacing: '0.08em' }}>
                      [ ATTACK // COORDINATED CARD TESTING ]
                    </span>
                    <h3 style={{ fontFamily: 'var(--font-display)', fontSize: '24px', fontWeight: 700, marginTop: '4px' }}>
                      Distributed Bot Card Testing
                    </h3>
                  </div>
                  <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                    <span style={{ fontSize: '12px', color: '#94a3b8' }}>Naive Single Rule:</span>
                    <span style={{ fontSize: '12px', padding: '4px 8px', borderRadius: '4px', background: 'rgba(16, 185, 129, 0.15)', color: '#10b981', fontWeight: 600 }}>
                      ₹15 PASS-THROUGH
                    </span>
                    <span style={{ fontSize: '12px', color: '#94a3b8', marginLeft: '8px' }}>Veyra:</span>
                    <span style={{ fontSize: '12px', padding: '4px 8px', borderRadius: '4px', background: 'rgba(239, 68, 68, 0.15)', color: '#f93f28', fontWeight: 600 }}>
                      TIER RESTRICT (FLAGGED)
                    </span>
                  </div>
                </div>

                <p style={{ color: '#cbd5e1', fontSize: '15px', lineHeight: 1.65, marginBottom: '28px' }}>
                  An automated botnet tests 500 stolen card numbers through rotating proxy IPs with ₹15 authorization requests. Volume matches the flash sale, but structure reveals the syndicate:
                </p>

                <div
                  style={{
                    display: 'grid',
                    gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))',
                    gap: '16px',
                    marginBottom: '32px',
                  }}
                >
                  <div style={{ padding: '16px', borderRadius: '8px', background: 'rgba(255, 255, 255, 0.03)', border: '1px solid rgba(255, 255, 255, 0.06)' }}>
                    <div style={{ fontSize: '11px', color: '#64748b', textTransform: 'uppercase' }}>Entity Clustering</div>
                    <div style={{ fontSize: '16px', fontWeight: 700, color: '#ffffff', marginTop: '4px' }}>11 Device Fingerprints</div>
                    <div style={{ fontSize: '12px', color: '#f93f28', marginTop: '2px' }}>Gini concentration &gt; 0.88</div>
                  </div>

                  <div style={{ padding: '16px', borderRadius: '8px', background: 'rgba(255, 255, 255, 0.03)', border: '1px solid rgba(255, 255, 255, 0.06)' }}>
                    <div style={{ fontSize: '11px', color: '#64748b', textTransform: 'uppercase' }}>Failure Pattern</div>
                    <div style={{ fontSize: '16px', fontWeight: 700, color: '#ffffff', marginTop: '4px' }}>84.6% Decline Rate</div>
                    <div style={{ fontSize: '12px', color: '#f93f28', marginTop: '2px' }}>Shannon entropy spikes</div>
                  </div>

                  <div style={{ padding: '16px', borderRadius: '8px', background: 'rgba(255, 255, 255, 0.03)', border: '1px solid rgba(255, 255, 255, 0.06)' }}>
                    <div style={{ fontSize: '11px', color: '#64748b', textTransform: 'uppercase' }}>Amount Dispersion</div>
                    <div style={{ fontSize: '16px', fontWeight: 700, color: '#ffffff', marginTop: '4px' }}>Fixed ₹15 Micro-Attempts</div>
                    <div style={{ fontSize: '12px', color: '#f93f28', marginTop: '2px' }}>Near-zero amount entropy</div>
                  </div>
                </div>

                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: '16px', borderTop: '1px solid rgba(255, 255, 255, 0.06)', paddingTop: '20px' }}>
                  <span style={{ fontSize: '13px', color: '#94a3b8' }}>
                    Outcome: Coordinated attack isolated and restricted before gateway auth fee fines accrue.
                  </span>
                  <button
                    onClick={() => onRunScenario('card_testing_burst')}
                    style={{
                      background: 'transparent',
                      border: '1px solid #f93f28',
                      color: '#f93f28',
                      padding: '10px 18px',
                      borderRadius: '6px',
                      fontSize: '13px',
                      fontWeight: 600,
                      cursor: 'pointer',
                      display: 'inline-flex',
                      alignItems: 'center',
                      gap: '6px',
                    }}
                  >
                    Run Card Testing in Console <ArrowRight size={14} />
                  </button>
                </div>
              </div>
            )}
          </div>
        </div>
      </section>

      {/* -------------------------------------------------------------
          WHAT VEYRA DOES: The 3 Core Architectural Layers
      -------------------------------------------------------------- */}
      <section
        style={{
          padding: 'clamp(60px, 8vw, 100px) 0',
          borderBottom: '1px solid rgba(255, 255, 255, 0.06)',
          background: '#060913',
        }}
      >
        <div className="container">
          <div style={{ textAlign: 'center', maxWidth: '720px', margin: '0 auto 56px' }}>
            <div
              style={{
                fontSize: '12px',
                fontFamily: 'var(--font-mono)',
                color: '#3b82f6',
                letterSpacing: '0.08em',
                textTransform: 'uppercase',
                marginBottom: '10px',
                fontWeight: 600,
              }}
            >
              [ DETECTION ARCHITECTURE ]
            </div>
            <h2
              style={{
                fontFamily: 'var(--font-display)',
                fontSize: 'clamp(28px, 4vw, 44px)',
                fontWeight: 700,
                color: '#ffffff',
                letterSpacing: '-0.02em',
                marginBottom: '14px',
              }}
            >
              How Veyra detects coordination
            </h2>
            <p style={{ color: '#94a3b8', fontSize: '16px', lineHeight: 1.65 }}>
              Instead of relying solely on single-payment threshold checks, Veyra evaluates three orthogonal dimensions across rolling temporal horizons.
            </p>
          </div>

          {/* 3 Architectural Cards */}
          <div
            style={{
              display: 'grid',
              gridTemplateColumns: 'repeat(auto-fit, minmax(300px, 1fr))',
              gap: '24px',
            }}
          >
            {/* Layer 1 */}
            <div
              style={{
                background: '#090d1c',
                border: '1px solid rgba(255, 255, 255, 0.08)',
                borderRadius: '12px',
                padding: '32px 28px',
                display: 'flex',
                flexDirection: 'column',
                justifyContent: 'space-between',
              }}
            >
              <div>
                <div
                  style={{
                    width: '42px',
                    height: '42px',
                    borderRadius: '8px',
                    background: 'rgba(37, 99, 235, 0.12)',
                    border: '1px solid rgba(37, 99, 235, 0.3)',
                    display: 'grid',
                    placeItems: 'center',
                    marginBottom: '20px',
                    color: '#60a5fa',
                  }}
                >
                  <Layers size={20} />
                </div>
                <div style={{ fontSize: '11px', fontFamily: 'var(--font-mono)', color: '#64748b', marginBottom: '6px', fontWeight: 600 }}>
                  [ LAYER 01 // HORIZONS ]
                </div>
                <h3 style={{ fontFamily: 'var(--font-display)', fontSize: '20px', fontWeight: 700, color: '#ffffff', marginBottom: '10px' }}>
                  Multi-Horizon Feature Engine
                </h3>
                <p style={{ color: '#94a3b8', fontSize: '15px', lineHeight: 1.65 }}>
                  Aggregates transaction velocity, decline entropy, and instrument novelty across 1m, 5m, 15m, and 1h rolling windows in single-pass vector computations.
                </p>
              </div>
              <div style={{ marginTop: '24px', paddingTop: '16px', borderTop: '1px solid rgba(255, 255, 255, 0.06)', fontSize: '12px', fontFamily: 'var(--font-mono)', color: '#3b82f6' }}>
                79 METRICS // STRICT PAST-ONLY GRID
              </div>
            </div>

            {/* Layer 2 */}
            <div
              style={{
                background: '#090d1c',
                border: '1px solid rgba(255, 255, 255, 0.08)',
                borderRadius: '12px',
                padding: '32px 28px',
                display: 'flex',
                flexDirection: 'column',
                justifyContent: 'space-between',
              }}
            >
              <div>
                <div
                  style={{
                    width: '42px',
                    height: '42px',
                    borderRadius: '8px',
                    background: 'rgba(249, 63, 40, 0.12)',
                    border: '1px solid rgba(249, 63, 40, 0.3)',
                    display: 'grid',
                    placeItems: 'center',
                    marginBottom: '20px',
                    color: '#f93f28',
                  }}
                >
                  <Clock size={20} />
                </div>
                <div style={{ fontSize: '11px', fontFamily: 'var(--font-mono)', color: '#64748b', marginBottom: '6px', fontWeight: 600 }}>
                  [ LAYER 02 // ROBUST BASELINES ]
                </div>
                <h3 style={{ fontFamily: 'var(--font-display)', fontSize: '20px', fontWeight: 700, color: '#ffffff', marginBottom: '10px' }}>
                  168-Hour Seasonal MAD Baselines
                </h3>
                <p style={{ color: '#94a3b8', fontSize: '15px', lineHeight: 1.65 }}>
                  Measures deviation in Median Absolute Deviation units for each hour-of-the-week slot, resisting baseline poisoning from prior attack bursts.
                </p>
              </div>
              <div style={{ marginTop: '24px', paddingTop: '16px', borderTop: '1px solid rgba(255, 255, 255, 0.06)', fontSize: '12px', fontFamily: 'var(--font-mono)', color: '#f93f28' }}>
                50% BREAKDOWN POINT RESILIENCE
              </div>
            </div>

            {/* Layer 3 */}
            <div
              style={{
                background: '#090d1c',
                border: '1px solid rgba(255, 255, 255, 0.08)',
                borderRadius: '12px',
                padding: '32px 28px',
                display: 'flex',
                flexDirection: 'column',
                justifyContent: 'space-between',
              }}
            >
              <div>
                <div
                  style={{
                    width: '42px',
                    height: '42px',
                    borderRadius: '8px',
                    background: 'rgba(16, 185, 129, 0.12)',
                    border: '1px solid rgba(16, 185, 129, 0.3)',
                    display: 'grid',
                    placeItems: 'center',
                    marginBottom: '20px',
                    color: '#10b981',
                  }}
                >
                  <Users size={20} />
                </div>
                <div style={{ fontSize: '11px', fontFamily: 'var(--font-mono)', color: '#64748b', marginBottom: '6px', fontWeight: 600 }}>
                  [ LAYER 03 // GRAPH TOPOLOGY ]
                </div>
                <h3 style={{ fontFamily: 'var(--font-display)', fontSize: '20px', fontWeight: 700, color: '#ffffff', marginBottom: '10px' }}>
                  Bipartite Entity Concentration
                </h3>
                <p style={{ color: '#94a3b8', fontSize: '15px', lineHeight: 1.65 }}>
                  Builds window-local bipartite graphs across Customer, Device, Instrument, and IP nodes in O(V+E) time to compute degree Gini concentration and isolate rings.
                </p>
              </div>
              <div style={{ marginTop: '24px', paddingTop: '16px', borderTop: '1px solid rgba(255, 255, 255, 0.06)', fontSize: '12px', fontFamily: 'var(--font-mono)', color: '#10b981' }}>
                LINEAR-TIME GRAPH TRAVERSAL
              </div>
            </div>
          </div>
        </div>
      </section>

      {/* -------------------------------------------------------------
          VIDEO SHOWCASE CONTAINER: Defined & Clean Video Section
      -------------------------------------------------------------- */}
      <section
        style={{
          padding: 'clamp(56px, 7vw, 88px) 0',
          background: '#040711',
          borderBottom: '1px solid rgba(255, 255, 255, 0.06)',
        }}
      >
        <div className="container" style={{ maxWidth: '1040px' }}>
          <div style={{ textAlign: 'center', marginBottom: '32px' }}>
            <div
              style={{
                fontSize: '12px',
                fontFamily: 'var(--font-mono)',
                color: '#3b82f6',
                letterSpacing: '0.08em',
                textTransform: 'uppercase',
                marginBottom: '8px',
                fontWeight: 600,
              }}
            >
              [ VIDEO DEMONSTRATION ]
            </div>
            <h2
              style={{
                fontFamily: 'var(--font-display)',
                fontSize: 'clamp(26px, 3.6vw, 38px)',
                fontWeight: 700,
                color: '#ffffff',
                marginBottom: '10px',
              }}
            >
              Product walkthrough & console guide
            </h2>
            <p style={{ color: '#94a3b8', fontSize: '15px' }}>
              A recorded overview explaining the console layout, scenario injection, and forensic evidence generation.
            </p>
          </div>

          <div
            style={{
              position: 'relative',
              borderRadius: '14px',
              padding: '6px',
              background: 'linear-gradient(180deg, rgba(255, 255, 255, 0.1) 0%, rgba(255, 255, 255, 0.02) 100%)',
              boxShadow: '0 20px 60px rgba(0, 0, 0, 0.8)',
            }}
          >
            <div
              style={{
                borderRadius: '10px',
                overflow: 'hidden',
                background: '#0a0e1c',
                border: '1px solid rgba(255, 255, 255, 0.08)',
              }}
            >
              {/* Header Bar */}
              <div
                style={{
                  height: '40px',
                  background: '#080b16',
                  borderBottom: '1px solid rgba(255, 255, 255, 0.06)',
                  padding: '0 16px',
                  display: 'flex',
                  justifyContent: 'space-between',
                  alignItems: 'center',
                }}
              >
                <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                  <span style={{ width: '9px', height: '9px', borderRadius: '50%', background: '#ff5f56' }} />
                  <span style={{ width: '9px', height: '9px', borderRadius: '50%', background: '#ffbd2e' }} />
                  <span style={{ width: '9px', height: '9px', borderRadius: '50%', background: '#27c93f' }} />
                  <span style={{ marginLeft: '10px', fontSize: '11px', fontFamily: 'var(--font-mono)', color: '#64748b' }}>
                    veyra-walkthrough://console-overview
                  </span>
                </div>

                <a
                  href={`https://youtu.be/${WALKTHROUGH_VIDEO_ID}`}
                  target="_blank"
                  rel="noopener noreferrer"
                  style={{
                    background: 'rgba(255, 255, 255, 0.05)',
                    border: '1px solid rgba(255, 255, 255, 0.08)',
                    color: '#94a3b8',
                    padding: '4px 10px',
                    borderRadius: '4px',
                    fontSize: '11px',
                    fontFamily: 'var(--font-mono)',
                    display: 'inline-flex',
                    alignItems: 'center',
                    gap: '6px',
                    textDecoration: 'none',
                    cursor: 'pointer',
                  }}
                >
                  <Video size={12} /> Watch on YouTube ↗
                </a>
              </div>

              {/* 16:9 Video Container — responsive at every breakpoint via the
                  padding-bottom aspect-ratio trick, iframe absolutely filling it. */}
              <div
                style={{
                  position: 'relative',
                  paddingBottom: '56.25%',
                  height: 0,
                  overflow: 'hidden',
                  background: '#000000',
                }}
              >
                <iframe
                  src={`https://www.youtube-nocookie.com/embed/${WALKTHROUGH_VIDEO_ID}?rel=0`}
                  title="Veyra System Walkthrough"
                  allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture; web-share"
                  allowFullScreen
                  loading="lazy"
                  style={{
                    position: 'absolute',
                    top: 0,
                    left: 0,
                    width: '100%',
                    height: '100%',
                    border: 'none',
                  }}
                />
              </div>
            </div>
          </div>
        </div>
      </section>

      {/* -------------------------------------------------------------
          WHO VEYRA IS BUILT FOR: Tabbed Role Breakdown
      -------------------------------------------------------------- */}
      <section
        style={{
          padding: 'clamp(60px, 8vw, 100px) 0',
          borderBottom: '1px solid rgba(255, 255, 255, 0.06)',
          background: '#060913',
        }}
      >
        <div className="container">
          <div style={{ textAlign: 'center', maxWidth: '720px', margin: '0 auto 40px' }}>
            <div
              style={{
                fontSize: '12px',
                fontFamily: 'var(--font-mono)',
                color: '#f93f28',
                letterSpacing: '0.08em',
                textTransform: 'uppercase',
                marginBottom: '10px',
                fontWeight: 600,
              }}
            >
              [ ROLES & STAKEHOLDERS ]
            </div>
            <h2
              style={{
                fontFamily: 'var(--font-display)',
                fontSize: 'clamp(28px, 4vw, 44px)',
                fontWeight: 700,
                color: '#ffffff',
                letterSpacing: '-0.02em',
                marginBottom: '14px',
              }}
            >
              Who Veyra is built for
            </h2>
            <p style={{ color: '#94a3b8', fontSize: '16px', lineHeight: 1.65 }}>
              Tailored risk intelligence for gateway operators, high-growth e-commerce, and agentic commerce workflows.
            </p>
          </div>

          {/* Tab buttons */}
          <div
            style={{
              display: 'flex',
              justifyContent: 'center',
              gap: '8px',
              flexWrap: 'wrap',
              marginBottom: '36px',
            }}
          >
            {audienceTabs.map((tab, idx) => (
              <button
                key={tab.id}
                onClick={() => setActiveAudienceTab(idx)}
                style={{
                  padding: '9px 18px',
                  borderRadius: '6px',
                  fontSize: '13px',
                  fontWeight: 600,
                  border:
                    activeAudienceTab === idx
                      ? '1px solid #f93f28'
                      : '1px solid rgba(255, 255, 255, 0.08)',
                  background:
                    activeAudienceTab === idx
                      ? 'rgba(249, 63, 40, 0.12)'
                      : 'rgba(255, 255, 255, 0.03)',
                  color: activeAudienceTab === idx ? '#ffffff' : '#94a3b8',
                  transition: 'all 0.15s ease',
                  cursor: 'pointer',
                }}
              >
                {tab.title}
              </button>
            ))}
          </div>

          {/* Tab content card */}
          {(() => {
            const current = audienceTabs[activeAudienceTab];
            return (
              <div
                style={{
                  maxWidth: '1040px',
                  margin: '0 auto',
                  background: '#090d1c',
                  border: '1px solid rgba(255, 255, 255, 0.1)',
                  borderRadius: '16px',
                  padding: 'clamp(28px, 4vw, 48px)',
                  display: 'grid',
                  gridTemplateColumns: 'repeat(auto-fit, minmax(300px, 1fr))',
                  gap: '36px',
                  alignItems: 'center',
                }}
              >
                <div>
                  <div style={{ fontSize: '11px', fontFamily: 'var(--font-mono)', color: '#f93f28', fontWeight: 700, letterSpacing: '0.08em', marginBottom: '10px' }}>
                    [ {current.badge} ]
                  </div>
                  <h3 style={{ fontFamily: 'var(--font-display)', fontSize: 'clamp(22px, 2.4vw, 30px)', fontWeight: 700, color: '#ffffff', marginBottom: '14px', lineHeight: 1.25 }}>
                    {current.headline}
                  </h3>
                  <p style={{ color: '#94a3b8', fontSize: '15px', lineHeight: 1.65, marginBottom: '24px' }}>
                    {current.description}
                  </p>

                  <div style={{ display: 'grid', gap: '10px', marginBottom: '28px' }}>
                    {current.features.map((feat, fIdx) => (
                      <div key={fIdx} style={{ display: 'flex', alignItems: 'flex-start', gap: '10px', fontSize: '13px', color: '#cbd5e1' }}>
                        <CheckCircle2 size={15} color="#10b981" style={{ flexShrink: 0, marginTop: '2px' }} />
                        <span>{feat}</span>
                      </div>
                    ))}
                  </div>

                  <button
                    onClick={() => onRunScenario(current.scenarioId)}
                    style={{
                      background: '#f93f28',
                      border: 'none',
                      color: '#ffffff',
                      padding: '11px 22px',
                      borderRadius: '6px',
                      fontSize: '13px',
                      fontWeight: 700,
                      display: 'inline-flex',
                      alignItems: 'center',
                      gap: '8px',
                      cursor: 'pointer',
                    }}
                  >
                    {current.ctaText} <ArrowRight size={14} />
                  </button>
                </div>

                {/* Stat Box */}
                <div
                  style={{
                    background: '#040711',
                    border: '1px solid rgba(255, 255, 255, 0.08)',
                    borderRadius: '12px',
                    padding: '36px',
                    textAlign: 'center',
                  }}
                >
                  <div style={{ fontSize: '28px', fontWeight: 800, color: '#10b981', fontFamily: 'var(--font-mono)', marginBottom: '8px' }}>
                    {current.metricVal}
                  </div>
                  <div style={{ fontSize: '13px', color: '#ffffff', fontWeight: 700, textTransform: 'uppercase', letterSpacing: '0.04em', marginBottom: '8px' }}>
                    {current.metricLabel}
                  </div>
                  <p style={{ color: '#64748b', fontSize: '13px', maxWidth: '280px', margin: '0 auto', lineHeight: 1.5 }}>
                    Evaluated against synthetic multi-merchant scenarios.
                  </p>
                </div>
              </div>
            );
          })()}
        </div>
      </section>

      {/* -------------------------------------------------------------
          FREQUENT QUESTIONS (FAQ ACCORDION)
      -------------------------------------------------------------- */}
      <section
        style={{
          padding: 'clamp(60px, 8vw, 100px) 0',
          borderBottom: '1px solid rgba(255, 255, 255, 0.06)',
          background: '#040711',
        }}
      >
        <div className="container" style={{ maxWidth: '840px' }}>
          <div style={{ textAlign: 'center', marginBottom: '48px' }}>
            <div
              style={{
                fontSize: '12px',
                fontFamily: 'var(--font-mono)',
                color: '#3b82f6',
                letterSpacing: '0.08em',
                textTransform: 'uppercase',
                marginBottom: '10px',
                fontWeight: 600,
              }}
            >
              [ ARCHITECTURAL FAQ ]
            </div>
            <h2
              style={{
                fontFamily: 'var(--font-display)',
                fontSize: 'clamp(28px, 4vw, 42px)',
                fontWeight: 700,
                color: '#ffffff',
                letterSpacing: '-0.02em',
              }}
            >
              Frequently asked questions
            </h2>
          </div>

          <div style={{ display: 'grid', gap: '12px' }}>
            {faqs.map((faq, idx) => {
              const isOpen = openFaq === idx;
              return (
                <div
                  key={idx}
                  style={{
                    background: '#090d1c',
                    border: '1px solid rgba(255, 255, 255, 0.08)',
                    borderRadius: '8px',
                    overflow: 'hidden',
                  }}
                >
                  <button
                    onClick={() => setOpenFaq(isOpen ? null : idx)}
                    style={{
                      width: '100%',
                      padding: '18px 22px',
                      background: 'transparent',
                      border: 'none',
                      display: 'flex',
                      justifyContent: 'space-between',
                      alignItems: 'center',
                      textAlign: 'left',
                      color: '#ffffff',
                      fontSize: '15px',
                      fontWeight: 700,
                      cursor: 'pointer',
                    }}
                  >
                    <span>{faq.q}</span>
                    <span
                      style={{
                        fontSize: '18px',
                        color: '#94a3b8',
                        transform: isOpen ? 'rotate(180deg)' : 'none',
                        transition: 'transform 0.2s ease',
                      }}
                    >
                      ↓
                    </span>
                  </button>

                  {isOpen && (
                    <div
                      style={{
                        padding: '0 22px 22px',
                        fontSize: '14px',
                        lineHeight: 1.7,
                        color: '#94a3b8',
                        borderTop: '1px solid rgba(255, 255, 255, 0.04)',
                        paddingTop: '14px',
                      }}
                    >
                      {faq.a}
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        </div>
      </section>

      {/* -------------------------------------------------------------
          BOTTOM CTA & REALITY DISCLAIMER
      -------------------------------------------------------------- */}
      <section
        style={{
          padding: 'clamp(64px, 8vw, 100px) 0',
          background:
            'radial-gradient(ellipse 60% 40% at 50% 100%, rgba(30, 58, 138, 0.25) 0%, rgba(6, 9, 19, 1) 100%)',
          textAlign: 'center',
        }}
      >
        <div className="container" style={{ maxWidth: '720px' }}>
          <h2
            style={{
              fontFamily: 'var(--font-display)',
              fontSize: 'clamp(28px, 4.4vw, 46px)',
              fontWeight: 700,
              color: '#ffffff',
              letterSpacing: '-0.02em',
              marginBottom: '14px',
            }}
          >
            Ready to explore the detection pipeline?
          </h2>
          <p style={{ color: '#94a3b8', fontSize: '16px', lineHeight: 1.65, marginBottom: '32px' }}>
            Run live scenario simulations in the Detection Console or stress test burst throughput in the Performance Lab.
          </p>

          <div style={{ display: 'flex', justifyContent: 'center', gap: '14px', flexWrap: 'wrap', marginBottom: '40px' }}>
            <button
              onClick={() => onNavigate('detection')}
              style={{
                background: '#f93f28',
                border: 'none',
                color: '#ffffff',
                padding: '13px 28px',
                borderRadius: '8px',
                fontSize: '14px',
                fontWeight: 700,
                cursor: 'pointer',
                display: 'inline-flex',
                alignItems: 'center',
                gap: '8px',
                boxShadow: '0 4px 20px rgba(249, 63, 40, 0.35)',
              }}
            >
              Launch Detection Console <ArrowRight size={15} />
            </button>

            <button
              onClick={() => onNavigate('architecture')}
              style={{
                background: 'rgba(255, 255, 255, 0.05)',
                border: '1px solid rgba(255, 255, 255, 0.14)',
                color: '#ffffff',
                padding: '13px 24px',
                borderRadius: '8px',
                fontSize: '14px',
                fontWeight: 600,
                cursor: 'pointer',
              }}
            >
              View 7-Stage Architecture
            </button>
          </div>

          <div
            style={{
              fontSize: '12px',
              color: '#64748b',
              lineHeight: 1.6,
              maxWidth: '580px',
              margin: '0 auto',
            }}
          >
            Disclaimer: Veyra is a research prototype evaluated on controlled synthetic data. It holds no official PCI-DSS, SOC 2, or card network certification.
          </div>
        </div>
      </section>
    </div>
  );
}
