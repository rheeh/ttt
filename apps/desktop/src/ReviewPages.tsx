import { useEffect, useMemo, useRef, useState } from 'react'
import { Activity, RefreshCw, TrendingDown, TrendingUp } from 'lucide-react'
import { api } from './api'
import { RequestProgress } from './RequestProgress'
import type { Candidate, DataSourceHealthResponse, IndustryDetail, IndustryRadar, IndustryRadarItem, IndustrySignalVerification, MarketReview, MarketReviewRun, PerformanceVerification } from './types'

const radarPct = (value?: number) => value == null ? '—' : `${value > 0 ? '+' : ''}${value.toFixed(2)}%`

function RadarCard({item, onOpenStock, onOpenIndustry}: {item: IndustryRadarItem; onOpenStock: (code: string) => void; onOpenIndustry: (item: IndustryRadarItem) => void}) {
  return <article className="panel radar-card"><div className="panel-title"><div><button type="button" className="radar-title-button" onClick={() => onOpenIndustry(item)}><h3>{item.name}</h3><small>{item.stage} · {item.score == null ? '不可评分' : `${item.score.toFixed(0)}分`}</small></button></div><span className={`source-badge ${item.status}`}>{item.status === 'ok' ? '成分已取' : '部分数据'}</span></div><div className="radar-metrics"><span>近5日 <b className={(item.return_5d_pct ?? 0) >= 0 ? 'positive' : 'negative'}>{radarPct(item.return_5d_pct)}</b></span><span>近20日 <b className={(item.return_20d_pct ?? 0) >= 0 ? 'positive' : 'negative'}>{radarPct(item.return_20d_pct)}</b></span><span>成分 <b>{item.constituent_observed == null ? '—' : `${item.constituent_observed}/${item.constituent_count ?? '—'}`}</b></span></div>{item.history_coverage_pct != null && <p className="source-note">历史覆盖 {item.history_coverage_pct.toFixed(1)}% · 缺失 {item.history_missing_codes?.length ?? 0} 只 · 当前成分回推</p>}<div className="radar-evidence">{item.evidence.slice(0, 3).map(text => <span key={text}>{text}</span>)}</div>{item.constituents?.length ? <div className="radar-constituents">{item.constituents.slice(0, 5).map(stock => <button type="button" key={stock.code} onClick={() => onOpenStock(stock.code)}>{stock.name}<small>{stock.code} {radarPct(stock.change_pct)}</small></button>)}</div> : null}{item.risks.length > 0 && <p className="source-note">风险：{item.risks.slice(-2).join("；")}</p>}</article>
}

export function IndustryRadarPage({radar, loading, onRefresh, onOpenStock}: {radar: IndustryRadar | null; loading: boolean; onRefresh: () => void; onOpenStock: (code: string) => void}) {
  const [detail, setDetail] = useState<IndustryDetail | null>(null)
  const [detailLoading, setDetailLoading] = useState(false)
  const [signalVerification, setSignalVerification] = useState<IndustrySignalVerification | null>(null)
  const [signalLoading, setSignalLoading] = useState(false)
  const [backfillLoading, setBackfillLoading] = useState(false)
  const [taskStatus, setTaskStatus] = useState<Awaited<ReturnType<typeof api.industryTasks>> | null>(null)
  const [actionError,setActionError] = useState('')
  const [actionMessage,setActionMessage] = useState('')
  const [stageFilter,setStageFilter] = useState('全部')
  const [expandedStages,setExpandedStages] = useState<string[]>([])
  const detailRequest = useRef(0)
  const [alerts, setAlerts] = useState<import('./types').IndustryAlert[]>([])

  useEffect(() => {
    if (!radar) return
    void api.industryAlerts().then(setAlerts).catch(() => setAlerts([]))
  }, [radar])

  useEffect(() => {
    let active = true
    void api.industryTasks().then(value => { if (active) setTaskStatus(value) }).catch(() => { if (active) setTaskStatus(null) })
    return () => { active = false }
  }, [radar, backfillLoading])

  async function openIndustry(item: IndustryRadarItem) {
    if (!item.industry_id) {setActionError('这份旧版板块记录缺少行业标识，请在「数据状态与维护」中更新全量数据后再查看详情。'); return}
    const version = ++detailRequest.current
    setDetailLoading(true); setActionError('')
    try { const result = await api.industryDetail(item.industry_id); if (version === detailRequest.current) setDetail(result) } catch (reason) { if (version === detailRequest.current) setActionError(reason instanceof Error ? reason.message : '板块详情读取失败') } finally { if (version === detailRequest.current) setDetailLoading(false) }
  }

  async function verifySignals() {
    setSignalLoading(true); setActionError('')
    try { setSignalVerification(await api.verifyIndustrySignals()) } catch (reason) {setActionError(reason instanceof Error ? reason.message : '核验失败，请重试')} finally { setSignalLoading(false) }
  }

  async function backfillHistory() {
    setBackfillLoading(true); setActionError('')
    try { await api.industryBackfill(); onRefresh() } catch (reason) {setActionError(reason instanceof Error ? reason.message : '历史数据回填失败，请重试')} finally { setBackfillLoading(false) }
  }

  const sections: [string, string, IndustryRadarItem[]][] = [
    ['正在筑底', '低位、跌势放缓、内部开始改善；不代表即将上涨。', radar?.building ?? []],
    ['刚刚确认', '相对强度或关键位置出现确认，仍需观察持续性。', radar?.confirmed ?? []],
    ['高位拥挤', '短期涨幅和位置偏热，作为风险提示而非追涨名单。', radar?.overheated ?? []],
    ['待补历史数据', '当前快照已返回，但历史样本不足，不做阶段判断。', radar?.other ?? []],
  ]
  const stageCounts = sections.map(([title, , items]) => ({title, count: items.length}))

  return <>
    <header>
      <div><p className="eyebrow">INDUSTRY RADAR</p><h1>板块雷达</h1><p>查看板块所处阶段，按条件筛选，再进入成分股研究。</p></div>
      <button className="icon-btn" title="刷新板块数据" aria-label="刷新板块数据" onClick={onRefresh} disabled={loading}>{loading ? <RefreshCw className="spin" /> : <RefreshCw />}</button>
    </header>
    <details className="radar-tools"><summary>数据状态与维护 · 更新、回填、导出</summary>
    <section className="review-meta">
      <span>数据源：{radar?.source ?? '尚未获取'}</span>
      {taskStatus && <span>后台更新：{taskStatus.running ? '运行中' : taskStatus.last_error ? '待补采' : '待下次交易日调度'} · 今日尝试 {taskStatus.attempts_today}/{taskStatus.max_attempts_per_day} 次 · 最近成功 {taskStatus.last_success_at ? new Date(taskStatus.last_success_at).toLocaleString('zh-CN') : '尚无'}{!taskStatus.calendar.known ? ` · 交易日历待更新（覆盖至 ${taskStatus.calendar.coverage_end}）` : ''}</span>}
      {taskStatus?.last_error && <span role="status">{taskStatus.last_error}{taskStatus.next_retry_at && taskStatus.attempts_today < taskStatus.max_attempts_per_day ? ` · 下次自动重试不早于 ${new Date(taskStatus.next_retry_at).toLocaleTimeString('zh-CN')}` : ' · 可手动重试，或等待下一交易日'}</span>}
      <span>全板块成分覆盖 {radar?.coverage_count ?? 0}/{radar?.detail_board_count ?? 0}</span>
      <span>缓存历史 {radar?.history_snapshot_count ?? 0} 天 · 最近交易日 {radar?.last_success_trade_date ?? '—'}</span>
      <span>沪深300近20日 {radar?.benchmark_return_20d_pct == null ? '—' : radarPct(radar.benchmark_return_20d_pct)}</span>
      <button className="scan-button" onClick={onRefresh} disabled={loading}>{loading ? '更新中…' : '更新全量数据'}</button><button className="scan-button" onClick={() => void backfillHistory()} disabled={backfillLoading}>{backfillLoading ? '回填中…' : '回填120日历史'}</button><button className="scan-button" onClick={() => window.open('/api/market/industry-radar/export?format=csv', '_blank')}>导出CSV</button><button className="scan-button" onClick={() => window.open('/api/backup', '_blank')}>备份SQLite</button>
    </section>
    </details>
    {actionError && <div className="app-feedback error" role="alert"><Activity size={19}/><div><strong>操作暂时未完成</strong><span>{actionError}</span></div><button onClick={() => setActionError('')}>知道了</button></div>}
    {actionMessage && <p className="save-message" role="status">{actionMessage}</p>}
    {(loading || backfillLoading || signalLoading) && <RequestProgress label={backfillLoading ? '正在补充板块历史数据' : signalLoading ? '正在核验板块信号' : '正在读取板块数据'}/>}
    {!!radar?.degraded_reasons.length && <details className="radar-tools"><summary>部分板块数据尚不完整 · 查看 {radar.degraded_reasons.length} 项说明</summary><div className="review-meta">{radar.degraded_reasons.map(reason => <p className="source-note" key={reason}>{reason}</p>)}</div></details>}
    {alerts.length > 0 && <section className="panel radar-alerts"><div className="panel-title"><div><h2>阶段提醒</h2><small>仅显示自选板块的阶段变化，不把每日重复快照当提醒。</small></div><span className="pill">{alerts.length} 条</span></div>{alerts.map(alert => <button type="button" key={alert.industry_id || alert.name} onClick={() => { const selected = [...(radar?.ranking ?? []), ...(radar?.building ?? []), ...(radar?.confirmed ?? []), ...(radar?.overheated ?? []), ...(radar?.other ?? [])].find(item => item.industry_id === alert.industry_id); if (selected) void openIndustry(selected) }}><strong>{alert.name}</strong><span>{alert.stage} · {alert.direction === 'improving' ? '改善' : alert.direction === 'weakening' ? '转弱' : '变化'}</span><small>{alert.trade_date ?? '—'} · {alert.evidence[0] ?? '查看详情'}</small></button>)}</section>}
    {radar && <section className="panel radar-verification">
      <div className="panel-title"><div><h2>板块信号核验</h2><small>仅统计已满足阶段规则的信号；历史样本不足时不展示有效率。</small></div><button className="scan-button" onClick={() => void verifySignals()} disabled={signalLoading}>{signalLoading ? '核验中…' : '运行核验'}</button></div>
      {signalVerification ? <div className="radar-verification-grid">{signalVerification.horizon_summary.map(item => <article key={item.horizon}><span>{item.horizon}</span><strong>{item.verified ? (item.win_rate_pct?.toFixed(1) ?? '—') + '%' : '—'}</strong><small>{item.verified} 个已验证 · 均值 {item.average_return_pct == null ? '—' : (item.average_return_pct > 0 ? '+' : '') + item.average_return_pct.toFixed(2) + '%'} · MFE/MAE见详情接口</small></article>)}</div> : <p className="source-note">尚未运行板块信号核验。</p>}
    </section>}
    {!radar ? <section className="panel review-empty"><Activity /><h2>{loading ? '正在读取板块状态' : '还没有板块数据'}</h2><p>先从本机读取记录，也可以点击下方按钮获取行情。</p><button className="scan-button" disabled={loading} onClick={onRefresh}>获取板块数据</button></section> : <>
      <section className="radar-stage-summary">{stageCounts.map(item => <article className="panel" key={item.title}><span>{item.title}</span><strong>{item.count}</strong></article>)}</section>
      <details className="radar-tools"><summary>查看完整行业排名</summary>
      <section className="panel radar-ranking">
        <div className="panel-title"><div><h2>行业排名</h2><small>只对严格行业分类排序；点击板块名称进入详情。</small></div><span className="pill">按20日收益</span></div>
        <div className="radar-table"><div className="radar-table-row radar-table-header"><span>板块</span><span>阶段</span><span>5日</span><span>20日</span><span>20日超额</span><span>60日</span><span>MA20宽度</span><span>行情覆盖</span></div>
          {radar.ranking.map(item => <button type="button" className="radar-table-row" key={item.industry_id || item.name} onClick={() => void openIndustry(item)}>
            <span><strong>{item.name}</strong><small>{item.industry_id}</small></span><span>{item.stage}</span><span className={(item.return_5d_pct ?? 0) >= 0 ? 'positive' : 'negative'}>{radarPct(item.return_5d_pct)}</span><span className={(item.return_20d_pct ?? 0) >= 0 ? 'positive' : 'negative'}>{radarPct(item.return_20d_pct)}</span><span className={(item.relative_return_20d_pct ?? 0) >= 0 ? 'positive' : 'negative'}>{radarPct(item.relative_return_20d_pct)}</span><span className={(item.return_60d_pct ?? 0) >= 0 ? 'positive' : 'negative'}>{radarPct(item.return_60d_pct)}</span><span>{item.breadth_ma20_pct == null ? '—' : item.breadth_ma20_pct.toFixed(1) + '%'}</span><span>{item.coverage_pct == null ? '—' : item.coverage_pct.toFixed(0) + '%'}</span>
          </button>)}
        </div>
      </section>
      </details>
      {detailLoading ? <div className="panel radar-empty">正在读取板块详情…</div> : detail ? <section className="panel radar-detail"><div className="panel-title"><div><h2>{detail.item.name}</h2><small>{detail.item.stage} · 规则证据：{detail.item.evidence.join('；')}</small></div><div><button className="scan-button" onClick={() => void api.addIndustryWatch(detail.item.industry_id).then(() => {setActionMessage('已加入阶段提醒，阶段发生变化时会显示在此页。'); return api.industryAlerts().then(setAlerts)}).catch(reason => setActionError(reason instanceof Error ? reason.message : '添加失败，请重试'))}>加入阶段提醒</button><button className="scan-button" onClick={() => setDetail(null)}>收起详情</button></div></div><div className="radar-detail-grid"><div><h3>阶段时间线</h3>{detail.stage_timeline.slice(-12).reverse().map(point => <p key={point.trade_date}><span>{point.trade_date}</span><strong>{point.stage}</strong>{point.score == null ? '' : ' · ' + point.score.toFixed(0) + '分'}</p>)}</div><div><h3>成分股下钻</h3><small className="source-note">领涨核心：相对行业强 + 站上MA20；低位改善：20日仍弱但5日回升；突破确认：突破前20日高点且放量；内部拖累：相对行业弱或跌破MA20。</small>{Object.entries(detail.constituent_groups ?? {}).map(([group, stocks]) => <div className="radar-group" key={group}><h4>{group}<span>{stocks.length}</span></h4><div className="radar-constituents">{stocks.map(stock => <button type="button" key={stock.code} onClick={() => onOpenStock(stock.code)}><strong>{stock.name}</strong><small>{stock.code} · 相对行业 {radarPct(stock.relative_return_20d_pct)} · {stock.history_days ?? 0}日</small></button>)}</div>{stocks.length === 0 && <small className="source-note">暂无满足条件的成分；先完成120日回填。</small>}</div>)}</div></div></section> : null}
      <div className="radar-filter" aria-label="按板块阶段筛选">{['全部',...sections.map(([title]) => title)].map(title => <button key={title} aria-pressed={stageFilter === title} onClick={() => setStageFilter(title)}>{title}</button>)}</div>
      {sections.filter(([title]) => stageFilter === '全部' || stageFilter === title).map(([title, description, items]) => <section className="radar-section" key={title}><div className="panel-title"><div><h2>{title}</h2><small>{description}</small></div><span className="pill">{items.length} 个板块</span></div>{items.length ? <div className="radar-grid">{items.slice(0,expandedStages.includes(title) ? items.length : 6).map(item => <RadarCard item={item} onOpenStock={onOpenStock} onOpenIndustry={(selected) => void openIndustry(selected)} key={item.industry_id || item.name} />)}{items.length > 6 && !expandedStages.includes(title) && <button className="ghost-button" onClick={() => setExpandedStages(current => [...current,title])}>展开其余 {items.length - 6} 个板块</button>}</div> : <div className="panel radar-empty">暂无满足当前门槛的板块</div>}</section>)}
    </>}
  </>
}

type ReviewProps = { review: MarketReview | null; runs: MarketReviewRun[]; selectedRunId?: number; loading: boolean; scanning: boolean; scanMessage?: string; onRefresh: (runId?: number) => void; onScan: () => void; onOpenStock: (code: string) => void }

const pct = (value?: number) => value == null ? '—' : `${value > 0 ? '+' : ''}${value.toFixed(2)}%`

export function MarketReviewPage({review, runs, selectedRunId, loading, scanning, scanMessage, onRefresh, onScan, onOpenStock}: ReviewProps) {
  return <>
    <header><div><p className="eyebrow">MARKET REVIEW</p><h1>市场复盘</h1><p>当前展示参考池扫描结果；全 A 市场健康度将使用独立日快照，不混入策略评分。</p></div><button className="icon-btn" onClick={() => onRefresh(selectedRunId ?? review?.run_id)} disabled={loading}>{loading ? <RefreshCw className="spin" /> : <RefreshCw />}</button></header>
    {!review?.run_id ? <section className="panel review-empty"><Activity /><h2>还没有可复盘的扫描</h2><p>点击下方按钮运行一次参考池扫描，复盘会自动读取本地 SQLite 快照。</p><button className="scan-button" onClick={onScan} disabled={scanning}>{scanning ? '扫描中…' : '运行参考池扫描'}</button></section> : <>
      <section className="review-meta"><label>历史扫描<select value={selectedRunId ?? review.run_id} onChange={event => onRefresh(Number(event.target.value))}>{runs.map(run => <option key={run.run_id} value={run.run_id}>#{run.run_id} · {new Date(run.completed_at).toLocaleString('zh-CN')}</option>)}</select></label><span>{review.source}</span><button className="scan-button" onClick={onScan} disabled={scanning}>{scanning ? '扫描中…' : '运行参考池扫描'}</button><button className="scan-button" onClick={() => onRefresh(selectedRunId ?? review.run_id)} disabled={loading}>{loading ? '刷新中…' : '刷新复盘'}</button></section>{scanMessage && <p className="scan-error"><Activity />{scanMessage}</p>}
      <section className="panel review-scope"><div><strong>{review.pool_name}</strong><span>参考池 · 版本 {review.pool_version}</span></div><div><strong>{review.pool_component_count} 只</strong><span>本次扫描成分数</span></div><div><strong>{review.transaction_date ?? '—'}</strong><span>交易日</span></div><div><strong>{review.scan_completed_at ? new Date(review.scan_completed_at).toLocaleString('zh-CN') : '—'}</strong><span>扫描完成时间</span></div><div><strong>{review.coverage_pct == null ? '—' : `${review.coverage_pct.toFixed(1)}%`}</strong><span>行情覆盖率 {review.coverage_count}/{review.coverage_total}</span></div><div><strong className={review.data_status === 'ok' ? 'positive' : review.data_status === 'degraded' ? '' : 'negative'}>{review.data_status === 'ok' ? '正常' : review.data_status === 'degraded' ? '部分降级' : '失败'}</strong><span>{review.degraded_reasons[0] ?? '数据状态'}</span></div></section>
      <section className="stats review-stats"><article><span>上涨 / 下跌</span><strong>{review.up_count} / {review.down_count}</strong><small>平盘 {review.flat_count} · 涨跌样本 {review.change_sample_count}</small></article><article><span>参考池样本上涨率</span><strong>{review.sample_up_rate_pct == null ? '—' : `${review.sample_up_rate_pct.toFixed(1)}%`}</strong><small>分母：有涨跌数据的参考池样本</small></article><article><span>平均涨跌</span><strong className={(review.average_change_pct ?? 0) >= 0 ? 'positive' : 'negative'}>{pct(review.average_change_pct)}</strong><small>参考池样本平均</small></article><article><span>策略评分摘要</span><strong>{review.strategy_average_score?.toFixed(1) ?? '—'}</strong><small>{review.strategy_scoreable} / {review.total} 可评分；不参与健康度</small></article></section>
      <div className="review-grid"><section className="panel"><div className="panel-title"><h2>涨幅靠前</h2><span className="pill">Top 10</span></div><div className="review-list">{review.top_gainers.map(item => <button key={item.stock_code} onClick={() => onOpenStock(item.stock_code)}><span><strong>{item.stock_name}</strong><small>{item.stock_code} · {item.sector}</small></span><b className={(item.change_pct ?? 0) >= 0 ? 'positive' : 'negative'}>{pct(item.change_pct)}</b><em>{item.grade ?? '—'}</em></button>)}</div></section><section className="panel"><div className="panel-title"><h2>评分靠前</h2><span className="pill">Top 10</span></div><div className="review-list">{review.top_scores.map(item => <button key={item.stock_code} onClick={() => onOpenStock(item.stock_code)}><span><strong>{item.stock_name}</strong><small>{item.stock_code} · {item.sector}</small></span><b>{item.score ?? '—'}</b><em>{item.grade ?? '—'}</em></button>)}</div></section></div>
      <section className="panel"><div className="panel-title"><h2>参考池行业横截面</h2><span className="pill">按平均涨跌排序 · 非全市场</span></div><div className="sector-review-table"><div className="sector-review-row sector-review-header"><span>行业</span><span>样本</span><span>上涨</span><span>平均涨跌</span><span>可评分</span><span>策略平均分</span></div>{review.sectors.map(item => <div className="sector-review-row" key={item.sector}><span>{item.sector}</span><span>{item.count}</span><span>{item.up_count}</span><span className={(item.average_change_pct ?? 0) >= 0 ? 'positive' : 'negative'}>{pct(item.average_change_pct)}</span><span>{item.scoreable}</span><span>{item.average_score?.toFixed(1) ?? '—'}</span></div>)}</div></section>
      <section className="review-callout"><TrendingUp /><span>轮动池 {review.rotation_pool_codes.length} 只：{review.rotation_pool_codes.slice(0, 8).join('、') || '暂无'}</span><TrendingDown /></section>
    </>}
  </>
}

type HealthProps = { health: DataSourceHealthResponse | null; testing: boolean; onTest: () => void; onRefresh: () => void }

export function SourceHealthPage({health, testing, onTest, onRefresh}: HealthProps) {
  return <>
    <header><div><p className="eyebrow">DATA SOURCES</p><h1>数据源状态</h1><p>区分已安装、接口可访问和数据有效；失败时保留最近一次成功时间。</p></div><button className="icon-btn" aria-label="刷新记录" onClick={onRefresh}><RefreshCw /></button></header>
    <section className="review-meta"><span>最近检查：{health?.checked_at ? new Date(health.checked_at).toLocaleString('zh-CN') : '尚未检查'}</span><span>本机数据源诊断</span><button className="scan-button" onClick={onTest} disabled={testing}>{testing ? '测试中…' : '测试全部数据源'}</button></section>
    {testing && <RequestProgress label="正在测试数据源连接"/>}
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
    <header><div><p className="eyebrow">SIGNAL CHECK</p><h1>信号核验</h1><p>核验候选信号在 1、5、20、60 个实际交易日后的表现，不把待验证结果当成收益。</p></div><button className="icon-btn" aria-label="刷新记录" onClick={onRefresh}><RefreshCw /></button></header>
    <section className="review-meta"><span>已保存候选 {candidates.length} 只</span><span>已验证 {verification?.verified ?? summary.verified}</span><span>待核验 {verification?.pending ?? summary.pending}</span><span>不可用 {verification?.unavailable ?? summary.unavailable}</span><button className="scan-button" onClick={onVerify} disabled={verifying}>{verifying ? '核验中…' : '运行核验'}</button></section>
    {verifying && <RequestProgress label="正在核验已保存信号"/>}
    {verification?.horizon_summary.length ? <section className="stats performance-stats">{verification.horizon_summary.map(item => <article key={item.horizon}><span>{item.horizon} 胜率</span><strong>{item.win_rate_pct == null ? '—' : `${item.win_rate_pct.toFixed(1)}%`}</strong><small>{item.verified} 个已验证 · 均值 {item.average_return_pct == null ? '—' : `${item.average_return_pct > 0 ? '+' : ''}${item.average_return_pct.toFixed(2)}%`} · 中位数 {item.median_return_pct == null ? '—' : `${item.median_return_pct > 0 ? '+' : ''}${item.median_return_pct.toFixed(2)}%`}</small><small>{item.average_relative_return_pct == null ? '沪深300相对收益：暂无基准快照' : `相对${item.benchmark_code}均值 ${item.average_relative_return_pct > 0 ? '+' : ''}${item.average_relative_return_pct.toFixed(2)}%`}</small></article>)}</section> : null}
    <section className="panel performance-panel"><div className="panel-title"><h2>候选表现</h2><span className="pill">本机行情快照</span></div>{candidates.length === 0 ? <div className="review-empty compact"><Activity /><p>还没有预选股。可从个股研究加入信号核验，或从板块雷达下钻。</p></div> : <div className="performance-table"><div className="performance-row performance-header"><span>股票</span><span>入选价</span><span>1日</span><span>5日</span><span>20日</span><span>60日</span><span>状态</span></div>{candidates.map(item => <div className="performance-row" key={item.id}><span><strong>{item.stock_name}</strong><small>{item.stock_code} · {new Date(item.selected_at).toLocaleDateString('zh-CN')}</small></span><span>¥{item.selected_price.toFixed(2)}</span>{(['1d', '5d', '20d', '60d'] as const).map(horizon => { const outcome = item.performance?.find(entry => entry.horizon === horizon); const detail = outcome?.realized_trade_date ? `实际交易日 ${outcome.realized_trade_date}` : outcome?.status === 'pending' ? '等待目标交易日后的有效行情快照' : '尚无有效行情快照'; return <span title={detail} className={outcome?.return_pct != null ? outcome.return_pct >= 0 ? 'positive' : 'negative' : ''} key={horizon}>{outcome?.return_pct == null ? outcome?.status === 'pending' ? '待核验' : '—' : pct(outcome.return_pct)}</span> })}<span className="status">{item.status === 'new' ? '新发现' : item.status}</span></div>)}</div>}</section>
  </>
}
