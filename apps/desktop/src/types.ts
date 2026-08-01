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
  performance?: {horizon: '1d'|'5d'|'20d'; status: string; return_pct?: number; due_date: string}[];
}

export type QuoteSnapshot = {
  stock_code: string; stock_name: string; price?: number; change_pct?: number;
  pe?: number; pb?: number; trade_at?: string; fetched_at: string; source: string;
  status: 'ok'|'degraded'|'error'; missing_fields: string[]; error?: string;
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

export type AnalysisReport = {
  report_id?: number; created_at: string; stock_code: string; stock_name: string; sector: string;
  source: string; status: 'ok'|'degraded'|'error'; missing_fields: string[];
  quote: {price?: number; change_pct?: number; pe?: number; pb?: number; turnover_pct?: number; amplitude_pct?: number; trade_at?: string};
  technical: {ma5?: number; ma10?: number; ma20?: number; ma60?: number; rsi14?: number; support20?: number; resistance20?: number; high52w?: number; low52w?: number; volume_ratio?: number; trend: string; bar_count: number; macd?: {dif: number; dea: number; hist: number; golden_cross: boolean; death_cross: boolean}};
  rocket: {score: number; level: string; missing_fields: string[]; dimensions: {key: string; label: string; score: number; reasons: string[]; available: boolean}[]};
  advice: {action: string; category: string; summary: string; risk_level: string; operations: string[]; zones: {name: string; low: number; high: number; action: string; tone: string}[]};
}
