import { beforeEach, describe, expect, it, vi } from 'vitest'

/**
 * node 环境无 localStorage——useUiPrefs 模块级（openingCardEnabled 初始化）
 * 就读存储，stub 必须先于动态 import。渐进提示是模块级单例缓存：
 * 每用例 resetModules + 动态 import 取全新实例（同 useEscStack.test.ts 惯例）。
 */
function stubLocalStorage() {
  const store: Record<string, string> = {}
  vi.stubGlobal('localStorage', {
    getItem: vi.fn((k: string) => store[k] ?? null),
    setItem: vi.fn((k: string, v: string) => { store[k] = v }),
    removeItem: vi.fn((k: string) => { delete store[k] }),
  })
  return () => store
}

let dump: () => Record<string, string>

beforeEach(() => {
  vi.resetModules()
  dump = stubLocalStorage()
})

describe('useProgressiveHint', () => {
  it('初始可见；markSeen 递增，达到 maxShows 后不可见并持久化', async () => {
    const { useProgressiveHint } = await import('../useProgressiveHint')
    const h = useProgressiveHint('t_ghost', 2)
    expect(h.visible.value).toBe(true)
    h.markSeen()
    expect(h.seenCount.value).toBe(1)
    expect(h.visible.value).toBe(true)
    h.markSeen()
    expect(h.seenCount.value).toBe(2)
    expect(h.visible.value).toBe(false)
    // 持久化进 velluma_ui_prefs_v1.hintsSeen
    const saved = JSON.parse(dump()['velluma_ui_prefs_v1'])
    expect(saved.hintsSeen.t_ghost).toBe(2)
  })

  it('次数跨会话读回：预置 hintsSeen=3 的新实例直接不可见', async () => {
    const { saveUiPrefs } = await import('../useUiPrefs')
    saveUiPrefs({ ...(await import('../useUiPrefs')).loadUiPrefs(), hintsSeen: { t_old: 3 } })
    vi.resetModules()
    const { useProgressiveHint } = await import('../useProgressiveHint')
    const h = useProgressiveHint('t_old', 3)
    expect(h.visible.value).toBe(false)
    expect(h.seenCount.value).toBe(3)
  })

  it('同一 key 多处消费共享同一实例（缓存防漂移）', async () => {
    const { useProgressiveHint } = await import('../useProgressiveHint')
    const a = useProgressiveHint('t_shared')
    const b = useProgressiveHint('t_shared')
    expect(b).toBe(a)
    a.markSeen()
    expect(b.seenCount.value).toBe(1)
  })
})
