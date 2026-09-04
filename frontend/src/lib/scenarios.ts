/** Human explanations for the scenarios the backend actually supports.
 *
 * Keyed by the `scenario_id` values returned from GET /v2/demo/scenarios. The
 * backend supplies ids, display names and an is_attack flag; it does not supply
 * plain-English descriptions, so they live here. Unknown ids fall back to the
 * backend's own name rather than breaking the UI, so adding a scenario server-side
 * degrades gracefully instead of crashing the picker.
 */

import type { ActionTier } from '../api/types';

export interface ScenarioCopy {
  /** One sentence a non-specialist can read. */
  summary: string;
  /** What separates it from its look-alike — the core product thesis in one line. */
  discriminator?: string;
}

export const SCENARIO_COPY: Record<string, ScenarioCopy> = {
  card_testing_burst: {
    summary: 'Many small authorization attempts probe stolen payment credentials.',
    discriminator: 'Looks like a sales spike by volume, but most attempts decline and few devices are involved.',
  },
  card_testing_low_value: {
    summary: 'Card testing hidden in very small amounts to stay under value checks.',
    discriminator: 'Amounts sit far below the merchant’s normal basket while decline rates stay high.',
  },
  bin_enumeration_attack: {
    summary: 'An attacker walks through a card number range to find live cards.',
    discriminator: 'Payment instruments cluster into one issuer range instead of the usual spread.',
  },
  device_farm_ring: {
    summary: 'Many fresh accounts transact from a small pool of devices.',
    discriminator: 'Account count rises but device count does not follow it.',
  },
  promo_coupon_harvesting: {
    summary: 'Automated signups drain a promotional discount.',
    discriminator: 'New accounts concentrate on one coupon at a narrow price point.',
  },
  ring_under_flash_sale: {
    summary: 'A coordinated ring operating underneath a genuine sale surge.',
    discriminator: 'The hardest case: real customers and an attack share the same window.',
  },
  slow_ramp_infiltration: {
    summary: 'Attack volume grows gradually to avoid tripping velocity thresholds.',
    discriminator: 'No sudden spike at all — visible only against a longer horizon.',
  },
  low_volume_relationship_anomaly: {
    summary: 'A small number of transactions sharing suspicious entity relationships.',
    discriminator: 'Volume never rises, so only the relationship structure gives it away.',
  },
  flash_sale_spike: {
    summary: 'A legitimate traffic surge that should not be mistaken for fraud.',
    discriminator: 'High volume from many independent buyers, with normal decline rates.',
  },
  gateway_retry_storm: {
    summary: 'A payment gateway problem causes customers to retry, inflating attempts.',
    discriminator: 'Failure rates look alarming, but each retry belongs to its own customer and device.',
  },
  subscription_renewal_batch: {
    summary: 'Scheduled recurring payments run together as a batch.',
    discriminator: 'A burst of activity on cards the merchant has legitimately seen before.',
  },
};

export function scenarioSummary(scenarioId: string, fallbackName: string): string {
  return SCENARIO_COPY[scenarioId]?.summary ?? `Scenario: ${fallbackName}.`;
}

export function scenarioDiscriminator(scenarioId: string): string | undefined {
  return SCENARIO_COPY[scenarioId]?.discriminator;
}

/** Merchant categories accepted by the demo endpoints. */
export const MERCHANT_CATEGORIES = [
  { value: 'electronics', label: 'Electronics' },
  { value: 'fashion_retail', label: 'Fashion & retail' },
  { value: 'grocery_qcommerce', label: 'Grocery / q-commerce' },
  { value: 'digital_services', label: 'Digital services' },
  { value: 'gaming_entertainment', label: 'Gaming & entertainment' },
  { value: 'travel_hospitality', label: 'Travel & hospitality' },
] as const;

export const WINDOW_OPTIONS = [
  { value: '1m', label: '1 minute', hint: 'Catches sharp, fast bursts.' },
  { value: '5m', label: '5 minutes', hint: 'Balanced default for most attacks.' },
  { value: '15m', label: '15 minutes', hint: 'Surfaces slower, paced activity.' },
  { value: '1h', label: '1 hour', hint: 'Reveals gradual ramps that hide from short windows.' },
] as const;

/** Decision tiers, in the order the policy escalates through them (ADR-006). */
export const TIER_ORDER: ActionTier[] = ['OBSERVE', 'ALERT', 'REVIEW', 'RESTRICT'];

export const TIER_COPY: Record<ActionTier, { label: string; meaning: string }> = {
  OBSERVE: { label: 'Observe', meaning: 'Recorded for context. No action suggested.' },
  ALERT: { label: 'Alert', meaning: 'Worth a look. Surfaced on the merchant dashboard.' },
  REVIEW: { label: 'Review', meaning: 'Queued for a human analyst to judge.' },
  RESTRICT: { label: 'Restrict', meaning: 'Recommends adding friction — never an automatic block.' },
};

export function tierColorVar(tier: string): string {
  switch (tier) {
    case 'OBSERVE':
      return 'var(--tier-observe)';
    case 'ALERT':
      return 'var(--tier-alert)';
    case 'REVIEW':
      return 'var(--tier-review)';
    case 'RESTRICT':
      return 'var(--tier-restrict)';
    default:
      return 'var(--text-secondary)';
  }
}

export function tierWashVar(tier: string): string {
  switch (tier) {
    case 'OBSERVE':
      return 'var(--tier-observe-wash)';
    case 'ALERT':
      return 'var(--tier-alert-wash)';
    case 'REVIEW':
      return 'var(--tier-review-wash)';
    case 'RESTRICT':
      return 'var(--tier-restrict-wash)';
    default:
      return 'rgba(255,255,255,0.06)';
  }
}

/** Plain-language headline for a score, so the verdict reads before the number. */
export function riskHeadline(tier: string): string {
  switch (tier) {
    case 'RESTRICT':
      return 'Coordinated payment anomaly detected';
    case 'REVIEW':
      return 'Suspicious activity — analyst review recommended';
    case 'ALERT':
      return 'Unusual activity worth watching';
    case 'OBSERVE':
      return 'Consistent with legitimate traffic';
    default:
      return 'Assessment complete';
  }
}

export function riskLabel(tier: string): string {
  switch (tier) {
    case 'RESTRICT':
      return 'High risk';
    case 'REVIEW':
      return 'Elevated risk';
    case 'ALERT':
      return 'Moderate risk';
    case 'OBSERVE':
      return 'Low risk';
    default:
      return 'Unknown';
  }
}

export function humanizeControl(control: string | null | undefined): string {
  if (!control) return 'No defensive friction needed';
  return control
    .replace(/^RECOMMEND_/, '')
    .replace(/_/g, ' ')
    .toLowerCase()
    .replace(/^\w/, (c) => c.toUpperCase());
}

export function windowLabel(windowSize: string): string {
  switch (windowSize) {
    case '1m':
      return '1 minute';
    case '5m':
      return '5 minutes';
    case '15m':
      return '15 minutes';
    case '1h':
      return '1 hour';
    default:
      return windowSize;
  }
}

