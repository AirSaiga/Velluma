import { describe, expect, it } from 'vitest'
import {
  anchorProgress,
  spineIntentText,
  buildStoryArcs,
  assignArcLanes,
  chapterMarks,
  groupReveals,
  alignTensionSamples,
} from '../storyline'

describe('anchorProgress', () => {
  it('无 spine / 无锚点返回 0/0', () => {
    expect(anchorProgress(null)).toEqual({ done: 0, total: 0 })
    expect(anchorProgress({})).toEqual({ done: 0, total: 0 })
    expect(anchorProgress({ anchors: [] })).toEqual({ done: 0, total: 0 })
  })

  it('dropped 不计总数，hit 计兑现', () => {
    const r = anchorProgress({
      anchors: [
        { id: '1', text: 'a', status: 'hit' },
        { id: '2', text: 'b', status: 'pending' },
        { id: '3', text: 'c', status: 'dropped' },
        { id: '4', text: 'd', status: 'hit' },
      ],
    })
    expect(r).toEqual({ done: 2, total: 3 })
  })
})

describe('spineIntentText', () => {
  it('空 spine 返回空串，有值去空白', () => {
    expect(spineIntentText(null)).toBe('')
    expect(spineIntentText({ intent: { text: '  逃出矿镇  ' } })).toBe('逃出矿镇')
  })
})

describe('buildStoryArcs', () => {
  const numberById = new Map([
    ['c1', 1],
    ['c2', 2],
    ['c3', 3],
  ])
  const valid = new Set([1, 2, 3])

  it('closed 埋收两端齐备成弧，open 成悬空弧', () => {
    const arcs = buildStoryArcs(
      [
        { id: 'a', content: '断剑', status: 'closed', plantedChapter: 1, resolvedChapterId: 'c3' },
        { id: 'b', content: '旧约', status: 'open', plantedChapter: 2, resolvedChapterId: null },
      ],
      numberById,
      valid,
    )
    expect(arcs).toEqual([
      { id: 'a', content: '断剑', fromN: 1, toN: 3, resolved: true },
      { id: 'b', content: '旧约', fromN: 2, toN: null, resolved: false },
    ])
  })

  it('dropped / 无埋设章 / 埋设章不在章列表 剔除', () => {
    const arcs = buildStoryArcs(
      [
        { id: 'd', content: '废弃', status: 'dropped', plantedChapter: 1, resolvedChapterId: 'c2' },
        { id: 'e', content: '无锚', status: 'open', plantedChapter: null, resolvedChapterId: null },
        { id: 'f', content: '埋在已删章', status: 'open', plantedChapter: 9, resolvedChapterId: null },
      ],
      numberById,
      valid,
    )
    expect(arcs).toEqual([])
  })

  it('closed 但回收章解析不到（章节已删）剔除，不做悬空假画', () => {
    const arcs = buildStoryArcs(
      [
        { id: 'g', content: '孤儿', status: 'closed', plantedChapter: 1, resolvedChapterId: 'cX' },
        { id: 'h', content: '无回收id', status: 'closed', plantedChapter: 1, resolvedChapterId: null },
      ],
      numberById,
      valid,
    )
    expect(arcs).toEqual([])
  })
})

describe('assignArcLanes', () => {
  const idx = new Map([
    [1, 0],
    [2, 1],
    [3, 2],
    [4, 3],
  ])

  it('不重叠弧线同道，重叠弧线堆新道', () => {
    const lanes = assignArcLanes(
      [
        { id: 'a', content: '', fromN: 1, toN: 2, resolved: true },
        { id: 'b', content: '', fromN: 3, toN: 4, resolved: true },
        { id: 'c', content: '', fromN: 1, toN: 4, resolved: true },
      ],
      idx,
      3,
    )
    // 排序后 a(0-1) b(2-3) 同道 0；c(0-3) 与 a 起点重叠进道 1
    const byId = Object.fromEntries(lanes.map((l) => [l.id, l]))
    expect(byId['a'].lane).toBe(0)
    expect(byId['b'].lane).toBe(0)
    expect(byId['c'].lane).toBe(1)
  })

  it('悬空弧线 end 落在 lastIdx', () => {
    const lanes = assignArcLanes(
      [{ id: 'o', content: '', fromN: 2, toN: null, resolved: false }],
      idx,
      3,
    )
    expect(lanes[0]).toMatchObject({ start: 1, end: 3 })
  })

  it('悬空弧线与后续起点重叠时开新道（悬空占满到右缘）', () => {
    const lanes = assignArcLanes(
      [
        { id: 'o', content: '', fromN: 1, toN: null, resolved: false },
        { id: 'p', content: '', fromN: 2, toN: 3, resolved: true },
      ],
      idx,
      3,
    )
    const byId = Object.fromEntries(lanes.map((l) => [l.id, l]))
    expect(byId['o'].lane).toBe(0)
    expect(byId['p'].lane).toBe(1)
  })

  it('端点相接（前弧 end == 后弧 start）不重叠，同道装下', () => {
    const lanes = assignArcLanes(
      [
        { id: 'x', content: '', fromN: 1, toN: 2, resolved: true },
        { id: 'y', content: '', fromN: 2, toN: 4, resolved: true },
      ],
      idx,
      3,
    )
    // x 区间 [0,1]、y 区间 [1,3]：端点相接 y.start(1) > x.end(1) 不成立 → 判重叠
    // （半开区间语义：道内上一条 end 必须 < 下一条 start）
    expect(lanes.map((l) => l.id)).toEqual(['x', 'y'])
    expect(lanes[0].lane).toBe(0)
    expect(lanes[1].lane).toBe(1)
  })
})

describe('chapterMarks', () => {
  it('埋/收按章号各计数', () => {
    const arcs = [
      { id: 'a', content: '', fromN: 1, toN: 3, resolved: true },
      { id: 'b', content: '', fromN: 1, toN: null, resolved: false },
      { id: 'c', content: '', fromN: 3, toN: 3, resolved: true },
    ]
    expect(chapterMarks(arcs, 1)).toEqual({ planted: 2, resolved: 0 })
    expect(chapterMarks(arcs, 3)).toEqual({ planted: 1, resolved: 2 })
    expect(chapterMarks(arcs, 2)).toEqual({ planted: 0, resolved: 0 })
  })
})

describe('groupReveals', () => {
  it('只收 非public 且带揭示章号 的条目', () => {
    const m = groupReveals([
      { label: '身世', visibility: 'secret', expected_reveal_chapter: 5 },
      { label: '公开设定', visibility: 'public', expected_reveal_chapter: 5 },
      { label: '半露', visibility: 'partial', expected_reveal_chapter: 5 },
      { label: '无计划', visibility: 'secret', expected_reveal_chapter: null },
      { label: '第7章', visibility: 'secret', expected_reveal_chapter: 7 },
    ])
    expect(m.get(5)).toEqual(['身世', '半露'])
    expect(m.get(7)).toEqual(['第7章'])
    expect(m.size).toBe(2)
  })
})

describe('alignTensionSamples', () => {
  it('画不到的章号剔除 + 张力夹取 0..10 + 按章号排序', () => {
    const out = alignTensionSamples(
      [
        { chapter_number: 2, overall_tension: 12 },
        { chapter_number: 1, overall_tension: 3, is_payoff_chapter: false },
        { chapter_number: 9, overall_tension: 5 },
        { chapter_number: 3, overall_tension: -2, is_payoff_chapter: true },
        { chapter_number: 2, overall_tension: Number.NaN },
      ],
      new Set([1, 2, 3]),
    )
    expect(out).toEqual([
      { n: 1, tension: 3, payoff: false },
      { n: 2, tension: 10, payoff: false },
      { n: 3, tension: 0, payoff: true },
    ])
  })
})
