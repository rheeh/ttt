import { useMemo } from 'react'
import { Activity, RefreshCw, TrendingDown, TrendingUp } from 'lucide-react'
import type { Candidate, DataSourceHealthResponse, MarketReview, MarketReviewRun, PerformanceVerification } from './types'

type ReviewProps = { review: MarketReview | null; runs: MarketReviewRun[]; selectedRunId?: number; loading: boolean; onRefresh: (runId?: number) => void; onOpenStock: (code: string) => void }

const pct = (value?: number) => value == null ? '—' : `${value > 0 ? '+' : ''}${value.toFixed(2)}%`

export function MarketReviewPage({review, runs, selectedRunId, loading, onRefresh, onOpenStock}: ReviewProps) {
  return <>
    <header><div><p className="eyebrow">MARKET REVIEW</p><h1>市场复盘</h1><p>读取最近一次参考池扫描，观察市场广度、行业强弱和评分集中度。</p></div><button className="icon-btn" onClick={() => onRefresh(selectedRunId ?? review?.run_id)} disabled={loading}>{loading ? <RefreshCw className="spin" /> : <RefreshCw />}</button></header>
    {!review?.run_id ? <section className="panel review-empty"><Activity /><h2>还没有可复盘的扫描</h2><p>先在研究台运行一次参考池扫描，复盘会自动读取本地 SQLite 快照。</p></section> : <>
      <section className="review-meta"><label>历史扫描<select value={selectedRunId ?? review.run_id} onChange={event => onRefresh(Number(event.target.value))}>{runs.map(run => <option key={run.run_id} value={run.run_id}>#{run.run_id} · {new Date(run.completed_at).toLocaleString('zh-CN')}</option>)}</select></label><span>{review.source}</span><button className="scan-button" onClick={() => onRefresh(selectedRunId ?? review.run_id)} disabled={loading}>{loading ? '刷新中…' : '刷新复盘'}</button></section>
      <section className="stats review-stats"><article><span>上涨 / 下跌</span><strong>{review.up_count} / {review.down_count}</strong><small>平盘 {review.flat_count}</small></article><article><span>市场广度</span><strong>{review.breadth_pct == null ? '—' : `${review.breadth_pct.toFixed(1)}%`}</strong><small>上涨股票占有涨跌数据样本</small></article><article><span>平均涨跌</span><strong className={(review.average_change_pct ?? 0) >= 0 ? 'positive' : 'negative'}>{pct(review.average_change_pct)}</strong><small>扫描样本平均</small></article><article><span>平均评分</span><strong>{review.average_score?.toFixed(1) ?? '—'}</strong><small>{review.scoreable} / {review.total} 可评分</small></article></section>
      <div className="review-grid"><section className="panel"><div className="panel-title"><h2>涨幅靠前</h2><span className="pill">Top 10</span></div><div className="review-list">{review.top_gainers.map(item => <button key={item.stock_code} onClick={() => onOpenStock(item.stock_code)}><span><strong>{item.stock_name}</strong><small>{item.stock_code} · {item.sector}</small></span><b className={(item.change_pct ?? 0) >= 0 ? 'positive' : 'negative'}>{pct(item.change_pct)}</b><em>{item.grade ?? '—'}</em></button>)}</div></section><section className="panel"><div className="panel-title"><h2>评分靠前</h2><span className="pill">Top 10</span></div><div className="review-list">{review.top_scores.map(item => <button key={item.stock_code} onClick={() => onOpenStock(item.stock_code)}><span><strong>{item.stock_name}</strong><small>{item.stock_code} · {item.sector}</small></span><b>{item.score ?? '—'}</b><em>{item.grade ?? '—'}</em></button>)}</div></section></div>
      <section className="panel"><div className="panel-title"><h2>行业横截面</h2><span className="pill">按平均涨跌排序</span></div><div className="sector-review-table"><div className="sector-review-row sector-review-header"><span>行业</span><span>样本</span><span>上涨</span><span>平均涨跌</span><span>可评分</span><span>平均分</span></div>{review.sectors.map(item => <div className="sector-review-row" key={item.sector}><span>{item.sector}</span><span>{item.count}</span><span>{item.up_count}</span><span className={(item.average_change_pct ?? 0) >= 0 ? 'positive' : 'negative'}>{pct(item.average_change_pct)}</span><span>{item.scoreable}</span><span>{item.average_score?.toFixed(1) ?? '—'}</span></div>)}</div></section>
      <section className="review-callout"><TrendingUp /><span>轮动池 {review.rotation_pool_codes.length} 只：{review.rotation_pool_codes.slice(0, 8).join('、') || '暂无'}</span><TrendingDown /></section>
    </>}
  </>
}

type HealthProps = { health: DataSourceHealthResponse | null; testing: boolean; onTest: () => void; onRefresh: () => void }

export function SourceHealthPage({health, testing, onTest, onRefresh}: HealthProps) {
  return <>
    <header><div><p className="eyebrow">DATA SOURCES</p><h1>数据源状态</h1><p>区分已安装、接口可访问和数据有效；失败时保留最近一次成功时间。</p></div><button className="icon-btn" onClick={onRefresh}><RefreshCw /></button></header>
    <section className="review-meta"><span>最近检查：{health?.checked_at ? new Date(health.checked_at).toLocaleString('zh-CN') : '尚未检查'}</span><span>本机数据源诊断</span><button className="scan-button" onClick={onTest} disabled={testing}>{testing ? '测试中…' : '测试全部数据源'}</button></section>
    {!health?.sources.length ? <section className="panel review-empty"><Activity /><h2>尚未进行数据源测试</h2><p>点击“测试全部数据源”检查腾讯、AKShare 和东方财富接口。</p></section> : <section className="source-health-grid">{health.sources.map(item => <article className="panel source-health-card" key={item.source}><div className="panel-title"><h2>{item.source}</h2><span className={`source-badge ${item.status}`}>{item.status === 'ok' ? '可用' : item.status === 'unavailable' ? '未安装' : item.status === 'degraded' ? '部分有效' : '失败'}</span></div><div className="health-flags"><span className={item.installed ? 'yes' : 'no'}>安装 {item.installed ? '是' : '否'}</span><span className={item.accessible ? 'yes' : 'no'}>可访问 {item.accessible ? '是' : '否'}</span><span className={item.valid ? 'yes' : 'no'}>数据有效 {item.valid ? '是' : '否'}</span></div><div className="health-detail"><span>分类：{item.category}</span><span>响应：{item.response_ms == null ? '—' : `${item.response_ms} ms`}</span><span>最近成功：{item.last_success_at ? new Date(item.last_success_at).toLocaleString('zh-CN') : '暂无'}</span></div>{item.error && <p className="source-note">{item.error}</p>}</article>)}</section>}
  </>
}

type PerformanceProps = { candidates: Candidate[]; summary?: PerformanceVerification; verifying: boolean; onVerify: () => void; onRefresh: () => void }

export function PerformanceReviewPage({candidates, summary: verification, verifying, onVerify, onRefresh}: PerformanceProps) {
  const summary = useMemo(() => {
    const outcomes = candidates.flatMap(item => item.performance ?? [])
    return {verified: outcomes.filter(item => item.status === 'verified').length, pending: outcomes.filter(item => item.status === 'pending').length, unavailable: outcomes.filter(item => item.status === 'unavailable').length}
  }, [candidates])
  return <>
    <header><div><p className="eyebrow">PERFORMANCE CHECK</p><h1>回测核验</h1><p>核验长期预选股在 1、5、20 个交易日后的实际表现，不把待验证结果当成收益。</p></div><button className="icon-btn" onClick={onRefresh}><RefreshCw /></button></header>
    <section className="review-meta"><span>已保存候选 {candidates.length} 只</span><span>已验证 {verification?.verified ?? summary.verified}</span><span>待核验 {verification?.pending ?? summary.pending}</span><span>不可用 {verification?.unavailable ?? summary.unavailable}</span><button className="scan-button" onClick={onVerify} disabled={verifying}>{verifying ? '核验中…' : '运行核验'}</button></section>
    {verification?.horizon_summary.length ? <section className="stats performance-stats">{verification.horizon_summary.map(item => <article key={item.horizon}><span>{item.horizon} 胜率</span><strong>{item.win_rate_pct == null ? '—' : `${item.win_rate_pct.toFixed(1)}%`}</strong><small>{item.verified} 个已验证 · 平均 {item.average_return_pct == null ? '—' : `${item.average_return_pct > 0 ? '+' : ''}${item.average_return_pct.toFixed(2)}%`}</small></article>)}</section> : null}
    <section className="panel performance-panel"><div className="panel-title"><h2>候选表现</h2><span className="pill">本机行情快照</span></div>{candidates.length === 0 ? <div className="review-empty compact"><Activity /><p>还没有预选股。先从研究台试算或批量加入候选。</p></div> : <div className="performance-table"><div className="performance-row performance-header"><span>股票</span><span>入选价</span><span>1日</span><span>5日</span><span>20日</span><span>状态</span></div>{candidates.map(item => <div className="performance-row" key={item.id}><span><strong>{item.stock_name}</strong><small>{item.stock_code} · {new Date(item.selected_at).toLocaleDateString('zh-CN')}</small></span><span>¥{item.selected_price.toFixed(2)}</span>{(['1d', '5d', '20d'] as const).map(horizon => { const outcome = item.performance?.find(entry => entry.horizon === horizon); return <span className={outcome?.return_pct != null ? outcome.return_pct >= 0 ? 'positive' : 'negative' : ''} key={horizon}>{outcome?.return_pct == null ? outcome?.status === 'pending' ? '待核验' : '—' : pct(outcome.return_pct)}</span> })}<span className="status">{item.status === 'new' ? '新发现' : item.status}</span></div>)}</div>}</section>
  </>
}
