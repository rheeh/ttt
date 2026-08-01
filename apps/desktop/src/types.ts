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
}
export type Candidate = ScoreResult & {
  id: number; selected_at: string; selected_price: number; status: string;
  source_name: string; reasons: string[]; note?: string;
}

