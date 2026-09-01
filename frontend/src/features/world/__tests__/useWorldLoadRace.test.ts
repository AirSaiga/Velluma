/**
 * useWorld.load 过期响应守卫锁（2026-09-01 页面逻辑审查）。
 *
 * 背景：快速切书时两次 load 并发，旧书的响应若后到会整包覆盖新书画面
 * （地点/事件/实体/时间轴视野全串书）。修复 = await 后校验「本请求仍是
 * 当前书」，过期整包丢弃（与心跳章节纪元守卫同款语义）。
 * 注意：被测模块在顶层给 window 挂 pagehide 监听、经 services/api 间接拉起
 * transport——node 环境须在 import 前就绪 window 桩（vi.hoisted 先于 import 执行）。
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'

const { locDeferreds } = vi.hoisted(() => ({
  locDeferreds: new Map<string, (v: any[]) => void>(),
}))

vi.hoisted(() => {
  ;(globalThis as Record<string, unknown>).window = {
    addEventListener: () => {},
    dispatchEvent: () => {},
  }
  ;(globalThis as Record<string, unknown>).localStorage = {
    getItem: () => null, setItem: () => {}, removeItem: () => {}, clear: () => {},
  }
})

vi.mock('../../../services/api', () => ({
  worldApi: {
    listLocations: (bookId: string) => new Promise((res) => locDeferreds.set(bookId, res)),
    listEvents: () => Promise.resolve([]),
    listEntities: () => Promise.resolve([]),
    listRelations: () => Promise.resolve([]),
    listChapterAnchors: () => Promise.resolve([]),
    listMapLayers: () => Promise.resolve([]),
    listMapStrokes: () => Promise.resolve([]),
    getTimelineView: () => Promise.resolve({}),
    patchTimelineView: () => Promise.resolve({}),
  },
  plotLedgerApi: { listByBook: () => Promise.resolve([]) },
}))

import { useWorld } from '../composables/useWorld'

function release(bookId: string, locs: any[]) {
  locDeferreds.get(bookId)!(locs)
}

describe('useWorld.load 过期响应守卫', () => {
  beforeEach(() => {
    locDeferreds.clear()
    vi.clearAllMocks()
  })

  it('旧书响应后到被丢弃，新书数据不被覆盖', async () => {
    const w = useWorld()
    const loadA = w.load('bookA')
    const loadB = w.load('bookB')
    // B 先回：新书数据落地
    release('bookB', [{ id: 'b-loc', name: 'B书地点' }])
    await loadB
    expect(w.locations.value.map((l) => l.id)).toEqual(['b-loc'])
    // A 后回：过期响应必须整包丢弃
    release('bookA', [{ id: 'a-loc', name: 'A书地点' }])
    await loadA
    expect(w.locations.value.map((l) => l.id)).toEqual(['b-loc'])
    expect(w.loadedBookId.value).toBe('bookB')
  })

  it('无并发时正常落地（守卫不误杀）', async () => {
    const w = useWorld()
    const p = w.load('bookC')
    release('bookC', [{ id: 'c-loc', name: 'C书地点' }])
    await p
    expect(w.locations.value.map((l) => l.id)).toEqual(['c-loc'])
  })
})
