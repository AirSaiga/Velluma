import { describe, expect, it, vi, beforeEach } from 'vitest'
import { ref } from 'vue'

// 四路 API mock（useStoryline 的契约面：字段映射 + 降级 + 过期守卫）
// spine 走书级批量（2026-09-17 前 mock 逐章 getSpine）：批量只返回非空章；
// getSpine 保留 mock 供「新建章增量补拉」路径。
vi.mock('../../../../services/api/domain/adaptive.api', () => ({
  adaptiveApi: {
    getSpinesByBook: vi.fn(async (bookId: string) => ({
      book_id: bookId,
      spines: { c1: { intent: { text: '逃出矿镇' }, anchors: [] } },
    })),
    getSpine: vi.fn(async (id: string) => {
      if (id === 'boom') throw new Error('network')
      return { spine: id === 'c1' ? { intent: { text: '逃出矿镇' }, anchors: [] } : null }
    }),
  },
}))

vi.mock('../../../../services/api/domain', () => ({
  plotLedgerApi: {
    listByBook: vi.fn(async (bookId: string) => [
      {
        id: 'l1',
        book_id: bookId,
        ledger_key: 'k1',
        entry_type: 'foreshadow',
        content: '断剑',
        status: 'open',
        created_at_chapter: 1,
        resolved_in_chapter_id: null,
      },
      {
        id: 'l2',
        book_id: bookId,
        ledger_key: 'k2',
        entry_type: 'foreshadow',
        content: '旧约',
        status: 'closed',
        created_at_chapter: 2,
        resolved_in_chapter_id: 'c3',
      },
      {
        id: 'l3',
        book_id: bookId,
        ledger_key: 'k3',
        entry_type: 'foreshadow',
        content: '废弃',
        status: 'dropped',
        created_at_chapter: 1,
        resolved_in_chapter_id: null,
      },
    ]),
  },
}))

vi.mock('../../../../services/api/domain/reader-mirror.api', () => ({
  readerMirrorApi: {
    get: vi.fn(async () => ({
      expectations: [],
      tension_curve: [
        { chapter_number: 1, overall_tension: 3 },
        { chapter_number: 2, overall_tension: 12, is_payoff_chapter: true },
      ],
      information_asymmetries: [],
    })),
  },
}))

vi.mock('../../../../services/api/domain/canon.api', () => ({
  canonApi: {
    listNodes: vi.fn(async () => [
      { label: '身世', visibility: 'secret', expected_reveal_chapter: 5 },
      { label: '公开', visibility: 'public', expected_reveal_chapter: 5 },
    ]),
  },
}))

import { useStoryline } from '../useStoryline'

async function flushAsync() {
  // 四路 Promise.all + 逐项 catch 都在微任务里，多轮 flush 保证收敛
  for (let i = 0; i < 8; i++) await Promise.resolve()
  await new Promise((r) => setTimeout(r, 0))
}

describe('useStoryline', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('伏笔账本字段映射：created_at_chapter → plantedChapter（dropped 保留由引擎层剔除）', async () => {
    const bookId = ref<string | null>('b1')
    const ids = ref(['c1', 'c2', 'c3'])
    const s = useStoryline(bookId, ids)
    await flushAsync()
    expect(s.ledgers.value).toEqual([
      { id: 'l1', content: '断剑', status: 'open', plantedChapter: 1, resolvedChapterId: null },
      { id: 'l2', content: '旧约', status: 'closed', plantedChapter: 2, resolvedChapterId: 'c3' },
      { id: 'l3', content: '废弃', status: 'dropped', plantedChapter: 1, resolvedChapterId: null },
    ])
  })

  it('spine 批量拉取（无 spine 章缺席，消费侧 ?? null）+ 张力样本透传 + 真相分组只收非公开', async () => {
    const bookId = ref<string | null>('b1')
    const ids = ref(['c1', 'boom', 'c3'])
    const s = useStoryline(bookId, ids)
    await flushAsync()
    expect(s.spines.value['c1']).toEqual({ intent: { text: '逃出矿镇' }, anchors: [] })
    expect(s.spines.value['boom']).toBeUndefined()  // 批量端点不返回无 spine 章
    expect(s.spines.value['c3']).toBeUndefined()
    expect(s.tensionSamples.value).toHaveLength(2)
    expect(s.reveals.value.get(5)).toEqual(['身世'])
  })

  it('spine 批量端点失败 → 降级空映射（不牵连账本/张力/真相）', async () => {
    const { adaptiveApi } = await import('../../../../services/api/domain/adaptive.api')
    vi.mocked(adaptiveApi.getSpinesByBook).mockRejectedValueOnce(new Error('network'))
    const bookId = ref<string | null>('b1')
    const ids = ref(['c1'])
    const s = useStoryline(bookId, ids)
    await flushAsync()
    expect(s.spines.value).toEqual({})
    expect(s.ledgers.value).toHaveLength(3)
  })

  it('bookId 置空清仓', async () => {
    const bookId = ref<string | null>('b1')
    const ids = ref<string[]>([])
    const s = useStoryline(bookId, ids)
    await flushAsync()
    bookId.value = null
    await flushAsync()
    expect(s.ledgers.value).toEqual([])
    expect(s.spines.value).toEqual({})
  })
})
