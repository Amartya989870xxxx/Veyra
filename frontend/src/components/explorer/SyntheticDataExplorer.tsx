/** Synthetic Data Explorer.
 *
 * Lets a reviewer page through and inspect the exact synthetic transaction stream
 * and feature vector that produced a specific /v2/demo/simulate verdict.
 *
 * Implements bounded pagination (server-side, never pulls all transactions at once)
 * and an inspectable transaction detail drawer without sensitive raw credentials.
 */

import { useCallback, useEffect, useState } from 'react';
import {
  ChevronLeft,
  ChevronRight,
  X,
  Database,
} from 'lucide-react';
import { ApiError, api } from '../../api/client';
import type {
  EntitySummary,
  FeatureSummary,
  RunDetail,
  TransactionPage,
  TransactionRow,
} from '../../api/types';
import { tierColorVar, tierWashVar } from '../../lib/scenarios';
import { Button, Card, EmptyState, ErrorState, LoadingBlock, Stat } from '../ui';
import { EntityGraph } from '../viz/EntityGraph';

interface SyntheticDataExplorerProps {
  runId: string | null;
  onSelectRunId?: (runId: string) => void;
}

export function SyntheticDataExplorer({ runId }: SyntheticDataExplorerProps) {
  const [activeRunId, setActiveRunId] = useState<string | null>(runId);
  const [runDetail, setRunDetail] = useState<RunDetail | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [detailError, setDetailError] = useState<ApiError | null>(null);

  // Pagination state
  const [page, setPage] = useState(1);
  const [pageSize] = useState(25);
  const [txData, setTxData] = useState<TransactionPage | null>(null);
  const [txLoading, setTxLoading] = useState(false);
  const [txError, setTxError] = useState<ApiError | null>(null);

  // Sub-tabs: Transactions, Entities, Features
  const [activeSubTab, setActiveSubTab] = useState<'transactions' | 'entities' | 'features'>('transactions');
  const [featuresData, setFeaturesData] = useState<FeatureSummary | null>(null);
  const [featuresLoading, setFeaturesLoading] = useState(false);
  const [entitiesData, setEntitiesData] = useState<EntitySummary | null>(null);
  const [entitiesLoading, setEntitiesLoading] = useState(false);

  // Detail drawer
  const [selectedTx, setSelectedTx] = useState<TransactionRow | null>(null);

  // Synchronize when external runId changes
  useEffect(() => {
    if (runId && runId !== activeRunId) {
      setActiveRunId(runId);
      setPage(1);
    }
  }, [runId, activeRunId]);

  // Load run detail
  const loadRunDetail = useCallback(async (id: string) => {
    setDetailLoading(true);
    setDetailError(null);
    try {
      const detail = await api.getRun(id);
      setRunDetail(detail);
    } catch (err) {
      setDetailError(err as ApiError);
      setRunDetail(null);
    } finally {
      setDetailLoading(false);
    }
  }, []);

  // Load transactions page
  const loadTransactions = useCallback(async (id: string, p: number, ps: number) => {
    setTxLoading(true);
    setTxError(null);
    try {
      const data = await api.getRunTransactions(id, p, ps);
      setTxData(data);
    } catch (err) {
      setTxError(err as ApiError);
      setTxData(null);
    } finally {
      setTxLoading(false);
    }
  }, []);

  // Load features summary
  const loadFeatures = useCallback(async (id: string) => {
    setFeaturesLoading(true);
    try {
      const feats = await api.getRunFeatures(id);
      setFeaturesData(feats);
    } catch {
      setFeaturesData(null);
    } finally {
      setFeaturesLoading(false);
    }
  }, []);

  // Load entities summary (Part 11: GET /v2/demo/runs/{id}/entities)
  const loadEntities = useCallback(async (id: string) => {
    setEntitiesLoading(true);
    try {
      const ent = await api.getRunEntities(id);
      setEntitiesData(ent);
    } catch {
      setEntitiesData(null);
    } finally {
      setEntitiesLoading(false);
    }
  }, []);

  useEffect(() => {
    if (activeRunId) {
      loadRunDetail(activeRunId);
      loadTransactions(activeRunId, page, pageSize);
      if (activeSubTab === 'features' && !featuresData) {
        loadFeatures(activeRunId);
      }
      if (activeSubTab === 'entities' && !entitiesData) {
        loadEntities(activeRunId);
      }
    }
  }, [activeRunId, page, pageSize, activeSubTab, loadRunDetail, loadTransactions, loadFeatures, loadEntities, featuresData, entitiesData]);

  if (!activeRunId) {
    return (
      <Card style={{ padding: 'var(--sp-7)' }}>
        <EmptyState
          title="No demo run selected"
          description="Execute a detection scenario in the Detection Console first, then click 'Inspect in Synthetic Data Explorer' to view its exact synthetic transaction stream."
        />
      </Card>
    );
  }

  if (detailLoading && !runDetail) {
    return (
      <Card style={{ padding: 'var(--sp-6)' }}>
        <LoadingBlock label={`Loading synthetic run ${activeRunId}…`} rows={5} />
      </Card>
    );
  }

  if (detailError) {
    return (
      <Card style={{ padding: 'var(--sp-6)' }}>
        <ErrorState
          title={detailError.status === 404 ? 'Run expired or not found' : 'Could not load synthetic run'}
          detail={detailError.detail || detailError.message}
          onRetry={() => activeRunId && loadRunDetail(activeRunId)}
        />
      </Card>
    );
  }

  const benignCount = (runDetail?.total_transactions ?? 0) - (runDetail?.abusive_transactions ?? 0);
  const tierColor = runDetail ? tierColorVar(runDetail.action_tier) : 'var(--text-secondary)';
  const tierWash = runDetail ? tierWashVar(runDetail.action_tier) : 'transparent';

  return (
    <div style={{ display: 'grid', gap: 'var(--sp-5)' }}>
      {/* ----------------- Run Metadata Header Card ----------------- */}
      <Card style={{ display: 'grid', gap: 16 }}>
        <div
          style={{
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            flexWrap: 'wrap',
            gap: 12,
            paddingBottom: 12,
            borderBottom: '1px solid rgba(255, 255, 255, 0.07)',
          }}
        >
          <div>
            <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
              <span
                style={{
                  display: 'inline-flex',
                  alignItems: 'center',
                  gap: 6,
                  background: 'rgba(59, 130, 246, 0.15)',
                  border: '1px solid rgba(59, 130, 246, 0.3)',
                  padding: '3px 8px',
                  borderRadius: 5,
                  fontSize: '11px',
                  fontWeight: 700,
                  fontFamily: 'var(--font-mono)',
                  color: 'var(--accent-bright)',
                }}
              >
                <Database size={12} />
                SYNTHETIC DATA EXPLORER
              </span>

              <span style={{ fontFamily: 'var(--font-mono)', fontSize: 'var(--text-xs)', color: 'var(--text-secondary)' }}>
                run: {runDetail?.run_id}
              </span>
            </div>
            <h2 style={{ fontSize: 'var(--text-lg)', marginTop: 6, fontWeight: 700 }}>
              Synthetic Dataset & Feature Evidence
            </h2>
          </div>

          <div style={{ display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap' }}>
            <span
              style={{
                display: 'inline-flex',
                alignItems: 'center',
                gap: 5,
                padding: '4px 10px',
                borderRadius: 6,
                background: tierWash,
                border: `1px solid ${tierColor}`,
                color: tierColor,
                fontFamily: 'var(--font-mono)',
                fontSize: '11px',
                fontWeight: 700,
              }}
            >
              DECISION: {runDetail?.action_tier} ({(Number(runDetail?.risk_score ?? 0) * 100).toFixed(1)}%)
            </span>

            {runDetail?.retention && (
              <span
                title="Bounded in-memory store for reviewer inspection"
                style={{
                  fontSize: '11px',
                  color: 'var(--text-muted)',
                  background: 'rgba(255, 255, 255, 0.03)',
                  padding: '3px 8px',
                  borderRadius: 4,
                  border: '1px solid rgba(255, 255, 255, 0.06)',
                }}
              >
                Retained in-memory (TTL {Math.round(runDetail.retention.ttl_seconds / 60)}m)
              </span>
            )}
          </div>
        </div>

        {/* Metadata Grid */}
        <div
          style={{
            display: 'grid',
            gridTemplateColumns: 'repeat(auto-fit, minmax(140px, 1fr))',
            gap: 12,
          }}
        >
          <div>
            <div style={{ fontSize: '10px', color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.04em' }}>
              Scenario
            </div>
            <div style={{ fontFamily: 'var(--font-mono)', fontSize: 'var(--text-xs)', fontWeight: 600, marginTop: 2 }}>
              {runDetail?.scenario_id}
            </div>
          </div>

          <div>
            <div style={{ fontSize: '10px', color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.04em' }}>
              Merchant
            </div>
            <div style={{ fontFamily: 'var(--font-mono)', fontSize: 'var(--text-xs)', fontWeight: 600, marginTop: 2 }}>
              {runDetail?.merchant_id} ({runDetail?.merchant_category})
            </div>
          </div>

          <div>
            <div style={{ fontSize: '10px', color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.04em' }}>
              Window Horizon
            </div>
            <div style={{ fontFamily: 'var(--font-mono)', fontSize: 'var(--text-xs)', fontWeight: 600, marginTop: 2 }}>
              {runDetail?.window_size}
            </div>
          </div>

          <div>
            <div style={{ fontSize: '10px', color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.04em' }}>
              Total Events
            </div>
            <div style={{ fontFamily: 'var(--font-mono)', fontSize: 'var(--text-xs)', fontWeight: 600, marginTop: 2 }}>
              {runDetail?.total_transactions} txns
            </div>
          </div>

          <div>
            <div style={{ fontSize: '10px', color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.04em' }}>
              Ground-Truth Composition
            </div>
            <div style={{ fontFamily: 'var(--font-mono)', fontSize: 'var(--text-xs)', fontWeight: 600, marginTop: 2, display: 'flex', gap: 6 }}>
              <span style={{ color: 'var(--color-critical)' }}>{runDetail?.abusive_transactions} abusive</span>
              <span style={{ color: 'var(--text-muted)' }}>/</span>
              <span style={{ color: 'var(--color-safe)' }}>{benignCount} legit</span>
            </div>
          </div>

          <div>
            <div style={{ fontSize: '10px', color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.04em' }}>
              Observed Entities
            </div>
            <div style={{ fontFamily: 'var(--font-mono)', fontSize: 'var(--text-xs)', fontWeight: 600, marginTop: 2 }}>
              {runDetail?.entity_counts.customers} cus · {runDetail?.entity_counts.devices} dev · {runDetail?.entity_counts.instruments} inst · {runDetail?.entity_counts.ip_addresses} ip
            </div>
          </div>
        </div>

        {/* Sub-tab switcher: Transactions vs Features */}
        <div style={{ display: 'flex', gap: 6, borderTop: '1px solid rgba(255, 255, 255, 0.06)', paddingTop: 12 }}>
          <button
            onClick={() => setActiveSubTab('transactions')}
            style={{
              padding: '6px 14px',
              borderRadius: 6,
              background: activeSubTab === 'transactions' ? 'var(--accent-wash)' : 'transparent',
              border: `1px solid ${activeSubTab === 'transactions' ? 'var(--accent)' : 'transparent'}`,
              color: activeSubTab === 'transactions' ? 'var(--accent-bright)' : 'var(--text-secondary)',
              fontSize: 'var(--text-xs)',
              fontWeight: 600,
              cursor: 'pointer',
            }}
          >
            Synthetic Transactions ({runDetail?.total_transactions ?? 0})
          </button>

          <button
            onClick={() => {
              setActiveSubTab('features');
              if (activeRunId && !featuresData) loadFeatures(activeRunId);
            }}
            style={{
              padding: '6px 14px',
              borderRadius: 6,
              background: activeSubTab === 'features' ? 'var(--accent-wash)' : 'transparent',
              border: `1px solid ${activeSubTab === 'features' ? 'var(--accent)' : 'transparent'}`,
              color: activeSubTab === 'features' ? 'var(--accent-bright)' : 'var(--text-secondary)',
              fontSize: 'var(--text-xs)',
              fontWeight: 600,
              cursor: 'pointer',
            }}
          >
            Extracted Feature Vector
          </button>

          <button
            onClick={() => {
              setActiveSubTab('entities');
              if (activeRunId && !entitiesData) loadEntities(activeRunId);
            }}
            style={{
              padding: '6px 14px',
              borderRadius: 6,
              background: activeSubTab === 'entities' ? 'var(--accent-wash)' : 'transparent',
              border: `1px solid ${activeSubTab === 'entities' ? 'var(--accent)' : 'transparent'}`,
              color: activeSubTab === 'entities' ? 'var(--accent-bright)' : 'var(--text-secondary)',
              fontSize: 'var(--text-xs)',
              fontWeight: 600,
              cursor: 'pointer',
            }}
          >
            Entities & Graph Topology
          </button>
        </div>
      </Card>

      {/* ----------------- Sub-Tab 1: Transactions Table ----------------- */}
      {activeSubTab === 'transactions' && (
        <Card style={{ padding: 0, overflow: 'hidden' }}>
          {/* Table Toolbar */}
          <div
            style={{
              padding: '12px 18px',
              background: 'rgba(255, 255, 255, 0.02)',
              borderBottom: '1px solid var(--border)',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'space-between',
              flexWrap: 'wrap',
              gap: 12,
            }}
          >
            <div style={{ fontSize: 'var(--text-xs)', color: 'var(--text-secondary)' }}>
              Showing transactions{' '}
              <span style={{ fontWeight: 600, color: 'var(--text-primary)' }}>
                {txData ? (page - 1) * pageSize + 1 : 0}–
                {txData ? Math.min(page * pageSize, txData.total_transactions) : 0}
              </span>{' '}
              of <span style={{ fontWeight: 600, color: 'var(--text-primary)' }}>{txData?.total_transactions ?? 0}</span>
            </div>

            {/* Pagination Controls */}
            <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
              <span style={{ fontSize: 'var(--text-xs)', color: 'var(--text-muted)' }}>
                Page {page} of {txData?.total_pages ?? 1}
              </span>

              <div style={{ display: 'flex', gap: 4 }}>
                <Button
                  variant="secondary"
                  size="sm"
                  disabled={page <= 1 || txLoading}
                  onClick={() => setPage((p) => Math.max(1, p - 1))}
                  icon={<ChevronLeft size={14} />}
                >
                  Prev
                </Button>

                <Button
                  variant="secondary"
                  size="sm"
                  disabled={!txData || page >= txData.total_pages || txLoading}
                  onClick={() => setPage((p) => p + 1)}
                  icon={<ChevronRight size={14} />}
                >
                  Next
                </Button>
              </div>
            </div>
          </div>

          {/* Table / Loading / Error */}
          {txLoading && !txData ? (
            <div style={{ padding: 'var(--sp-6)' }}>
              <LoadingBlock label="Fetching page of transactions…" rows={6} />
            </div>
          ) : txError ? (
            <div style={{ padding: 'var(--sp-6)' }}>
              <ErrorState
                title="Failed to fetch transactions"
                detail={txError.detail || txError.message}
                onRetry={() => activeRunId && loadTransactions(activeRunId, page, pageSize)}
              />
            </div>
          ) : !txData || txData.items.length === 0 ? (
            <div style={{ padding: 'var(--sp-6)' }}>
              <EmptyState title="No transactions found" description="No transactions in this window." />
            </div>
          ) : (
            <div style={{ overflowX: 'auto' }}>
              <table
                style={{
                  width: '100%',
                  borderCollapse: 'collapse',
                  fontSize: 'var(--text-xs)',
                  fontFamily: 'var(--font-mono)',
                }}
              >
                <thead>
                  <tr
                    style={{
                      borderBottom: '1px solid var(--border)',
                      background: 'rgba(255, 255, 255, 0.03)',
                      color: 'var(--text-muted)',
                      textAlign: 'left',
                      fontSize: '11px',
                    }}
                  >
                    <th style={{ padding: '10px 14px' }}>Timestamp</th>
                    <th style={{ padding: '10px 14px' }}>Transaction ID</th>
                    <th style={{ padding: '10px 14px' }}>Customer</th>
                    <th style={{ padding: '10px 14px' }}>Device FP</th>
                    <th style={{ padding: '10px 14px' }}>Instrument Token</th>
                    <th style={{ padding: '10px 14px' }}>IP Token</th>
                    <th style={{ padding: '10px 14px' }}>Amount</th>
                    <th style={{ padding: '10px 14px' }}>Outcome</th>
                    <th style={{ padding: '10px 14px' }} title="Synthetic generator ground truth — not a model output">
                      Ground Truth
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {txData.items.map((row) => {
                    const isSelected = selectedTx?.transaction_id === row.transaction_id;
                    const dateObj = new Date(row.timestamp);
                    const timeStr = dateObj.toLocaleTimeString();

                    return (
                      <tr
                        key={row.transaction_id}
                        onClick={() => setSelectedTx(row)}
                        style={{
                          borderBottom: '1px solid rgba(255, 255, 255, 0.04)',
                          cursor: 'pointer',
                          background: isSelected
                            ? 'rgba(59, 130, 246, 0.12)'
                            : row.ground_truth_is_abusive
                            ? 'rgba(255, 46, 76, 0.03)'
                            : 'transparent',
                          transition: 'background 0.15s ease',
                        }}
                        onMouseEnter={(e) => {
                          if (!isSelected) {
                            e.currentTarget.style.background = 'rgba(255, 255, 255, 0.05)';
                          }
                        }}
                        onMouseLeave={(e) => {
                          if (!isSelected) {
                            e.currentTarget.style.background = row.ground_truth_is_abusive
                              ? 'rgba(255, 46, 76, 0.03)'
                              : 'transparent';
                          }
                        }}
                      >
                        <td style={{ padding: '10px 14px', color: 'var(--text-secondary)' }}>{timeStr}</td>
                        <td style={{ padding: '10px 14px', fontWeight: 600, color: 'var(--text-primary)' }}>
                          {row.transaction_id}
                        </td>
                        <td style={{ padding: '10px 14px', color: 'var(--text-secondary)' }}>
                          {row.customer_id || '—'}
                        </td>
                        <td style={{ padding: '10px 14px', color: 'var(--text-secondary)' }}>
                          {row.device_id ? row.device_id.slice(0, 12) : '—'}
                        </td>
                        <td style={{ padding: '10px 14px', color: 'var(--text-secondary)' }}>
                          {row.instrument_token ? row.instrument_token.slice(0, 14) : '—'}
                        </td>
                        <td style={{ padding: '10px 14px', color: 'var(--text-secondary)' }}>
                          {row.ip_token ? row.ip_token.slice(0, 12) : '—'}
                        </td>
                        <td style={{ padding: '10px 14px', fontWeight: 600, color: 'var(--text-primary)' }}>
                          ₹{Number(row.amount).toFixed(2)}
                        </td>
                        <td style={{ padding: '10px 14px' }}>
                          <span
                            style={{
                              display: 'inline-block',
                              padding: '2px 6px',
                              borderRadius: 4,
                              fontSize: '10px',
                              background:
                                row.outcome_status === 'CAPTURED'
                                  ? 'rgba(16, 185, 129, 0.12)'
                                  : 'rgba(239, 68, 68, 0.12)',
                              color:
                                row.outcome_status === 'CAPTURED'
                                  ? 'var(--color-safe)'
                                  : 'var(--color-critical)',
                              border: `1px solid ${
                                row.outcome_status === 'CAPTURED'
                                  ? 'rgba(16, 185, 129, 0.3)'
                                  : 'rgba(239, 68, 68, 0.3)'
                              }`,
                            }}
                          >
                            {row.outcome_status || 'UNKNOWN'}
                          </span>
                        </td>
                        <td style={{ padding: '10px 14px' }}>
                          <span
                            style={{
                              display: 'inline-flex',
                              alignItems: 'center',
                              gap: 4,
                              padding: '2px 6px',
                              borderRadius: 4,
                              fontSize: '10px',
                              background: row.ground_truth_is_abusive
                                ? 'rgba(255, 46, 76, 0.15)'
                                : 'rgba(255, 255, 255, 0.05)',
                              color: row.ground_truth_is_abusive
                                ? 'var(--color-critical)'
                                : 'var(--text-muted)',
                              border: `1px solid ${
                                row.ground_truth_is_abusive
                                  ? 'rgba(255, 46, 76, 0.35)'
                                  : 'rgba(255, 255, 255, 0.1)'
                              }`,
                            }}
                          >
                            {row.ground_truth_is_abusive ? 'ABUSIVE' : 'BENIGN'}
                          </span>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
        </Card>
      )}

      {/* ----------------- Sub-Tab 2: Entities & Graph Topology (Part 11) ----------------- */}
      {activeSubTab === 'entities' && (
        <Card style={{ display: 'grid', gap: 16 }}>
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', flexWrap: 'wrap', gap: 12 }}>
            <div>
              <h3 style={{ fontSize: 'var(--text-md)', fontWeight: 700 }}>
                Entity Graph & Bipartite Concentrations
              </h3>
              <p style={{ fontSize: 'var(--text-xs)', color: 'var(--text-secondary)', marginTop: 4 }}>
                Aggregated topology from GET /v2/demo/runs/{activeRunId}/entities. Shows entity clustering without exposing raw credentials.
              </p>
            </div>
            {entitiesData && (
              <span style={{ fontFamily: 'var(--font-mono)', fontSize: 'var(--text-xs)', color: 'var(--accent-bright)' }}>
                {entitiesData.total_entities} observed entities
              </span>
            )}
          </div>

          {entitiesLoading && !entitiesData ? (
            <LoadingBlock label="Loading entity topology…" rows={6} />
          ) : !entitiesData ? (
            <EmptyState title="No entity data loaded" description="Click to load entity concentrations for this run." />
          ) : (
            <div style={{ display: 'grid', gap: 16 }}>
              {/* Entity Count Stats */}
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(130px, 1fr))', gap: 12 }}>
                <Stat label="Customers" value={entitiesData.counts.customers.toLocaleString()} />
                <Stat label="Devices" value={entitiesData.counts.devices.toLocaleString()} />
                <Stat label="Instruments" value={entitiesData.counts.instruments.toLocaleString()} />
                <Stat label="IP Addresses" value={entitiesData.counts.ip_addresses.toLocaleString()} />
                <Stat label="Total Entities" value={entitiesData.total_entities.toLocaleString()} accent="var(--accent-bright)" />
              </div>

              {/* Ratios & Graph Concentration Metrics */}
              <div
                style={{
                  background: 'rgba(255, 255, 255, 0.02)',
                  border: '1px solid var(--border)',
                  borderRadius: 'var(--radius-sm)',
                  padding: '14px 16px',
                  display: 'grid',
                  gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))',
                  gap: 12,
                }}
              >
                <div>
                  <div style={{ fontSize: '10px', color: 'var(--text-muted)', textTransform: 'uppercase' }}>
                    Instruments / Customer
                  </div>
                  <div style={{ fontFamily: 'var(--font-mono)', fontSize: 'var(--text-sm)', fontWeight: 700, marginTop: 2 }}>
                    {entitiesData.instruments_per_customer !== null ? entitiesData.instruments_per_customer.toFixed(2) : '—'}
                  </div>
                </div>

                <div>
                  <div style={{ fontSize: '10px', color: 'var(--text-muted)', textTransform: 'uppercase' }}>
                    Transactions / Device
                  </div>
                  <div style={{ fontFamily: 'var(--font-mono)', fontSize: 'var(--text-sm)', fontWeight: 700, marginTop: 2 }}>
                    {entitiesData.transactions_per_device !== null ? entitiesData.transactions_per_device.toFixed(2) : '—'}
                  </div>
                </div>

                <div>
                  <div style={{ fontSize: '10px', color: 'var(--text-muted)', textTransform: 'uppercase' }}>
                    Largest Cluster Volume Share
                  </div>
                  <div style={{ fontFamily: 'var(--font-mono)', fontSize: 'var(--text-sm)', fontWeight: 700, marginTop: 2 }}>
                    {entitiesData.largest_cluster_volume_share !== null ? `${(entitiesData.largest_cluster_volume_share * 100).toFixed(1)}%` : '—'}
                  </div>
                </div>

                <div>
                  <div style={{ fontSize: '10px', color: 'var(--text-muted)', textTransform: 'uppercase' }}>
                    Bipartite Graph Gini
                  </div>
                  <div style={{ fontFamily: 'var(--font-mono)', fontSize: 'var(--text-sm)', fontWeight: 700, marginTop: 2 }}>
                    {entitiesData.bipartite_gini !== null ? entitiesData.bipartite_gini.toFixed(3) : '—'}
                  </div>
                </div>
              </div>

              {/* Entity Graph Visualizer */}
              {runDetail?.entity_graph && (
                <div style={{ marginTop: 8 }}>
                  <EntityGraph graph={runDetail.entity_graph} />
                </div>
              )}
            </div>
          )}
        </Card>
      )}

      {/* ----------------- Sub-Tab 3: Extracted Features Vector ----------------- */}
      {activeSubTab === 'features' && (
        <Card style={{ display: 'grid', gap: 16 }}>
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
            <div>
              <h3 style={{ fontSize: 'var(--text-md)', fontWeight: 700 }}>Extracted Feature Vector by Family</h3>
              <p style={{ fontSize: 'var(--text-xs)', color: 'var(--text-secondary)', marginTop: 4 }}>
                Real values calculated during the window scoring run. Includes deviation from historical median (MAD).
              </p>
            </div>
            {featuresData && (
              <span
                style={{
                  fontFamily: 'var(--font-mono)',
                  fontSize: 'var(--text-xs)',
                  color: 'var(--accent-bright)',
                }}
              >
                {featuresData.model_feature_count} model inputs · {featuresData.evidence_feature_count} evidence features
              </span>
            )}
          </div>

          {featuresLoading && !featuresData ? (
            <LoadingBlock label="Loading feature families…" rows={6} />
          ) : !featuresData ? (
            <EmptyState title="No features loaded" description="Click to load features for this run." />
          ) : (
            <div style={{ display: 'grid', gap: 16 }}>
              {Object.entries(featuresData.families).map(([familyKey, features]) => (
                <div
                  key={familyKey}
                  style={{
                    background: 'rgba(255, 255, 255, 0.02)',
                    border: '1px solid var(--border)',
                    borderRadius: 'var(--radius-sm)',
                    overflow: 'hidden',
                  }}
                >
                  <div
                    style={{
                      padding: '8px 14px',
                      background: 'rgba(255, 255, 255, 0.03)',
                      borderBottom: '1px solid var(--border)',
                      fontWeight: 700,
                      fontSize: 'var(--text-xs)',
                      fontFamily: 'var(--font-mono)',
                      color: 'var(--accent-bright)',
                    }}
                  >
                    Family {familyKey} ({features.length} features)
                  </div>
                  <div style={{ padding: '8px 14px', display: 'grid', gap: 8 }}>
                    {features.map((f) => (
                      <div
                        key={f.feature_id}
                        style={{
                          display: 'flex',
                          alignItems: 'center',
                          justifyContent: 'space-between',
                          fontSize: 'var(--text-xs)',
                          fontFamily: 'var(--font-mono)',
                          padding: '4px 0',
                          borderBottom: '1px solid rgba(255, 255, 255, 0.03)',
                        }}
                      >
                        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                          <span style={{ color: 'var(--text-primary)', fontWeight: 600 }}>{f.feature_id}</span>
                          {f.is_model_input && (
                            <span
                              style={{
                                fontSize: '9px',
                                background: 'rgba(59, 130, 246, 0.15)',
                                color: 'var(--accent-bright)',
                                padding: '1px 5px',
                                borderRadius: 3,
                              }}
                            >
                              MODEL INPUT
                            </span>
                          )}
                        </div>

                        <div style={{ display: 'flex', alignItems: 'center', gap: 14 }}>
                          <span style={{ color: 'var(--text-primary)', fontWeight: 700 }}>
                            {f.value.toFixed(3)}
                          </span>
                          {f.deviation_mad !== null && (
                            <span
                              style={{
                                fontSize: '11px',
                                color:
                                  Math.abs(f.deviation_mad) > 3
                                    ? 'var(--color-critical)'
                                    : 'var(--text-muted)',
                              }}
                            >
                              {f.deviation_mad > 0 ? `+${f.deviation_mad.toFixed(1)} MAD` : `${f.deviation_mad.toFixed(1)} MAD`}
                            </span>
                          )}
                        </div>
                      </div>
                    ))}
                  </div>
                </div>
              ))}
            </div>
          )}
        </Card>
      )}

      {/* ----------------- Transaction Detail Side Drawer ----------------- */}
      {selectedTx && (
        <div
          style={{
            position: 'fixed',
            top: 0,
            right: 0,
            bottom: 0,
            width: 'min(480px, 90vw)',
            background: 'var(--surface-1)',
            borderLeft: '1px solid var(--border)',
            boxShadow: '-8px 0 30px rgba(0, 0, 0, 0.5)',
            zIndex: 9999,
            padding: 'var(--sp-5)',
            overflowY: 'auto',
            display: 'grid',
            gridTemplateRows: 'auto 1fr',
            gap: 16,
          }}
        >
          {/* Drawer Header */}
          <div
            style={{
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'space-between',
              paddingBottom: 12,
              borderBottom: '1px solid var(--border)',
            }}
          >
            <div>
              <div style={{ fontSize: '10px', color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.04em' }}>
                Synthetic Transaction Inspector
              </div>
              <h3 style={{ fontSize: 'var(--text-md)', fontWeight: 700, fontFamily: 'var(--font-mono)', marginTop: 2 }}>
                {selectedTx.transaction_id}
              </h3>
            </div>
            <button
              onClick={() => setSelectedTx(null)}
              style={{
                background: 'rgba(255, 255, 255, 0.05)',
                border: '1px solid var(--border)',
                borderRadius: '50%',
                width: 32,
                height: 32,
                display: 'grid',
                placeItems: 'center',
                color: 'var(--text-primary)',
                cursor: 'pointer',
              }}
            >
              <X size={16} />
            </button>
          </div>

          {/* Drawer Body */}
          <div style={{ display: 'grid', gap: 14 }}>
            <div>
              <div style={{ fontSize: '10px', color: 'var(--text-muted)', textTransform: 'uppercase' }}>
                Timestamp
              </div>
              <div style={{ fontFamily: 'var(--font-mono)', fontSize: 'var(--text-xs)', marginTop: 3 }}>
                {new Date(selectedTx.timestamp).toUTCString()}
              </div>
            </div>

            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 10 }}>
              <div>
                <div style={{ fontSize: '10px', color: 'var(--text-muted)', textTransform: 'uppercase' }}>
                  Amount
                </div>
                <div style={{ fontFamily: 'var(--font-mono)', fontSize: 'var(--text-sm)', fontWeight: 700, marginTop: 3 }}>
                  ₹{Number(selectedTx.amount).toFixed(2)} {selectedTx.currency}
                </div>
              </div>

              <div>
                <div style={{ fontSize: '10px', color: 'var(--text-muted)', textTransform: 'uppercase' }}>
                  Outcome Status
                </div>
                <div style={{ fontFamily: 'var(--font-mono)', fontSize: 'var(--text-xs)', marginTop: 3 }}>
                  {selectedTx.outcome_status || 'None'}{' '}
                  {selectedTx.outcome_failure_code ? `(${selectedTx.outcome_failure_code})` : ''}
                </div>
              </div>
            </div>

            <div>
              <div style={{ fontSize: '10px', color: 'var(--text-muted)', textTransform: 'uppercase' }}>
                Ground Truth Label
              </div>
              <div style={{ marginTop: 4 }}>
                <span
                  style={{
                    display: 'inline-flex',
                    alignItems: 'center',
                    gap: 6,
                    padding: '3px 8px',
                    borderRadius: 4,
                    fontSize: '11px',
                    fontFamily: 'var(--font-mono)',
                    fontWeight: 700,
                    background: selectedTx.ground_truth_is_abusive
                      ? 'rgba(255, 46, 76, 0.15)'
                      : 'rgba(16, 185, 129, 0.15)',
                    color: selectedTx.ground_truth_is_abusive
                      ? 'var(--color-critical)'
                      : 'var(--color-safe)',
                    border: `1px solid ${
                      selectedTx.ground_truth_is_abusive
                        ? 'rgba(255, 46, 76, 0.3)'
                        : 'rgba(16, 185, 129, 0.3)'
                    }`,
                  }}
                >
                  {selectedTx.ground_truth_is_abusive ? 'ABUSIVE TRANSACTION' : 'BENIGN TRANSACTION'}
                </span>
                <p style={{ fontSize: '10px', color: 'var(--text-muted)', marginTop: 4 }}>
                  Generator ground truth for scenario: {selectedTx.ground_truth_scenario_id}
                </p>
              </div>
            </div>

            <div
              style={{
                background: 'rgba(255, 255, 255, 0.02)',
                border: '1px solid var(--border)',
                borderRadius: 6,
                padding: 12,
                display: 'grid',
                gap: 8,
              }}
            >
              <div style={{ fontSize: '11px', fontWeight: 600, color: 'var(--text-secondary)' }}>
                Synthetic Entity Identifiers
              </div>
              <div style={{ fontSize: '11px', fontFamily: 'var(--font-mono)', color: 'var(--text-muted)' }}>
                Customer: <span style={{ color: 'var(--text-primary)' }}>{selectedTx.customer_id || 'null'}</span>
              </div>
              <div style={{ fontSize: '11px', fontFamily: 'var(--font-mono)', color: 'var(--text-muted)' }}>
                Device FP: <span style={{ color: 'var(--text-primary)' }}>{selectedTx.device_id || 'null'}</span>
              </div>
              <div style={{ fontSize: '11px', fontFamily: 'var(--font-mono)', color: 'var(--text-muted)' }}>
                Instrument Token:{' '}
                <span style={{ color: 'var(--text-primary)' }}>{selectedTx.instrument_token || 'null'}</span>
              </div>
              <div style={{ fontSize: '11px', fontFamily: 'var(--font-mono)', color: 'var(--text-muted)' }}>
                IP Token: <span style={{ color: 'var(--text-primary)' }}>{selectedTx.ip_token || 'null'}</span>
              </div>
            </div>

            <div
              style={{
                fontSize: '11px',
                color: 'var(--text-muted)',
                background: 'rgba(59, 130, 246, 0.05)',
                borderLeft: '2px solid var(--accent)',
                padding: 8,
                lineHeight: 1.5,
              }}
            >
              Privacy & Provenance: Identifiers shown are generator-produced synthetic hashes. No real card numbers (PANs) or cardholder data are ever stored or returned by the Veyra API.
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
