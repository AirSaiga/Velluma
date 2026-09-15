import { describe, expect, it } from 'vitest'
import { defatText } from '../defat'

describe('defatText', () => {
  it('正常叙述零命中 → 原文不变、removed 为空（宁漏勿误）', () => {
    const text = '老周把扳手塞进工具包，锁了仓库门。雨还没停。'
    expect(defatText(text)).toEqual({ text, removed: [] })
  })

  it('AI 腔口头禅整词删除并记入 removed', () => {
    const { text, removed } = defatText('他心中一紧，转身就走。')
    expect(text).toBe('他，转身就走。')
    expect(removed).toContain('心中一紧')
  })

  it('套路"地"字副词删除', () => {
    const { text, removed } = defatText('他缓缓地推开门。')
    expect(text).toBe('他推开门。')
    expect(removed).toContain('缓缓地')
  })

  it('同一词多次出现全部删除', () => {
    const { text } = defatText('他顿时站起来，顿时又坐下。')
    expect(text).not.toContain('顿时')
  })

  it('删词产生的叠标点收敛（，，→，；，。→。）', () => {
    const { text } = defatText('他仿佛，顿时，站在门口。')
    expect(text).not.toMatch(/，，/)
    expect(text).not.toMatch(/，。/)
  })

  it('无命中时不做标点收敛（原文可能有合法双空格）', () => {
    // removed 为空 → 清理分支不进：原文原样返回
    const text = '他坐下来。  想了想。'
    expect(defatText(text).text).toBe(text)
  })

  it('多个不同黑名单词一并删净', () => {
    const { text, removed } = defatText('她眼神中闪过一丝异样，不由得后退半步。')
    expect(text).not.toContain('眼神中闪过')
    expect(text).not.toContain('不由得')
    expect(removed.length).toBeGreaterThanOrEqual(2)
  })
})
