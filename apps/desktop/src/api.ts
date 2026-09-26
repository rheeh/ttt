import type { AnalysisReport, AnalysisSnapshotResponse, Candidate, CompareResponse, DataSourceHealthResponse, IndustryAlert, IndustryDetail, IndustryRadar, IndustrySignalVerification, IndustryWatchItem, MarketScan, PerformanceVerification, ScoreInput, ScoreResult, StockSearchResult, WatchlistItem } from './types'

async function parse<T>(response: Response): Promise<T> {
  if (!response.ok) {
    const body = await response.json().catch(() => ({}))
    const detail = body.detail?.message ?? body.detail
    throw new Error(typeof detail === 'string' ? detail : Array.isArray(detail) ? '输入信息格式不正确，请检查后重试。' : `请求失败 (${response.status})`)
  }
  return response.json() as Promise<T>
}

export const api = {
  score: (input: ScoreInput) => fetch('/api/score', {
    method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(input),
  }).then(parse<ScoreResult>),
  listCandidates: () => fetch('/api/candidates').then(parse<{candidates: Candidate[]; total: number}>),
  saveCandidate: (input: ScoreInput) => fetch('/api/candidates', {
    method: 'POST', headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({score_input: input, source_type: 'manual', source_name: '手动试算'}),
  }).then(parse<Candidate>),
  addAnalysisSignal: (report: AnalysisReport, plannedHorizon: '1d'|'5d'|'20d'|'60d' = '20d', note?: string) => fetch('/api/candidates/from-analysis', {
    method: 'POST', headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({report, planned_horizon: plannedHorizon, note}),
  }).then(parse<Candidate>),
  scanPool: () => fetch('/api/market/scan', {
    method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({include_etfs: false}),
  }).then(parse<MarketScan>),
  saveScanCandidates: (runId: number, limit = 10) => fetch('/api/market/scan/candidates', {
    method: 'POST', headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({run_id: runId, limit, min_grade: 'B'}),
  }).then(parse<{created: number; skipped: number}>),
  industryRadar: (refresh = false) => fetch(refresh ? '/api/market/industry-radar/refresh' : '/api/market/industry-radar', {method: refresh ? 'POST' : 'GET'}).then(parse<IndustryRadar>),
  industryBackfill: () => fetch('/api/market/industry-radar/backfill', {method: 'POST'}).then(parse<IndustryRadar>),
  industryTasks: () => fetch('/api/market/industry-radar/tasks').then(parse<{running: boolean; last_error?: string; last_success_at?: string; attempts_today: number; max_attempts_per_day: number; next_retry_at?: string; calendar: {known: boolean; coverage_end: string; expected_trade_date?: string}}>),
  industryDetail: (industryId: string) => fetch(`/api/market/industry-radar/${encodeURIComponent(industryId)}`).then(parse<IndustryDetail>),
  verifyIndustrySignals: () => fetch('/api/market/industry-radar/signals/verify', {method: 'POST'}).then(parse<IndustrySignalVerification>),
  listIndustryWatches: () => fetch('/api/market/industry-radar/watches').then(parse<IndustryWatchItem[]>),
  addIndustryWatch: (industryId: string) => fetch('/api/market/industry-radar/watches', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({industry_id: industryId})}).then(parse<IndustryWatchItem>),
  deleteIndustryWatch: (industryId: string) => fetch(`/api/market/industry-radar/watches/${encodeURIComponent(industryId)}`, {method: 'DELETE'}),
  industryAlerts: () => fetch('/api/market/industry-radar/alerts').then(parse<IndustryAlert[]>),
  verifyPerformance: () => fetch('/api/candidates/performance/verify', {method: 'POST'}).then(parse<PerformanceVerification>),
  sourceHealth: () => fetch('/api/health/sources').then(parse<DataSourceHealthResponse>),
  testSourceHealth: () => fetch('/api/health/sources/test', {method: 'POST'}).then(parse<DataSourceHealthResponse>),
  analyze: (stock: string, isHolding = false, positionCost?: number, signal?: AbortSignal) => fetch('/api/analysis', {
    method: 'POST', headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({stock, is_holding: isHolding, position_cost: positionCost || undefined}), signal,
  }).then(parse<AnalysisReport>),
  saveAnalysisSnapshot: (report: AnalysisReport, note?: string) => fetch('/api/analysis/snapshots', {
    method: 'POST', headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({report, reason: 'manual', note}),
  }).then(parse<AnalysisSnapshotResponse>),
  compareStocks: (stocks: string[], signal?: AbortSignal) => fetch('/api/analysis/compare', {
    method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({stocks}), signal,
  }).then(parse<CompareResponse>),
  listAnalyses: (stockCode?: string, limit = 20) => fetch(`/api/analysis?limit=${limit}${stockCode ? `&stock_code=${encodeURIComponent(stockCode)}` : ''}`).then(parse<AnalysisReport[]>),
  getAnalysis: (reportId: number) => fetch(`/api/analysis/${reportId}`).then(parse<AnalysisReport>),
  searchStocks: (query: string) => fetch(`/api/stocks/search?q=${encodeURIComponent(query)}`).then(parse<StockSearchResult[]>),
  listWatchlist: () => fetch('/api/watchlist').then(parse<WatchlistItem[]>),
  addWatchlist: (item: StockSearchResult) => fetch('/api/watchlist', {
    method: 'POST', headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({code: item.code, name: item.name, asset_type: item.asset_type}),
  }).then(parse<WatchlistItem>),
  deleteWatchlist: (code: string) => fetch(`/api/watchlist/${encodeURIComponent(code)}`, {method: 'DELETE'}).then(async response => { if (!response.ok) await parse(response) }),
}
