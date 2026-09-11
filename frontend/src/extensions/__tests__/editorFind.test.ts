import { describe, expect, it } from 'vitest'
import { Schema } from '@tiptap/pm/model'
import { collectDocMatches, findTextMatches } from '../editorFind'

/**
 * 查找命中扫描单测（2026-09-10）。
 *
 * 重点不在「找得到」，而在**位置映射对不对**：正文里行内格式（加粗/残留颜色）
 * 会把一句话切成多个文本节点，@提及/细纲胶囊是原子节点——命中区间的文档位置
 * 必须跨节点算准，否则「替换」会改错地方（这是查找功能唯一的危险面）。
 */

/** 最小可用 schema（不依赖 DOM）：段落 + 文本 + 粗体标记 + 原子提及节点 */
const schema = new Schema({
  nodes: {
    doc: { content: 'block+' },
    paragraph: { content: 'inline*', group: 'block' },
    text: { group: 'inline' },
    mention: { group: 'inline', inline: true, atom: true, attrs: { label: { default: '' } } },
  },
  marks: {
    bold: {},
  },
})

const p = (...content: any[]) => schema.node('paragraph', null, content)
const doc = (...blocks: any[]) => schema.node('doc', null, blocks)

describe('findTextMatches — 纯文本扫描', () => {
  it('中文子串逐个命中（不重叠，去重靠前推进）', () => {
    expect(findTextMatches('林尘看着林尘', '林尘')).toEqual([
      [0, 2],
      [4, 6],
    ])
  })

  it('英文默认不区分大小写，开关打开后区分', () => {
    expect(findTextMatches('Lin Chen lin', 'lin')).toEqual([
      [0, 3],
      [9, 12],
    ])
    expect(findTextMatches('Lin Chen lin', 'lin', true)).toEqual([[9, 12]])
  })

  it('空词/空文本返回空，不无限循环', () => {
    expect(findTextMatches('村子', '')).toEqual([])
    expect(findTextMatches('', '村子')).toEqual([])
  })
})

describe('collectDocMatches — 跨文本节点的位置映射', () => {
  it('命中横跨粗体边界时，起止位置各自落在正确的文档位置上', () => {
    // 段落：粗体「村子」+ 普通「...好」——两个文本节点
    const d = doc(p(schema.text('村子', [schema.marks.bold.create()]), schema.text('...好')))
    const matches = collectDocMatches(d, '子.')
    expect(matches).toHaveLength(1)
    // 段落内容从 1 起：村=1 子=2 .=3 → [2, 4)
    expect(matches[0]).toEqual({ from: 2, to: 4 })
    expect(d.textBetween(matches[0].from, matches[0].to)).toBe('子.')
  })

  it('逐条命中落在正确的段落里（多段不串位）', () => {
    const d = doc(p(schema.text('林尘来了')), p(schema.text('王叔走了')), p(schema.text('又叫林尘')))
    const matches = collectDocMatches(d, '林尘')
    expect(matches).toHaveLength(2)
    expect(d.textBetween(matches[0].from, matches[0].to)).toBe('林尘')
    expect(d.textBetween(matches[1].from, matches[1].to)).toBe('林尘')
  })

  it('原子节点（@提及）以占位挡住：不给提及内部做匹配，也不跨原子连读', () => {
    const d = doc(p(schema.text('好'), schema.node('mention', { label: '林尘' }), schema.text('坏')))
    expect(collectDocMatches(d, '林尘')).toEqual([])
    // 「好」与「坏」在文档上被原子隔开——拼出来的文本里有占位符，连不成「好坏」
    expect(collectDocMatches(d, '好坏')).toEqual([])
  })

  it('无命中返回空数组', () => {
    const d = doc(p(schema.text('林尘来了')))
    expect(collectDocMatches(d, '王叔')).toEqual([])
    expect(collectDocMatches(d, '')).toEqual([])
  })
})
