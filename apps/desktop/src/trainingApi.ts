export type TrainingBar = {index: number; week: number; label: string; open: number; high: number; low: number; close: number; volume: number}
export type TrainingMetrics = {equity: number; return_pct: number; benchmark_pct: number; excess_pct: number; max_drawdown_pct: number; fees: number; position_pct: number; trades: number}
export type TrainingAction = {step: number; index: number; action: 'buy' | 'sell' | 'hold'; fraction: number; shares: number; price: number | null; fee: number; status: string; reason: string; note: string}
export type TrainingSession = {
  id: string; status: 'active' | 'completed' | 'abandoned'; revision: number; created_at: string; pool: string; total_steps: number; step: number; warmup: number; initial_cash: number; cash: number; shares: number; sellable_shares: number; bars: TrainingBar[]; actions: TrainingAction[];
  equity_curve: {step: number; equity: number; benchmark: number}[]; metrics: TrainingMetrics; rules_version: string; data_source: string; cache_used: boolean;
  reveal: {stock_code: string; stock_name: string; start_date: string; end_date: string; fetched_at: string; notes: string[]} | null
}
export type TrainingOverview = {
  pools: {id: string; count: number}[]; cache_count: number; active_id: string | null;
  summary: {completed: number; win_rate: number | null; average_return: number | null; best_return: number | null};
  history: {id: string; status: string; created_at: string; step: number; total_steps: number; stock_name: string; metrics: TrainingMetrics}[]
}
async function request<T>(path = '', body?: unknown): Promise<T> {
  const response = await fetch(`/api/training${path}`, body ? {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body)} : undefined)
  if (!response.ok) {
    const data = await response.json().catch(() => ({}))
    throw new Error(typeof data.detail === 'string' ? data.detail : `请求失败 (${response.status})`)
  }
  return response.json() as Promise<T>
}
export const trainingApi = {
  overview: () => request<TrainingOverview>(),
  get: (id: string) => request<TrainingSession>(`/sessions/${encodeURIComponent(id)}`),
  create: (pool: string, steps: number) => request<TrainingSession>('/sessions', {pool, steps}),
  act: (session: TrainingSession, action: string, fraction: number, note: string) => request<TrainingSession>(`/sessions/${session.id}/actions`, {revision: session.revision, action, fraction, note}),
}
