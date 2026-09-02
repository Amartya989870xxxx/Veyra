/** The single place the frontend talks to the Veyra API.
 *
 * Every backend call in the app goes through here. No component issues its own
 * fetch, and there is no mock/offline path that fabricates a successful result —
 * a failed call surfaces as an ApiError and the UI renders an error state. The
 * previous frontend fell back to `handleMockSimulation()` on failure, which made
 * a dead backend look like a working detection.
 */

import {
  ApiError,
  type BaselinesResponse,
  type HealthResponse,
  type IncidentActionRequest,
  type IncidentActionResponse,
  type IncidentDetail,
  type IncidentSummary,
  type ScenarioSummary,
  type ScoreWindowRequest,
  type ScoreWindowResponse,
  type SimulateRequest,
  type SimulationReport,
  type StressTestRequest,
  type StressTestResult,
} from './types';

/** Public configuration only. Never put a credential in a VITE_ variable —
 *  anything here ships to the browser in plain text. */
export const API_BASE_URL: string =
  (import.meta.env.VITE_API_BASE_URL as string | undefined)?.replace(/\/$/, '') ??
  'http://localhost:8008';

/** Merchant context for demo/local use. Authorization is decided server-side from
 *  the authenticated principal; this header only *narrows* scope and can never
 *  widen it (see resolve_tenant_scope in app/core/auth.py). It is not a
 *  credential and grants nothing on its own. */
export const DEMO_MERCHANT_ID = 'm_electronics_01';

interface RequestOptions {
  method?: 'GET' | 'POST';
  body?: unknown;
  signal?: AbortSignal;
  timeoutMs?: number;
}

async function request<T>(path: string, opts: RequestOptions = {}): Promise<T> {
  const { method = 'GET', body, signal, timeoutMs = 120_000 } = opts;

  // Stress tests and simulations are genuinely slow; an unbounded fetch that
  // never resolves is worse than a clear timeout error.
  const controller = new AbortController();
  const timer = window.setTimeout(() => controller.abort(), timeoutMs);
  if (signal) signal.addEventListener('abort', () => controller.abort(), { once: true });

  let response: Response;
  try {
    response = await fetch(`${API_BASE_URL}${path}`, {
      method,
      headers: {
        'Content-Type': 'application/json',
        'X-Merchant-ID': DEMO_MERCHANT_ID,
      },
      body: body === undefined ? undefined : JSON.stringify(body),
      signal: controller.signal,
    });
  } catch (err) {
    window.clearTimeout(timer);
    if ((err as Error)?.name === 'AbortError') {
      throw new ApiError('The request took too long and was cancelled.', 0, 'timeout');
    }
    throw new ApiError(
      'Could not reach the Veyra API.',
      0,
      `${API_BASE_URL} did not respond. Check that the backend is running.`,
    );
  }
  window.clearTimeout(timer);

  if (!response.ok) {
    let detail = '';
    try {
      const payload = (await response.json()) as { detail?: unknown; error?: unknown };
      const raw = payload.detail ?? payload.error;
      detail = typeof raw === 'string' ? raw : raw ? JSON.stringify(raw) : '';
    } catch {
      detail = await response.text().catch(() => '');
    }
    throw new ApiError(
      response.status === 401 || response.status === 403
        ? 'Not authorised for this merchant.'
        : `Request failed (${response.status}).`,
      response.status,
      detail.slice(0, 400),
    );
  }

  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

export const api = {
  getHealth: (signal?: AbortSignal) => request<HealthResponse>('/health', { signal }),

  listScenarios: (signal?: AbortSignal) =>
    request<ScenarioSummary[]>('/v2/demo/scenarios', { signal }),

  runSimulation: (payload: SimulateRequest, signal?: AbortSignal) =>
    request<SimulationReport>('/v2/demo/simulate', { method: 'POST', body: payload, signal }),

  runStressTest: (payload: StressTestRequest, signal?: AbortSignal) =>
    request<StressTestResult>('/v2/demo/stress-test', {
      method: 'POST',
      body: payload,
      signal,
      timeoutMs: 300_000,
    }),

  scoreWindow: (payload: ScoreWindowRequest, signal?: AbortSignal) =>
    request<ScoreWindowResponse>('/v2/score-window', { method: 'POST', body: payload, signal }),

  listIncidents: (
    params: { merchant_id?: string; status?: string; limit?: number } = {},
    signal?: AbortSignal,
  ) => {
    const q = new URLSearchParams();
    if (params.merchant_id) q.set('merchant_id', params.merchant_id);
    if (params.status) q.set('status', params.status);
    if (params.limit) q.set('limit', String(params.limit));
    const qs = q.toString();
    return request<IncidentSummary[]>(`/v2/incidents${qs ? `?${qs}` : ''}`, { signal });
  },

  getIncident: (incidentId: string, signal?: AbortSignal) =>
    request<IncidentDetail>(`/v2/incidents/${encodeURIComponent(incidentId)}`, { signal }),

  applyIncidentAction: (
    incidentId: string,
    payload: IncidentActionRequest,
    signal?: AbortSignal,
  ) =>
    request<IncidentActionResponse>(
      `/v2/incidents/${encodeURIComponent(incidentId)}/action`,
      { method: 'POST', body: payload, signal },
    ),

  getBaselines: (merchantId: string, signal?: AbortSignal) =>
    request<BaselinesResponse>(
      `/v2/merchants/${encodeURIComponent(merchantId)}/baselines`,
      { signal },
    ),
};

export { ApiError };
