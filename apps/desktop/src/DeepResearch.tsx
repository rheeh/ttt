import { useEffect, useRef, useState } from 'react'
import { AlertTriangle, ArrowLeft, BrainCircuit, RefreshCw } from 'lucide-react'
import { api } from './api'
import type { AnalysisReport, StockSearchResult, WatchlistItem } from './types'

type Props = { initialStock?: string; onBack?: () => void }

type ChartBar = AnalysisReport['bars'][number]

function KlineChart({bars, range, support, resistance, history, stockCode}: {bars: ChartBar[]; range: number; support?: number; resistance?: number; history: AnalysisReport[]; stockCode: string}) {
  if (!bars.length) return <div className="chart-empty">暂无 K 线数据</div>
  const visible = bars.slice(-range), width = 1000, height = 390, left = 48, right = 12, top = 16, priceBottom = 274, volumeTop = 298, volumeBottom = 362
  const lows = visible.map(bar => bar.low), highs = visible.map(bar => bar.high)
  const min = Math.min(...lows, ...(support != null ? [support] : [])), max = Math.max(...highs, ...(resistance != null ? [resistance] : [])), priceRange = Math.max(max - min, .01)
  const maxVolume = Math.max(...visible.map(bar => bar.volume), 1), slot = (width - left - right) / visible.length, bodyWidth = Math.max(1.5, Math.min(10, slot * .6))
  const x = (index: number) => left + (index + .5) * slot
  const y = (value: number) => top + (max - value) / priceRange * (priceBottom - top)
  const volumeY = (value: number) => volumeBottom - value / maxVolume * (volumeBottom - volumeTop)
  const ma = (index: number, period: number) => { const end = bars.length - visible.length + index + 1; if (end < period) return null; return bars.slice(end - period, end).reduce((sum, bar) => sum + bar.close, 0) / period }
  const line = (period: number) => visible.map((_, index) => { const value = ma(index, period); return value == null ? '' : `${x(index)},${y(value)}` }).filter(Boolean).join(' ')
  const scoreMarkers = history.filter(item => item.stock_code === stockCode && item.zhixing_index != null).map(item => {
    const dateText = new Date(item.created_at).toISOString().slice(0, 10)
    let index = visible.findIndex(bar => bar.trade_date === dateText)
    if (index < 0) index = visible.findIndex(bar => bar.trade_date >= dateText)
    return index >= 0 ? {index, score: item.zhixing_index, date: dateText} : null
  }).filter(Boolean) as {index: number; score: number; date: string}[]
  const labelIndexes = [0, Math.floor((visible.length - 1) / 2), visible.length - 1]
  return <div className="kline-wrap"><svg className="kline-chart" viewBox={`0 0 ${width} ${height}`} role="img" aria-label="K线、成交量和均线图"><rect x={left} y={top} width={width - left - right} height={priceBottom - top} fill="#fbfcfb" />{[0, .25, .5, .75, 1].map(level => <line key={level} x1={left} x2={width - right} y1={top + level * (priceBottom - top)} y2={top + level * (priceBottom - top)} stroke="#e8ede8" strokeWidth="1" />)}<line x1={left} x2={width - right} y1={volumeTop - 8} y2={volumeTop - 8} stroke="#e8ede8" strokeWidth="1" />{support != null && support >= min && support <= max && <><line className="kline-level support" x1={left} x2={width - right} y1={y(support)} y2={y(support)} /><text className="kline-level-label support" x={width - right - 3} y={y(support) - 4} textAnchor="end">支撑 {support.toFixed(2)}</text></>}{resistance != null && resistance >= min && resistance <= max && <><line className="kline-level resistance" x1={left} x2={width - right} y1={y(resistance)} y2={y(resistance)} /><text className="kline-level-label resistance" x={width - right - 3} y={y(resistance) - 4} textAnchor="end">压力 {resistance.toFixed(2)}</text></>}{visible.map((bar, index) => { const rising = bar.close >= bar.open; const candleColor = rising ? '#c45f55' : '#3f8561'; const candleTop = y(Math.max(bar.open, bar.close)), candleHeight = Math.max(1, Math.abs(y(bar.close) - y(bar.open))); return <g key={bar.trade_date}><line x1={x(index)} x2={x(index)} y1={y(bar.high)} y2={y(bar.low)} stroke={candleColor} strokeWidth="1" /><rect x={x(index) - bodyWidth / 2} y={candleTop} width={bodyWidth} height={candleHeight} fill={rising ? '#fff' : candleColor} stroke={candleColor} strokeWidth="1" /><rect x={x(index) - bodyWidth / 2} y={volumeY(bar.volume)} width={bodyWidth} height={Math.max(1, volumeBottom - volumeY(bar.volume))} fill={`${candleColor}55`} /></g> })}<polyline points={line(5)} fill="none" stroke="#8c5a9f" strokeWidth="1.5" /><polyline points={line(10)} fill="none" stroke="#b18445" strokeWidth="1.5" /><polyline points={line(20)} fill="none" stroke="#3d7255" strokeWidth="1.8" /><polyline points={line(60)} fill="none" stroke="#4b789e" strokeWidth="1.5" />{scoreMarkers.map(marker => <g key={`${marker.date}-${marker.score}`}><circle cx={x(marker.index)} cy={y(visible[marker.index].close)} r="4" fill="#b18445" stroke="#fff" strokeWidth="1.5" /><text className="score-marker" x={x(marker.index)} y={y(visible[marker.index].close) - 8} textAnchor="middle">{marker.score.toFixed(0)}</text></g>)}{labelIndexes.map(index => <text key={index} className="kline-date" x={x(index)} y={height - 8} textAnchor={index === 0 ? 'start' : index === visible.length - 1 ? 'end' : 'middle'}>{visible[index].trade_date.slice(5)}</text>)}</svg><div className="kline-legend"><span><i className="legend-candle rise" />上涨</span><span><i className="legend-candle fall" />下跌</span><span><i className="legend-line ma5" />MA5</span><span><i className="legend-line ma10" />MA10</span><span><i className="legend-line ma20" />MA20</span><span><i className="legend-line ma60" />MA60</span><span><i className="legend-dot" />历史评分</span></div></div>
}

function RadarChart({dimensions}: {dimensions: AnalysisReport['radar']}) {
  if (!dimensions.length) return <div className="chart-empty">暂无雷达数据</div>
  const center = 50, radius = 38
  const point = (index: number, value: number) => { const angle = -Math.PI / 2 + index * Math.PI * 2 / dimensions.length; const r = radius * value / 100; return `${center + Math.cos(angle) * r},${center + Math.sin(angle) * r}` }
  const outline = dimensions.map((_, index) => point(index, 100)).join(' ')
  const polygon = dimensions.map((dimension, index) => point(index, dimension.score)).join(' ')
  return <div className="radar-wrap"><svg className="radar-chart" viewBox="0 0 100 100" role="img" aria-label="六维雷达图"><polygon points={outline} fill="none" stroke="#d8ded9" strokeWidth=".7" />{[25,50,75].map(level => <polygon key={level} points={dimensions.map((_, index) => point(index, level)).join(' ')} fill="none" stroke="#e8ece8" strokeWidth=".5" />)}<polygon points={polygon} fill="#557f6330" stroke="#426b50" strokeWidth="1.2" /></svg><div className="radar-labels">{dimensions.map(dimension => <span key={dimension.key}>{dimension.label} {dimension.score.toFixed(0)}</span>)}</div></div>
}

function SourceBadge({status, source, endpoint, cacheExpired, error}: {status: string; source: string; endpoint?: string; cacheExpired?: boolean; error?: string}) {
  const label = status === 'ok' ? '已接入' : status === 'stale' ? '使用缓存' : cacheExpired ? '缓存过期' : status === 'degraded' ? '字段缺失' : status === 'error' ? '获取失败' : '状态未知'
  return <span className={`source-badge ${status}`} title={error || undefined}>{label} · {source}{endpoint ? ` · ${endpoint}` : ''}</span>
}

function NumberValue({value, suffix = ''}: {value?: number; suffix?: string}) {
  return <strong>{value == null || Number.isNaN(value) ? '—' : `${value.toFixed(2)}${suffix}`}</strong>
}

function DataAge({seconds, status, cacheUsed}: {seconds?: number; status?: string; cacheUsed?: boolean}) {
  if (seconds == null) return null
  const age = seconds < 3600 ? `${Math.max(1, Math.round(seconds / 60))} 分钟` : `${(seconds / 3600).toFixed(1)} 小时`
  const label = cacheUsed || status === 'stale' ? '缓存年龄' : status === 'error' ? '请求于' : status === 'degraded' ? '数据年龄' : '数据年龄'
  return <span> · {label} {age}</span>
}

type FreshnessInfo = AnalysisReport['freshness'][string]

function freshnessAge(seconds?: number) {
  if (seconds == null) return '时间未知'
  if (seconds < 60) return `${Math.max(1, Math.round(seconds))} 秒前`
  if (seconds < 3600) return `${Math.max(1, Math.round(seconds / 60))} 分钟前`
  return `${(seconds / 3600).toFixed(1)} 小时前`
}

function FreshnessItem({label, info, fallback}: {label: string; info?: FreshnessInfo; fallback?: string}) {
  const state = info?.state ?? 'unknown'
  const stateLabel = state === 'fresh' ? '实时/新鲜' : state === 'warning' ? '接近过期' : state === 'stale' ? '使用缓存' : state === 'expired' ? '缓存已过期' : state === 'error' ? '获取失败' : '暂无记录'
  const agePrefix = state === 'error' ? '请求于' : state === 'expired' ? '检查于' : state === 'stale' ? '缓存于' : '更新于'
  const detail = info?.latest_trade_date ? `截至 ${info.latest_trade_date} · ${info.bar_count ?? 0} 条` : info?.report_date ? `报告期 ${info.report_date}` : info?.trade_date ? `交易日 ${info.trade_date}` : info?.age_seconds != null ? `${agePrefix} ${freshnessAge(info.age_seconds)}` : fallback ?? '时间未知'
  return <div className={`freshness-item freshness-${state}`}><div><strong>{label}</strong><span>{stateLabel}</span></div><small>{detail}</small></div>
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
  const [history, setHistory] = useState<AnalysisReport[]>([])
  const [suggestions, setSuggestions] = useState<StockSearchResult[]>([])
  const [suggesting, setSuggesting] = useState(false)
  const [searching, setSearching] = useState(false)
  const [chartMode, setChartMode] = useState<'daily' | 'weekly'>('daily')
  const [chartRange, setChartRange] = useState(120)
  const skipNextSuggestion = useRef(false)
  useEffect(() => { void api.listWatchlist().then(setWatchlist).catch(() => setWatchlist([])); void api.listAnalyses(undefined, 12).then(setHistory).catch(() => setHistory([])) }, [])
  useEffect(() => {
    const query = stock.trim()
    if (skipNextSuggestion.current) { skipNextSuggestion.current = false; return }
    let active = true
    const timer = window.setTimeout(async () => {
      if (!query) { if (active) { setSuggestions([]); setSuggesting(false) }; return }
      setSuggesting(true)
      try { const results = await api.searchStocks(query); if (active) setSuggestions(results.slice(0, 8)) }
      catch { if (active) setSuggestions([]) }
      finally { if (active) setSuggesting(false) }
    }, query ? 260 : 0)
    return () => { active = false; window.clearTimeout(timer) }
  }, [stock])
  async function run() {
    setBusy(true); setError('')
    try { const next = await api.analyze(stock, holding, cost ? Number(cost) : undefined); setReport(next); setHistory(current => [next, ...current.filter(item => item.report_id !== next.report_id)].slice(0, 12)) }
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
  function chooseSuggestion(item: StockSearchResult) {
    if (item.code !== stock.trim()) skipNextSuggestion.current = true
    setStock(item.code)
    setSearchQuery(item.name)
    setSuggestions([])
  }
  return <>
    <header><div><p className="eyebrow">INDIVIDUAL RESEARCH</p><h1>个股研究</h1><p>搜索全市场股票，自动抓取行情、K线、财务和新闻，形成可解释的研究快照。</p></div>{onBack && <button className="icon-btn" onClick={onBack}><ArrowLeft /></button>}</header>
    <section className="panel deep-search">
      <div className="deep-search-row"><div className="stock-autocomplete"><label>股票代码或名称<input autoComplete="off" placeholder="例如 600519 / 贵州茅台" value={stock} onChange={event => setStock(event.target.value)} /></label>{(suggestions.length > 0 || suggesting) && <div className="stock-suggestions" role="listbox">{suggesting && suggestions.length === 0 ? <div className="suggestion-loading">正在搜索全市场…</div> : suggestions.map(item => <button type="button" key={item.code} role="option" onMouseDown={event => event.preventDefault()} onClick={() => chooseSuggestion(item)}><strong>{item.name}</strong><span>{item.code} · {item.market ?? 'A股'}</span></button>)}</div>}</div><label className="holding-check"><input type="checkbox" checked={holding} onChange={event => setHolding(event.target.checked)} /><span />当前已持有</label>{holding && <label>持仓成本<input type="number" value={cost} onChange={event => setCost(event.target.value)} /></label>}<button className="primary deep-run" disabled={busy || !stock.trim()} onClick={run}>{busy ? <RefreshCw className="spin" /> : <BrainCircuit />}{busy ? '分析中…' : '开始深研'}</button></div>
      <div className="watchlist-tools"><label>搜索全部股票并加入自选<input placeholder="输入名称或代码，例如 九安医疗 / 002432" value={searchQuery} onChange={event => setSearchQuery(event.target.value)} /></label><button className="scan-button" onClick={search} disabled={searching || !searchQuery.trim()}>{searching ? <RefreshCw className="spin" /> : <BrainCircuit />}{searching ? '搜索中…' : '搜索股票'}</button></div>
      {searchResults.length > 0 && <div className="search-results">{searchResults.map(item => <button key={item.code} onClick={() => void add(item)}><strong>{item.name}</strong><small>{item.code} · {item.market ?? 'A股'} · 点击加入</small></button>)}</div>}
      <div className="watchlist-strip"><span>我的自选</span>{watchlist.length === 0 ? <small>搜索股票后加入自己的观察列表</small> : watchlist.map(item => <button key={item.code} onClick={() => setStock(item.code)}>{item.name}<small>{item.code}</small></button>)}</div>
      {error && <p className="scan-error"><AlertTriangle />{error}</p>}
    </section>
    {history.length > 0 && <section className="panel history-panel"><div className="panel-title"><div><span className="step">04</span><h2>历史分析报告</h2></div><span className="pill">本机 SQLite</span></div><div className="history-list">{history.map(item => <button key={item.report_id} onClick={() => item.report_id && void api.getAnalysis(item.report_id).then(setReport).catch(reason => setError(String(reason)))}><span><strong>{item.stock_name}</strong><small>{item.stock_code} · {new Date(item.created_at).toLocaleString('zh-CN')}</small></span><b>{item.zhixing_index.toFixed(0)}</b><em className={`history-status ${item.enrichment_status}`}>{item.enrichment_status === 'stale' ? '缓存' : item.enrichment_status === 'ok' ? '完整' : '降级'}</em></button>)}</div></section>}
    {!report ? <section className="panel deep-empty"><BrainCircuit /><h2>输入一只股票开始分析</h2><p>首版使用腾讯实时行情和前复权日线，缺失的资金、财务、板块和新闻字段会明确标注。</p></section> : <>
      <section className="deep-hero"><div><div className="status-row"><span className={`data-status ${report.core_status}`}>{report.core_status === 'ok' ? '核心数据完整' : report.core_status === 'degraded' ? '核心数据部分降级' : '核心数据失败'}</span><span className={`data-status ${report.enrichment_status}`}>{report.enrichment_status === 'ok' ? '增强数据完整' : report.enrichment_status === 'stale' ? '增强数据使用缓存' : report.enrichment_status === 'degraded' ? '增强数据部分缺失' : '增强数据失败'}</span></div><h2>{report.stock_name}<small>{report.stock_code} · {report.sector}</small></h2><p>{report.diagnosis.summary}</p></div><div className="rocket-score"><strong>{report.zhixing_index.toFixed(0)}</strong><span>知行指数 · {report.zhixing_level}</span><small>覆盖 {report.factor_coverage} · 可信度 {report.zhixing_confidence.toFixed(0)}%</small></div></section>
      <section className="diagnosis-banner"><strong>{report.diagnosis.position}</strong><span>{report.diagnosis.summary}</span>{report.diagnosis.conflicts.length > 0 && <em>存在日周线矛盾</em>}</section>
      <section className="panel freshness-panel"><div className="panel-title"><div><h2>数据新鲜度</h2><small>黄色表示超过类别阈值，红色表示失败或缓存已过期</small></div><span className="pill">按抓取时间</span></div><div className="freshness-grid"><FreshnessItem label="行情" info={report.freshness?.quote} fallback={report.quote.fetched_at ? `抓取于 ${new Date(report.quote.fetched_at).toLocaleTimeString('zh-CN')}` : undefined} /><FreshnessItem label="日线" info={report.freshness?.daily_bars} /><FreshnessItem label="资金流" info={report.freshness?.fund_flow} /><FreshnessItem label="财务" info={report.freshness?.finance} /><FreshnessItem label="行业" info={report.freshness?.industry} /><FreshnessItem label="新闻" info={report.freshness?.news} /></div></section>
      <section className="supplement-grid">
        <article className="panel source-panel"><div className="panel-title"><h2>资金流</h2><SourceBadge status={report.fund_flow.status} source={report.fund_flow.source} endpoint={report.fund_flow.endpoint} cacheExpired={report.fund_flow.cache_expired} error={report.fund_flow.error} /></div><div className="source-metrics"><div><span>主力净流入（亿元）</span><NumberValue value={report.fund_flow.main_inflow} /></div><div><span>主力净流入占比</span><NumberValue value={report.fund_flow.main_flow_ratio != null ? report.fund_flow.main_flow_ratio * 100 : undefined} suffix="%" /></div></div><small className="source-note">交易日：{report.fund_flow.trade_date ?? '—'}<DataAge seconds={report.fund_flow.data_age_seconds} status={report.fund_flow.status} cacheUsed={report.fund_flow.cache_used} />{report.fund_flow.error ? ` · ${report.fund_flow.error}` : ''}</small></article>
        <article className="panel source-panel"><div className="panel-title"><h2>财务增速</h2><SourceBadge status={report.finance.status} source={report.finance.source} cacheExpired={report.finance.cache_expired} error={report.finance.error} /></div><div className="source-metrics"><div><span>营收同比</span><NumberValue value={report.finance.revenue_yoy} suffix="%" /></div><div><span>净利润同比</span><NumberValue value={report.finance.profit_yoy} suffix="%" /></div></div><small className="source-note">报告期：{report.finance.report_date ?? '—'}<DataAge seconds={report.finance.data_age_seconds} status={report.finance.status} cacheUsed={report.finance.cache_used} />{report.finance.error ? ` · ${report.finance.error}` : ''}</small></article>
        <article className="panel source-panel"><div className="panel-title"><h2>行业热度</h2><SourceBadge status={report.industry.status} source={report.industry.source} endpoint={report.industry.endpoint} cacheExpired={report.industry.cache_expired} error={report.industry.error} /></div><div className="source-metrics"><div><span>行业</span><strong>{report.industry.name ?? '—'}</strong></div><div><span>涨幅排名</span><strong>{report.industry.rank != null ? `${report.industry.rank} / ${report.industry.total ?? '—'}` : '—'}</strong></div><div><span>行业涨幅</span><NumberValue value={report.industry.change_pct} suffix="%" /></div></div><small className="source-note">按行业涨幅横截面排序<DataAge seconds={report.industry.data_age_seconds} status={report.industry.status} cacheUsed={report.industry.cache_used} />{report.industry.error ? ` · ${report.industry.error}` : ''}</small></article>
        <article className="panel source-panel news-panel"><div className="panel-title"><h2>相关新闻</h2><div><SourceBadge status={report.news.status} source={report.news.source} cacheExpired={report.news.cache_expired} error={report.news.error} /><small className="source-note"><DataAge seconds={report.news.data_age_seconds} status={report.news.status} cacheUsed={report.news.cache_used} /></small></div></div>{report.news.items.length === 0 ? <p className="source-note">暂无可用新闻{report.news.error ? ` · ${report.news.error}` : ''}</p> : <div className="news-list">{report.news.items.slice(0, 4).map((item, index) => <a href={item.url || undefined} target="_blank" rel="noreferrer" key={`${item.title}-${index}`}><span className={`news-sentiment ${item.sentiment}`}>{item.sentiment === 'bull' ? '利好' : item.sentiment === 'bear' ? '风险' : '中性'}</span><strong>{item.title}</strong><small>{item.source_name || '公开资讯'} · {item.published_at || '时间未知'}</small></a>)}</div>}</article>
      </section>
      <div className="deep-grid"><section className="panel chart-panel kline-panel"><div className="panel-title"><div><h2>{chartMode === 'daily' ? '日线 K 线' : '周线 K 线'}</h2><small>腾讯前复权 · 成交量 · 支撑/压力 · 历史评分</small></div><div className="chart-toolbar"><div>{(['daily', 'weekly'] as const).map(mode => <button type="button" className={chartMode === mode ? 'active' : ''} key={mode} onClick={() => { setChartMode(mode); setChartRange(mode === 'daily' ? 120 : 52) }}>{mode === 'daily' ? '日线' : '周线'}</button>)}</div><div>{(chartMode === 'daily' ? [60, 120, 252] : [26, 52, 104]).map(value => <button type="button" className={chartRange === value ? 'active' : ''} key={value} onClick={() => setChartRange(value)}>{value === 252 || value === 104 ? '全部' : value}{value === 252 || value === 104 ? '' : chartMode === 'daily' ? '日' : '周'}</button>)}</div></div></div><KlineChart bars={chartMode === 'daily' ? report.bars : report.weekly_bars} range={chartRange} support={report.technical.support20} resistance={report.technical.resistance20} history={history} stockCode={report.stock_code} /></section><section className="panel chart-panel"><div className="panel-title"><h2>六维雷达</h2><span className="pill">0–100</span></div><RadarChart dimensions={report.radar} /></section></div>
      <div className="deep-grid"><section className="panel"><div className="panel-title"><h2>行情与日周线</h2><span className="pill">日线 {report.technical.trend} · 周线 {report.weekly.trend}</span></div><div className="metric-grid">{[['现价', report.quote.price], ['涨跌', report.quote.change_pct != null ? `${report.quote.change_pct.toFixed(2)}%` : null], ['PE', report.quote.pe], ['MA5', report.technical.ma5], ['MA20', report.technical.ma20], ['MA60', report.technical.ma60], ['周MA5', report.weekly.ma5], ['RSI14', report.technical.rsi14], ['量比', report.technical.volume_ratio], ['支撑', report.technical.support20], ['压力', report.technical.resistance20]].map(([label, value]) => <div key={label as string}><span>{label}</span><strong>{typeof value === 'number' ? value.toFixed(2) : value ?? '—'}</strong></div>)}</div>{report.technical.macd && <p className="signal-line">MACD：{report.technical.macd.golden_cross ? '金叉' : report.technical.macd.death_cross ? '死叉' : report.technical.macd.hist > 0 ? '多头' : '空头'} · DIF {report.technical.macd.dif.toFixed(3)} · DEA {report.technical.macd.dea.toFixed(3)}</p>}</section>
        <section className="panel"><div className="panel-title"><h2>十因子评分</h2><span className="pill">{report.factor_coverage} 可用 · 算法 {report.algorithm_version}</span></div><div className="rocket-dimensions">{report.factors.map(factor => <article key={factor.key}><div><span>{factor.label}</span><strong className={factor.score >= 60 ? 'positive' : factor.score < 40 ? 'negative' : ''}>{factor.score.toFixed(0)}</strong></div><small>{factor.reason}{factor.available ? '' : ' · 缺失按中性 50 计入'}</small></article>)}</div></section>
      </div>
      <section className="panel evidence-panel"><div className="panel-title"><div><span className="step">03</span><h2>积极证据 / 风险证据 / 多空矛盾</h2></div><span className="pill">规则诊断</span></div><div className="evidence-grid"><div><h3>积极证据</h3>{report.diagnosis.positive_evidence.map(item => <p className="evidence-positive" key={item}>＋ {item}</p>)}</div><div><h3>风险证据</h3>{report.diagnosis.risk_evidence.map(item => <p className="evidence-risk" key={item}>－ {item}</p>)}</div><div><h3>矛盾提示</h3>{(report.diagnosis.conflicts.length ? report.diagnosis.conflicts : ['暂未发现日周线矛盾']).map(item => <p className="evidence-conflict" key={item}>△ {item}</p>)}</div></div><div className="reassess-line">重新评估条件：{report.diagnosis.reassess_conditions.join('；') || '数据补齐后再评估'}</div></section>
      <section className="panel advice-panel"><div className="panel-title"><div><span className="step">03</span><h2>操作参考与价格区间</h2></div><span className="pill">仅研究参考</span></div><div className="advice-head"><div className="advice-action">{report.advice.action}</div><div><strong>{report.advice.category}</strong><p>{report.advice.summary}</p></div><span className="status">风险：{report.advice.risk_level}</span></div><div className="zone-grid">{report.advice.zones.map(zone => <article className={`zone-${zone.tone}`} key={zone.name}><strong>{zone.name}</strong><span>¥{zone.low.toFixed(2)} ~ ¥{zone.high.toFixed(2)}</span><small>{zone.action}</small></article>)}</div><p className="deep-note">核心缺失：{report.core_missing_fields.length ? report.core_missing_fields.join('、') : '无'}；增强缺失：{report.enrichment_missing_fields.length ? report.enrichment_missing_fields.join('、') : '无'}；缓存：{report.enrichment_stale_fields.length ? report.enrichment_stale_fields.join('、') : '无'}。旧版火箭评分状态：{report.legacy_score_status}。规则指纹：{report.rule_fingerprint}。</p></section>
    </>}
  </>
}
