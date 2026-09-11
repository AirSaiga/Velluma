/**
 * B3 · 用量可见单测：usageChart 纯几何函数 + usageApi 端点 URL（mock transport）。
 */
import { describe, expect, it, vi, beforeEach } from 'vitest'
import {
  buildTrendChart,
  formatCost,
  groupStagesByLane,
  shortDate,
  stageBarPercent,
  TREND_MAX_DAYS,
} from '../usageChart'
import type {
  DailyUsage,
  UsageStageEntry,
} from '../../../services/api/domain/usage.api'

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
    cost: 0,
    unpriced_tokens: 0,
  }
}

function _stage(
  stage: string,
  label: string,
  lane: string,
  laneLabel: string,
  tokens: number,
  calls = 1,
  cost = 0,
  unpricedTokens = 0,
): UsageStageEntry {
  return {
    stage,
    label,
    lane,
    lane_label: laneLabel,
    calls,
    prompt_tokens: tokens,
    completion_tokens: 0,
    thinking_tokens: 0,
    total_tokens: tokens,
    cost,
    unpriced_tokens: unpricedTokens,
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

describe('groupStagesByLane（链路分组 · 2026-09-10 真实调用流程对齐）', () => {
  const rows = [
    _stage('adaptive.dock_generator', '挂件生发', 'perceive', '写作中感知', 263400, 107),
    _stage('adaptive.future_projection', '未来推测（走向卡）', 'perceive', '写作中感知', 97000, 106),
    _stage('adaptive.stitch_ghost.stitch', '续写·缝合', 'ghost', '续写', 12500, 5),
    _stage('adaptive.event_scout.auto_read', '自动阅读·记事', 'auto_read', '系统自己去读', 187900, 14),
    _stage('loop3.emergent_facts', '涌现抽取（沉淀）', 'settle', '沉淀与完稿', 48800, 17),
  ]
  const byLane = [
    { lane: 'perceive', label: '写作中感知', calls: 213, total_tokens: 360400, share: 55.6, cost: 3.2, unpriced_tokens: 0 },
    { lane: 'ghost', label: '续写', calls: 5, total_tokens: 12500, share: 1.9, cost: 0.1, unpriced_tokens: 0 },
    { lane: 'settle', label: '沉淀与完稿', calls: 17, total_tokens: 48800, share: 7.5, cost: 0.4, unpriced_tokens: 0 },
    { lane: 'auto_read', label: '系统自己去读', calls: 14, total_tokens: 187900, share: 28.9, cost: 1.6, unpriced_tokens: 0 },
  ]

  it('组序跟随 by_lane 流程序（自动阅读量再大也居沉淀之后）', () => {
    const groups = groupStagesByLane(rows, byLane, 649000)
    expect(groups.map((g) => g.lane)).toEqual(['perceive', 'ghost', 'settle', 'auto_read'])
  })

  it('组头小计用 by_lane 权威值；组内行保持量降序、rowMax 组内归一', () => {
    const groups = groupStagesByLane(rows, byLane, 649000)
    const perceive = groups[0]
    expect(perceive.label).toBe('写作中感知')
    expect(perceive.totalTokens).toBe(360400)
    expect(perceive.share).toBe(55.6)
    expect(perceive.rows.map((r) => r.stage)).toEqual([
      'adaptive.dock_generator', 'adaptive.future_projection',
    ])
    expect(perceive.rowMax).toBe(263400)
    // 组内归一：第二行条形 ≈ 97k/263.4k = 37%
    expect(stageBarPercent(perceive.rows[1].total_tokens, perceive.rowMax)).toBe('37%')
  })

  it('by_lane 缺失（旧后端）→ 按行首现序兜底、share 由总账现算、lane_label 兜组名', () => {
    const groups = groupStagesByLane(rows, [], 649000)
    expect(groups.map((g) => g.lane)).toEqual(['perceive', 'ghost', 'auto_read', 'settle'])
    const perceive = groups[0]
    expect(perceive.label).toBe('写作中感知')
    expect(perceive.totalTokens).toBe(360400)
    expect(perceive.share).toBeCloseTo((360400 / 649000) * 100, 1)
  })

  it('未登记 stage 落 other 组、排后；空输入 → 空分组', () => {
    const mystery = _stage('mystery.stage', 'mystery.stage', 'other', '其他', 100)
    const groups = groupStagesByLane(
      [mystery, ...rows.slice(0, 1)],
      byLane.slice(0, 1),
      1000,
    )
    expect(groups[groups.length - 1].lane).toBe('other')
    expect(groups[groups.length - 1].label).toBe('其他')
    expect(groupStagesByLane([], [], 0)).toEqual([])
  })

  it('组头带成本与未计价 token（分组求和）', () => {
    const groups = groupStagesByLane(
      [
        _stage('adaptive.dock_generator', '挂件生发', 'perceive', '写作中感知', 100000, 10, 0.5),
        _stage('adaptive.future_projection', '未来推测', 'perceive', '写作中感知', 50000, 5, 0, 50000),
        _stage('adaptive.stitch_ghost.stitch', '续写·缝合', 'ghost', '续写', 20000, 1, 0.1),
      ],
      [],
      170000,
    )
    const perceive = groups[0]
    expect(perceive.cost).toBeCloseTo(0.5)
    expect(perceive.unpricedTokens).toBe(50000)
    expect(groups[1].cost).toBeCloseTo(0.1)
  })
})

describe('formatCost（成本金额 · 2026-09-11）', () => {
  it('0 → ¥0（区分「免费」与「未计价」——未计价由 unpriced_tokens 单独呈现）', () => {
    expect(formatCost(0)).toBe('¥0')
    expect(formatCost(undefined as unknown as number)).toBe('¥0')
  })
  it('≥1 元两位小数；≥0.01 三位；更小四位（写作用量常见毫厘级）', () => {
    expect(formatCost(3.1)).toBe('¥3.10')
    expect(formatCost(12.3456)).toBe('¥12.35')
    expect(formatCost(0.042)).toBe('¥0.042')
    expect(formatCost(0.00042)).toBe('¥0.0004')
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
