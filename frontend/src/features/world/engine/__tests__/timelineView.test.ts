import { describe, expect, it } from 'vitest'
import { normalizeTimelineCursor, normalizeTimelineRange } from '../timelineView'

describe('normalizeTimelineCursor', () => {
  it('接受非负有限数并取整', () => {
    expect(normalizeTimelineCursor(0)).toBe(0)
    expect(normalizeTimelineCursor(500)).toBe(500)
    expect(normalizeTimelineCursor(500.9)).toBe(500)
  })

  it('拒绝负数/非数/NaN/Infinity', () => {
    expect(normalizeTimelineCursor(-1)).toBeNull()
    expect(normalizeTimelineCursor('500')).toBeNull()
    expect(normalizeTimelineCursor(NaN)).toBeNull()
    expect(normalizeTimelineCursor(Infinity)).toBeNull()
    expect(normalizeTimelineCursor(null)).toBeNull()
    expect(normalizeTimelineCursor(undefined)).toBeNull()
  })
})

describe('normalizeTimelineRange', () => {
  it('接受日空间非空的窗口（整数或浮点）', () => {
    expect(normalizeTimelineRange({ start: 1, end: 2177 })).toEqual({ start: 1, end: 2177 })
    // 浮点年 = 日精度窗口（2026-09-02 起）：viewStart 日计数 = round((start-1)*365)
    expect(normalizeTimelineRange({ start: 2157.5, end: 2158 })).toEqual({
      start: 2157.5,
      end: 2158,
    })
    // 坐标约定 start=1+起日/365、end=止日/365——窗口落在单年内时 start 可大于 end：
    // 整数 {5,5} = 只看第 5 年（365 天），旧 start<end 规则曾误判为空窗口
    expect(normalizeTimelineRange({ start: 5, end: 5 })).toEqual({ start: 5, end: 5 })
    // 实测事故对：2171 年内的 132 天浮点窗口
    expect(normalizeTimelineRange({ start: 2171.186301369863, end: 2170.5479452054797 })).toEqual({
      start: 2171.186301369863,
      end: 2170.5479452054797,
    })
  })

  it('拒绝非法窗口', () => {
    expect(normalizeTimelineRange({ start: 0, end: 5 })).toBeNull() // start < 1
    expect(normalizeTimelineRange({ start: 6, end: 5 })).toBeNull() // end <= start-1：日空间窗口为空
    expect(normalizeTimelineRange({ start: 2, end: 1.001 })).toBeNull() // 名义跨度 < 1 天
    expect(normalizeTimelineRange({ start: NaN, end: 5 })).toBeNull() // 非有限数
    expect(normalizeTimelineRange({ start: 1, end: Infinity })).toBeNull()
    expect(normalizeTimelineRange({ start: 1 })).toBeNull() // 缺键
    expect(normalizeTimelineRange(null)).toBeNull()
    expect(normalizeTimelineRange('1-5')).toBeNull()
    expect(normalizeTimelineRange([1, 5])).toBeNull()
  })
})
