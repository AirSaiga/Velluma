/**
 * 时间轴布局纯函数（WorldTimeline 的数学部分，抽出来便于单测）。
 *
 * - fitWindowToContent：自动视野贴合内容时刻集（事件起止/章节锚/伏笔埋收），
 *   替代旧「从创世 0 年铺满」——稀疏史书不再有大半空白带。
 * - chooseTickStep / buildYearTicks：刻度年步长按轨道像素宽自适应（标签不挤），
 *   且标签年对齐步长整数倍（2160/2170，而非 2157/2167 的窗口缘年份）。
 * - assignRows：像素级重叠的标记（事件点/章节片）贪心分行，保证每个都可点。
 */
import { yearOf, fromYMD, breakdownTime } from './timeFormat'

export interface TimeWindow {
  start: number
  end: number
}

const DAYS_PER_YEAR = 365

/**
 * 自动视野：内容最早/最晚时刻 ± 边距（8% 或 30 天取大），内容跨度不足 2 年
 * 时以中点扩到 2 年（单事件书也有可读刻度）；起点不早于创世 0。
 * 空内容返回 null（调用方回落缺省窗口）。
 */
export function fitWindowToContent(
  times: number[],
  opts: { padRatio?: number; minPad?: number; minSpan?: number; floor?: number } = {},
): TimeWindow | null {
  const valid = times.filter((t) => Number.isFinite(t) && t >= 0)
  if (!valid.length) return null
  const padRatio = opts.padRatio ?? 0.08
  const minPad = opts.minPad ?? 30
  const minSpan = opts.minSpan ?? DAYS_PER_YEAR * 2
  const floor = opts.floor ?? 0
  let lo = Math.min(...valid)
  let hi = Math.max(...valid)
  const pad = Math.max((hi - lo) * padRatio, minPad)
  lo -= pad
  hi += pad
  if (hi - lo < minSpan) {
    const mid = (lo + hi) / 2
    lo = mid - minSpan / 2
    hi = mid + minSpan / 2
  }
  if (lo < floor) {
    hi += floor - lo // 保跨度整体右移
    lo = floor
  }
  return { start: Math.floor(lo), end: Math.ceil(hi) }
}

const TICK_STEPS = [1, 2, 5, 10, 20, 50, 100, 200, 500, 1000]

/** 通用步长选择：候选序列中「间距 ≥ minGapPx」的最小步长（全不满足取最大候选） */
function pickStep(steps: number[], spanUnits: number, widthPx: number, minGapPx: number): number {
  const w = Math.max(1, widthPx)
  const s = Math.max(1, spanUnits)
  for (const step of steps) {
    if ((step / s) * w >= minGapPx) return step
  }
  return steps[steps.length - 1]
}

/** 刻度年步长：标签间距 ≥ minGapPx 的最小候选步长 */
export function chooseTickStep(spanYears: number, widthPx: number, minGapPx = 72): number {
  return pickStep(TICK_STEPS, spanYears, widthPx, minGapPx)
}

/** 整年刻度（窗口内，年份对齐步长整数倍） */
export function buildYearTicks(
  viewStart: number,
  viewEnd: number,
  stepYears: number,
): { t: number; year: number }[] {
  const startY = yearOf(viewStart)
  const endY = yearOf(Math.max(viewStart, viewEnd - 1)) // 窗内最后一个占地整年
  const first = Math.ceil(startY / stepYears) * stepYears
  const out: { t: number; year: number }[] = []
  for (let y = Math.max(1, first); y <= endY; y += stepYears) {
    out.push({ t: fromYMD(y, 1, 1), year: y })
  }
  return out
}

// ===== 三档刻度（年/月/日）：视野缩到亚年粒度后，年标签失去区分度，自动降档 =====

export interface ScaleTick {
  t: number
  label: string
  /** major=年界/月界（视觉上加重），minor=日网格 */
  major: boolean
}

const MONTH_STEPS = [1, 2, 3, 6]
const DAY_STEPS = [1, 2, 5, 10, 15]

/**
 * 刻度总装：按窗口跨度自动降档——
 * >3 年 → 年档（对齐步长整数倍）；>62 天 → 月档（年界恒选为 major）；否则日档
 * （月初恒选为 major + 日网格 minor，贴近月界的日刻度让位防标签相撞）。
 */
export function buildScaleTicks(viewStart: number, viewEnd: number, widthPx: number): ScaleTick[] {
  const span = Math.max(1, viewEnd - viewStart)
  if (span > 365 * 3) {
    const step = chooseTickStep(yearOf(viewEnd - 1) - yearOf(viewStart) + 1, widthPx)
    return buildYearTicks(viewStart, viewEnd, step).map(({ t, year }) => ({
      t,
      label: `${year}`,
      major: true,
    }))
  }
  if (span > 62) {
    // 月档：枚举窗内全部月初，年界恒选，其余按步长疏化。
    // 13 月不出刻度——它只是年末 5 天残月，标签会和 5 天后的年份主刻度撞车
    // （实测「13」叠印「2174」），年界已承载定位；序号照占，步进节奏不变。
    const stepM = pickStep(MONTH_STEPS, span / 30, widthPx, 56)
    const out: ScaleTick[] = []
    const y0 = yearOf(viewStart)
    const y1 = yearOf(Math.max(viewStart, viewEnd - 1))
    let seq = 0
    for (let y = y0; y <= y1; y++) {
      for (let m = 1; m <= 13; m++) {
        const t = fromYMD(y, m, 1)
        if (t >= viewEnd) continue
        if (t < viewStart) {
          seq++ // 窗外月份仍占序号，保持步进节奏不随窗口起点漂移
          continue
        }
        const isYearEdge = m === 1
        if (!isYearEdge && m === 13) {
          seq++ // 13 月（年末 5 天残月）不出刻度——标签会与 5 天后的年界主刻度撞车
          continue
        }
        if (isYearEdge || seq % stepM === 0) {
          out.push({ t, label: isYearEdge ? `${y}` : `${m}月`, major: isYearEdge })
        }
        seq++
      }
    }
    return out
  }
  // 日档：月初 major + 绝对日网格 minor（与月界相距不足半步的日刻度让位）
  const stepD = pickStep(DAY_STEPS, span, widthPx, 44)
  const monthStarts: ScaleTick[] = []
  const y0 = yearOf(viewStart)
  const y1 = yearOf(Math.max(viewStart, viewEnd - 1))
  for (let y = y0; y <= y1; y++) {
    for (let m = 1; m <= 13; m++) {
      const t = fromYMD(y, m, 1)
      if (t >= viewStart && t < viewEnd) {
        monthStarts.push({ t, label: m === 1 ? `${y}年1月` : `${m}月`, major: true })
      }
    }
  }
  const out: ScaleTick[] = [...monthStarts]
  for (let d = Math.ceil(viewStart); d < viewEnd; d++) {
    if (d % stepD !== 0) continue
    if (monthStarts.some((ms) => Math.abs(ms.t - d) < stepD / 2)) continue
    out.push({ t: d, label: `${breakdownTime(d).day}日`, major: false })
  }
  return out.sort((a, b) => a.t - b.t)
}

/**
 * 视野窗口的头部文案（自适应粒度）：
 * ≥1 年 → 「第 X–Y 年」；同年跨月 →「2157年3月–7月」；同月 →「2157年3月1–15日」；
 * 跨年亚年 →「2156年12月–2157年2月」。viewEnd 为排他边界（显示端 = viewEnd-1 天）。
 */
export function formatWindowLabel(viewStart: number, viewEnd: number): string {
  const endDay = Math.max(viewStart, viewEnd - 1)
  if (viewEnd - viewStart >= 365) return `第 ${yearOf(viewStart)}–${yearOf(endDay)} 年`
  const a = breakdownTime(viewStart)
  const b = breakdownTime(endDay)
  if (a.year === b.year) {
    if (a.month === b.month) return `${a.year}年${a.month}月${a.day}–${b.day}日`
    return `${a.year}年${a.month}月–${b.month}月`
  }
  return `${a.year}年${a.month}月–${b.year}年${b.month}月`
}

/**
 * 重叠标记分行（区间划分贪心）：按横向位置排序后逐枚放入「容得下它的第一行」
 * （与该行上一枚的中心距 ≥ 两枚半宽和 + 4px 余量），都放不下就压在最末行
 * （接受偶发重叠，保证单调与确定性）。返回与输入等长、按下标对齐的行号。
 * widths 为逐枚像素宽（点=8，章节片按标签长度估算）。
 */
export function assignRows(pxPositions: number[], widths: number | number[], maxRows = 3): number[] {
  const widthAt = (i: number) => (Array.isArray(widths) ? widths[i] : widths)
  const order = pxPositions.map((x, i) => ({ x, i })).sort((a, b) => a.x - b.x)
  const lastIdx: (number | undefined)[] = []
  const rows = new Array<number>(pxPositions.length).fill(0)
  for (const { x, i } of order) {
    let row = maxRows - 1
    for (let r = 0; r < maxRows; r++) {
      const li = lastIdx[r]
      if (li === undefined || x - pxPositions[li] >= (widthAt(li) + widthAt(i)) / 2 + 4) {
        row = r
        break
      }
    }
    rows[i] = row
    lastIdx[row] = i
  }
  return rows
}
