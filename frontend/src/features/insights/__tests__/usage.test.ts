/**
 * B3 · 用量可见单测：usageChart 纯几何函数 + usageApi 端点 URL（mock transport）。
 */
import { describe, expect, it, vi, beforeEach } from 'vitest'
import { buildTrendChart, shortDate, stageBarPercent, TREND_MAX_DAYS } from '../usageChart'
import type { DailyUsage } from '../../../services/api/domain/usage.api'

vi.mock('../../../services/api/transport', () => ({
  requestJson: vi.fn().mockResolvedValue({}),
}))

import { requestJson } from '../../../services/api/transport'
import { usageApi } from '../../../services/api/domain/usage.api'

function _day(date: string, tokens: number, calls = 1): DailyUsage {
  return {
    date,
    calls,
    prompt_tokens: tokens,
    completion_tokens: 0,
    thinking_tokens: 0,
    total_tokens: tokens,
  }
}

describe('shortDate', () => {
  it('ISO 日期 → M/D', () => {
    expect(shortDate('2026-08-19')).toBe('8/19')
    expect(shortDate('2026-11-03')).toBe('11/3')
  })
  it('非 ISO 格式原样返回', () => {
    expect(shortDate('n/a')).toBe('n/a')
  })
})

describe('buildTrendChart', () => {
  it('空数据 → 无 bar、零峰值、空标签', () => {
    const chart = buildTrendChart([])
    expect(chart.bars).toEqual([])
    expect(chart.maxTotal).toBe(0)
    expect(chart.firstLabel).toBe('')
    expect(chart.lastLabel).toBe('')
  })

  it('峰值日满高、其余按比例；零 token 日高度 0', () => {
    const chart = buildTrendChart([
      _day('2026-08-18', 1000),
      _day('2026-08-19', 0, 0),
      _day('2026-08-20', 500),
    ])
    expect(chart.maxTotal).toBe(1000)
    expect(chart.bars).toHaveLength(3)
    // 峰值日：h = innerH = height - pad*2 = 96 - 28 = 68
    expect(chart.bars[0].h).toBeCloseTo(68)
    expect(chart.bars[0].y).toBeCloseTo(96 - 14 - 68)
    // 零日
    expect(chart.bars[1].h).toBe(0)
    // 半量日
    expect(chart.bars[2].h).toBeCloseTo(34)
    expect(chart.firstLabel).toBe('8/18')
    expect(chart.lastLabel).toBe('8/20')
  })

  it('超 maxDays 截最近 N 天', () => {
    const days: DailyUsage[] = Array.from({ length: TREND_MAX_DAYS + 10 }, (_, i) =>
      _day(`2026-09-${String((i % 28) + 1).padStart(2, '0')}`, i + 1),
    )
    const chart = buildTrendChart(days)
    expect(chart.bars).toHaveLength(TREND_MAX_DAYS)
    // 峰值应来自保留窗口的最后一天（值最大），而非被丢弃的前 10 天
    expect(chart.maxTotal).toBe(days[days.length - 1].total_tokens)
  })

  it('bar 底边落在基线上（y + h = height - pad）', () => {
    const chart = buildTrendChart([_day('2026-08-01', 300), _day('2026-08-02', 900)])
    for (const b of chart.bars) {
      expect(b.y + b.h).toBeCloseTo(chart.height - 14)
      expect(b.w).toBeGreaterThan(0)
    }
  })
})

describe('stageBarPercent', () => {
  it('max=0 或 total=0 → 0%', () => {
    expect(stageBarPercent(100, 0)).toBe('0%')
    expect(stageBarPercent(0, 100)).toBe('0%')
  })
  it('按比例取整', () => {
    expect(stageBarPercent(500, 1000)).toBe('50%')
    expect(stageBarPercent(1000, 1000)).toBe('100%')
  })
  it('超峰值封顶 100%（防御脏数据）', () => {
    expect(stageBarPercent(2000, 1000)).toBe('100%')
  })
})

describe('usageApi', () => {
  beforeEach(() => {
    vi.mocked(requestJson).mockClear()
  })

  it('章端点打到 /chapters/{id}/adaptive/usage（GET 缺省）', async () => {
    await usageApi.getChapterUsage('ch-42')
    expect(requestJson).toHaveBeenCalledWith('/chapters/ch-42/adaptive/usage')
  })

  it('书端点打到 /books/{id}/adaptive/usage', async () => {
    await usageApi.getBookUsage('bk-7')
    expect(requestJson).toHaveBeenCalledWith('/books/bk-7/adaptive/usage')
  })
})
