import type { Candidate, MarketScan, ScoreInput, ScoreResult } from './types'

async function parse<T>(response: Response): Promise<T> {
  if (!response.ok) {
    const body = await response.json().catch(() => ({}))
    throw new Error(body.detail?.message ?? body.detail ?? `请求失败 (${response.status})`)
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
  scanPool: () => fetch('/api/market/scan', {
    method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({include_etfs: false}),
  }).then(parse<MarketScan>),
}
