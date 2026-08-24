import { describe, it, expect } from 'vitest'
import { breakdownTime, fromYMD, formatTime } from '../timeFormat'

// 历法双射回归：365 = 12×30 + 5，年末余 5 天两侧必须一致记作「13 月 1~5 日」，
// 否则编辑面「分解→重组」往返丢 30 天（2026-08-24 实测事故）

describe('timeFormat 历法往返', () => {
  it('breakdownTime → fromYMD 对全部时刻恒等（含每年末 5 天）', () => {
    for (let t = 0; t <= 2200; t++) {
      const b = breakdownTime(t)
      expect(fromYMD(b.year, b.month, b.day)).toBe(t)
    }
  })

  it('年末余日记作 13 月 1~5 日', () => {
    expect(breakdownTime(360)).toEqual({ year: 1, month: 13, day: 1 })
    expect(breakdownTime(364)).toEqual({ year: 1, month: 13, day: 5 })
    expect(breakdownTime(725)).toEqual({ year: 2, month: 13, day: 1 })
    expect(formatTime(362)).toBe('第1年13月3日')
  })

  it('fromYMD 钳位：年 ≥1、月 1~13、13 月日 1~5、平月日 1~30', () => {
    expect(fromYMD(1, 13, 5)).toBe(364)
    expect(fromYMD(1, 13, 99)).toBe(364)   // 13 月日钳 5
    expect(fromYMD(1, 14, 1)).toBe(360)    // 月钳 13
    expect(fromYMD(1, 0, 1)).toBe(0)       // 月钳 1
    expect(fromYMD(1, 12, 99)).toBe(359)   // 平月日钳 30
    expect(fromYMD(0, 1, 1)).toBe(0)       // 年钳 1
  })
})
