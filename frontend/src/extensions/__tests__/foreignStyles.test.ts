import { describe, expect, it } from 'vitest'
import { scrubStyleDeclarations } from '../foreignStyles'

/**
 * 外来样式净化单测（2026-09-10）。
 *
 * 病灶实录：存量章节里有 `<span style="color: rgb(43, 45, 49);">` 这类
 * 粘贴残留——深色主题下就是深色纸面上的深色字（读不出来）。这里只测纯函数
 * 那层（DOM 那层靠浏览器，node 环境没有 DOMParser）。
 */

describe('scrubStyleDeclarations', () => {
  it('剥掉真实病灶里的颜色声明，保留排版意图', () => {
    expect(scrubStyleDeclarations('color: rgb(43, 45, 49); font-weight: 700')).toBe('font-weight: 700')
  })

  it('单独的长相属性整条摘掉（返回空串=调用方摘 style 属性）', () => {
    expect(scrubStyleDeclarations('background-color:#fff')).toBe('')
    expect(scrubStyleDeclarations('font-family: "Songti SC", serif')).toBe('')
    expect(scrubStyleDeclarations('font-size: 18px; line-height: 2')).toBe('')
  })

  it('粗体/斜体/下划线/对齐等非长相样式原样保留', () => {
    const kept = 'font-weight: bold; font-style: italic; text-decoration: underline; text-align: center'
    expect(scrubStyleDeclarations(kept)).toBe(kept)
  })

  it('空值与畸形声明不炸（缺冒号的裸词按属性名处理并丢弃）', () => {
    expect(scrubStyleDeclarations('')).toBe('')
    expect(scrubStyleDeclarations(';; color: red ;;')).toBe('')
    expect(scrubStyleDeclarations('nonsense')).toBe('')
  })
})
