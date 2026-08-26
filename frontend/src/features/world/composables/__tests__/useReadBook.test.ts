/**
 * 全书通读向导·阶段 B 跳过计账（2026-08-26 审计修复）。
 *
 * 事故：runEvents 曾把 autoRead 的 skipped 响应整个丢弃——额度用完/间隔未到
 * 时完成页谎报「读完了、0 条」。锁行为：显式 skipped 计入 skippedCount；
 * 网络失败维持不计（与阶段 A catch 口径一致）。
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
vi.mock('../../../../services/api/domain/world.api', () => ({ worldApi: { listEntities: vi.fn() } }))

const chapter = (id: string, n: number) => ({
  id, chapter_number: n, title: `第${n}章`, content_text: 'x'.repeat(150),
})

describe('通读向导阶段 B 跳过计账', () => {
  it('ran=false 且带 skipped 的章计入 skippedCount，不再静默丢弃', async () => {
    vi.mocked(chapterApi.getAll).mockResolvedValue([chapter('c1', 1), chapter('c2', 2)])
    vi.mocked(adaptiveApi.autoRead)
      .mockResolvedValueOnce({ ran: true, created: 3 })
      .mockResolvedValueOnce({ ran: false, skipped: { code: 'daily_cap', reason: '今天的自动阅读额度用完了' } })

    const rb = useReadBook()
    await rb.runEvents('b1')

    expect(rb.phase.value).toBe('done')
    expect(rb.createdCandidates.value).toBe(3)
    expect(rb.skippedCount.value).toBe(1)
  })

  it('ran=false 但无 skipped 原因（如 no_chapter）同样计账', async () => {
    vi.mocked(chapterApi.getAll).mockResolvedValue([chapter('c1', 1)])
    vi.mocked(adaptiveApi.autoRead)
      .mockResolvedValueOnce({ ran: false, skipped: { code: 'no_chapter', reason: '章节不存在' } })

    const rb = useReadBook()
    await rb.runEvents('b1')

    expect(rb.skippedCount.value).toBe(1)
    expect(rb.createdCandidates.value).toBe(0)
  })

  it('网络失败不冒泡也不计跳过（单章失败不阻塞整批，语义保持）', async () => {
    vi.mocked(chapterApi.getAll).mockResolvedValue([chapter('c1', 1)])
    vi.mocked(adaptiveApi.autoRead).mockRejectedValue(new Error('network'))

    const rb = useReadBook()
    await rb.runEvents('b1')

    expect(rb.phase.value).toBe('done')
    expect(rb.skippedCount.value).toBe(0)
  })
})
