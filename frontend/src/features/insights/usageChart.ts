/**
 * B3 · 用量卡图表几何（P5 地基加固期批次 1）。
 *
 * 纯函数：把后端 by_date / by_stage 聚合结果换算成 SVG 条形几何与归一宽度。
 * 不依赖 Vue 运行时，单测直接打这里（__tests__/usage.test.ts）。
 */
import type {
  DailyUsage,
  UsageLaneEntry,
  UsageStageEntry,
} from '../../services/api/domain/usage.api'

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

// ============================================================
// 链路（lane）分组：AI 消耗卡按真实调用流程分组呈现（2026-09-10）
// ============================================================

/** 一个链路分组：组头小计 + 组内 stage 行（组内条形归一，组头承载数量级） */
export interface LaneGroup {
  lane: string
  label: string
  calls: number
  totalTokens: number
  /** 占总账百分比（0-100，一位小数） */
  share: number
  /** 组内已计价成本（元） */
  cost: number
  /** 组内未计价 token 量（模型未配价） */
  unpricedTokens: number
  rows: UsageStageEntry[]
  /** 组内条形归一基准（组内最大 total_tokens；0 = 全空组） */
  rowMax: number
}

/**
 * by_stage → 链路分组列表。
 *
 * - 组序/组名/占比优先采用后端 by_lane（流程序：感知→续写→沉淀完稿→自动阅读），
 *   后端未带 by_lane（旧版本）时按行首现序兜底、占比由 grandTotal 现算。
 * - 组内行保持后端 by_stage 的量降序；条形按组内峰值归一（全局归一会让
 *   非头部行全部缩成看不见的细条——数量级由组头小计承载）。
 */
export function groupStagesByLane(
  byStage: UsageStageEntry[],
  byLane: UsageLaneEntry[] = [],
  grandTotal = 0,
): LaneGroup[] {
  const rowsByLane = new Map<string, UsageStageEntry[]>()
  for (const s of byStage) {
    const key = s.lane || 'other'
    const rows = rowsByLane.get(key)
    if (rows) rows.push(s)
    else rowsByLane.set(key, [s])
  }
  const laneMeta = new Map<string, UsageLaneEntry>()
  for (const l of byLane) laneMeta.set(l.lane, l)

  // 后端流程序为准；行里出现而 byLane 没有的 lane（未登记 stage 的 other 组）
  // 按首现序排在后面
  const order: string[] = byLane.map((l) => l.lane)
  for (const key of rowsByLane.keys()) {
    if (!order.includes(key)) order.push(key)
  }

  const groups: LaneGroup[] = []
  for (const lane of order) {
    const rows = rowsByLane.get(lane)
    if (!rows || rows.length === 0) continue
    const meta = laneMeta.get(lane)
    const totalTokens = rows.reduce((sum, r) => sum + (r.total_tokens || 0), 0)
    const calls = rows.reduce((sum, r) => sum + (r.calls || 0), 0)
    const cost = rows.reduce((sum, r) => sum + (r.cost || 0), 0)
    const unpricedTokens = rows.reduce((sum, r) => sum + (r.unpriced_tokens || 0), 0)
    groups.push({
      lane,
      label: meta?.label || rows[0]?.lane_label || lane,
      calls,
      totalTokens,
      share: meta ? meta.share : grandTotal > 0 ? Math.round((totalTokens * 1000) / grandTotal) / 10 : 0,
      cost,
      unpricedTokens,
      rows,
      rowMax: rows.reduce((m, r) => Math.max(m, r.total_tokens || 0), 0),
    })
  }
  return groups
}

/**
 * 成本金额格式化（元）：
 * ≥ 1 元 → 两位小数；≥ 0.01 → 三位；更小 → 四位（写作用量常见毫厘级）。
 * 0 → '¥0'（区分「免费」与「未计价」——未计价由 unpriced_tokens 单独呈现）。
 */
export function formatCost(cost: number): string {
  const c = cost || 0
  if (c === 0) return '¥0'
  if (c >= 1) return `¥${c.toFixed(2)}`
  if (c >= 0.01) return `¥${c.toFixed(3)}`
  return `¥${c.toFixed(4)}`
}
