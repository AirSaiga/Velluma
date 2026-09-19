/**
 * 蒸发找回窗测试（2026-09-19 审计 H1 修复对拍）。
 *
 * 事故：tryReviveGhost 本地重放走 beginGhost（置 ghostStreaming=true）+
 * appendGhost，但不发 SSE——markGhostDone 的唯一调用点在 GHOST_DONE 回调，
 * 永远不会来 → 找回的幽灵被「未灌完不上膛」（ghostActionReady）永久吃键，
 * Tab/Enter 无效，只能再 Esc 丢一次。修复=appendGhost 后补 markGhostDone()。
 *
 * 同根守卫（H2）：abortInflight 打断在飞流后补 markGhostDone（守卫
 * ghostStreaming）——那条在 useAdaptiveAssist 闭包内，装配面重不单测，
 * 机制同此测。node 环境（无 jsdom）：collabEventBus 桩掉（真实实现走 window）。
 */
import { describe, it, expect, beforeEach, vi } from 'vitest'

vi.mock('../../../composables/collabEventBus', () => ({
  dispatchCollabEvent: vi.fn(),
}))

import {
  ghostActive,
  ghostStreaming,
  beginGhost,
  appendGhost,
  evaporateGhost,
  tryReviveGhost,
  ghostActionReady,
} from '../composables/useGhostDraft'
import { chapterEditorHandle } from '../../chapter-editor/editorHandle'

const ghostMark = { type: { name: 'ghostDraft' } }

/** 最小编辑器替身：descendants/findGhostRange + textBetween/chain 全够用。 */
function mockEditor(withGhost: boolean, ghostText = '找回的幽灵') {
  const plain = { isText: true, nodeSize: 4, marks: [], text: '正文。' }
  const marked = { isText: true, nodeSize: 4, marks: [ghostMark], text: ghostText }
  const nodes = withGhost ? [plain, marked] : [plain]
  const chain: any = {
    command: () => chain,
    insertContentAt: () => chain,
    deleteRange: () => chain,
    run: () => {},
  }
  return {
    state: {
      doc: {
        descendants(cb: (node: any, pos: number) => void) {
          nodes.forEach((n, i) => cb(n, i * 4))
          return true
        },
        textBetween: () => (withGhost ? ghostText : ''),
      },
      selection: { $from: { pos: 2, start: () => 0, end: () => 3 } },
    },
    chain: () => chain,
    view: { coordsAtPos: () => ({ top: 0, bottom: 10, left: 10 }) },
  } as any
}

beforeEach(() => {
  chapterEditorHandle.value = mockEditor(false)
  ghostActive.value = false
  ghostStreaming.value = false
})

describe('蒸发找回窗（tryReviveGhost）', () => {
  it('窗内重按触发键：本地重放后流式标志关闭，缓冲窗过后续写可用', () => {
    chapterEditorHandle.value = mockEditor(true, '他推门进来')
    beginGhost('stitch')
    appendGhost('，带进一身寒气')
    expect(ghostStreaming.value).toBe(true)

    evaporateGhost() // Esc 蒸发 → 记入找回窗
    expect(ghostActive.value).toBe(false)

    expect(tryReviveGhost()).toBe(true)
    expect(ghostActive.value).toBe(true)
    // 修复点：重放不走 SSE，无人关流式标志 → 三键永久吃键（H1）
    expect(ghostStreaming.value).toBe(false)
    // 灌完缓冲窗内不上膛（防误触）→ 窗后上膛（Tab/Enter 恢复可用）
    expect(ghostActionReady()).toBe(false)
    const now = Date.now()
    vi.spyOn(Date, 'now').mockReturnValue(now + 401)
    expect(ghostActionReady()).toBe(true)
    vi.restoreAllMocks()
  })

  it('找回一次性消费：再按不再重现', () => {
    chapterEditorHandle.value = mockEditor(true, '窗内只有一枚')
    beginGhost('stitch')
    evaporateGhost()
    expect(tryReviveGhost()).toBe(true)
    expect(tryReviveGhost()).toBe(false)
  })

  it('窗过期（>60s）不找回', () => {
    chapterEditorHandle.value = mockEditor(true, '过期的幽灵')
    beginGhost('stitch')
    evaporateGhost()
    const spy = vi.spyOn(Date, 'now')
    const now = Date.now()
    spy.mockReturnValue(now + 60_001)
    expect(tryReviveGhost()).toBe(false)
    spy.mockRestore()
  })
})
