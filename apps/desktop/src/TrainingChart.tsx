import { useEffect, useRef, useState } from 'react'
import type { TrainingBar, TrainingSession } from './trainingApi'

export function TrainingChart({session}: {session: TrainingSession}) {
  const [period, setPeriod] = useState<'day' | 'week'>('day')
  const [showMA, setShowMA] = useState(true)
  const scroll = useRef<HTMLDivElement>(null)
  useEffect(() => {
    const element = scroll.current
    if (!element) return
    const followLatest = () => { element.scrollLeft = element.scrollWidth }
    followLatest()
    const observer = new ResizeObserver(followLatest)
    observer.observe(element)
    return () => observer.disconnect()
  }, [session.step, period])
  const [selected, setSelected] = useState<number | null>(null)
  let bars = session.bars
  if (period === 'week') {
    const weeks: TrainingBar[] = []
    for (const bar of bars) {
      const last = weeks.at(-1)
      if (last?.week === bar.week) {
        last.high = Math.max(last.high, bar.high); last.low = Math.min(last.low, bar.low)
        last.close = bar.close; last.volume += bar.volume; last.index = bar.index
      } else weeks.push({...bar, label: `第 ${bar.week + 1} 周`})
    }
    bars = weeks
  }
  const focus = bars[selected ?? bars.length - 1] ?? bars[bars.length - 1]
  const width = 900, left = 14, right = 66, top = 25, floor = 285, volumeFloor = 360
  const low = Math.min(...bars.map(bar => bar.low)), high = Math.max(...bars.map(bar => bar.high))
  const padding = (high - low) * .12 || high * .02
  const min = low - padding, max = high + padding
  const y = (price: number) => floor - (price - min) / (max - min) * (floor - top)
  const gap = (width - left - right) / bars.length
  const x = (index: number) => left + gap * (index + .5)
  const candleWidth = Math.max(2, Math.min(12, gap * .65))
  const maxVolume = Math.max(1, ...bars.map(bar => bar.volume))
  const series = (window: number) => bars.map((_, index) => index + 1 < window ? null : `${x(index)},${y(bars.slice(index + 1 - window, index + 1).reduce((sum, bar) => sum + bar.close, 0) / window)}`).filter(Boolean).join(' ')
  const warmupIndex = bars.findIndex(bar => bar.index >= session.warmup)
  const marker = (bar: TrainingBar) => session.actions.filter(action => action.status === 'filled' && (period === 'day' ? action.index === bar.index : session.bars[action.index]?.week === bar.week))
  return <section className="dojo-chart-card">
    <div className="dojo-chart-head"><div><span className="dojo-kicker">PRICE ACTION</span><h2>{session.reveal ? `${session.reveal.stock_name} · ${session.reveal.stock_code}` : '匿名标的 · 看走势，做判断'}</h2></div><div className="dojo-toggles" aria-label="K线显示设置"><button aria-pressed={period === 'day'} onClick={() => {setPeriod('day'); setSelected(null)}}>日线</button><button aria-pressed={period === 'week'} onClick={() => {setPeriod('week'); setSelected(null)}}>周线</button><button aria-pressed={showMA} onClick={() => setShowMA(!showMA)}>均线</button></div></div>
    <div className="dojo-ohlc"><strong>{focus.label}</strong><span>开 {focus.open.toFixed(2)}</span><span>高 {focus.high.toFixed(2)}</span><span>低 {focus.low.toFixed(2)}</span><span>收 {focus.close.toFixed(2)}</span></div>
    <div className="dojo-chart-scroll" ref={scroll}><svg className="dojo-candles" viewBox="0 0 900 395" role="img" aria-label={`${period === 'day' ? '日' : '周'}K线，已展示 ${bars.length} 根；红色空心上涨，绿色实心下跌；下方为成交量`} onPointerMove={event => {const rect = event.currentTarget.getBoundingClientRect(); setSelected(Math.max(0, Math.min(bars.length - 1, Math.floor(((event.clientX - rect.left) / rect.width * width - left) / gap))))}} onPointerLeave={() => setSelected(null)}>
      <title>已揭示行情及交易标记</title>
      {[0, 1, 2, 3, 4].map(tick => {const price = min + (max - min) * tick / 4; return <g key={tick}><line className="dojo-grid-line" x1={left} x2={width - right} y1={y(price)} y2={y(price)} /><text className="dojo-axis" x={width - right + 10} y={y(price) + 4}>{price.toFixed(2)}</text></g>})}
      {warmupIndex >= 0 && <><rect x={x(warmupIndex) - gap / 2} y={top} width={width - right - x(warmupIndex) + gap / 2} height={volumeFloor - top} className="dojo-training-zone"/><line className="dojo-divider" x1={x(warmupIndex) - gap / 2} x2={x(warmupIndex) - gap / 2} y1={top} y2={volumeFloor}/></>}
      {bars.map((bar, index) => <g key={bar.index} className={bar.close >= bar.open ? 'dojo-rise' : 'dojo-fall'}><line x1={x(index)} x2={x(index)} y1={y(bar.high)} y2={y(bar.low)} /><rect x={x(index) - candleWidth / 2} y={y(Math.max(bar.open, bar.close))} width={candleWidth} height={Math.max(1, Math.abs(y(bar.open) - y(bar.close)))} /><rect className="dojo-volume" x={x(index) - candleWidth / 2} y={volumeFloor - bar.volume / maxVolume * 44} width={candleWidth} height={Math.max(.5, bar.volume / maxVolume * 44)} />{marker(bar).map((action, offset) => <text key={action.step} className={`dojo-trade-label ${action.action}`} x={x(index)} y={y(bar.high) - 8 - offset * 13} textAnchor="middle">{action.action === 'buy' ? 'B' : 'S'}</text>)}</g>)}
      {showMA && [5, 10, 20].map(window => <polyline key={window} className={`dojo-ma dojo-ma${window}`} points={series(window)}/>)}
      {selected !== null && <line className="dojo-crosshair" x1={x(Math.min(selected, bars.length - 1))} x2={x(Math.min(selected, bars.length - 1))} y1={top} y2={volumeFloor}/>}
      <text className="dojo-axis" x={left} y={310}>成交量 · 相对规模</text>
      {[0, Math.floor(bars.length / 2), bars.length - 1].map((index, n) => <text key={n} className="dojo-axis" x={x(index)} y={385} textAnchor={n === 0 ? 'start' : n === 2 ? 'end' : 'middle'}>{bars[index].label}</text>)}
    </svg></div>
    <div className="dojo-chart-legend"><span className="dojo-up">□ 上涨</span><span className="dojo-down">■ 下跌</span>{showMA && <><span className="ma5">MA5</span><span className="ma10">MA10</span><span className="ma20">MA20</span></>}<span>B 买入 / S 卖出</span><span>{period === 'week' ? '周线仅聚合已揭示日线，最后一周可能未完整' : '浅色区域为本局推演 · 价格单位：元（前复权）'}</span></div>
    <label className="dojo-chart-access">查看每根 K 线<select aria-label="查看K线数据" value={selected ?? bars.length - 1} onChange={event => setSelected(Number(event.target.value))}>{bars.map((bar, index) => <option key={bar.index} value={index}>{bar.label} · 收盘 {bar.close.toFixed(2)}</option>)}</select></label>
  </section>
}

export function EquityChart({session}: {session: TrainingSession}) {
  const points = session.equity_curve
  const values = points.flatMap(point => [point.equity, point.benchmark])
  const min = Math.min(...values) * .995, max = Math.max(...values) * 1.005
  const line = (key: 'equity' | 'benchmark') => points.map((point, index) => `${12 + index / Math.max(1, points.length - 1) * 656},${135 - (point[key] - min) / (max - min) * 110}`).join(' ')
  return <section className="dojo-equity"><div className="dojo-section-title"><h2>资金曲线</h2><span>实线 我的权益 · 虚线 买入持有</span></div><svg viewBox="0 0 680 155" role="img" aria-label={`我的权益 ${session.metrics.equity.toFixed(2)} 元，同期买入持有收益 ${session.metrics.benchmark_pct}%`}><line className="dojo-grid-line" x1="12" x2="668" y1="135" y2="135"/><polyline className="dojo-benchmark" points={line('benchmark')}/><polyline className="dojo-equity-line" points={line('equity')}/></svg><div className="dojo-equity-range"><span>起始 ¥100,000</span><span>第 {session.step} 个交易日 · 每日收盘权益</span></div></section>
}
