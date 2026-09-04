/** Types mirroring the live FastAPI contract.
 *
 * Derived directly from `app/schemas/demo.py` and `app/schemas/benchmark.py`.
 * Where the backend serialises a Decimal it arrives as a string (e.g. financial_exposure values);
 * those are typed as strings here and parsed at the formatting boundary.
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

// ---------------- Demo Detection Pipeline (/v2/demo/simulate) ----------------

export type StageStatus = 'pending' | 'running' | 'completed' | 'failed' | 'skipped';

/** One real, server-timed step of a demo run (PipelineStage in app/schemas/demo.py). */
export interface PipelineStage {
  sequence: number;
  id: string;
  label: string;
  status: StageStatus;
  duration_ms: number;
  started_at: string;
  ended_at: string;
  detail?: Record<string, unknown> | null;
}

/** Legacy execution stage shape from /v2/demo/stress-test. */
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
  promo_exposure?: string;
  total_exposure: string;
}

export interface SimulateRequest {
  scenario_id: string;
  merchant_category: string;
  intensity: number;
  window_size: WindowSize;
  seed: number;
}

export interface Provenance {
  data_source: 'synthetic' | string;
  generated_for: 'demo_run' | string;
  is_production_data: false;
  ground_truth_semantics?: string;
}

export interface EntityCounts {
  customers: number;
  devices: number;
  instruments: number;
  ip_addresses: number;
}

export interface ServerTiming {
  server_processing_ms: number;
  stage_count: number;
  measurement: 'time.perf_counter' | string;
  includes_frontend_presentation_time: false;
  note: string;
}

export interface DemoModelInfo {
  model_name: string;
  model_version: string;
  trained_this_call: boolean;
  was_cached: boolean;
  trained_at: string;
  training_seed: number;
  training_window_start: string;
  training_window_end: string;
  training_transactions: number;
  training_windows: number;
  train_duration_ms: number;
}

export interface DemoRunMeta {
  run_id: string;
  created_at: string;
  scenario_id: string;
  merchant_category: string;
  merchant_id: string;
  intensity: number;
  seed: number;
  window_size: string;
  window_end: string;
  total_transactions: number;
  time_span_seconds: number;
  entity_counts: EntityCounts;
  total_entities: number;
  feature_count: number;
  baseline_confidence: string;
  baselines_available: boolean;
  model: DemoModelInfo;
  risk_score: number;
  action_tier: string;
  total_server_duration_ms: number;
  timing: ServerTiming;
  provenance: Provenance;
}

export interface GroundTruth {
  scenario_id: string;
  scenario_is_labelled_attack: boolean;
  abusive_transaction_count: number;
  total_transaction_count: number;
  note: string;
}

/** POST /v2/demo/simulate */
export interface SimulationReport {
  run: DemoRunMeta;
  scenario_name: string;
  risk_score: number;
  action_tier: ActionTier | string;
  recommended_defensive_control: string | null;
  model_matches_ground_truth: boolean;
  ground_truth: GroundTruth;
  explanation: string;
  financial_exposure: FinancialExposure;
  top_feature_deviations: FeatureDeviation[];
  entity_graph: EntityGraph;
  features_summary: Record<string, number>;
  stages: PipelineStage[];
  export_formats: Record<string, string>;

  // Optional backward compatibility accessors for helpers
  scenario_id?: string;
  is_attack?: boolean;
  merchant_id?: string;
  merchant_category?: string;
  window_size?: string;
  window_end?: string;
  total_transactions?: number;
  abusive_transactions?: number;
}

// ---------------- Synthetic Data Explorer (/v2/demo/runs/*) ----------------

export interface TransactionRow {
  transaction_id: string;
  timestamp: string;
  merchant_id: string;
  customer_id: string | null;
  instrument_token: string;
  device_id: string | null;
  ip_token: string | null;
  amount: string;
  currency: string;
  outcome_status: string | null;
  outcome_failure_code: string | null;
  ground_truth_is_abusive: boolean;
  ground_truth_is_spike: boolean;
  ground_truth_scenario_id: string;
}

export interface TransactionPage {
  run_id: string;
  page: number;
  page_size: number;
  total_transactions: number;
  total_pages: number;
  items: TransactionRow[];
  provenance: Provenance;
}

export interface FeatureValue {
  feature_id: string;
  family: string;
  value: number;
  deviation_mad: number | null;
  is_model_input: boolean;
  is_evidence_only: boolean;
}

export interface FeatureSummary {
  run_id: string;
  families: Record<string, FeatureValue[]>;
  model_feature_count: number;
  evidence_feature_count: number;
  baseline_confidence: string;
  provenance: Provenance;
}

export interface EntitySummary {
  run_id: string;
  counts: EntityCounts;
  total_entities: number;
  transactions: number;
  instruments_per_customer: number | null;
  transactions_per_device: number | null;
  largest_cluster_volume_share: number | null;
  bipartite_gini: number | null;
  provenance: Provenance;
}

export interface RunSummary {
  run_id: string;
  scenario_id: string;
  window_size: string;
  window_end: string;
  total_transactions: number;
  abusive_transactions: number;
  benign_transactions: number;
  time_range_start: string;
  time_range_end: string;
  entity_counts: EntityCounts;
  action_tier: string;
  risk_score: number;
  provenance: Provenance;
}

export interface RunRetention {
  storage: string;
  max_runs_retained: number;
  ttl_seconds: number;
}

export interface RunLinks {
  transactions: string;
  features: string;
  summary: string;
  entities: string;
}

export interface RunDetail {
  run_id: string;
  created_at: string;
  scenario_id: string;
  merchant_id: string;
  merchant_category: string;
  window_size: string;
  window_end: string;
  total_transactions: number;
  abusive_transactions: number;
  scenario_is_labelled_attack: boolean;
  risk_score: number;
  action_tier: string;
  entity_counts: EntityCounts;
  time_range_start: string;
  time_range_end: string;
  entity_graph: EntityGraph;
  links: RunLinks;
  retention: RunRetention;
  provenance: Provenance;
}

// ---------------- Workload Scaling Benchmarks (/v2/demo/benchmarks/*) ----------------

export type WorkloadTier = 'safe' | 'extended' | 'experimental';
export type BenchmarkMode = 'ingestion' | 'pipeline';
export type BenchmarkStatus =
  | 'queued'
  | 'running'
  | 'completed'
  | 'stopped_early'
  | 'capped'
  | 'failed'
  | 'rejected';

export type StopReason =
  | 'wall_clock_budget_exceeded'
  | 'safety_ceiling_reached'
  | 'persistence_unavailable'
  | 'internal_error';

export type ScenarioMix =
  | 'all_legit'
  | 'legit_90_fraud_10'
  | 'mixed_50_50'
  | 'fraud_90_legit_10'
  | 'all_fraud'
  | 'custom';

export interface WorkloadPreset {
  workload_size: number;
  label: string;
  tier: WorkloadTier;
  will_be_capped: boolean;
  executed_size_if_requested: number;
}

export interface ScenarioMixOption {
  id: string;
  label: string;
  fraud_ratio: number | null;
}

export interface BenchmarkModeOption {
  id: BenchmarkMode;
  label: string;
}

export interface BenchmarkGuardrails {
  hard_cap_events: number;
  max_seconds: number;
  chunk_size: number;
  max_sample_windows: number;
  concurrent_jobs: number;
  sample_rows_per_bucket: number;
  allow_experimental: boolean;
}

export interface BenchmarkPresetsResponse {
  presets: WorkloadPreset[];
  scenario_mixes: ScenarioMixOption[];
  modes: BenchmarkModeOption[];
  guardrails: BenchmarkGuardrails;
  notice: string;
}

export interface BenchmarkCreateRequest {
  workload_size: number;
  duration_minutes?: number;
  fraud_ratio?: number;
  scenario_mix?: ScenarioMix | string;
  benchmark_mode?: BenchmarkMode;
}

export interface BenchmarkCreateResponse {
  run_id: string;
  status: BenchmarkStatus;
  workload_tier: WorkloadTier;
  requested_workload_size: number;
  planned_executed_size: number;
  capped: boolean;
  poll: {
    run: string;
    progress: string;
  };
  notice: string;
}

export interface BenchmarkProgress {
  stage: string;
  events_processed: number;
  events_target: number;
  percent: number;
  elapsed_ms: number;
}

export interface BenchmarkProgressResponse {
  run_id: string;
  status: BenchmarkStatus;
  progress: BenchmarkProgress | null;
  finished: boolean;
  error?: string | null;
}

export interface BenchmarkEnvironment {
  database: string;
  database_url_scheme: string;
  python: string;
  platform: string;
  cpu_count: number | null;
}

export interface TrafficComposition {
  requested_events: number;
  generated_events: number;
  processed_events: number;
  legitimate_events: number;
  fraud_events: number;
  requested_fraud_ratio: number;
  actual_fraud_ratio: number | null;
  ground_truth_semantics: string;
}

export interface IngestionScale {
  events_generated: number;
  events_persisted: number;
  write_duration_ms: number | null;
  events_per_second: number | null;
  persistence_errors: number;
  unit: 'events_per_second';
}

export interface ComputationScale {
  sampled_windows: number;
  sample_cap: number;
  feature_extraction_total_ms: number;
  feature_extraction_per_window_ms: number;
  entity_graph_total_ms: number;
  entity_graph_per_window_ms: number;
  model_inference_total_ms: number;
  model_inference_per_window_ms: number;
  total_computation_ms: number;
  per_window_latency_ms: number;
  unit: 'milliseconds_per_merchant_window';
  is_full_workload_pass: false;
  note: string;
}

export interface MemoryMetrics {
  metric: 'tracemalloc_traced_python_heap';
  peak_traced_python_heap_mb: number | null;
  includes_process_rss: false;
  includes_native_allocations: false;
  description: string;
}

export interface StorageMetrics {
  metric: 'sqlite_file_size_delta';
  storage_delta_mb: number | null;
  measured_before_cleanup: true;
  rows_deleted_on_cleanup: number | null;
  description: string;
}

export interface BenchmarkSampleTransaction {
  transaction_id: string;
  timestamp: string;
  merchant_id: string;
  customer_id: string | null;
  device_fingerprint: string | null;
  instrument_fingerprint: string;
  ip_fingerprint: string | null;
  amount: string;
  currency: string;
  outcome_status: string | null;
  ground_truth_is_abusive: boolean;
  ground_truth_scenario_id: string;
}

export interface BenchmarkSamples {
  legitimate: BenchmarkSampleTransaction[];
  fraud: BenchmarkSampleTransaction[];
  random: BenchmarkSampleTransaction[];
  per_bucket_cap: number;
  is_full_workload: false;
  ground_truth_semantics: string;
}

/** Nested BenchmarkResult matching app/schemas/benchmark.py exactly. */
export interface BenchmarkResult {
  status: BenchmarkStatus;
  stop_reason: StopReason | null;
  requested_workload_size: number;
  capped_workload_size: number;
  capped: boolean;
  workload_tier: WorkloadTier;
  scenario_mix: string;
  benchmark_mode: string;
  duration_minutes: number;

  traffic: TrafficComposition;
  ingestion: IngestionScale;
  computation: ComputationScale | null;
  memory: MemoryMetrics;
  storage: StorageMetrics;
  total_ms: number;
  samples: BenchmarkSamples;
  environment: BenchmarkEnvironment;
  limitations: string[];
}

export interface BenchmarkRun {
  run_id: string;
  status: BenchmarkStatus;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
  request: BenchmarkCreateRequest;
  progress: BenchmarkProgress | null;
  result: BenchmarkResult | null;
  error: string | null;
}

export interface BenchmarkListResponse {
  retained_runs: number;
  max_runs_retained: number;
  ttl_seconds: number;
}

// ---------------- Stress Test & Production Score ----------------

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
