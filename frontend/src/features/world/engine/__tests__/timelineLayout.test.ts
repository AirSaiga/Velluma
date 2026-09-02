import { describe, expect, it } from 'vitest'
import {
  fitWindowToContent,
  chooseTickStep,
  buildYearTicks,
  buildScaleTicks,
  formatWindowLabel,
  assignRows,
} from '../timelineLayout'
import { fromYMD } from '../timeFormat'

describe('fitWindowToContent', () => {
  it('空内容返回 null（调用方回落缺省窗口）', () => {
    expect(fitWindowToContent([])).toBeNull()
    expect(fitWindowToContent([NaN, -5])).toBeNull()
  })

  it('内容两侧留边距（8% 与 30 天取大）', () => {
    // 第 100 年元旦 到 第 110 年元旦：跨度 3650 天，pad = 292
    const w = fitWindowToContent([fromYMD(100, 1, 1), fromYMD(110, 1, 1)])!
    expect(w.end - w.start).toBe(3650 + 292 * 2)
    expect(w.start).toBe(fromYMD(100, 1, 1) - 292)
    expect(w.end).toBe(fromYMD(110, 1, 1) + 292)
  })

  it('单点内容扩到最小跨度 2 年（以中点居中）', () => {
    const t = fromYMD(100, 7, 15)
    const w = fitWindowToContent([t])!
    expect(w.end - w.start).toBe(365 * 2)
    expect(w.start).toBeLessThan(t)
    expect(w.end).toBeGreaterThan(t)
  })

  it('起点不早于创世 0（触底保跨度右移）', () => {
    const w = fitWindowToContent([fromYMD(1, 6, 1)])!
    expect(w.start).toBe(0)
    expect(w.end - w.start).toBe(365 * 2)
  })
})

describe('chooseTickStep', () => {
  it('窄轨道选大步长，宽轨道选小步长', () => {
    // 24 年跨度 / 300px：1 年=12.5px、2 年=25px、5 年=62.5px、10 年=125px ≥72 → 10
    expect(chooseTickStep(24, 300)).toBe(10)
    // 24 年跨度 / 2000px：1 年=83px ≥72 → 1
    expect(chooseTickStep(24, 2000)).toBe(1)
  })

  it('超宽跨度兜底最大步长；退化入参不炸', () => {
    expect(chooseTickStep(100000, 800)).toBe(1000)
    expect(chooseTickStep(0, 800)).toBe(1)
    expect(chooseTickStep(24, 0)).toBe(1000)
  })
})

describe('buildYearTicks', () => {
  it('标签年对齐步长整数倍（2160/2170，而非窗口缘的 2157）', () => {
    const ticks = buildYearTicks(fromYMD(2157, 3, 1), fromYMD(2181, 1, 1), 10)
    expect(ticks.map((t) => t.year)).toEqual([2160, 2170, 2180])
    expect(ticks[0].t).toBe(fromYMD(2160, 1, 1))
  })

  it('起点恰对齐时含起点年；空窗（end<=start）只产起点年刻度', () => {
    const ticks = buildYearTicks(fromYMD(100, 1, 1), fromYMD(110, 1, 1), 5)
    expect(ticks.map((t) => t.year)).toEqual([100, 105])
    // 单年窗口（end = 次年元旦）
    const one = buildYearTicks(fromYMD(100, 6, 1), fromYMD(101, 1, 1), 1)
    expect(one.map((t) => t.year)).toEqual([100])
  })
})

describe('buildScaleTicks（年/月/日三档）', () => {
  it('>3 年窗走年档（对齐整数倍、全 major）', () => {
    const ticks = buildScaleTicks(fromYMD(2157, 3, 1), fromYMD(2181, 1, 1), 1000)
    expect(ticks[0]).toEqual({ t: fromYMD(2158, 1, 1), label: '2158', major: true })
    expect(ticks.length).toBe(12) // 2158..2180 步长 2
    expect(ticks.every((t) => t.major)).toBe(true)
  })

  it('1 年窗走月档：年界出年份标签（major），其余出「N月」', () => {
    const ticks = buildScaleTicks(fromYMD(2157, 1, 1), fromYMD(2158, 1, 1), 1180)
    expect(ticks.length).toBe(12) // 12 个月初全选（步长 1）；13 月=年末 5 天残月不出刻度
    expect(ticks[0]).toEqual({ t: fromYMD(2157, 1, 1), label: '2157', major: true })
    expect(ticks[1]).toEqual({ t: fromYMD(2157, 2, 1), label: '2月', major: false })
    expect(ticks[11].label).toBe('12月')
    expect(ticks.map((t) => t.label)).not.toContain('13月')
  })

  it('月档跨年时 13 月不与年界主刻度撞车（用户实测「13」叠印「2174」）', () => {
    const ticks = buildScaleTicks(fromYMD(2173, 8, 1), fromYMD(2176, 1, 1), 1180)
    const labels = ticks.map((t) => t.label)
    expect(labels).toContain('2174')
    expect(labels).toContain('2175')
    expect(labels).not.toContain('13月')
    // 每个年界主刻度与前一个标签刻度至少隔 25 天（12 月界距年界 30 天）——不再可能叠印
    for (const [i, tk] of ticks.entries()) {
      if (!tk.major || i === 0) continue
      expect(tk.t - ticks[i - 1].t).toBeGreaterThanOrEqual(25)
    }
  })

  it('窄月档窗按像素疏化月标签但年界恒选', () => {
    // 两年窗 / 300px：月步长疏化到 3，1 月仍恒选
    const ticks = buildScaleTicks(fromYMD(100, 6, 1), fromYMD(102, 6, 1), 300)
    const labels = ticks.map((t) => t.label)
    expect(labels).toContain('101') // 第 101 年 1 月（年界）
    expect(labels).toContain('102')
    expect(ticks.filter((t) => t.major).map((t) => t.label)).toEqual(['101', '102'])
  })

  it('10 天窗走日档：月初 major + 日网格 minor，月界处日刻度让位', () => {
    const ticks = buildScaleTicks(fromYMD(2157, 3, 1), fromYMD(2157, 3, 1) + 10, 1180)
    expect(ticks[0]).toEqual({ t: fromYMD(2157, 3, 1), label: '3月', major: true })
    const minors = ticks.filter((t) => !t.major).map((t) => t.label)
    expect(minors).toEqual(['2日', '3日', '4日', '5日', '6日', '7日', '8日', '9日', '10日'])
  })
})

describe('formatWindowLabel', () => {
  it('≥1 年窗出「第 X–Y 年」（end 为排他边界）', () => {
    expect(formatWindowLabel(fromYMD(2157, 1, 1), fromYMD(2181, 1, 1))).toBe('第 2157–2180 年')
    expect(formatWindowLabel(fromYMD(2157, 3, 1), fromYMD(2158, 3, 1))).toBe('第 2157–2158 年')
  })

  it('亚年同年跨月出「2157年3月–7月」', () => {
    expect(formatWindowLabel(fromYMD(2157, 3, 1), fromYMD(2157, 7, 25))).toBe('2157年3月–7月')
  })

  it('同月出「2157年3月1–15日」', () => {
    expect(formatWindowLabel(fromYMD(2157, 3, 1), fromYMD(2157, 3, 16))).toBe('2157年3月1–15日')
  })

  it('跨年亚年出双端年月', () => {
    expect(formatWindowLabel(fromYMD(2156, 12, 1), fromYMD(2157, 2, 10))).toBe('2156年12月–2157年2月')
  })
})

describe('assignRows', () => {
  it('互不重叠全在第 0 行', () => {
    expect(assignRows([10, 100, 200], 8)).toEqual([0, 0, 0])
  })

  it('重叠链分到 0/1/2 行，返回按下标对齐（非排序序）', () => {
    // 输入乱序：x=30(下标0) x=10(下标1) x=20(下标2)，宽 20 → 中心距需 ≥24
    expect(assignRows([30, 10, 20], 20)).toEqual([2, 0, 1])
  })

  it('超过行数上限压在最末行（不炸、单调）', () => {
    const rows = assignRows([0, 1, 2, 3, 4], 8, 3)
    expect(rows).toEqual([0, 1, 2, 2, 2])
  })

  it('逐枚宽度数组（章节片）：宽片挤开邻位', () => {
    // 两枚中心距 20：宽 8 时 (8+8)/2+4=12 ≤20 同行；宽 30 时 (30+30)/2+4=34 >20 分行
    expect(assignRows([0, 20], 8)).toEqual([0, 0])
    expect(assignRows([0, 20], [30, 30])).toEqual([0, 1])
  })
})
