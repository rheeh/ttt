import { useEffect, useMemo, useState } from 'react'
import { AlertTriangle, BarChart3, RefreshCw, X } from 'lucide-react'
import { api } from './api'
import type { AnalysisReport, StockSearchResult } from './types'

type Props = { onOpenStock: (code: string) => void }
type Row = {label: string; value: (report: AnalysisReport) => string; tone?: (report: AnalysisReport) => string}
const colors = ['#3d7255', '#b18445', '#8c5a9f']
const number = (value?: number, digits = 2) => value == null || Number.isNaN(value) ? '—' : value.toFixed(digits)
const pct = (value?: number) => value == null || Number.isNaN(value) ? '—' : `${value > 0 ? '+' : ''}${value.toFixed(2)}%`

function normalizedSeries(report: AnalysisReport, dates: string[]) {
  const byDate = new Map(report.bars.map(bar => [bar.trade_date, bar.close]))
  const first = dates.map(date => byDate.get(date)).find(value => value != null)
  return dates.map(date => { const close = byDate.get(date); return close != null && first ? close / first * 100 : null })
}

function maxDrawdown(report: AnalysisReport) {
  let peak = 0, drawdown = 0
  for (const bar of report.bars.slice(-120)) { peak = Math.max(peak, bar.close); if (peak) drawdown = Math.min(drawdown, (bar.close / peak - 1) * 100) }
  return drawdown
}

function volatility(report: AnalysisReport) {
  const closes = report.bars.slice(-61).map(bar => bar.close)
  const changes = closes.slice(1).map((close, index) => close / closes[index] - 1)
  if (changes.length < 2) return undefined
  const average = changes.reduce((sum, value) => sum + value, 0) / changes.length
  return Math.sqrt(changes.reduce((sum, value) => sum + (value - average) ** 2, 0) / changes.length) * 100
}

function TrendCompare({reports}: {reports: AnalysisReport[]}) {
  const dateSets = reports.map(report => new Set(report.bars.map(bar => bar.trade_date)))
  const dates = [...new Set(reports.flatMap(report => report.bars.slice(-120).map(bar => bar.trade_date)))].filter(date => dateSets.every(set => set.has(date))).slice(-120)
  if (dates.length < 2) return <div className="chart-empty">共同交易日不足，无法比较走势</div>
  const series = reports.map(report => normalizedSeries(report, dates))
  const values = series.flatMap(items => items.filter((value): value is number => value != null))
  const min = Math.min(...values, 95), max = Math.max(...values, 105), range = Math.max(max - min, 1)
  const point = (index: number, value: number) => `${index / Math.max(dates.length - 1, 1) * 100},${96 - (value - min) / range * 86}`
  return <div className="compare-chart-wrap"><svg className="compare-chart" viewBox="0 0 100 100" preserveAspectRatio="none" role="img" aria-label="标准化走势比较"><line x1="0" y1={96 - (100 - min) / range * 86} x2="100" y2={96 - (100 - min) / range * 86} stroke="#d6ddd6" strokeDasharray="2 2" vectorEffect="non-scaling-stroke" />{series.map((items, index) => <polyline key={reports[index].stock_code} points={items.map((value, pointIndex) => value == null ? '' : point(pointIndex, value)).filter(Boolean).join(' ')} fill="none" stroke={colors[index]} strokeWidth="1.8" vectorEffect="non-scaling-stroke" />)}</svg><div className="compare-chart-legend">{reports.map((report, index) => <span key={report.stock_code}><i style={{background: colors[index]}} />{report.stock_name} · 100起点</span>)}</div><small className="source-note">共同交易日：{dates[0]} 至 {dates[dates.length - 1]} · 仅比较相对走势，不比较绝对股价</small></div>
}

function CompareTable({reports}: {reports: AnalysisReport[]}) {
  const rows: Row[] = [
    {label: '现价', value: report => `¥${number(report.quote.price)}`},
    {label: '今日涨跌', value: report => pct(report.quote.change_pct), tone: report => (report.quote.change_pct ?? 0) >= 0 ? 'positive' : 'negative'},
    {label: '换手率', value: report => pct(report.quote.turnover_pct)},
    {label: '振幅', value: report => pct(report.quote.amplitude_pct)},
    {label: '20日收益', value: report => pct(report.technical.return_20d_pct), tone: report => (report.technical.return_20d_pct ?? 0) >= 0 ? 'positive' : 'negative'},
    {label: '60日收益', value: report => pct(report.technical.return_60d_pct), tone: report => (report.technical.return_60d_pct ?? 0) >= 0 ? 'positive' : 'negative'},
    {label: '最大回撤', value: report => pct(maxDrawdown(report)), tone: () => 'negative'},
    {label: '60日波动', value: report => pct(volatility(report))},
    {label: '趋势', value: report => report.technical.trend},
    {label: 'RSI14', value: report => number(report.technical.rsi14)},
    {label: 'MA5 / MA20', value: report => `${number(report.technical.ma5)} / ${number(report.technical.ma20)}`},
    {label: '支撑 / 压力', value: report => `${number(report.technical.support20)} / ${number(report.technical.resistance20)}`},
    {label: 'PE / PB', value: report => `${number(report.quote.pe)} / ${number(report.quote.pb)}`},
    {label: '营收同比', value: report => pct(report.finance.revenue_yoy), tone: report => (report.finance.revenue_yoy ?? 0) >= 0 ? 'positive' : 'negative'},
    {label: '净利润同比', value: report => pct(report.finance.profit_yoy), tone: report => (report.finance.profit_yoy ?? 0) >= 0 ? 'positive' : 'negative'},
    {label: '主力流入比', value: report => pct(report.fund_flow.main_flow_ratio == null ? undefined : report.fund_flow.main_flow_ratio * 100), tone: report => (report.fund_flow.main_flow_ratio ?? 0) >= 0 ? 'positive' : 'negative'},
    {label: '行业位置', value: report => report.industry.rank != null ? `${report.industry.rank} / ${report.industry.total ?? '—'}` : '—'},
    {label: '知行指数', value: report => `${number(report.zhixing_index, 0)} · ${report.zhixing_level}`},
    {label: '覆盖 / 可信度', value: report => `${report.factor_coverage} · ${number(report.zhixing_confidence, 0)}%`},
  ]
  return <div className="compare-table"><div className="compare-table-row compare-table-header"><span>指标</span>{reports.map(report => <span key={report.stock_code}>{report.stock_name}<small>{report.stock_code}</small></span>)}</div>{rows.map(row => <div className="compare-table-row" key={row.label}><span>{row.label}</span>{reports.map(report => <strong className={row.tone?.(report) ?? ''} key={report.stock_code}>{row.value(report)}</strong>)}</div>)}</div>
}

export function ComparePage({onOpenStock}: Props) {
  const [query, setQuery] = useState('')
  const [suggestions, setSuggestions] = useState<StockSearchResult[]>([])
  const [selected, setSelected] = useState<StockSearchResult[]>([])
  const [reports, setReports] = useState<AnalysisReport[]>([])
  const [errors, setErrors] = useState<Record<string, string>>({})
  const [loading, setLoading] = useState(false)
  const [suggesting, setSuggesting] = useState(false)

  useEffect(() => {
    const value = query.trim()
    let active = true
    const timer = window.setTimeout(async () => {
      if (!value) { if (active) { setSuggestions([]); setSuggesting(false) }; return }
      setSuggesting(true)
      try { const rows = await api.searchStocks(value); if (active) setSuggestions(rows.filter(row => !selected.some(item => item.code === row.code)).slice(0, 8)) }
      catch { if (active) setSuggestions([]) }
      finally { if (active) setSuggesting(false) }
    }, value ? 220 : 0)
    return () => { active = false; window.clearTimeout(timer) }
  }, [query, selected])

  function add(item: StockSearchResult) {
    if (selected.length >= 3 || selected.some(row => row.code === item.code)) return
    setSelected(rows => [...rows, item]); setQuery(''); setSuggestions([])
  }
  function remove(code: string) { setSelected(rows => rows.filter(row => row.code !== code)); setReports(rows => rows.filter(row => row.stock_code !== code)) }
  async function compare() {
    if (selected.length < 2) return
    setLoading(true); setErrors({})
    try { const result = await api.compareStocks(selected.map(item => item.code)); setReports(result.reports); setErrors(result.errors) }
    catch (error) { setErrors({request: String(error)}) }
    finally { setLoading(false) }
  }

  const sectorWarning = useMemo(() => new Set(reports.map(report => report.sector)).size > 1, [reports])
  return <>
    <header><div><p className="eyebrow">STOCK COMPARISON</p><h1>股票对比</h1><p>选择 2～3 只股票，用标准化走势、技术面、估值、财务和知行指数做并排比较。</p></div></header>
    <section className="panel compare-picker"><div className="panel-title"><div><h2>选择股票</h2><small>输入名称或代码，最多选择 3 只</small></div><span className="pill">{selected.length} / 3</span></div><div className="compare-search"><label>搜索股票<input autoComplete="off" placeholder="例如 云南、600519、九安" value={query} onChange={event => setQuery(event.target.value)} /></label>{(suggestions.length > 0 || suggesting) && <div className="compare-suggestions">{suggesting && suggestions.length === 0 ? <div>正在搜索…</div> : suggestions.map(item => <button type="button" key={item.code} onMouseDown={event => event.preventDefault()} onClick={() => add(item)}><strong>{item.name}</strong><small>{item.code} · {item.market ?? 'A股'}</small></button>)}</div>}</div><div className="selected-stocks">{selected.map((item, index) => <span key={item.code} style={{borderColor: colors[index]}}><b>{item.name}</b><small>{item.code}</small><button type="button" onClick={() => remove(item.code)} aria-label={`移除${item.name}`}><X /></button></span>)}{selected.length < 3 && <em>还可添加 {3 - selected.length} 只</em>}</div><button className="primary compare-run" disabled={selected.length < 2 || loading} onClick={() => void compare()}>{loading ? <RefreshCw className="spin" /> : <BarChart3 />}{loading ? '分析对比中…' : '运行对比'}</button></section>
    {errors.request && <p className="scan-error"><AlertTriangle />{errors.request}</p>}
    {Object.keys(errors).some(key => key !== 'request') && <p className="scan-error"><AlertTriangle />部分股票无法分析：{Object.entries(errors).filter(([key]) => key !== 'request').map(([key, value]) => `${key}：${value}`).join('；')}</p>}
    {!reports.length ? <section className="panel compare-empty"><BarChart3 /><h2>选择股票后开始比较</h2><p>价格统一以起点 100 标准化，避免直接拿 100 元和 10 元股票比较价格高低。</p></section> : <>
      {sectorWarning && <div className="compare-warning">这些股票不属于同一行业，PE/PB 只比较行业分位，不直接比较绝对估值。</div>}
      <section className="compare-cards">{reports.map((report, index) => <article className="panel compare-card" key={report.stock_code}><div className="compare-card-head"><span style={{background: colors[index]}} /><button type="button" onClick={() => onOpenStock(report.stock_code)}><strong>{report.stock_name}</strong><small>{report.stock_code} · {report.sector}</small></button><b>{report.zhixing_index.toFixed(0)}</b></div><p>{report.diagnosis.summary}</p><div className="compare-card-tags"><span>{report.zhixing_level}</span><span>{report.factor_coverage} 可用</span><span>{report.enrichment_status === 'not_applicable' ? '个股增强不适用' : report.enrichment_status === 'stale' ? '缓存数据' : report.enrichment_status === 'ok' ? '增强完整' : '增强缺失'}</span></div><div className="compare-evidence"><div><b>优势</b>{report.diagnosis.positive_evidence.slice(0, 2).map(item => <small key={item}>＋ {item}</small>)}</div><div><b>风险</b>{report.diagnosis.risk_evidence.slice(0, 2).map(item => <small key={item}>－ {item}</small>)}</div></div></article>)}</section>
      <section className="panel"><div className="panel-title"><div><h2>标准化走势</h2><small>共同交易日，起点 = 100</small></div><span className="pill">近 120 日</span></div><TrendCompare reports={reports} /></section>
      <section className="panel"><div className="panel-title"><div><h2>指标对比</h2><small>数值保留原始单位，缺失数据显示为 —</small></div><span className="pill">确定性规则</span></div><CompareTable reports={reports} /></section>
    </>}
  </>
}
