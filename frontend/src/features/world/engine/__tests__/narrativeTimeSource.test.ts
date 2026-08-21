import { describe, expect, it } from 'vitest'
import {
  narrativeSourceText,
  futureEventWarning,
  type NarrativeSourceInfo,
} from '../narrativeTimeSource'

describe('narrativeSourceText（切片条来源小字）', () => {
  it('四级来源各有文案，附加信息缺席时退到无细节说法', () => {
    expect(narrativeSourceText({ source: 'chapter_anchor' })).toBe('来自本章锚')
    expect(narrativeSourceText({ source: 'prev_anchor', chapter: 3 })).toBe('来自第3章锚')
    expect(narrativeSourceText({ source: 'prev_anchor' })).toBe('来自前章锚') // 章号缺席
    expect(narrativeSourceText({ source: 'max_event', note: '结局之战' })).toBe(
      '来自事件『结局之战』',
    )
    expect(narrativeSourceText({ source: 'max_event' })).toBe('来自最远事件') // 摘要缺席
    expect(narrativeSourceText({ source: 'zero' })).toBe('未锚定')
  })

  it('未知 source 兜底为未锚定（向后兼容）', () => {
    expect(narrativeSourceText({ source: 'future_source' } as NarrativeSourceInfo)).toBe('未锚定')
  })

  it('null 与 undefined 的附加信息均按缺席处理', () => {
    expect(narrativeSourceText({ source: 'prev_anchor', chapter: null })).toBe('来自前章锚')
    expect(narrativeSourceText({ source: 'max_event', note: null })).toBe('来自最远事件')
  })
})

describe('futureEventWarning（录入侧警示显隐）', () => {
  const anchored = { narrative_time: 100 }
  const unanchored = { narrative_time: null }

  it('锚定信息缺席（无章节数据）→ 静默不显示', () => {
    expect(futureEventWarning({ timeStart: 9999, chapterAnchors: [] })).toBeNull()
  })

  it('全部章节已锚 → 无人被拉动，静默', () => {
    expect(
      futureEventWarning({ timeStart: 9999, chapterAnchors: [anchored, { narrative_time: 200 }] }),
    ).toBeNull()
  })

  it('有锚书：超出最大章锚才提示，文案带事件日数', () => {
    const warn = futureEventWarning({ timeStart: 1240, chapterAnchors: [anchored, unanchored] })
    expect(warn).toBe('这个事件发生在故事当前时间之后——没定时间的章节，『此刻』会被拉到第 1240 日')
    // 等于/不超出最大锚 → 不提示
    expect(futureEventWarning({ timeStart: 100, chapterAnchors: [anchored, unanchored] })).toBeNull()
    expect(futureEventWarning({ timeStart: 99, chapterAnchors: [anchored, unanchored] })).toBeNull()
  })

  it('无锚书：超出事件流最大时刻（未锚章节的③级基准）才提示', () => {
    expect(
      futureEventWarning({ timeStart: 500, chapterAnchors: [unanchored], maxEventTime: 400 }),
    ).toBe('这个事件发生在故事当前时间之后——没定时间的章节，『此刻』会被拉到第 500 日')
    expect(
      futureEventWarning({ timeStart: 400, chapterAnchors: [unanchored], maxEventTime: 400 }),
    ).toBeNull() // 等于不超出
    expect(
      futureEventWarning({ timeStart: 300, chapterAnchors: [unanchored], maxEventTime: 400 }),
    ).toBeNull()
  })

  it('无锚书且无事件：基准为 0，任何正时刻事件提示（首事件教学场景）', () => {
    expect(
      futureEventWarning({ timeStart: 10, chapterAnchors: [unanchored] }),
    ).toBe('这个事件发生在故事当前时间之后——没定时间的章节，『此刻』会被拉到第 10 日')
  })

  it('有锚书优先按最大章锚判（事件流最大时刻不参与）', () => {
    // 若按无锚书规则（1500 > 事件最大 1000）会提示；有锚书按最大章锚 2000 判 → 不提示
    expect(
      futureEventWarning({
        timeStart: 1500,
        chapterAnchors: [{ narrative_time: 2000 }, unanchored],
        maxEventTime: 1000,
      }),
    ).toBeNull()
  })
})
