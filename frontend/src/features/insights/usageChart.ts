/**
 * B3 · 用量卡图表几何（P5 地基加固期批次 1）。
 *
 * 纯函数：把后端 by_date / by_stage 聚合结果换算成 SVG 条形几何与归一宽度。
 * 不依赖 Vue 运行时，单测直接打这里（__tests__/usage.test.ts）。
 */
import type { DailyUsage } from '../../services/api/domain/usage.api'

/** 趋势图最多展示的天数（老书长尾截断，取最近 N 天） */
export const TREND_MAX_DAYS = 30

export interface TrendBar {
  x: number
  y: number
  w: number
  h: number
  date: string
  label: string
  calls: number
  totalTokens: number
}

export interface TrendChart {
  bars: TrendBar[]
  width: number
  height: number
  /** 展示窗口内的日峰值（bar 高度归一基准；0 = 全空） */
  maxTotal: number
  firstLabel: string
  lastLabel: string
}

/** '2026-08-19' → '8/19'（非该格式原样返回） */
export function shortDate(iso: string): string {
  const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(iso)
  if (!m) return iso
  return `${Number(m[2])}/${Number(m[3])}`
}

/** 按日数据 → SVG 条形几何（基线 y = height - pad；超 maxDays 取最近 N 天） */
export function buildTrendChart(
  byDate: DailyUsage[],
  opts: { width?: number; height?: number; pad?: number; maxDays?: number } = {},
): TrendChart {
  const width = opts.width ?? 320
  const height = opts.height ?? 96
  const pad = opts.pad ?? 14
  const maxDays = opts.maxDays ?? TREND_MAX_DAYS

  const days = byDate.slice(-maxDays)
  const n = days.length
  const maxTotal = days.reduce((m, d) => Math.max(m, d.total_tokens || 0), 0)
  const innerH = height - pad * 2
  const step = n > 0 ? width / n : 0
  const barW = n > 0 ? Math.max(2, step * 0.6) : 0

  const bars: TrendBar[] = days.map((d, i) => {
    const total = d.total_tokens || 0
    // 非零日至少 2px 高（可见）；峰值日内按比例
    const h = maxTotal > 0 ? Math.max(total > 0 ? 2 : 0, (total / maxTotal) * innerH) : 0
    return {
      x: i * step + (step - barW) / 2,
      y: height - pad - h,
      w: barW,
      h,
      date: d.date,
      label: shortDate(d.date),
      calls: d.calls || 0,
      totalTokens: total,
    }
  })

  return {
    bars,
    width,
    height,
    maxTotal,
    firstLabel: bars.length ? bars[0].label : '',
    lastLabel: bars.length ? bars[bars.length - 1].label : '',
  }
}

/** 组件条形宽度百分比（对 by_stage 最大 total_tokens 归一，封顶 100%） */
export function stageBarPercent(total: number, max: number): string {
  if (max <= 0 || total <= 0) return '0%'
  return `${Math.min(100, Math.round((total / max) * 100))}%`
}
