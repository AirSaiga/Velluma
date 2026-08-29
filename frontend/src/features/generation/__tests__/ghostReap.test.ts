/**
 * 幽灵死亡收割测试（2026-08-29 手动删除事故护栏）。
 *
 * 事故：作者 Space 生成幽灵后用退格亲手删光幽灵文本（而非 Esc 蒸发）——
 * 文档里 ghostDraft 节点没了，ghostActive 仍为真 → 僵尸态吃 Tab（结构闸
 * 「ghostActive 只吞不唤」）、禁 Space（spaceActive 判 !ghostActive）、卡
 * authorLane 在 ghostStitching、sticky 卡舱恢复等不到落沿。reapGhostIfDead
 * 由编辑器 onUpdate 在每个文档事务后调用：状态说有幽灵而文档扫不到即收尾。
 *
 * node 环境（无 jsdom）：collabEventBus 桩掉（真实实现走 window）。
 */
import { describe, it, expect, beforeEach, vi } from 'vitest'

vi.mock('../../../composables/collabEventBus', () => ({
  dispatchCollabEvent: vi.fn(),
}))

import { dispatchCollabEvent } from '../../../composables/collabEventBus'
import {
  ghostActive,
  ghostWarnings,
  beginGhost,
  setGhostWarnings,
  reapGhostIfDead,
} from '../composables/useGhostDraft'
import { chapterEditorHandle } from '../../chapter-editor/editorHandle'

const ghostMark = { type: { name: 'ghostDraft' } }

/** 最小编辑器替身：findGhostRange 只消费 state.doc.descendants + marks。 */
function mockEditor(withGhost: boolean) {
  const base = { isText: true, nodeSize: 4 }
  const nodes = withGhost ? [{ ...base, marks: [ghostMark] }] : [{ ...base, marks: [] }]
  return {
    state: {
      doc: {
        descendants(cb: (node: any, pos: number) => void) {
          nodes.forEach((n, i) => cb(n, i * 4))
          return true
        },
      },
      selection: { $from: { pos: 2, start: () => 0, end: () => 3 } },
    },
    view: { coordsAtPos: () => ({ top: 0, bottom: 10, left: 10 }) },
  } as any
}

beforeEach(() => {
  vi.mocked(dispatchCollabEvent).mockClear()
  chapterEditorHandle.value = mockEditor(false)
  ghostActive.value = false
})

describe('reapGhostIfDead（幽灵死亡收割）', () => {
  it('作者删光幽灵（文档无 ghostDraft 节点）→ 状态收尾 + 埋 ghost_discard', () => {
    beginGhost('stitch')
    setGhostWarnings([{ kind: 'dead_speak', span_text: 'x', message: 'y' }] as any)
    expect(ghostActive.value).toBe(true)

    // 作者退格删光幽灵文本——文档已无带 mark 的节点
    chapterEditorHandle.value = mockEditor(false)
    reapGhostIfDead()

    expect(ghostActive.value).toBe(false)           // 僵尸态解除（Tab/Space 复活）
    expect(ghostWarnings.value).toHaveLength(0)      // 生命周期字段全重置
    const kinds = vi.mocked(dispatchCollabEvent).mock.calls.map((c) => c[0])
    expect(kinds).toContain('ghost_discard')          // 作者亲手蒸发也计入学习回流
    expect(kinds).not.toContain('ghost_discard_reason') // 不弹理由 toast 问第二遍
  })

  it('幽灵还在（部分删除/改词，mark 存活）→ 不动（走 ghostDirty 微调语义）', () => {
    beginGhost('stitch')
    chapterEditorHandle.value = mockEditor(true)
    reapGhostIfDead()
    expect(ghostActive.value).toBe(true)
    expect(dispatchCollabEvent).not.toHaveBeenCalled()
  })

  it('无幽灵时 no-op（零事件零误伤）', () => {
    reapGhostIfDead()
    expect(ghostActive.value).toBe(false)
    expect(dispatchCollabEvent).not.toHaveBeenCalled()
  })

  it('收割后可立即开新幽灵（状态机无残锁）', () => {
    beginGhost('stitch')
    chapterEditorHandle.value = mockEditor(false)
    reapGhostIfDead()
    beginGhost('stitch')                           // 紧接着再按 Space
    expect(ghostActive.value).toBe(true)
  })
})
