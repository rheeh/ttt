import { useEffect, useState } from 'react'
import { LoaderCircle } from 'lucide-react'

export function RequestProgress({label = '正在读取行情和研究数据', onCancel}: {label?:string; onCancel?:()=>void}) {
  const [seconds,setSeconds] = useState(0)
  useEffect(() => {const started = Date.now(); const timer = window.setInterval(() => setSeconds(Math.floor((Date.now() - started) / 1000)),1000); return () => clearInterval(timer)},[])
  return <div className="request-progress" role="status"><LoaderCircle className="spin" size={21}/><div><strong>{label} <span>已等待 {seconds} 秒</span></strong><p>{seconds < 10 ? '请求完成后会显示结果，可以先切换到其他模块。' : '部分外部数据源响应较慢，现有结果仍可查看。'}</p></div>{onCancel && <button type="button" onClick={onCancel}>停止等待</button>}</div>
}
