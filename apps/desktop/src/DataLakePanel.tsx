import { useEffect, useState } from 'react'
import { Database, RefreshCw } from 'lucide-react'
import './data-lake.css'

type Job = {id: string; status: string; mode: string; created_at: string; current_step: string; error?: string; steps: {name: string; status: string; rows_written?: number; error?: string}[]}
type Dataset = {dataset: string; label: string; has_data: boolean; coverage_start?: string; coverage_end?: string; history_mode: string; pit_quality?: string}
type LakeStatus = {installed_version?: string; required_version: string; root: string; error?: string; settings: {symbols: string[]; auto_update: boolean}; datasets: Dataset[]; jobs: Job[]; schedule: string}
const labels: Record<string, string> = {queued:'等待开始',running:'采集中',success:'已完成',partial:'部分完成',failed:'失败',interrupted:'已中断',warning:'有缺失'}
async function read<T>(url: string, init?: RequestInit): Promise<T> {
  const response = await fetch(url, init)
  const body = await response.json()
  if (!response.ok) throw new Error(typeof body.detail === 'string' ? body.detail : '数据湖请求失败，请检查输入和服务状态')
  return body
}

export function DataLakePanel() {
  const [status, setStatus] = useState<LakeStatus | null>(null)
  const [symbols, setSymbols] = useState('')
  const [auto, setAuto] = useState(true)
  const [dirty, setDirty] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const active = status?.jobs.some(job => ['queued','running'].includes(job.status)) ?? false
  useEffect(() => {
    let live = true
    const refresh = async () => {
      try {
        const value = await read<LakeStatus>('/api/data-lake/status')
        if (live) {setStatus(value); if (!dirty) {setSymbols(value.settings.symbols.join(', ')); setAuto(value.settings.auto_update)}}
      } catch (reason) {if (live) setError(reason instanceof Error ? reason.message : '状态读取失败')}
    }
    void refresh()
    const timer = window.setInterval(() => void refresh(), active ? 3000 : 30000)
    return () => {live = false; window.clearInterval(timer)}
  }, [active, dirty])

  async function run(mode?: string) {
    setBusy(true); setError(''); setNotice('')
    try {
      await read('/api/data-lake/settings', {method:'PUT', headers:{'Content-Type':'application/json'}, body:JSON.stringify({symbols:symbols.split(/[,，\s]+/).filter(Boolean), auto_update:auto})})
      setDirty(false)
      if (mode) await read('/api/data-lake/collect', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({mode, history_days:1100})})
      setStatus(await read<LakeStatus>('/api/data-lake/status'))
      setNotice(mode ? '采集已启动，可切换页面；历史数据会保存在本机。' : '采集设置已保存。')
    } catch (reason) {setError(reason instanceof Error ? reason.message : '操作失败')}
    finally {setBusy(false)}
  }
  const latest = status?.jobs[0]
  return <section className="panel lake-panel" aria-label="长期历史数据湖">
    <div className="panel-title"><div><h2><Database size={19}/> 长期历史数据湖</h2><p>收盘后更新，本地长期保存，研究与训练共用。盘中现价继续通过行情接口获取。</p></div><span className="pill">{status?.installed_version ? `CNEquity ${status.installed_version}` : '尚未安装'}</span></div>
    {!status?.installed_version && <p className="source-note">安装数据后端后可开始采集：<code>.venv/bin/python -m pip install -r requirements-data.txt</code></p>}
    <div className="lake-form"><label>采集股票（最多200只，逗号分隔）<textarea rows={2} value={symbols} onChange={event => {setSymbols(event.target.value); setDirty(true)}} placeholder="600519.SH, 000001.SZ"/></label><label className="lake-checkbox"><input type="checkbox" checked={auto} onChange={event => {setAuto(event.target.checked); setDirty(true)}}/>应用运行时自动更新</label></div>
    <div className="lake-actions"><button disabled={busy || active || !status?.installed_version} onClick={() => void run('update')}><RefreshCw size={15}/>{active ? '正在采集…' : '更新历史数据'}</button><button disabled={busy || active || !status?.installed_version} onClick={() => void run('backfill')}>回补最近3年</button><button disabled={busy || active || !status?.installed_version} onClick={() => void run('research')}>采集财报、公告与行业</button><button disabled={busy || !dirty} onClick={() => void run()}>保存设置</button></div>
    <p className="source-note">日线按上面的股票范围采集，指数单独采集；公告为最近7天全市场索引，行业为近一年申万成员历史。数据覆盖不代表全市场已完整建库。</p>
    {notice && <p role="status" className="source-note">{notice}</p>}
    {(error || status?.error) && <p role="alert" className="lake-error">{error || status?.error}</p>}
    <div className="lake-datasets">{status?.datasets.map(item => <article key={item.dataset}><strong>{item.label}</strong><span>{item.has_data ? item.coverage_start || item.coverage_end ? `${item.coverage_start ?? '—'} → ${item.coverage_end ?? '—'}` : '名录已保存' : '尚未采集'}</span><small>{item.history_mode === 'snapshot_only' ? '只积累实际采集快照' : item.history_mode === 'snapshot_with_backfill' ? '快照＋专用历史来源' : '历史可回补'}{item.pit_quality === 'reconstructed' ? ' · 历史时点重建' : ''}</small></article>)}</div>
    {latest && <details className="lake-job" open={active}><summary>最近任务：{labels[latest.status] ?? latest.status} · {latest.current_step} · {new Date(latest.created_at).toLocaleString('zh-CN')}</summary>{latest.error && <p className="lake-error">{latest.error}</p>}<ol>{latest.steps.map((step,index) => <li key={`${step.name}-${index}`}><span>{step.name}</span><b>{labels[step.status] ?? step.status}</b>{step.error && <small>{step.error}</small>}</li>)}</ol></details>}
    <details className="lake-location"><summary>保存位置与更新规则</summary><p>{status?.root ?? '读取中…'}</p><p>{status?.schedule}</p><p>原始价格与复权因子分别保存；财报读取保留时点质量标记。不会将备用接口的前复权价格写入原始行情库。</p></details>
  </section>
}
