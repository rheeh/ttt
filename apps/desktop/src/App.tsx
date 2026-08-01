import { useEffect, useMemo, useState } from 'react'
import { Activity, BarChart3, Bell, BookOpen, ChevronRight, CircleGauge, Database, FlaskConical, LayoutDashboard, Plus, RefreshCw, Search, Settings, Sparkles } from 'lucide-react'
import { api } from './api'
import type { Candidate, ScoreInput, ScoreResult } from './types'

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

  return <div className="shell">
    <aside>
      <div className="brand"><span>知行</span><small>STOCK LAB</small></div>
      <nav>
        <button className="active"><LayoutDashboard />研究台</button>
        <button><CircleGauge />市场复盘</button><button><Search />条件选股</button>
        <button><BarChart3 />个股深研</button><button><FlaskConical />回测核验</button>
        <button><BookOpen />研究日志</button><button><Bell />达人消息</button>
      </nav>
      <div className="nav-foot"><Database />仅本机存储 <span className="status-dot" /></div>
    </aside>

    <main>
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

      <section className="panel candidates">
        <div className="panel-title"><div><span className="step">03</span><h2>最近预选股</h2></div><button className="text-btn" onClick={refresh}>查看全部 <ChevronRight/></button></div>
        {items.length === 0 ? <div className="empty-row">还没有预选股，从上方完成第一次试算。</div> : <div className="candidate-list">{items.slice(0,5).map(item=><article key={item.id}><span className={`mini-grade grade-${item.grade.toLowerCase()}`}>{item.grade}</span><div><strong>{item.stock_name}</strong><small>{item.stock_code} · {item.source_name}</small></div><div className="candidate-score">{item.total_score}<small>分</small></div><div><strong>¥{item.selected_price.toFixed(2)}</strong><small>{new Date(item.selected_at).toLocaleString('zh-CN')}</small></div><span className="status">{item.status === 'new' ? '新发现' : item.status}</span></article>)}</div>}
      </section>
      <footer>本工具仅用于个人研究与复盘，不构成投资建议，不执行任何交易。</footer>
    </main>
  </div>
}

export default App
