/**
 * useGenerationSession.loadForChapter 快照恢复归正的回归测试。
 *
 * 【2026-09-12 写后检查收敛批更新】Refinery 退役后 stage 的 done/refining/error
 * 写入点全部消失，快照恢复统一归正 idle（旧快照可能存着 done/error——其产物
 * 字段 streamText/refinery* 已随本批退役，原样恢复只会显示假状态）。本文件
 * 原有的「切章中止在飞诊断 SSE」用例随 startRefinery/confirmRefinery 一并退役
 * （stitch 的同类风险由独立的 _staleEpoch 章节纪元守卫防护，见 useAdaptiveAssist）。
 */
import { describe, it, expect, beforeEach, vi } from 'vitest'

vi.mock('../../../services/api/domain', () => ({
  chapterApi: { defatSelection: vi.fn() },
}))
import { useGenerationSession } from '../composables/useGenerationSession'

const storageKey = (chapterId: string) => `velluma:gensess:${chapterId}`

class LocalStorageMock {
  private store = new Map<string, string>()
  getItem(key: string): string | null { return this.store.has(key) ? this.store.get(key)! : null }
  setItem(key: string, value: string) { this.store.set(key, String(value)) }
  removeItem(key: string) { this.store.delete(key) }
  clear() { this.store.clear() }
  key(index: number): string | null { return [...this.store.keys()][index] ?? null }
  get length() { return this.store.size }
}

function seedSnapshot(chapterId: string, overrides: Record<string, unknown>) {
  localStorage.setItem(storageKey(chapterId), JSON.stringify({
    v: 1,
    chapterId,
    savedAt: Date.now(),
    engine: 'v3.2',
    stage: 'idle',
    // 旧版本快照可能带 streamText/refinery* 字段——恢复侧必须静默忽略（字段已退役）
    streamText: '旧版残留的抛光正文……',
    ...overrides,
  }))
}

describe('useGenerationSession.loadForChapter 快照恢复（Refinery 退役后契约）', () => {
  beforeEach(() => {
    // node 环境无 localStorage；被测模块以裸标识符引用（调用时解析全局），挂内存桩即可
    ;(globalThis as Record<string, unknown>).localStorage = new LocalStorageMock()
  })

  it('error 快照归正为 idle，不再原样恢复', () => {
    seedSnapshot('ch-1', { stage: 'error' })
    const session = useGenerationSession()
    session.loadForChapter('ch-1')
    expect(session.stage.value).toBe('idle')
    expect(session.error.value).toBeNull()
    expect(session.generating.value).toBe(false)
  })

  it('done 快照（Refinery 时代遗产）同样归正为 idle——产物字段已退役，恢复成 done 只会显示假状态', () => {
    seedSnapshot('ch-2', { stage: 'done', streamText: '完稿正文' })
    const session = useGenerationSession()
    session.loadForChapter('ch-2')
    expect(session.stage.value).toBe('idle')
  })

  it('无快照重置为干净 idle', () => {
    const session = useGenerationSession()
    session.loadForChapter('ch-never')
    expect(session.stage.value).toBe('idle')
  })

  it('切换章节：旧章状态持久化、新章恢复（currentChapterId 绑定语义不变）', () => {
    seedSnapshot('chapterA', { stage: 'idle' })
    const session = useGenerationSession()
    session.loadForChapter('chapterA')
    // 切到无快照的新章：不抛错、归 idle
    session.loadForChapter('chapterB')
    expect(session.stage.value).toBe('idle')
    // 切回有旧快照的章：照常恢复（idle 契约）
    session.loadForChapter('chapterA')
    expect(session.stage.value).toBe('idle')
  })
})
