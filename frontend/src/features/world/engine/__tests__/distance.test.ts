/**
 * D4 空间换算前端单测——与后端 test_spatial.py 对拍（同构契约）。
 */
import { describe, expect, it } from 'vitest'
import {
  pxPerDay, distanceDays, formatDistance, formatDistanceWithScale, encounterBand,
  blankAtlasSuggestedDays,
} from '../distance'
import type { MapScale } from '../distance'

const SCALE: MapScale = {
  refs: [{ ax: 0, ay: 0, bx: 100, by: 0, days_foot: 1.0, label: '骑马一天' }],
  detour_factor: 1.2,
  modes: { walk: 1.0, horse: 2.5 },
}

describe('D4 空间换算', () => {
  it('未标定静默降级', () => {
    expect(pxPerDay(null)).toBeNull()
    expect(pxPerDay({})).toBeNull()
    expect(distanceDays([0, 0], [100, 0], null)).toBeNull()
    expect(formatDistanceWithScale([0, 0], [100, 0], null)).toBe('')
    expect(encounterBand(null)).toBeNull()
  })

  it('标定算术与后端对拍', () => {
    expect(pxPerDay(SCALE)!).toBeCloseTo(100.0, 9)
    expect(distanceDays([0, 0], [200, 0], SCALE)!).toBeCloseTo(2.4, 9)
    expect(formatDistanceWithScale([0, 0], [100, 0], SCALE)).toBe('约 1.2 天步程')
  })

  it('作者的话', () => {
    expect(formatDistance(0.1)).toBe('近在咫尺')
    expect(formatDistance(0.6)).toBe('约半日步程')
    expect(formatDistance(2.0)).toBe('约 2 天步程')
    expect(formatDistance(25.0)).toBe('约 25 天步程')
    expect(formatDistance(3.0, 'horse', SCALE)).toBe('约 1.2 天行程')
  })

  it('多参考线均值', () => {
    const s: MapScale = { refs: [
      { ax: 0, ay: 0, bx: 100, by: 0, days_foot: 1.0 },
      { ax: 0, ay: 0, bx: 100, by: 0, days_foot: 2.0 },
    ] }
    expect(pxPerDay(s)!).toBeCloseTo(75.0, 9)
  })

  it('相遇分档', () => {
    expect(encounterBand(0.01)).toBeNull()
    expect(encounterBand(0.3)).toBe('半日内可达')
    expect(encounterBand(2.0)).toBe('1-3 天路程')
    expect(encounterBand(9.0)).toBe('更远')
  })

  it('空白舆图地球尺度预填（§2.2，与后端 blank_atlas_suggested_scale 同构）', () => {
    // 图宽 900 内部单位 = 赤道一圈 ≈ 1335.8 步行日
    expect(blankAtlasSuggestedDays(900)).toBeCloseTo(40075 / 30, 6)
    expect(blankAtlasSuggestedDays(90)).toBeCloseTo((40075 / 30) / 10, 6)   // 十分之一图宽
    expect(blankAtlasSuggestedDays(0)).toBe(0)
    expect(blankAtlasSuggestedDays(100, 0)).toBe(0)
  })
})
