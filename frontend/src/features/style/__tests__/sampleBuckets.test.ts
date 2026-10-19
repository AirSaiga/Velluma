/** 样本分桶纯函数测试（我的笔迹库批，2026-09）。 */
import { describe, expect, it } from 'vitest'
import { bucketSamples, canEnterLibrary, extractPrefillCandidates, foreignSampleHint, isForeignSample, libraryStandbyLabel } from '../sampleBuckets'
import type { AuthorSample } from '../../../types'

function makeSample(over: Partial<AuthorSample> & { id: string }): AuthorSample {
  return {
    book_id: 'b1',
    scene_type: 'general',
    content: '一段字',
    word_count: 3,
    source: 'manual',
    era: 'recent',
    favorite: false,
    created_at: '2026-09-24T00:00:00Z',
    ...over,
  }
}

describe('bucketSamples（scope 分桶）', () => {
  it('按 scope 字段分到本书段 / 笔迹库段', () => {
    const a = makeSample({ id: 'a', scope: 'book' })
    const b = makeSample({ id: 'b', scope: 'global' })
    const c = makeSample({ id: 'c' }) // 缺省视为本书（容错老响应体）
    const { book, library } = bucketSamples([a, b, c])
    expect(book.map(s => s.id)).toEqual(['a', 'c'])
    expect(library.map(s => s.id)).toEqual(['b'])
  })

  it('各段保持接口新→旧原序，不重排不丢条', () => {
    const list = [1, 2, 3, 4, 5].map(i =>
      makeSample({ id: `s${i}`, scope: i % 2 === 0 ? 'global' : 'book' }),
    )
    const { book, library } = bucketSamples(list)
    expect(book.map(s => s.id)).toEqual(['s1', 's3', 's5'])
    expect(library.map(s => s.id)).toEqual(['s2', 's4'])
    expect(book.length + library.length).toBe(list.length)
  })

  it('空列表与全 global 列表', () => {
    expect(bucketSamples([])).toEqual({ book: [], library: [] })
    const only = bucketSamples([makeSample({ id: 'g', scope: 'global' })])
    expect(only.book).toEqual([])
    expect(only.library.map(s => s.id)).toEqual(['g'])
  })
})

describe('canEnterLibrary（AI 学 AI 红线）', () => {
  it('手写/黄金片段/章节收编可转入笔迹库', () => {
    for (const source of ['manual', 'golden_snippet', 'published_chapter']) {
      expect(canEnterLibrary(makeSample({ id: 'x', source }))).toBe(true)
    }
  })

  it('采纳幽灵样本（AI 写的）禁入笔迹库——与后端 422 闸同口径', () => {
    expect(canEnterLibrary(makeSample({ id: 'g', source: 'adopted_ghost' }))).toBe(false)
  })
})

describe('isForeignSample（外来样本只读判定，2026-09 用户拍板）', () => {
  it('book_id 不等于当前书 → 外来，只读', () => {
    expect(isForeignSample(makeSample({ id: 'x', book_id: 'other-book', scope: 'global' }), 'b1')).toBe(true)
  })

  it('本书自己转入笔迹库的样本不受限', () => {
    expect(isForeignSample(makeSample({ id: 'own', book_id: 'b1', scope: 'global' }), 'b1')).toBe(false)
    expect(isForeignSample(makeSample({ id: 'own2', book_id: 'b1', scope: 'book' }), 'b1')).toBe(false)
  })

  it('缺 book_id / 缺当前书 ID 的容错：视为本书，宁可放行不误伤', () => {
    expect(isForeignSample(makeSample({ id: 'noid', book_id: '' as unknown as string }), 'b1')).toBe(false)
    expect(isForeignSample(makeSample({ id: 'nobook', book_id: 'other' }), null)).toBe(false)
    expect(isForeignSample(makeSample({ id: 'undef', book_id: undefined as unknown as string }), undefined)).toBe(false)
  })
})

describe('foreignSampleHint（只读悬停解释，作者语言）', () => {
  it('知道书名时点名来源书', () => {
    const s = makeSample({ id: 'x', book_id: 'b2' })
    expect(foreignSampleHint(s, { b2: '灯塔与雾' })).toBe('来自《灯塔与雾》的样本——去那本书的文风页里改')
  })

  it('书名映射缺失时退化为通用指路文案', () => {
    const s = makeSample({ id: 'x', book_id: 'b2' })
    expect(foreignSampleHint(s)).toBe('来自其他书的样本——去那本书的文风页里改')
    expect(foreignSampleHint(s, {})).toBe('来自其他书的样本——去那本书的文风页里改')
  })
})

describe('extractPrefillCandidates（提炼预填只取本书样本）', () => {
  it('外来样本即使最长也不进预填；本书样本按字数降序取前 3', () => {
    const list = [
      makeSample({ id: 'f', book_id: 'b2', scope: 'global', word_count: 999, content: '别书的字' }),
      makeSample({ id: 'a', book_id: 'b1', word_count: 100, content: '甲' }),
      makeSample({ id: 'b', book_id: 'b1', word_count: 300, content: '乙' }),
      makeSample({ id: 'c', book_id: 'b1', word_count: 200, content: '丙' }),
      makeSample({ id: 'd', book_id: 'b1', word_count: 50, content: '丁' }),
    ]
    expect(extractPrefillCandidates(list, 'b1')).toEqual(['乙', '丙', '甲'])
  })

  it('本书自己转入笔迹库的样本（own global）仍在预填候选内', () => {
    const list = [makeSample({ id: 'g', book_id: 'b1', scope: 'global', word_count: 100, content: '己' })]
    expect(extractPrefillCandidates(list, 'b1')).toEqual(['己'])
  })

  it('本书零样本 → 空数组（弹窗走手贴路径）；count 截断生效', () => {
    expect(extractPrefillCandidates([makeSample({ id: 'f', book_id: 'b2' })], 'b1')).toEqual([])
    const two = [
      makeSample({ id: 'a', book_id: 'b1', word_count: 1, content: '甲' }),
      makeSample({ id: 'b', book_id: 'b1', word_count: 2, content: '乙' }),
    ]
    expect(extractPrefillCandidates(two, 'b1', 1)).toEqual(['乙'])
  })
})

describe('libraryStandbyLabel（作者语言，零术语）', () => {
  it('有待命条目时显示条数与补位说明', () => {
    expect(libraryStandbyLabel(3)).toBe('笔迹库 · 3 条待命——新书与缺场景时自动补位')
  })

  it('空库引导转入；单条不带复数语义问题（中文无屈折，快照锁定文案）', () => {
    expect(libraryStandbyLabel(1)).toBe('笔迹库 · 1 条待命——新书与缺场景时自动补位')
    expect(libraryStandbyLabel(0)).toBe('笔迹库还空着——把最像你的字转入，新书缺范例时自动补位')
  })
})
