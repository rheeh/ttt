import { useEffect, useMemo, useState } from 'react'
import { Activity, AlertTriangle, BarChart3, Bell, BookOpen, ChevronRight, CircleGauge, Clock3, Database, FlaskConical, LayoutDashboard, Plus, Radar, RefreshCw, Search, Settings, Sparkles } from 'lucide-react'
import { api } from './api'
import { DeepResearch } from './DeepResearch'
import type { Candidate, MarketScan, ScoreInput, ScoreResult } from './types'

const initial: ScoreInput = {
  stock_code: 'sh603501', stock_name: '韦尔股份', sector: '半导体', price: 103.6,
  pe: 34.2, pb: 5.1, pe_percentile: .24, pb_percentile: .38,
  change_pct: 1.8, turnover_pct: 3.6, amplitude_pct: 4.2,
  main_flow_ratio: .036, sector_change_pct: 2.4, quality_score: 2,
  ma5: 101.8, ma10: 98.7, ma20: 94.2, in_rotation_pool: true,
}

const fields: {key: keyof ScoreInput; label: string; step?: string}[] = [
  {key:'price',label:'现价'},{key:'change_pct',label:'涨跌 %'},{key:'pe',label:'PE'},{key:'pb',label:'PB'},
  {key:'pe_percentile',label:'PE 分位',step:'.01'},{key:'pb_percentile',label:'PB 分位',step:'.01'},
  {key:'turnover_pct',label:'换手 %'},{key:'amplitude_pct',label:'振幅 %'},
  {key:'main_flow_ratio',label:'主力流入比',step:'.001'},{key:'sector_change_pct',label:'板块涨幅 %'},
  {key:'quality_score',label:'扣非质量分'},{key:'ma5',label:'MA5'},{key:'ma10',label:'MA10'},{key:'ma20',label:'MA20'},
]

function App() {
  const [input, setInput] = useState(initial)
  const [result, setResult] = useState<ScoreResult | null>(null)
  const [items, setItems] = useState<Candidate[]>([])
  const [busy, setBusy] = useState(false)
  const [message, setMessage] = useState('')
  const [scan, setScan] = useState<MarketScan | null>(null)
  const [scanning, setScanning] = useState(false)
  const [scanMessage, setScanMessage] = useState('')
  const [savingScan, setSavingScan] = useState(false)
  const [view, setView] = useState<'desk' | 'deep'>('desk')
  const [analysisStock, setAnalysisStock] = useState('')
  const best = useMemo(() => items.filter(x => x.grade === 'S' || x.grade === 'A').length, [items])

  const refresh = () => api.listCandidates().then(x => setItems(x.candidates)).catch(() => setItems([]))
  useEffect(() => { void refresh() }, [])

  async function runScore() {
    setBusy(true); setMessage('')
    try { setResult(await api.score(input)) } catch (error) { setMessage(String(error)) } finally { setBusy(false) }
  }
  async function save() {
    setBusy(true); setMessage('')
    try { await api.saveCandidate(input); await refresh(); setMessage('已保存到本地预选股') }
    catch (error) { setMessage(String(error)) } finally { setBusy(false) }
  }
  async function scanPool() {
    setScanning(true); setScanMessage('')
    try { setScan(await api.scanPool()) }
    catch (error) { setScanMessage(String(error)) }
    finally { setScanning(false) }
  }
  async function saveScanCandidates() {
    if (!scan?.run_id) return
    setSavingScan(true); setScanMessage('')
    try { const saved = await api.saveScanCandidates(scan.run_id); await refresh(); setScanMessage(`已将前 ${saved.created} 只 S/A/B 候选加入长期预选`) }
    catch (error) { setScanMessage(String(error)) }
    finally { setSavingScan(false) }
  }

  return <div className="shell">
    <aside>
      <div className="brand"><span>知行</span><small>STOCK LAB</small></div>
      <nav>
        <button className={view === 'desk' ? 'active' : ''} onClick={() => setView('desk')}><LayoutDashboard />研究台</button>
        <button className="nav-pending" disabled title="建设中"><CircleGauge />市场复盘<span>建设中</span></button>
        <button className="nav-pending" disabled title="建设中"><Search />条件选股<span>建设中</span></button>
        <button className={view === 'deep' ? 'active' : ''} onClick={() => setView('deep')}><BarChart3 />个股深研</button>
        <button className="nav-pending" disabled title="建设中"><FlaskConical />回测核验<span>建设中</span></button>
        <button className="nav-pending" disabled title="建设中"><BookOpen />研究日志<span>建设中</span></button>
        <button className="nav-pending" disabled title="建设中"><Bell />达人消息<span>建设中</span></button>
      </nav>
      <div className="nav-foot"><Database />仅本机存储 <span className="status-dot" /></div>
    </aside>

    <main>
      {view === 'deep' ? <DeepResearch initialStock={analysisStock} onBack={() => setView('desk')} /> : <>
      <header><div><p className="eyebrow">PERSONAL RESEARCH DESK</p><h1>今日研究台</h1><p>把经验规则变成可解释、可保存、可回看的证据。</p></div><button className="icon-btn"><Settings /></button></header>

      <section className="stats">
        <article><span>长期预选</span><strong>{items.length}</strong><small>全部保留，不自动删除</small></article>
        <article><span>S / A 级</span><strong>{best}</strong><small>只是研究优先级</small></article>
        <article><span>当前策略</span><strong className="strategy-name">群友原版</strong><small>v1.0.0 · 固定池 · 最多 4 只</small></article>
      </section>

      <div className="workspace">
        <section className="panel form-panel">
          <div className="panel-title"><div><span className="step">01</span><h2>输入标准化事实</h2></div><span className="pill">MANUAL</span></div>
          <div className="identity-row">
            <label>股票代码<input value={input.stock_code} onChange={e=>setInput({...input,stock_code:e.target.value})}/></label>
            <label>名称<input value={input.stock_name} onChange={e=>setInput({...input,stock_name:e.target.value})}/></label>
            <label>板块<input value={input.sector} onChange={e=>setInput({...input,sector:e.target.value})}/></label>
          </div>
          <div className="field-grid">{fields.map(field => <label key={field.key}>{field.label}<input type="number" step={field.step ?? '0.1'} value={input[field.key] as number ?? ''} onChange={e=>setInput({...input,[field.key]:Number(e.target.value)})}/></label>)}</div>
          <label className="switch-row"><input type="checkbox" checked={input.in_rotation_pool} onChange={e=>setInput({...input,in_rotation_pool:e.target.checked})}/><span />当前在轮动池（+4）</label>
          <button className="primary" onClick={runScore} disabled={busy}>{busy ? <RefreshCw className="spin"/> : <Sparkles/>}运行规则试算</button>
          {message && <p className="message">{message}</p>}
        </section>

        <section className="panel result-panel">
          <div className="panel-title"><div><span className="step">02</span><h2>评分解释</h2></div>{result && <span className="pill">{result.strategy_version}</span>}</div>
          {!result ? <div className="empty"><Activity/><h3>等待一次试算</h3><p>评分不只给结论，会保留每个维度的得分理由。</p></div> : <>
            <div className="score-head"><div className={`grade grade-${result.grade.toLowerCase()}`}>{result.grade}</div><div><strong>{result.total_score}</strong><span>综合分</span></div><p>{result.eligible ? '通过强制过滤，可加入观察。' : result.rejected_reasons.join('、')}</p></div>
            <div className="dimensions">{result.dimensions.map(d=><article key={d.name}><span>{d.label}</span><strong className={d.score >= 0 ? 'positive':'negative'}>{d.score>0?'+':''}{d.score}</strong><small>{d.reasons.join(' · ') || '未触发明确信号'}</small></article>)}</div>
            <button className="save" disabled={!result.eligible || busy} onClick={save}><Plus/>加入长期预选</button>
          </>}
        </section>
      </div>

      <section className="panel pool-scan">
        <div className="panel-title"><div><span className="scan-icon"><Radar/></span><div><h2>固定观察池扫描</h2><small>66 只 A 股 · 腾讯行情 · 群友原版评分</small></div></div><button className="scan-button" onClick={scanPool} disabled={scanning}>{scanning ? <RefreshCw className="spin"/> : <Radar/>}{scanning ? '正在扫描…' : '扫描全部股票'}</button></div>
        {scanMessage && <p className="scan-error"><AlertTriangle/>{scanMessage}</p>}
        {!scan ? <div className="scan-placeholder"><p>从真实行情中计算行业 PE/PB 分位、板块动量和 S/A/B/C 等级。</p><span>数据缺失时会标明降级，不用伪造数据补位。</span></div> : <>
          <div className="scan-summary">
            <span><b>{scan.succeeded}</b> / {scan.total} 成功</span>
            <span className="degraded"><b>{scan.degraded}</b> 条降级</span>
            <span className={scan.failed ? 'failed':''}><b>{scan.failed}</b> 条失败</span>
            <span><b>{scan.scoreable}</b> 条可评分</span>
            <button className="scan-save" onClick={saveScanCandidates} disabled={savingScan || !scan.run_id}>{savingScan ? '保存中…' : '批量加入预选'}</button>
            <span className="scan-time"><Clock3/>{new Date(scan.completed_at).toLocaleTimeString('zh-CN')} · {scan.source}</span>
          </div>
          <div className="scan-table"><div className="scan-row scan-header"><span>等级</span><span>股票</span><span>板块</span><span>现价</span><span>涨跌</span><span>PE / PB</span><span>总分</span><span>数据状态</span></div>{scan.items.slice(0,10).map(item=><div className="scan-row" key={item.preset.code}>
            <span className={`mini-grade grade-${(item.score?.grade ?? 'c').toLowerCase()}`}>{item.score?.grade ?? '—'}</span>
            <span><button className="scan-stock-link" onClick={() => { setAnalysisStock(item.preset.code); setView('deep') }}>{item.quote.stock_name || item.preset.name}</button><small>{item.preset.code}</small></span><span>{item.preset.sector}</span>
            <span>¥{item.quote.price?.toFixed(2) ?? '—'}</span><span className={(item.quote.change_pct ?? 0)>=0?'positive':'negative'}>{item.quote.change_pct != null ? `${item.quote.change_pct>0?'+':''}${item.quote.change_pct.toFixed(2)}%` : '—'}</span>
            <span>{item.quote.pe?.toFixed(1) ?? '—'} / {item.quote.pb?.toFixed(1) ?? '—'}</span><span><strong>{item.score?.total_score ?? '—'}</strong></span>
            <span className={`data-status ${item.quote.status}`}>{item.quote.status === 'ok' ? '完整' : item.quote.status === 'degraded' ? '已降级' : '失败'}</span>
          </div>)}</div>
        </>}
      </section>

      <section className="panel candidates">
        <div className="panel-title"><div><span className="step">03</span><h2>最近预选股</h2></div><button className="text-btn" onClick={refresh}>查看全部 <ChevronRight/></button></div>
        {items.length === 0 ? <div className="empty-row">还没有预选股，从上方完成第一次试算。</div> : <div className="candidate-list">{items.slice(0,5).map(item=><article key={item.id}><span className={`mini-grade grade-${item.grade.toLowerCase()}`}>{item.grade}</span><div><strong>{item.stock_name}</strong><small>{item.stock_code} · {item.source_name}</small></div><div className="candidate-score">{item.total_score}<small>分</small></div><div><strong>¥{item.selected_price.toFixed(2)}</strong><small>{new Date(item.selected_at).toLocaleString('zh-CN')}</small></div><span className="status">{item.status === 'new' ? '新发现' : item.status}</span></article>)}</div>}
      </section>
      <footer>本工具仅用于个人研究与复盘，不构成投资建议，不执行任何交易。</footer>
      </>}
    </main>
  </div>
}

export default App
