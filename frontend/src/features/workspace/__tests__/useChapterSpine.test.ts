/**
 * useChapterSpine 切章竞态与保存契约单测（纯逻辑，mock adaptiveApi，不依赖网络）。
 *
 * 覆盖的修复：
 * 1. 切章竞态——load/unload **冲刷**在途防抖保存到旧章（2026-09-01 丢稿修复：
 *    旧语义直接丢弃 <2s 在途编辑，GUI 实测丢稿）+ 定时器回调章 id 兜底
 *    （A 章 spine 不误写到 B 章）；
 * 2. save 回包快照比对——PATCH 往返期间的在途编辑不被服务器整包回滚；
 * 3. removeAnchor 删空主动清库——watcher 对 null 早退的死路径不再吞掉清空；
 * 4. 防抖保存 422 静默——watcher 调用点 .catch(() => {})，无 unhandled rejection
 *    （测试进程未被 rejection 炸掉本身即是通过条件）。
 */
import { nextTick } from 'vue'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { adaptiveApi } from '../../../services/api/domain/adaptive.api'
import type { ChapterSpine } from '../../../services/api/domain/adaptive.api'
import { logCollabEvent } from '../../../composables/useCollabTelemetry'
import { spine, useChapterSpine } from '../composables/useChapterSpine'

vi.mock('../../../services/api/domain/adaptive.api', () => ({
  adaptiveApi: {
    getSpine: vi.fn(),
    patchSpine: vi.fn(),
    spineSuggest: vi.fn(),
  },
}))
// 协作埋点 mock 成 no-op（真实实现写本地 jsonl，单测不应碰盘）
vi.mock('../../../composables/useCollabTelemetry', () => ({
  logCollabEvent: vi.fn(),
}))

// 模块级单例：只调用一次激活共享 watcher（重复调用会叠加 watcher）
const api = useChapterSpine()

describe('useChapterSpine 切章竞态与保存契约', () => {
  beforeEach(() => {
    vi.mocked(adaptiveApi.getSpine).mockResolvedValue({ spine: null })
    vi.mocked(adaptiveApi.patchSpine).mockResolvedValue({ spine: null })
  })

  afterEach(() => {
    api.unload() // 清模块级单例状态（含在途定时器）
    vi.clearAllMocks()
    vi.useRealTimers()
  })

  it('对照组：未切章时 2s 防抖保存正常落地（防测试空洞）', async () => {
    vi.useFakeTimers()
    await api.load('chapterA')
    api.addAnchor('唯一锚')
    await nextTick() // 等深 watcher 排程出定时器
    await vi.advanceTimersByTimeAsync(2000)
    expect(adaptiveApi.patchSpine).toHaveBeenCalledTimes(1)
    expect(adaptiveApi.patchSpine).toHaveBeenCalledWith(
      'chapterA',
      expect.objectContaining({ anchors: [expect.objectContaining({ text: '唯一锚' })] }),
    )
  })

  it('切章冲刷（load）：A 章在途编辑立即落库且不误写 B 章', async () => {
    vi.useFakeTimers()
    await api.load('chapterA')
    api.addAnchor('A 章锚点')
    await nextTick() // 定时器已挂（闭包携带 chapterA 的 spine）
    await api.load('chapterB') // 切章——冲刷在途防抖到 A 章（丢稿修复）
    expect(adaptiveApi.patchSpine).toHaveBeenCalledTimes(1)
    expect(adaptiveApi.patchSpine).toHaveBeenCalledWith(
      'chapterA',
      expect.objectContaining({ anchors: [expect.objectContaining({ text: 'A 章锚点' })] }),
    )
    await vi.advanceTimersByTimeAsync(2000)
    expect(adaptiveApi.patchSpine).toHaveBeenCalledTimes(1) // 旧回调闭包不再补一发 B 章写入
  })

  it('卸载冲刷（unload）：setIntent 在途编辑不再被丢弃', async () => {
    vi.useFakeTimers()
    await api.load('chapterA')
    api.setIntent('写完这段就收尾')
    await nextTick()
    api.unload() // 离开写作页——冲刷而非丢弃
    expect(adaptiveApi.patchSpine).toHaveBeenCalledWith(
      'chapterA',
      expect.objectContaining({ intent: { text: '写完这段就收尾', source: 'author' } }),
    )
    await vi.advanceTimersByTimeAsync(2000)
    expect(adaptiveApi.patchSpine).toHaveBeenCalledTimes(1)
  })

  it('save 回包快照比对：PATCH 往返期间的在途编辑不被回滚', async () => {
    vi.useFakeTimers()
    await api.load('chapterA')
    let resolvePatch!: (v: { spine: ChapterSpine | null }) => void
    vi.mocked(adaptiveApi.patchSpine).mockImplementationOnce(
      () => new Promise((res) => { resolvePatch = res }),
    )
    const inflight = api.save({ intent: { text: '旧意图', source: 'author' } })
    // 模拟往返期间本地再次编辑（意图输入 / 心跳回写 hit）
    spine.value = { intent: { text: '在途新编辑', source: 'author' }, anchors: [] }
    resolvePatch({ spine: { intent: { text: '旧意图', source: 'author' } } })
    await inflight
    expect(spine.value?.intent?.text).toBe('在途新编辑')
  })

  it('save 回包：本地未被再次编辑时接受服务器值（含状态同步）', async () => {
    vi.useFakeTimers()
    await api.load('chapterA')
    spine.value = { anchors: [] }
    await nextTick()
    const serverSpine: ChapterSpine = {
      anchors: [{ id: 's1', text: '服务端锚', source: 'author', status: 'hit' }],
    }
    vi.mocked(adaptiveApi.patchSpine).mockResolvedValueOnce({ spine: serverSpine })
    await api.save({ anchors: [] }) // sent 与本地序列化一致 → 接受
    // ref 深层响应式会包 reactive Proxy（引用不同），用深比较断言服务器值已被接受
    expect(spine.value).toStrictEqual(serverSpine)
  })

  it('removeAnchor 删空主动清库：watcher 对 null 早退的死路径不再吞掉清空', async () => {
    vi.useFakeTimers()
    await api.load('chapterA')
    spine.value = { anchors: [{ id: 'a1', text: '唯一', source: 'author', status: 'pending' }] }
    await nextTick()
    await api.removeAnchor('a1')
    expect(adaptiveApi.patchSpine).toHaveBeenCalledWith('chapterA', { anchors: [] })
    expect(spine.value).toBeNull()
  })

  it('防抖保存 422 静默：无 unhandled rejection，本地编辑保留', async () => {
    vi.useFakeTimers()
    const err: any = new Error('锚点已达上限')
    err.status = 422
    vi.mocked(adaptiveApi.patchSpine).mockRejectedValueOnce(err)
    await api.load('chapterA')
    api.addAnchor('锚点')
    await nextTick()
    await vi.advanceTimersByTimeAsync(2000)
    expect(spine.value?.anchors).toHaveLength(1) // 本地不回滚
  })
})
