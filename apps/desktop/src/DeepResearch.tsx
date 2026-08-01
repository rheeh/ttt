import { useState } from 'react'
import { AlertTriangle, ArrowLeft, BrainCircuit, RefreshCw } from 'lucide-react'
import { api } from './api'
import type { AnalysisReport } from './types'

type Props = { initialStock?: string; onBack: () => void }

export function DeepResearch({ initialStock = '', onBack }: Props) {
  const [stock, setStock] = useState(initialStock)
  const [holding, setHolding] = useState(false)
  const [cost, setCost] = useState('')
  const [report, setReport] = useState<AnalysisReport | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  async function run() {
    setBusy(true); setError('')
    try { setReport(await api.analyze(stock, holding, cost ? Number(cost) : undefined)) }
    catch (reason) { setError(String(reason)) }
    finally { setBusy(false) }
  }
  return <>
    <header><div><p className="eyebrow">INDIVIDUAL RESEARCH</p><h1>个股深研</h1><p>在 S/A/B/C 初筛之后，查看技术面与火箭评分的第二层证据。</p></div><button className="icon-btn" onClick={onBack}><ArrowLeft /></button></header>
    <section className="panel deep-search">
      <div className="deep-search-row"><label>股票代码或名称<input placeholder="例如 600519 / 贵州茅台" value={stock} onChange={event => setStock(event.target.value)} /></label><label className="holding-check"><input type="checkbox" checked={holding} onChange={event => setHolding(event.target.checked)} /><span />当前已持有</label>{holding && <label>持仓成本<input type="number" value={cost} onChange={event => setCost(event.target.value)} /></label>}<button className="primary deep-run" disabled={busy || !stock.trim()} onClick={run}>{busy ? <RefreshCw className="spin" /> : <BrainCircuit />}{busy ? '分析中…' : '开始深研'}</button></div>
      {error && <p className="scan-error"><AlertTriangle />{error}</p>}
    </section>
    {!report ? <section className="panel deep-empty"><BrainCircuit /><h2>输入一只股票开始分析</h2><p>首版使用腾讯实时行情和前复权日线，缺失的资金、财务、板块和新闻字段会明确标注。</p></section> : <>
      <section className="deep-hero"><div><span className={`data-status ${report.status}`}>{report.status === 'ok' ? '数据完整' : '部分降级'}</span><h2>{report.stock_name}<small>{report.stock_code} · {report.sector}</small></h2><p>{report.advice.summary}</p></div><div className="rocket-score"><strong>{report.rocket.score}</strong><span>火箭评分 · {report.rocket.level}</span></div></section>
      <div className="deep-grid"><section className="panel"><div className="panel-title"><h2>行情与技术指标</h2><span className="pill">{report.technical.trend}</span></div><div className="metric-grid">{[['现价', report.quote.price], ['涨跌', report.quote.change_pct != null ? `${report.quote.change_pct.toFixed(2)}%` : null], ['PE', report.quote.pe], ['MA5', report.technical.ma5], ['MA20', report.technical.ma20], ['MA60', report.technical.ma60], ['RSI14', report.technical.rsi14], ['量比', report.technical.volume_ratio], ['支撑', report.technical.support20], ['压力', report.technical.resistance20]].map(([label, value]) => <div key={label as string}><span>{label}</span><strong>{typeof value === 'number' ? value.toFixed(2) : value ?? '—'}</strong></div>)}</div>{report.technical.macd && <p className="signal-line">MACD：{report.technical.macd.golden_cross ? '金叉' : report.technical.macd.death_cross ? '死叉' : report.technical.macd.hist > 0 ? '多头' : '空头'} · DIF {report.technical.macd.dif.toFixed(3)} · DEA {report.technical.macd.dea.toFixed(3)}</p>}</section>
        <section className="panel"><div className="panel-title"><h2>八维火箭评分</h2><span className="pill">{report.rocket.missing_fields.length ? '有字段未接入' : '八维完整'}</span></div><div className="rocket-dimensions">{report.rocket.dimensions.map(d => <article key={d.key}><div><span>{d.label}</span><strong className={d.score >= 0 ? 'positive' : 'negative'}>{d.score > 0 ? '+' : ''}{d.score}</strong></div><small>{d.available ? d.reasons.join(' · ') || '中性' : `${d.reasons.join(' · ')}（降级）`}</small></article>)}</div></section>
      </div>
      <section className="panel advice-panel"><div className="panel-title"><div><span className="step">03</span><h2>操作参考与价格区间</h2></div><span className="pill">仅研究参考</span></div><div className="advice-head"><div className="advice-action">{report.advice.action}</div><div><strong>{report.advice.category}</strong><p>{report.advice.summary}</p></div><span className="status">风险：{report.advice.risk_level}</span></div><div className="zone-grid">{report.advice.zones.map(zone => <article className={`zone-${zone.tone}`} key={zone.name}><strong>{zone.name}</strong><span>¥{zone.low.toFixed(2)} ~ ¥{zone.high.toFixed(2)}</span><small>{zone.action}</small></article>)}</div><p className="deep-note">缺失字段：{report.missing_fields.length ? report.missing_fields.join('、') : '无'}。火箭评分是经验公式，不代表预测或交易指令。</p></section>
    </>}
  </>
}
