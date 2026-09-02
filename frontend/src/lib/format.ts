/** Presentation formatting. Every number the user sees goes through here.
 *
 * Two jobs: locale-aware output, and never rendering NaN / undefined / null /
 * Infinity / floating-point artifacts. Backend money fields arrive as Decimal
 * strings ("1824.19"); parsing them here — once — is what keeps
 * `₹8243.14000000001` off the screen.
 */

const EM_DASH = '—';

/** Coerce anything the API might hand us into a finite number, or null. */
export function toNumber(value: unknown): number | null {
  if (value === null || value === undefined || value === '') return null;
  const n = typeof value === 'number' ? value : Number(value);
  return Number.isFinite(n) ? n : null;
}

export function formatMoney(value: unknown, currency = 'INR'): string {
  const n = toNumber(value);
  if (n === null) return EM_DASH;
  return new Intl.NumberFormat('en-IN', {
    style: 'currency',
    currency,
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  }).format(n);
}

/** Compact money for tight spaces: ₹61.7K, ₹1.2Cr. */
export function formatMoneyCompact(value: unknown, currency = 'INR'): string {
  const n = toNumber(value);
  if (n === null) return EM_DASH;
  return new Intl.NumberFormat('en-IN', {
    style: 'currency',
    currency,
    notation: 'compact',
    maximumFractionDigits: 1,
  }).format(n);
}

/** `fraction` is 0..1 as the backend emits it. */
export function formatPercent(fraction: unknown, digits = 1): string {
  const n = toNumber(fraction);
  if (n === null) return EM_DASH;
  return `${(n * 100).toFixed(digits)}%`;
}

export function formatCount(value: unknown): string {
  const n = toNumber(value);
  if (n === null) return EM_DASH;
  return new Intl.NumberFormat('en-IN').format(n);
}

export function formatLatency(ms: unknown): string {
  const n = toNumber(ms);
  if (n === null) return EM_DASH;
  if (n >= 1000) return `${(n / 1000).toFixed(2)} s`;
  return `${n.toFixed(2)} ms`;
}

export function formatTps(value: unknown): string {
  const n = toNumber(value);
  if (n === null) return EM_DASH;
  return `${new Intl.NumberFormat('en-IN', { maximumFractionDigits: 0 }).format(n)} TPS`;
}

/** Signed MAD distance, e.g. "+10.6 MAD". */
export function formatMad(value: unknown, digits = 1): string {
  const n = toNumber(value);
  if (n === null) return EM_DASH;
  const sign = n > 0 ? '+' : '';
  return `${sign}${n.toFixed(digits)} MAD`;
}

export function formatNumber(value: unknown, digits = 2): string {
  const n = toNumber(value);
  if (n === null) return EM_DASH;
  return n.toFixed(digits);
}

/** Local human time; UTC is exposed separately in technical details. */
export function formatTimestamp(iso: unknown): string {
  if (typeof iso !== 'string' || !iso) return EM_DASH;
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return EM_DASH;
  return d.toLocaleString(undefined, {
    year: 'numeric',
    month: 'short',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
  });
}

export function formatTimestampUtc(iso: unknown): string {
  if (typeof iso !== 'string' || !iso) return EM_DASH;
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return EM_DASH;
  return `${d.toISOString().replace('T', ' ').replace(/\.\d+Z$/, '')} UTC`;
}

export const WINDOW_LABELS: Record<string, string> = {
  '1m': '1 minute',
  '5m': '5 minutes',
  '15m': '15 minutes',
  '1h': '1 hour',
};

export function windowLabel(size: string | undefined | null): string {
  if (!size) return EM_DASH;
  return WINDOW_LABELS[size] ?? size;
}

/** Turn a backend feature id (`C.failure_rate`) into readable English. */
export function humanizeFeatureId(featureId: string): string {
  const withoutFamily = featureId.replace(/^[A-J]\./, '');
  const isDeviation = withoutFamily.endsWith('_dev');
  const base = isDeviation ? withoutFamily.slice(0, -4) : withoutFamily;
  const words = base
    .split('_')
    .map((w) => (w === 'gmv' ? 'GMV' : w === 'cv' ? 'variability' : w === 'ip' ? 'IP' : w))
    .join(' ');
  const sentence = words.charAt(0).toUpperCase() + words.slice(1);
  return isDeviation ? `${sentence} (vs baseline)` : sentence;
}

/** Backend control identifiers → sentence case. */
export function humanizeControl(control: string | null | undefined): string {
  if (!control) return 'No control recommended';
  return control
    .replace(/^RECOMMEND_/, '')
    .toLowerCase()
    .split('_')
    .join(' ')
    .replace(/^\w/, (c) => c.toUpperCase());
}

export { EM_DASH };
