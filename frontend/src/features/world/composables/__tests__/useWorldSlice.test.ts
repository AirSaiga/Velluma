/**
 * useWorldSlice 候选竞态守卫（2026-09-17 补齐，与 load 的 slice 守卫同口径）：
 * 切章途中旧章的 candidates 响应落地不得覆盖新章候选。
 *
 * 世界域首个 api mock harness（batchAccept 注释曾记「无 api mock harness」——
 * 本文件用 vi.mock 桩 worldApi 打破此例，仅桩本测试消费的方法）。
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'

vi.mock('../../../../services/api/domain/world.api', () => ({
  worldApi: {
    getSceneSlice: vi.fn(),
    listCandidates: vi.fn(),
    setChapterAnchor: vi.fn(),
    setScenePin: vi.fn(),
    acceptCandidate: vi.fn(),
    rejectCandidate: vi.fn(),
    deleteEvent: vi.fn(),
    reopenCandidate: vi.fn(),
    undoAcceptCandidate: vi.fn(),
  },
}))

import { worldApi } from '../../../../services/api/domain/world.api'
import { useWorldSlice } from '../useWorldSlice'

// attachListeners 直接调 window.addEventListener（无 typeof 守卫），node 环境挂内存桩
;(globalThis as Record<string, unknown>).window = new EventTarget()

const api = worldApi as unknown as {
  getSceneSlice: ReturnType<typeof vi.fn>
  listCandidates: ReturnType<typeof vi.fn>
}

function sliceOf(t: number) {
  return {
    t,
    t_source: 'zero',
    presence: [],
    scene: null,
    foreshadows: [],
    expectations: [],
    version: { events: 0, updated_at: null },
  }
}

function deferred<T>() {
  let resolve!: (v: T) => void
  let reject!: (e: unknown) => void
  const promise = new Promise<T>((res, rej) => {
    resolve = res
    reject = rej
  })
  return { promise, resolve, reject }
}

describe('useWorldSlice candidates 竞态守卫', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    api.getSceneSlice.mockImplementation((_b: string, ch: string) =>
      Promise.resolve(sliceOf(ch === 'ch1' ? 1 : 2)),
    )
  })

  it('切章途中旧章候选响应落地不覆盖新章候选', async () => {
    const c1 = deferred<unknown[]>()
    const c2 = deferred<unknown[]>()
    api.listCandidates.mockImplementation((_b: string, ch: string) =>
      ch === 'ch1' ? c1.promise : c2.promise,
    )
    const { load, candidates } = useWorldSlice()

    const p1 = load('b1', 'ch1')
    const p2 = load('b1', 'ch2')
    c2.resolve([{ id: 'new-chapter-candidate' }])
    await p2
    expect(candidates.value).toEqual([{ id: 'new-chapter-candidate' }])

    // 旧章响应迟到——守卫命中，不得落地
    c1.resolve([{ id: 'stale-candidate' }])
    await p1
    expect(candidates.value).toEqual([{ id: 'new-chapter-candidate' }])
  })

  it('同章候选响应正常落地（守卫不误伤在章响应）', async () => {
    const c1 = deferred<unknown[]>()
    api.listCandidates.mockImplementation(() => c1.promise)
    const { load, candidates } = useWorldSlice()

    const p = load('b1', 'ch1')
    c1.resolve([{ id: 'current-candidate' }])
    await p
    expect(candidates.value).toEqual([{ id: 'current-candidate' }])
  })

  it('旧章候选请求失败不清空新章候选（catch 同样过守卫）', async () => {
    const c1 = deferred<unknown[]>()
    const c2 = deferred<unknown[]>()
    // 原 promise 预挂空捕获（防 unhandled 噪音）；loadCandidates 的 await 仍收到拒绝
    void c1.promise.catch(() => {})
    api.listCandidates.mockImplementation((_b: string, ch: string) =>
      ch === 'ch1' ? c1.promise : c2.promise,
    )
    const { load, candidates } = useWorldSlice()

    const p1 = load('b1', 'ch1')
    const p2 = load('b1', 'ch2')
    c2.resolve([{ id: 'kept' }])
    await p2
    // 旧章请求在新章候选落地之后才失败——无守卫时 catch 会把 candidates 清成 []
    c1.reject(new Error('network'))
    await p1
    expect(candidates.value).toEqual([{ id: 'kept' }])
  })
})
