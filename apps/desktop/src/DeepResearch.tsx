import { useEffect, useState } from 'react'
import { AlertTriangle, ArrowLeft, BrainCircuit, RefreshCw } from 'lucide-react'
import { api } from './api'
import type { AnalysisReport, StockSearchResult, WatchlistItem } from './types'

type Props = { initialStock?: string; onBack: () => void }

function TrendChart({points}: {points: AnalysisReport['trend_series']}) {
  if (!points.length) return <div className="chart-empty">暂无走势数据</div>
  const values = points.flatMap(point => [point.close, ...(point.ma20 ? [point.ma20] : [])])
  const min = Math.min(...values), max = Math.max(...values), range = Math.max(max - min, .01)
  const path = (key: 'close' | 'ma20') => points.map((point, index) => point[key] == null ? '' : `${(index / Math.max(points.length - 1, 1)) * 100},${96 - ((point[key] - min) / range) * 86}`).filter(Boolean).join(' ')
  return <svg className="trend-chart" viewBox="0 0 100 100" preserveAspectRatio="none" role="img" aria-label="近120日走势"><polyline points={path('close')} fill="none" stroke="#3d7255" strokeWidth="1.4" vectorEffect="non-scaling-stroke" /><polyline points={path('ma20')} fill="none" stroke="#b18445" strokeWidth="1" strokeDasharray="3 2" vectorEffect="non-scaling-stroke" /><line x1="0" y1="96" x2="100" y2="96" stroke="#d9ded9" strokeWidth=".5" vectorEffect="non-scaling-stroke" /></svg>
}

function RadarChart({dimensions}: {dimensions: AnalysisReport['radar']}) {
  if (!dimensions.length) return <div className="chart-empty">暂无雷达数据</div>
  const center = 50, radius = 38
  const point = (index: number, value: number) => { const angle = -Math.PI / 2 + index * Math.PI * 2 / dimensions.length; const r = radius * value / 100; return `${center + Math.cos(angle) * r},${center + Math.sin(angle) * r}` }
  const outline = dimensions.map((_, index) => point(index, 100)).join(' ')
  const polygon = dimensions.map((dimension, index) => point(index, dimension.score)).join(' ')
  return <div className="radar-wrap"><svg className="radar-chart" viewBox="0 0 100 100" role="img" aria-label="六维雷达图"><polygon points={outline} fill="none" stroke="#d8ded9" strokeWidth=".7" />{[25,50,75].map(level => <polygon key={level} points={dimensions.map((_, index) => point(index, level)).join(' ')} fill="none" stroke="#e8ece8" strokeWidth=".5" />)}<polygon points={polygon} fill="#557f6330" stroke="#426b50" strokeWidth="1.2" /></svg><div className="radar-labels">{dimensions.map(dimension => <span key={dimension.key}>{dimension.label} {dimension.score.toFixed(0)}</span>)}</div></div>
}

function SourceBadge({status, source}: {status: string; source: string}) {
  return <span className={`source-badge ${status}`}>{status === 'ok' ? '已接入' : status === 'degraded' ? '部分数据' : '未接入'} · {source}</span>
}

function NumberValue({value, suffix = ''}: {value?: number; suffix?: string}) {
  return <strong>{value == null || Number.isNaN(value) ? '—' : `${value.toFixed(2)}${suffix}`}</strong>
}

export function DeepResearch({ initialStock = '', onBack }: Props) {
  const [stock, setStock] = useState(initialStock)
  const [holding, setHolding] = useState(false)
  const [cost, setCost] = useState('')
  const [report, setReport] = useState<AnalysisReport | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [searchQuery, setSearchQuery] = useState(initialStock)
  const [searchResults, setSearchResults] = useState<StockSearchResult[]>([])
  const [watchlist, setWatchlist] = useState<WatchlistItem[]>([])
  const [searching, setSearching] = useState(false)
  useEffect(() => { void api.listWatchlist().then(setWatchlist).catch(() => setWatchlist([])) }, [])
  async function run() {
    setBusy(true); setError('')
    try { setReport(await api.analyze(stock, holding, cost ? Number(cost) : undefined)) }
    catch (reason) { setError(String(reason)) }
    finally { setBusy(false) }
  }
  async function search() {
    setSearching(true); setError('')
    try { setSearchResults(await api.searchStocks(searchQuery)) }
    catch (reason) { setError(String(reason)) }
    finally { setSearching(false) }
  }
  async function add(item: StockSearchResult) {
    try { const saved = await api.addWatchlist(item); setWatchlist(current => [saved, ...current.filter(entry => entry.code !== saved.code)]); setStock(item.code) }
    catch (reason) { setError(String(reason)) }
  }
  return <>
    <header><div><p className="eyebrow">INDIVIDUAL RESEARCH</p><h1>个股深研</h1><p>搜索全市场股票，或从“我的自选”打开技术面与火箭评分。</p></div><button className="icon-btn" onClick={onBack}><ArrowLeft /></button></header>
    <section className="panel deep-search">
      <div className="deep-search-row"><label>股票代码或名称<input placeholder="例如 600519 / 贵州茅台" value={stock} onChange={event => setStock(event.target.value)} /></label><label className="holding-check"><input type="checkbox" checked={holding} onChange={event => setHolding(event.target.checked)} /><span />当前已持有</label>{holding && <label>持仓成本<input type="number" value={cost} onChange={event => setCost(event.target.value)} /></label>}<button className="primary deep-run" disabled={busy || !stock.trim()} onClick={run}>{busy ? <RefreshCw className="spin" /> : <BrainCircuit />}{busy ? '分析中…' : '开始深研'}</button></div>
      <div className="watchlist-tools"><label>搜索全部股票并加入自选<input placeholder="输入名称或代码，例如 九安医疗 / 002432" value={searchQuery} onChange={event => setSearchQuery(event.target.value)} /></label><button className="scan-button" onClick={search} disabled={searching || !searchQuery.trim()}>{searching ? <RefreshCw className="spin" /> : <BrainCircuit />}{searching ? '搜索中…' : '搜索股票'}</button></div>
      {searchResults.length > 0 && <div className="search-results">{searchResults.map(item => <button key={item.code} onClick={() => void add(item)}><strong>{item.name}</strong><small>{item.code} · {item.market ?? 'A股'} · 点击加入</small></button>)}</div>}
      <div className="watchlist-strip"><span>我的自选</span>{watchlist.length === 0 ? <small>搜索股票后加入自己的观察列表</small> : watchlist.map(item => <button key={item.code} onClick={() => setStock(item.code)}>{item.name}<small>{item.code}</small></button>)}</div>
      {error && <p className="scan-error"><AlertTriangle />{error}</p>}
    </section>
    {!report ? <section className="panel deep-empty"><BrainCircuit /><h2>输入一只股票开始分析</h2><p>首版使用腾讯实时行情和前复权日线，缺失的资金、财务、板块和新闻字段会明确标注。</p></section> : <>
      <section className="deep-hero"><div><span className={`data-status ${report.status}`}>{report.status === 'ok' ? '数据完整' : '部分降级'}</span><h2>{report.stock_name}<small>{report.stock_code} · {report.sector}</small></h2><p>{report.diagnosis.summary}</p></div><div className="rocket-score"><strong>{report.zhixing_index.toFixed(0)}</strong><span>知行指数 · {report.zhixing_level}</span></div></section>
      <section className="diagnosis-banner"><strong>{report.diagnosis.position}</strong><span>{report.diagnosis.summary}</span>{report.diagnosis.conflicts.length > 0 && <em>存在日周线矛盾</em>}</section>
      <section className="supplement-grid">
        <article className="panel source-panel"><div className="panel-title"><h2>资金流</h2><SourceBadge status={report.fund_flow.status} source={report.fund_flow.source} /></div><div className="source-metrics"><div><span>主力净流入（亿元）</span><NumberValue value={report.fund_flow.main_inflow} /></div><div><span>主力净流入占比</span><NumberValue value={report.fund_flow.main_flow_ratio != null ? report.fund_flow.main_flow_ratio * 100 : undefined} suffix="%" /></div></div><small className="source-note">交易日：{report.fund_flow.trade_date ?? '—'}{report.fund_flow.error ? ` · ${report.fund_flow.error}` : ''}</small></article>
        <article className="panel source-panel"><div className="panel-title"><h2>财务增速</h2><SourceBadge status={report.finance.status} source={report.finance.source} /></div><div className="source-metrics"><div><span>营收同比</span><NumberValue value={report.finance.revenue_yoy} suffix="%" /></div><div><span>净利润同比</span><NumberValue value={report.finance.profit_yoy} suffix="%" /></div></div><small className="source-note">报告期：{report.finance.report_date ?? '—'}{report.finance.error ? ` · ${report.finance.error}` : ''}</small></article>
        <article className="panel source-panel"><div className="panel-title"><h2>行业热度</h2><SourceBadge status={report.industry.status} source={report.industry.source} /></div><div className="source-metrics"><div><span>行业</span><strong>{report.industry.name ?? '—'}</strong></div><div><span>涨幅排名</span><strong>{report.industry.rank != null ? `${report.industry.rank} / ${report.industry.total ?? '—'}` : '—'}</strong></div><div><span>行业涨幅</span><NumberValue value={report.industry.change_pct} suffix="%" /></div></div><small className="source-note">按行业涨幅横截面排序{report.industry.error ? ` · ${report.industry.error}` : ''}</small></article>
        <article className="panel source-panel news-panel"><div className="panel-title"><h2>相关新闻</h2><SourceBadge status={report.news.status} source={report.news.source} /></div>{report.news.items.length === 0 ? <p className="source-note">暂无可用新闻{report.news.error ? ` · ${report.news.error}` : ''}</p> : <div className="news-list">{report.news.items.slice(0, 4).map((item, index) => <a href={item.url || undefined} target="_blank" rel="noreferrer" key={`${item.title}-${index}`}><span className={`news-sentiment ${item.sentiment}`}>{item.sentiment === 'bull' ? '利好' : item.sentiment === 'bear' ? '风险' : '中性'}</span><strong>{item.title}</strong><small>{item.source_name || '公开资讯'} · {item.published_at || '时间未知'}</small></a>)}</div>}</article>
      </section>
      <div className="deep-grid"><section className="panel chart-panel"><div className="panel-title"><h2>近120日走势</h2><span className="pill">实线收盘 · 虚线 MA20</span></div><TrendChart points={report.trend_series} /></section><section className="panel chart-panel"><div className="panel-title"><h2>六维雷达</h2><span className="pill">0–100</span></div><RadarChart dimensions={report.radar} /></section></div>
      <div className="deep-grid"><section className="panel"><div className="panel-title"><h2>行情与日周线</h2><span className="pill">日线 {report.technical.trend} · 周线 {report.weekly.trend}</span></div><div className="metric-grid">{[['现价', report.quote.price], ['涨跌', report.quote.change_pct != null ? `${report.quote.change_pct.toFixed(2)}%` : null], ['PE', report.quote.pe], ['MA5', report.technical.ma5], ['MA20', report.technical.ma20], ['MA60', report.technical.ma60], ['周MA5', report.weekly.ma5], ['RSI14', report.technical.rsi14], ['量比', report.technical.volume_ratio], ['支撑', report.technical.support20], ['压力', report.technical.resistance20]].map(([label, value]) => <div key={label as string}><span>{label}</span><strong>{typeof value === 'number' ? value.toFixed(2) : value ?? '—'}</strong></div>)}</div>{report.technical.macd && <p className="signal-line">MACD：{report.technical.macd.golden_cross ? '金叉' : report.technical.macd.death_cross ? '死叉' : report.technical.macd.hist > 0 ? '多头' : '空头'} · DIF {report.technical.macd.dif.toFixed(3)} · DEA {report.technical.macd.dea.toFixed(3)}</p>}</section>
        <section className="panel"><div className="panel-title"><h2>十因子评分</h2><span className="pill">可解释</span></div><div className="rocket-dimensions">{report.factors.map(factor => <article key={factor.key}><div><span>{factor.label}</span><strong className={factor.score >= 60 ? 'positive' : factor.score < 40 ? 'negative' : ''}>{factor.score.toFixed(0)}</strong></div><small>{factor.reason}{factor.available ? '' : ' · 未接入/不计入指数'}</small></article>)}</div></section>
      </div>
      <section className="panel evidence-panel"><div className="panel-title"><div><span className="step">03</span><h2>积极证据 / 风险证据 / 多空矛盾</h2></div><span className="pill">规则诊断</span></div><div className="evidence-grid"><div><h3>积极证据</h3>{report.diagnosis.positive_evidence.map(item => <p className="evidence-positive" key={item}>＋ {item}</p>)}</div><div><h3>风险证据</h3>{report.diagnosis.risk_evidence.map(item => <p className="evidence-risk" key={item}>－ {item}</p>)}</div><div><h3>矛盾提示</h3>{(report.diagnosis.conflicts.length ? report.diagnosis.conflicts : ['暂未发现日周线矛盾']).map(item => <p className="evidence-conflict" key={item}>△ {item}</p>)}</div></div><div className="reassess-line">重新评估条件：{report.diagnosis.reassess_conditions.join('；') || '数据补齐后再评估'}</div></section>
      <section className="panel advice-panel"><div className="panel-title"><div><span className="step">03</span><h2>操作参考与价格区间</h2></div><span className="pill">仅研究参考</span></div><div className="advice-head"><div className="advice-action">{report.advice.action}</div><div><strong>{report.advice.category}</strong><p>{report.advice.summary}</p></div><span className="status">风险：{report.advice.risk_level}</span></div><div className="zone-grid">{report.advice.zones.map(zone => <article className={`zone-${zone.tone}`} key={zone.name}><strong>{zone.name}</strong><span>¥{zone.low.toFixed(2)} ~ ¥{zone.high.toFixed(2)}</span><small>{zone.action}</small></article>)}</div><p className="deep-note">缺失字段：{report.missing_fields.length ? report.missing_fields.join('、') : '无'}。火箭评分是经验公式，不代表预测或交易指令。</p></section>
    </>}
  </>
}
