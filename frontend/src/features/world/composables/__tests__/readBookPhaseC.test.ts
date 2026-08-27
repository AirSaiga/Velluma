/**
 * 全书通读向导·阶段 C 呈现关系回填（世界内核 B4 · 2026-08-28）。
 *
 * 锁行为：
 * 1. runEvents 毕自动接 runDepictions（三阶段保序）；
 * 2. 候选进过目清单（depictions-review），勾选计数正确；
 * 3. 裁决串行调 confirm/reject，计数只涨勾选的；
 * 4. 零候选直接 done（诚实降级，不过目空清单）；
 * 5. 章节列表失败静默跳过阶段 C 不阻塞完成页。
 */
import { describe, it, expect, vi } from 'vitest'
import { useReadBook } from '../useReadBook'
import { chapterApi } from '../../../../services/api/domain'
import { adaptiveApi } from '../../../../services/api/domain/adaptive.api'
import { worldApi } from '../../../../services/api/domain/world.api'

vi.mock('../../../../services/api/domain', () => ({ chapterApi: { getAll: vi.fn() } }))
vi.mock('../../../../services/api/domain/adaptive.api', () => ({
  adaptiveApi: { autoRead: vi.fn(), readEntities: vi.fn() },
}))
vi.mock('../../../../services/api/domain/world.api', () => ({
  worldApi: {
    listEntities: vi.fn(),
    backfillDepictions: vi.fn(),
    confirmDepiction: vi.fn(),
    rejectDepiction: vi.fn(),
  },
}))

const chapter = (id: string, n: number) => ({
  id, chapter_number: n, title: `第${n}章`, content_text: 'x'.repeat(150),
})

describe('通读向导阶段 C（呈现关系回填）', () => {
  it('阶段 B 毕自动接阶段 C：候选进过目清单', async () => {
    vi.mocked(chapterApi.getAll).mockResolvedValue([chapter('c1', 1)])
    vi.mocked(adaptiveApi.autoRead).mockResolvedValue({ ran: true, created: 1 })
    vi.mocked(worldApi.backfillDepictions).mockResolvedValue({
      created: 2,
      candidates: [
        { id: 'd1', subject_id: 'n1', label: '守塔人身份' },
        { id: 'd2', subject_id: 'n2', label: '地下金库' },
      ],
    })

    const rb = useReadBook()
    await rb.runEvents('b1')

    expect(worldApi.backfillDepictions).toHaveBeenCalledWith('b1', 'c1')
    expect(rb.phase.value).toBe('depictions-review')
    expect(rb.depictionCandidates.value).toHaveLength(2)
    expect(rb.depictionCandidates.value[0]).toMatchObject({
      id: 'd1', subjectId: 'n1', label: '守塔人身份', checked: true,
    })
    expect(rb.depictionReviewCount.value).toBe(2)
  })

  it('裁决：勾选 confirm、划掉 reject，计数只涨勾选的', async () => {
    vi.mocked(chapterApi.getAll).mockResolvedValue([chapter('c1', 1)])
    vi.mocked(worldApi.backfillDepictions).mockResolvedValue({
      created: 2,
      candidates: [
        { id: 'd1', subject_id: 'n1', label: 'A' },
        { id: 'd2', subject_id: 'n2', label: 'B' },
      ],
    })
    const rb = useReadBook()
    await rb.runDepictions('b1')
    rb.depictionCandidates.value[1].checked = false // 划掉第二条

    await rb.confirmDepictions('b1')

    expect(worldApi.confirmDepiction).toHaveBeenCalledWith('b1', 'd1')
    expect(worldApi.rejectDepiction).toHaveBeenCalledWith('b1', 'd2')
    expect(rb.confirmedDepictions.value).toBe(1)
    expect(rb.phase.value).toBe('done')
  })

  it('零候选直接 done（诚实降级，不过目空清单）', async () => {
    vi.mocked(chapterApi.getAll).mockResolvedValue([chapter('c1', 1)])
    vi.mocked(worldApi.backfillDepictions).mockResolvedValue({ created: 0, candidates: [] })

    const rb = useReadBook()
    await rb.runDepictions('b1')

    expect(rb.phase.value).toBe('done')
    expect(rb.depictionCandidates.value).toHaveLength(0)
  })

  it('单章 backfill 失败不阻塞整批（下一章继续）', async () => {
    vi.mocked(chapterApi.getAll).mockResolvedValue([chapter('c1', 1), chapter('c2', 2)])
    vi.mocked(worldApi.backfillDepictions)
      .mockRejectedValueOnce(new Error('network'))
      .mockResolvedValueOnce({ created: 1, candidates: [{ id: 'd9', subject_id: 'n9', label: 'X' }] })

    const rb = useReadBook()
    await rb.runDepictions('b1')

    expect(rb.phase.value).toBe('depictions-review')
    expect(rb.depictionCandidates.value).toHaveLength(1)
  })

  it('章节列表失败静默跳过阶段 C（完成页不报错）', async () => {
    vi.mocked(chapterApi.getAll).mockRejectedValue(new Error('network'))

    const rb = useReadBook()
    await rb.runDepictions('b1')

    expect(rb.phase.value).toBe('done')
  })
})
