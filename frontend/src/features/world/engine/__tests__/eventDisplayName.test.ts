/**
 * 事件显示名纯函数对拍（2026-09-13 标题批）。
 *
 * 锁定回退链：用户自拟标题（trim 后非空）优先 → 模板标签 → event_type 原文。
 * 消费面（列表/时间轴/地图标注/实体编年/浮卡/删除确认/搜索）统一走 eventDisplayName，
 * 不再各自 getTemplate(...)?.label 拼一份。
 */
import { describe, expect, it } from 'vitest'
import { eventDisplayName } from '../eventTemplates'

describe('eventDisplayName 回退链', () => {
  it('有标题（含首尾空白）→ 标题优先', () => {
    expect(eventDisplayName({ event_type: 'birth', title: '林尘降生' })).toBe('林尘降生')
    expect(eventDisplayName({ event_type: 'birth', title: '  血夜  ' })).toBe('血夜')
  })

  it('空标题/null/undefined → 回退模板标签', () => {
    expect(eventDisplayName({ event_type: 'birth', title: '' })).toBe('出生')
    expect(eventDisplayName({ event_type: 'birth', title: '   ' })).toBe('出生')
    expect(eventDisplayName({ event_type: 'custom', title: null })).toBe('自定义')
    expect(eventDisplayName({ event_type: 'move' })).toBe('移动')
  })

  it('未知类型 → event_type 原文兜底', () => {
    expect(eventDisplayName({ event_type: 'future_kind', title: '' })).toBe('future_kind')
  })
})
