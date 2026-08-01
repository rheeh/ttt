import { useEffect, useState } from 'react'
import { BookOpen, CircleGauge, Database, FlaskConical, GitCompare, LayoutDashboard } from 'lucide-react'
import { api } from './api'
import { ComparePage } from './ComparePage'
import { DeepResearch } from './DeepResearch'
import { MarketReviewPage, PerformanceReviewPage, SourceHealthPage } from './ReviewPages'
import type { Candidate, DataSourceHealthResponse, MarketReview, MarketReviewRun, PerformanceVerification } from './types'

type View = 'research' | 'compare' | 'review' | 'performance' | 'sources'

function App() {
  const [view, setView] = useState<View>('research')
  const [analysisStock, setAnalysisStock] = useState('')
  const [items, setItems] = useState<Candidate[]>([])
  const [marketReview, setMarketReview] = useState<MarketReview | null>(null)
  const [reviewRuns, setReviewRuns] = useState<MarketReviewRun[]>([])
  const [reviewRunId, setReviewRunId] = useState<number | undefined>()
  const [reviewLoading, setReviewLoading] = useState(false)
  const [scanning, setScanning] = useState(false)
  const [scanMessage, setScanMessage] = useState('')
  const [verifying, setVerifying] = useState(false)
  const [verification, setVerification] = useState<PerformanceVerification | undefined>()
  const [sourceHealth, setSourceHealth] = useState<DataSourceHealthResponse | null>(null)
  const [testingSources, setTestingSources] = useState(false)

  const refreshCandidates = () => api.listCandidates().then(result => setItems(result.candidates)).catch(() => setItems([]))
  useEffect(() => { void refreshCandidates() }, [])

  async function refreshReview(runId?: number, preferLatest = false) {
    setReviewLoading(true); setScanMessage('')
    try {
      const runs = await api.marketReviewRuns()
      setReviewRuns(runs)
      const selected = runId ?? (preferLatest ? runs[0]?.run_id : reviewRunId ?? runs[0]?.run_id)
      setReviewRunId(selected)
      setMarketReview(await api.marketReview(selected))
    } catch (error) { setScanMessage(String(error)) } finally { setReviewLoading(false) }
  }
  async function runReferenceScan() {
    setScanning(true); setScanMessage('')
    try { await api.scanPool(); await refreshReview(undefined, true) }
    catch (error) { setScanMessage(String(error)) }
    finally { setScanning(false) }
  }
  async function verifyPerformance() {
    setVerifying(true)
    try { setVerification(await api.verifyPerformance()); await refreshCandidates() }
    catch { /* the page retains its previous local snapshot */ }
    finally { setVerifying(false) }
  }
  async function refreshSourceHealth() {
    try { setSourceHealth(await api.sourceHealth()) } catch { setSourceHealth(null) }
  }
  async function testSourceHealth() {
    setTestingSources(true)
    try { setSourceHealth(await api.testSourceHealth()) } finally { setTestingSources(false) }
  }
  function openStock(code: string) { setAnalysisStock(code); setView('research') }

  return <div className="shell">
    <aside>
      <div className="brand"><span>知行</span><small>STOCK LAB</small></div>
      <nav>
        <button className={view === 'research' ? 'active' : ''} onClick={() => setView('research')}><LayoutDashboard />个股研究</button>
        <button className={view === 'compare' ? 'active' : ''} onClick={() => setView('compare')}><GitCompare />股票对比</button>
        <button className={view === 'review' ? 'active' : ''} onClick={() => { setView('review'); void refreshReview() }}><CircleGauge />市场复盘</button>
        <button className={view === 'performance' ? 'active' : ''} onClick={() => { setView('performance'); void refreshCandidates() }}><FlaskConical />回测核验</button>
        <button className={view === 'sources' ? 'active' : ''} onClick={() => { setView('sources'); void refreshSourceHealth() }}><Database />数据源状态</button>
        <button className="nav-pending" disabled title="后续决定"><BookOpen />研究日志<span>后续决定</span></button>
      </nav>
      <div className="nav-foot"><Database />仅本机存储 <span className="status-dot" /></div>
    </aside>
    <main>
      {view === 'research' ? <DeepResearch initialStock={analysisStock} /> : view === 'compare' ? <ComparePage onOpenStock={openStock} /> : view === 'review' ? <MarketReviewPage review={marketReview} runs={reviewRuns} selectedRunId={reviewRunId} loading={reviewLoading} scanning={scanning} scanMessage={scanMessage} onScan={() => void runReferenceScan()} onRefresh={runId => void refreshReview(runId)} onOpenStock={openStock} /> : view === 'performance' ? <PerformanceReviewPage candidates={items} summary={verification} verifying={verifying} onVerify={() => void verifyPerformance()} onRefresh={() => void refreshCandidates()} /> : <SourceHealthPage health={sourceHealth} testing={testingSources} onTest={() => void testSourceHealth()} onRefresh={() => void refreshSourceHealth()} />}
    </main>
  </div>
}

export default App
