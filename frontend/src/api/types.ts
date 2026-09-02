/** Types mirroring the live FastAPI contract.
 *
 * Derived from the running backend's OpenAPI document and from real captured
 * responses — not from documentation, which can drift. Where the backend
 * serialises a Decimal it arrives as a *string* (e.g. financial_exposure values);
 * those are typed as strings here and parsed at the formatting boundary rather
 * than being silently coerced into floats that print artifacts.
 */

export type WindowSize = '1m' | '5m' | '15m' | '1h';
export type ActionTier = 'OBSERVE' | 'ALERT' | 'REVIEW' | 'RESTRICT';

export interface HealthResponse {
  status: string;
  version: string;
  environment: string;
}

export interface ScenarioSummary {
  scenario_id: string;
  name: string;
  is_attack: boolean;
  category: string;
}

export interface ExecutionStage {
  stage_number: number;
  name: string;
  description: string;
  duration_ms: number;
  status: string;
  details: Record<string, unknown>;
}

export interface FeatureDeviation {
  feature_id: string;
  deviation_mad: number;
  raw_value: number;
  direction: string;
}

export type EntityNodeType = 'customer' | 'device' | 'instrument' | 'ip';

export interface EntityNode {
  id: string;
  type: EntityNodeType;
  label: string;
}

export interface EntityEdge {
  source: string;
  target: string;
  type: string;
}

export interface EntityGraph {
  nodes: EntityNode[];
  edges: EntityEdge[];
  total_nodes: number;
  total_edges: number;
}

/** Decimal-as-string money fields, exactly as the backend serialises them. */
export interface FinancialExposure {
  at_risk_gmv: string;
  p_loss: number;
  direct_fraud_loss: string;
  operational_loss: string;
  promo_exposure: string;
  total_exposure: string;
}

export interface SimulateRequest {
  scenario_id: string;
  merchant_category: string;
  intensity: number;
  window_size: WindowSize;
  seed: number;
}

/** POST /v2/demo/simulate */
export interface SimulationReport {
  scenario_id: string;
  scenario_name: string;
  /** Generator ground truth for the chosen scenario — NOT a detector output.
   *  The UI must never present this as the model's judgement. */
  is_attack: boolean;
  merchant_id: string;
  merchant_category: string;
  window_size: string;
  window_end: string;
  total_transactions: number;
  abusive_transactions: number;
  risk_score: number;
  action_tier: ActionTier | string;
  recommended_defensive_control: string | null;
  explanation: string;
  financial_exposure: FinancialExposure;
  top_feature_deviations: FeatureDeviation[];
  entity_graph: EntityGraph;
  features_summary: Record<string, number>;
  stages: ExecutionStage[];
  /** Only 'markdown' and 'csv' are produced server-side. */
  export_formats: Record<string, string>;
}

export interface StressTestRequest {
  scenario_id: string;
  burst_count: number;
  merchant_category: string;
}

/** POST /v2/demo/stress-test */
export interface StressTestResult {
  burst_count: number;
  total_time_ms: number;
  throughput_tps: number;
  ingestion_time_ms: number;
  feature_time_ms: number;
  scoring_time_ms: number;
  risk_score: number;
  action_tier: ActionTier | string;
  abusive_detected: number;
  status: string;
  stages: ExecutionStage[];
}

export interface ScoreWindowRequest {
  merchant_id: string;
  window_size?: WindowSize;
  window_end?: string | null;
}

/** POST /v2/score-window */
export interface ScoreWindowResponse {
  merchant_id: string;
  window_size: string;
  window_end: string;
  risk_score: number;
  action_tier: ActionTier | string;
  recommended_defensive_control: string | null;
  incident_id: string | null;
  financial_exposure: FinancialExposure;
  explanation: string;
  top_feature_deviations: FeatureDeviation[];
  entity_graph: EntityGraph;
  baseline_confidence: string;
  model_version: string;
}

/** GET /v2/incidents */
export interface IncidentSummary {
  incident_id: string;
  merchant_id: string;
  window_size: string | null;
  window_end: string;
  action_tier: string;
  risk_score: number;
  status: string;
  recommended_action: string | null;
  created_at: string | null;
}

/** GET /v2/incidents/{id} */
export interface IncidentDetail extends IncidentSummary {
  evidence_payload: Record<string, unknown>;
  analyst_notes: string;
}

/** GET /v2/merchants/{merchant_id}/baselines */
export interface BaselineRow {
  feature_id: string;
  window_size: string;
  hour_of_week: number;
  expected_median: number;
  variability_mad: number;
  confidence: string;
  sample_count: number;
}

export interface BaselinesResponse {
  merchant_id: string;
  total_baselines: number;
  baselines: BaselineRow[];
}

/** POST /v2/incidents/{id}/action */
export interface IncidentActionRequest {
  action: 'ACKNOWLEDGE' | 'APPLY_DEFENSE' | 'DISMISS' | 'RESOLVE';
  analyst_notes?: string;
}

export interface IncidentActionResponse {
  incident_id: string;
  status: string;
  analyst_notes: string;
  message: string;
}

/** Normalised transport failure. The UI renders these; it never swallows them. */
export class ApiError extends Error {
  readonly status: number;
  readonly detail: string;

  constructor(message: string, status: number, detail = '') {
    super(message);
    this.name = 'ApiError';
    this.status = status;
    this.detail = detail;
  }

  get isNetwork(): boolean {
    return this.status === 0;
  }
}
