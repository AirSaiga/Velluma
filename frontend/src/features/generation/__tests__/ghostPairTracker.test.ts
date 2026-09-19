/**
 * 对拍口径：锁「幽灵改稿自动捕获」的书签决策契约（03 下一阶段 M1）——
 * 干净采纳跳过/有改动提交/越窗拒绝/塌缩不成对；位置映射的插删塌缩三形态；
 * 覆盖语义（同一幽灵只留最新版：POST 新对 + DELETE 旧对）；final 清账。
 * ProseMirror 装饰器（GhostTrack）与键位接线走 IAB 实机（组件胶水惯例）。
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

vi.mock('../../../services/api/domain', () => ({
  deaiApi: {
    savePair: vi.fn(async () => ({ id: 'p-new', total: 1 })),
    deletePair: vi.fn(async () => ({ deleted: true, total: 0 })),
  },
}))

import { deaiApi } from '../../../services/api/domain'
import {
  decidePairAction,
  flushGhostPairs,
  mapTrackedPositions,
  resetGhostPairs,
  trackAdoptedGhost,
  trackedRangesOf,
  PAIR_BAD_MAX,
} from '../composables/useGhostPairTracker'
import { beginGhost, ghostActionReady, markGhostDone } from '../composables/useGhostDraft'

const api = deaiApi as unknown as {
  savePair: ReturnType<typeof vi.fn>
  deletePair: ReturnType<typeof vi.fn>
}

beforeEach(() => {
  vi.clearAllMocks()
  resetGhostPairs()
})

describe('decidePairAction（纯决策）', () => {
  const bad = '他缓缓抬起头，目光落在远处的山脊上。'

  it('干净采纳（现文与原文一致）→ 跳过不误记', () => {
    expect(decidePairAction(bad, '', bad)).toEqual({ op: 'skip' })
  })

  it('有改动 → 提交（good=现文）', () => {
    const out = decidePairAction(bad, '', '他抬起头，望向远处的山脊。')
    expect(out).toEqual({ op: 'submit', good: '他抬起头，望向远处的山脊。' })
  })

  it('与上次已提交版一致（无新改动）→ 跳过', () => {
    const good = '他抬起头，望向山脊。'
    expect(decidePairAction(bad, good, good)).toEqual({ op: 'skip' })
  })

  it('塌缩为零宽（整段删光=完全否决）→ 不成对', () => {
    expect(decidePairAction(bad, '', '')).toEqual({ op: 'skip' })
  })

  it('bad 超 100 字契约窗 → 拒绝（一期只收短稿）', () => {
    expect(decidePairAction('长'.repeat(PAIR_BAD_MAX + 1), '', '改后')).toEqual({ op: 'reject' })
  })

  it('good 超 600 字硬顶 → 拒绝', () => {
    expect(decidePairAction(bad, '', '改'.repeat(601))).toEqual({ op: 'reject' })
  })
})

describe('mapTrackedPositions（书签三形态）', () => {
  it('中间插字 → 尾书签后移，首书签不动', () => {
    trackAdoptedGhost('c1', '幽灵原文', 10, 20)
    mapTrackedPositions({ map: (pos: number, assoc?: number) => pos < 15 ? pos : pos + 5 })
    const [r] = trackedRangesOf('c1')
    expect(r.from).toBe(10)
    expect(r.to).toBe(25)
  })

  it('删句 → 两书签靠拢', () => {
    trackAdoptedGhost('c1', '幽灵原文', 10, 20)
    mapTrackedPositions({ map: (pos: number) => pos < 12 ? pos : Math.max(pos - 4, 12) })
    const [r] = trackedRangesOf('c1')
    expect(r.to).toBeLessThan(20)
    expect(r.to).toBeGreaterThanOrEqual(r.from)
  })

  it('整段删除 → 塌缩为零宽守原地（from==to，不漂走）', () => {
    trackAdoptedGhost('c1', '幽灵原文', 10, 20)
    mapTrackedPositions({ map: () => 10 })
    const [r] = trackedRangesOf('c1')
    expect(r.from).toBe(10)
    expect(r.to).toBe(10)
  })

  it('只跟踪本章书签（跨章隔离）', () => {
    trackAdoptedGhost('c1', '幽灵原文', 10, 20)
    expect(trackedRangesOf('c2')).toEqual([])
    expect(trackedRangesOf('c1')).toHaveLength(1)
  })

  it('超窗 bad（>100 字）不入跟踪', () => {
    trackAdoptedGhost('c1', '长'.repeat(PAIR_BAD_MAX + 1), 10, 20)
    expect(trackedRangesOf('c1')).toEqual([])
  })
})

describe('flushGhostPairs（成对提交与覆盖语义）', () => {
  afterEach(() => {
    vi.useRealTimers()
  })

  it('有改动 → POST（source=auto_ghost）；再改 → POST 新对 + DELETE 旧对', async () => {
    trackAdoptedGhost('c1', 'AI 原句', 10, 20)
    // 第一次冲账：现文已改
    let text = '作者改定的句子'
    let ids = await flushGhostPairs('c1', 'b1', () => text)
    expect(ids).toEqual(['p-new'])
    expect(api.savePair).toHaveBeenCalledWith({
      bad: 'AI 原句', good: '作者改定的句子', book_id: 'b1', chapter_id: 'c1', source: 'auto_ghost',
    })
    expect(api.deletePair).not.toHaveBeenCalled()

    // 第二次冲账：又改了 → 覆盖（新 POST + 删旧对，同一幽灵只留最新版）
    text = '作者再改的句子'
    ids = await flushGhostPairs('c1', 'b1', () => text)
    expect(ids).toEqual(['p-new'])
    expect(api.deletePair).toHaveBeenCalledWith('p-new')

    // 干净再冲账（无新改动）→ 不再提交
    await flushGhostPairs('c1', 'b1', () => text)
    expect(api.savePair).toHaveBeenCalledTimes(2)
  })

  it('干净采纳全程零提交', async () => {
    trackAdoptedGhost('c1', '原样', 10, 20)
    const ids = await flushGhostPairs('c1', 'b1', () => '原样')
    expect(ids).toEqual([])
    expect(api.savePair).not.toHaveBeenCalled()
  })

  it('final=true 清账（书签寿命=章节会话）', async () => {
    trackAdoptedGhost('c1', 'AI 原句', 10, 20)
    await flushGhostPairs('c1', 'b1', () => '改定', true)
    expect(trackedRangesOf('c1')).toEqual([])
  })

  it('提交失败静默（书签保留，下轮再试）', async () => {
    api.savePair.mockRejectedValueOnce(new Error('network'))
    trackAdoptedGhost('c1', 'AI 原句', 10, 20)
    const ids = await flushGhostPairs('c1', 'b1', () => '改定')
    expect(ids).toEqual([])
    expect(trackedRangesOf('c1')).toHaveLength(1)
  })
})

describe('ghostActionReady（三键上膛判定）', () => {
  afterEach(() => {
    vi.useRealTimers()
  })

  it('流式中恒未上膛（只打断不采纳；判据=ghostStreaming 而非旧 stitching）', () => {
    beginGhost('stitch')  // begin 起 ghostStreaming（无编辑器时只置状态，安全）
    expect(ghostActionReady()).toBe(false)
  })

  it('GHOST_DONE 后缓冲窗内未上膛，窗外上膛', () => {
    vi.useFakeTimers()
    beginGhost('stitch')
    markGhostDone()  // GHOST_DONE：关流式 + 开缓冲窗
    expect(ghostActionReady()).toBe(false)  // 缓冲窗内（防生成延迟期误触）
    vi.advanceTimersByTime(500)
    expect(ghostActionReady()).toBe(true)
  })
})
