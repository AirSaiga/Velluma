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
  it('接受 1 <= start < end 的整数年份', () => {
    expect(normalizeTimelineRange({ start: 1, end: 2177 })).toEqual({ start: 1, end: 2177 })
  })

  it('拒绝非法窗口', () => {
    expect(normalizeTimelineRange({ start: 0, end: 5 })).toBeNull() // start < 1
    expect(normalizeTimelineRange({ start: 5, end: 5 })).toBeNull() // end <= start
    expect(normalizeTimelineRange({ start: 6, end: 5 })).toBeNull()
    expect(normalizeTimelineRange({ start: 1.5, end: 5 })).toBeNull() // 非整数
    expect(normalizeTimelineRange({ start: 1 })).toBeNull() // 缺键
    expect(normalizeTimelineRange(null)).toBeNull()
    expect(normalizeTimelineRange('1-5')).toBeNull()
    expect(normalizeTimelineRange([1, 5])).toBeNull()
  })
})
