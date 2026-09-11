import { describe, expect, it } from 'vitest'
import { Schema } from '@tiptap/pm/model'
import {
  collectPunctuationEdits,
  hasCjk,
  normalizeChinesePunctuation,
  punctuationEdits,
} from '../chineseTypography'

/**
 * 中文标点规范化单测（2026-09-10）。
 *
 * 用例取自**真实存量正文**（data/velluma.db 的《村子》第 1 章原文）与
 * 「绝不能动」的反例（英文/数字/代码串）——判据是「宁漏勿误」，
 * 所以反例与正例同等重要。
 */

/** 文档级用例用的最小 schema（不依赖 DOM）：段落 + 文本 + 粗体 + 幽灵标记 + 原子提及 */
const schema = new Schema({
  nodes: {
    doc: { content: 'block+' },
    paragraph: { content: 'inline*', group: 'block' },
    text: { group: 'inline' },
    mention: { group: 'inline', inline: true, atom: true, attrs: { label: { default: '' } } },
  },
  marks: {
    bold: {},
    ghostDraft: {},
  },
})

const p = (...content: any[]) => schema.node('paragraph', null, content)
const doc = (...blocks: any[]) => schema.node('doc', null, blocks)

describe('normalizeChinesePunctuation — 省略号', () => {
  it('收掉真实章节里的 ASCII 三点省略号（存量为证：19 章里 8 章在用）', () => {
    expect(normalizeChinesePunctuation('“咳咳...阿尘啊...这发电机还能修得好吗？”')).toBe(
      '“咳咳……阿尘啊……这发电机还能修得好吗？”',
    )
  })

  it('已经写成全角句号点列（逐字输入被转过的形态）也认', () => {
    expect(normalizeChinesePunctuation('他说。。。')).toBe('他说……')
    expect(normalizeChinesePunctuation('他说。.。')).toBe('他说……')
  })

  it('四点及以上一并收成一个省略号（不叠加）', () => {
    expect(normalizeChinesePunctuation('沉默....')).toBe('沉默……')
  })

  it('英文句子里的三点省略号不动', () => {
    expect(normalizeChinesePunctuation('Mr. Smith said hello...')).toBe('Mr. Smith said hello...')
  })
})

describe('normalizeChinesePunctuation — 半角标点', () => {
  it('中文后的半角逗号句号问号叹号转全角', () => {
    expect(normalizeChinesePunctuation('林尘,你来了.走吗?好!')).toBe('林尘，你来了。走吗？好！')
  })

  it('中文后的半角冒号分号括号转全角', () => {
    expect(normalizeChinesePunctuation('他说:别动;好吧(笑)')).toBe('他说：别动；好吧（笑）')
  })

  it('破折号：中文后的双连字符转中文破折号', () => {
    expect(normalizeChinesePunctuation('他张了张嘴--什么也没说')).toBe('他张了张嘴——什么也没说')
  })

  it('数字与拉丁字母后的半角标点一律不动（3.14 / 1,000 / Mr.）', () => {
    const src = '圆周率 3.14，数量 1,000，Mr. Smith'
    expect(normalizeChinesePunctuation(src)).toBe(src)
  })
})

describe('normalizeChinesePunctuation — 直引号', () => {
  it('引号里是中文的成对直引号转中文引号', () => {
    expect(normalizeChinesePunctuation('"好嘞，搞定。"')).toBe('“好嘞，搞定。”')
  })

  it('英文引文原样（引号里没有中文）', () => {
    const src = 'he said "hello world" loudly'
    expect(normalizeChinesePunctuation(src)).toBe(src)
  })

  it('单个直引号不成对时不猜（don\'t 的撇号不会被配成中文单引号）', () => {
    expect(normalizeChinesePunctuation("don't")).toBe("don't")
    expect(normalizeChinesePunctuation('他说"')).toBe('他说"')
  })
})

describe('normalizeChinesePunctuation — 空格', () => {
  it('清掉全角标点两侧的 ASCII 空格', () => {
    expect(normalizeChinesePunctuation('你好 ，再见')).toBe('你好，再见')
    expect(normalizeChinesePunctuation('他说（ 笑 ）')).toBe('他说（笑）')
  })
})

describe('normalizeChinesePunctuation — 契约', () => {
  it('幂等：同一段文本跑两遍结果一致', () => {
    const samples = [
      '“咳咳...阿尘啊...”他说，"真的吗?"',
      '他说:"好--就这?"（笑）',
      '林尘,你来了.',
      'Hello... world',
    ]
    for (const s of samples) {
      const once = normalizeChinesePunctuation(s)
      expect(normalizeChinesePunctuation(once)).toBe(once)
    }
  })

  it('空串与纯英文段落零变化', () => {
    expect(normalizeChinesePunctuation('')).toBe('')
    const en = 'The quick brown fox, jumps over 3 lazy dogs.'
    expect(normalizeChinesePunctuation(en)).toBe(en)
  })

  it('替换位置精确（供文档批处理映射回 ProseMirror 位置）', () => {
    const edits = punctuationEdits('村子...好')
    expect(edits).toEqual([{ start: 2, end: 5, text: '……' }])
  })

  it('替换清单按位置升序（回归：引号会先记右引号的账，不排会拼接错位）', () => {
    const edits = punctuationEdits('他说:"好--就这?"（笑）')
    const starts = edits.map((e) => e.start)
    expect(starts).toEqual([...starts].sort((a, b) => a - b))
    expect(normalizeChinesePunctuation('他说:"好--就这?"（笑）')).toBe('他说：“好——就这？”（笑）')
  })

  it('hasCjk 只对中日韩为真', () => {
    expect(hasCjk('林尘')).toBe(true)
    expect(hasCjk('，')).toBe(true)
    expect(hasCjk('Lin Chen 123')).toBe(false)
  })
})

describe('collectPunctuationEdits — 文档位置映射', () => {
  it('单段落：命中区间的文档位置精确（供单事务倒序替换）', () => {
    // 段落内容从 1 起：林=1 尘=2 ,=3 你=4 好=5 .=6
    const d = doc(p(schema.text('林尘,你好.')))
    expect(collectPunctuationEdits(d)).toEqual([
      { from: 3, to: 4, text: '，' },
      { from: 6, to: 7, text: '。' },
    ])
  })

  it('跨行内格式的相邻文本节点仍能识别（前一位在隔壁节点）', () => {
    // 粗体「林尘」+ 普通「,你好」——逗号的前一位在另一个文本节点里
    const d = doc(p(schema.text('林尘', [schema.marks.bold.create()]), schema.text(',你好')))
    expect(collectPunctuationEdits(d)).toEqual([{ from: 3, to: 4, text: '，' }])
  })

  it('幽灵草稿（未确认的 AI 中间态）不动：它内部的标点不归一，也不当邻居', () => {
    const d = doc(p(schema.text('好'), schema.text('...', [schema.marks.ghostDraft.create()]), schema.text(',在')))
    // 「好」与幽灵之间隔着占位符 → 幽灵内部的 ... 不转，紧随其后的半角逗号也不认「中文前一位」
    expect(collectPunctuationEdits(d)).toEqual([])
  })

  it('多段落各自定位，不串位', () => {
    const d = doc(p(schema.text('甲,')), p(schema.text('乙.')))
    const edits = collectPunctuationEdits(d)
    expect(edits).toEqual([
      { from: 2, to: 3, text: '，' },
      { from: 6, to: 7, text: '。' },
    ])
    expect(d.textBetween(edits[0].from, edits[0].to)).toBe(',')
    expect(d.textBetween(edits[1].from, edits[1].to)).toBe('.')
  })

  it('选区范围只扫区间内（作者点名范围时不越界改）', () => {
    const d = doc(p(schema.text('甲,')), p(schema.text('乙.')))
    // 只覆盖第一段（doc 位置 0..4）
    expect(collectPunctuationEdits(d, 0, 4)).toEqual([{ from: 2, to: 3, text: '，' }])
  })

  it('本来干净的中文正文零改动（幂等：整理两遍等于整理一遍）', () => {
    const d = doc(p(schema.text('林尘，你好。')))
    expect(collectPunctuationEdits(d)).toEqual([])
  })
})
