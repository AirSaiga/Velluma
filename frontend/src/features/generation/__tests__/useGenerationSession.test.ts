/**
 * useGenerationSession.loadForChapter 快照恢复归正的回归测试。
 *
 * 事故背景：confirmRefinery 失败会把 stage='error' 持久化进 localStorage 快照，
 * 恢复时 error 被当终态原样还原——但错误原文不持久化（error.value 恒恢复为 null），
 * 消费 error 态的 Overlay/Stepper 错误卡已随步进 UI 删除，唯一可见后果是顶栏长期
 * 挂一句无因由的「生成失败」（WorkspaceView nleStateLabel），还挡住「启动精修」
 * 按钮（要求 stage='done'）。修复：error 与中断态同归正（有正文→done，无正文→idle）。
 */
import { describe, it, expect, beforeEach } from 'vitest'
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
    streamText: '',
    ...overrides,
  }))
}

describe('useGenerationSession.loadForChapter 快照恢复', () => {
  beforeEach(() => {
    // node 环境无 localStorage；被测模块以裸标识符引用（调用时解析全局），挂内存桩即可
    ;(globalThis as Record<string, unknown>).localStorage = new LocalStorageMock()
  })

  it('error 快照（无正文）归正为 idle，不再原样恢复', () => {
    seedSnapshot('ch-1', { stage: 'error', streamText: '' })
    const session = useGenerationSession()
    session.loadForChapter('ch-1')
    expect(session.stage.value).toBe('idle')
    expect(session.error.value).toBeNull()
    expect(session.generating.value).toBe(false)
  })

  it('error 快照（有残留正文）归正为 done，与中断态同规则', () => {
    seedSnapshot('ch-2', { stage: 'error', streamText: '未完成的抛光残文……' })
    const session = useGenerationSession()
    session.loadForChapter('ch-2')
    expect(session.stage.value).toBe('done')
    expect(session.error.value).toBeNull()
  })

  it('done 快照原样恢复（既有契约不变）', () => {
    seedSnapshot('ch-3', { stage: 'done', streamText: '完稿正文' })
    const session = useGenerationSession()
    session.loadForChapter('ch-3')
    expect(session.stage.value).toBe('done')
  })

  it('无快照重置为干净 idle', () => {
    const session = useGenerationSession()
    session.loadForChapter('ch-never')
    expect(session.stage.value).toBe('idle')
  })
})
