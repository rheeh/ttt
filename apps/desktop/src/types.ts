export type ScoreInput = {
  stock_code: string; stock_name: string; sector: string; price: number;
  pe: number; pb: number; pe_percentile: number; pb_percentile: number;
  change_pct: number; turnover_pct: number; amplitude_pct: number;
  main_flow_ratio: number; sector_change_pct: number; quality_score: number;
  ma5?: number; ma10?: number; ma20?: number; in_rotation_pool: boolean;
}

export type Dimension = {name: string; label: string; score: number; reasons: string[]}
export type ScoreResult = {
  stock_code: string; stock_name: string; total_score: number; grade: 'S'|'A'|'B'|'C';
  eligible: boolean; rejected_reasons: string[]; dimensions: Dimension[];
  strategy_id: string; strategy_version: string;
  rule_fingerprint: string;
}
export type Candidate = ScoreResult & {
  id: number; selected_at: string; selected_price: number; status: string;
  source_name: string; reasons: string[]; note?: string;
  performance?: {candidate_id: number; horizon: '1d'|'5d'|'20d'; status: 'pending'|'verified'|'unavailable'; due_date: string; baseline_price: number; realized_price?: number; realized_trade_date?: string; return_pct?: number; benchmark_code?: string; benchmark_return_pct?: number; relative_return_pct?: number; measured_at?: string; source?: string; note?: string}[];
}

export type QuoteSnapshot = {
  stock_code: string; stock_name: string; price?: number; change_pct?: number;
  pe?: number; pb?: number; trade_at?: string; fetched_at: string; source: string;
  status: 'ok'|'degraded'|'error'; missing_fields: string[]; error?: string; fallback_reason?: string;
}
export type MarketScanItem = {
  preset: {code: string; name: string; sector: string; asset_type: 'stock'|'etf'};
  quote: QuoteSnapshot; score?: ScoreResult;
}
export type MarketScan = {
  started_at: string; completed_at: string; source: string; total: number;
  succeeded: number; degraded: number; failed: number; items: MarketScanItem[];
  scoreable: number; run_id?: number; rule_fingerprint: string; rotation_pool_codes: string[];
}
export type MarketReviewItem = {stock_code: string; stock_name: string; sector: string; price?: number; change_pct?: number; grade?: 'S'|'A'|'B'|'C'; score?: number; status: 'ok'|'degraded'|'error'}
export type MarketReview = {run_id?: number; as_of?: string; source: string; total: number; succeeded: number; degraded: number; failed: number; scoreable: number; up_count: number; down_count: number; flat_count: number; breadth_pct?: number; sample_up_rate_pct?: number; change_sample_count: number; average_change_pct?: number; average_score?: number; strategy_average_score?: number; strategy_scoreable: number; rotation_pool_codes: string[]; top_gainers: MarketReviewItem[]; top_scores: MarketReviewItem[]; sectors: {sector: string; count: number; average_change_pct?: number; up_count: number; scoreable: number; average_score?: number}[]; scope: 'reference_pool'|'all_a_market'; pool_name: string; pool_version: string; pool_component_count: number; transaction_date?: string; scan_started_at?: string; scan_completed_at?: string; coverage_count: number; coverage_total: number; coverage_pct?: number; data_status: 'ok'|'degraded'|'error'; degraded_reasons: string[]}
export type MarketReviewRun = {run_id: number; completed_at: string; source: string; total: number; scoreable: number; average_change_pct?: number; scope: 'reference_pool'|'all_a_market'; pool_name: string; pool_version: string; pool_component_count: number; transaction_date?: string; coverage_pct?: number; data_status: 'ok'|'degraded'|'error'}
export type DataSourceHealth = {source: string; category: string; installed: boolean; accessible: boolean; valid: boolean; status: 'ok'|'degraded'|'error'|'unavailable'; checked_at: string; response_ms?: number; last_success_at?: string; error?: string; details?: string}
export type DataSourceHealthResponse = {checked_at?: string; sources: DataSourceHealth[]}
export type PerformanceVerification = {as_of: string; processed: number; verified: number; pending: number; unavailable: number; outcomes: Candidate['performance']; horizon_summary: {horizon: '1d'|'5d'|'20d'; samples: number; verified: number; wins: number; win_rate_pct?: number; average_return_pct?: number; median_return_pct?: number; benchmark_code?: string; average_relative_return_pct?: number}[]}

export type AnalysisReport = {
  report_id?: number; trade_date?: string; snapshot_reason?: 'legacy_run'|'manual'|'meaningful_change'|'daily_close'; snapshot_note?: string; content_fingerprint?: string; created_at: string; stock_code: string; stock_name: string; sector: string; asset_type: 'stock'|'etf';
  source: string; status: 'ok'|'degraded'|'error'; missing_fields: string[];
  core_status: 'ok'|'degraded'|'error'; core_missing_fields: string[];
  enrichment_status: 'ok'|'degraded'|'stale'|'error'|'not_applicable'; enrichment_missing_fields: string[]; enrichment_stale_fields: string[];
  legacy_score_status: 'ok'|'degraded'|'error'; legacy_missing_fields: string[];
  quote: {price?: number; change_pct?: number; pe?: number; pb?: number; turnover_pct?: number; amplitude_pct?: number; trade_at?: string; fetched_at?: string; source?: string; status?: string};
  technical: {ma5?: number; ma10?: number; ma20?: number; ma60?: number; rsi14?: number; support20?: number; resistance20?: number; high52w?: number; low52w?: number; volume_ratio?: number; volume_ratio_basis?: 'completed_day'|'intraday_unavailable'; trend: string; bar_count: number; atr14?: number; bollinger_width?: number; return_20d_pct?: number; return_60d_pct?: number; macd?: {dif: number; dea: number; hist: number; golden_cross: boolean; death_cross: boolean}};
  weekly: {ma5?: number; ma10?: number; ma20?: number; ma60?: number; rsi14?: number; trend: string; bar_count: number; macd?: {dif: number; dea: number; hist: number; golden_cross: boolean; death_cross: boolean}};
  rocket: {score: number; level: string; missing_fields: string[]; dimensions: {key: string; label: string; score: number; reasons: string[]; available: boolean}[]};
  zhixing_index: number; zhixing_level: string; zhixing_raw_score: number; raw_score: number; zhixing_confidence: number; confidence: number; factor_coverage: string; algorithm_version: string; rule_fingerprint: string;
  factors: {key: string; label: string; score: number; reason: string; available: boolean; source: string}[];
  radar: {key: string; label: string; score: number; factor_keys: string[]}[];
  trend_series: {trade_date: string; close: number; ma20?: number}[];
  bars: {trade_date: string; open: number; close: number; high: number; low: number; volume: number}[];
  weekly_bars: {trade_date: string; open: number; close: number; high: number; low: number; volume: number}[];
  diagnosis: {summary: string; position: string; positive_evidence: string[]; risk_evidence: string[]; conflicts: string[]; reassess_conditions: string[]};
  fund_flow: {trade_date?: string; main_inflow?: number; main_flow_ratio?: number; main_inflow_5d?: number; main_inflow_10d?: number; ratio_kind?: string; small_inflow?: number; medium_inflow?: number; large_inflow?: number; super_inflow?: number; source: string; endpoint?: string; fetched_at: string; status: string; error?: string; data_age_seconds?: number; cache_used?: boolean; cache_expired?: boolean};
  finance: {report_date?: string; notice_date?: string; revenue?: number; revenue_yoy?: number; profit?: number; profit_yoy?: number; roe?: number; source: string; fetched_at: string; status: string; error?: string; data_age_seconds?: number; cache_used?: boolean; cache_expired?: boolean};
  industry: {name?: string; rank?: number; total?: number; change_pct?: number; main_inflow?: number; constituent_count?: number; up_count?: number; down_count?: number; average_amount?: number; leader_name?: string; leader_change_pct?: number; source: string; endpoint?: string; fetched_at: string; status: string; error?: string; data_age_seconds?: number; cache_used?: boolean; cache_expired?: boolean};
  news: {items: {title: string; snippet: string; source_name: string; published_at: string; url: string; sentiment: 'bull'|'bear'|'neutral'}[]; source: string; fetched_at: string; status: string; error?: string; data_age_seconds?: number; cache_used?: boolean; cache_expired?: boolean};
  freshness: Record<string, {key?: string; state: 'fresh'|'warning'|'stale'|'expired'|'error'|'unknown'; fetched_at?: string; trade_at?: string; trade_date?: string; report_date?: string; latest_trade_date?: string; expected_trade_date?: string; bar_count?: number; note?: string; age_seconds?: number; warning_threshold_seconds?: number; cache_used?: boolean; cache_expired?: boolean}>;
  advice: {action: string; category: string; summary: string; risk_level: string; operations: string[]; triggered_conditions: string[]; unmet_conditions: string[]; invalidation_conditions: string[]; data_confidence: number; review_after: string; zones: {name: string; low: number; high: number; action: string; tone: string}[]};
}

export type CompareResponse = {reports: AnalysisReport[]; errors: Record<string, string>}
export type AnalysisSnapshotResponse = {report: AnalysisReport; saved: boolean; message: string}

export type StockSearchResult = {code: string; name: string; market?: string; asset_type: 'stock'|'etf'; source: string}
export type WatchlistItem = {id: number; code: string; name: string; sector: string; asset_type: 'stock'|'etf'; added_at: string; source: string}

export type IndustryRadarItem = {
  name: string; stage: '下跌中'|'低位企稳'|'底部改善'|'突破确认'|'高位拥挤'|'数据不足'; score?: number;
  low_position_score?: number; deceleration_score?: number; breadth_score?: number;
  volume_price_score?: number; relative_strength_score?: number; change_pct?: number;
  return_5d_pct?: number; return_20d_pct?: number; drawdown_1y_pct?: number;
  up_count?: number; down_count?: number; constituent_count?: number; coverage_pct?: number;
  evidence: string[]; risks: string[]; status: 'ok'|'degraded'|'error'; source: string; fetched_at: string;
}
export type IndustryRadar = {
  scope: 'all_industries'; snapshot_at: string; source: string; data_status: 'ok'|'degraded'|'error';
  coverage_count: number; coverage_total: number; coverage_pct?: number; confirmation_days: number;
  rule_version: string; building: IndustryRadarItem[]; confirmed: IndustryRadarItem[];
  overheated: IndustryRadarItem[]; other: IndustryRadarItem[]; degraded_reasons: string[];
}
