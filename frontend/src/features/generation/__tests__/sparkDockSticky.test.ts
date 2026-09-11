/**
 * 卡片舱 sticky/stash/restore 机制测试（2026-08-28 唤醒交互修复的护栏）。
 *
 * 背景：setSparkSticky 曾全工程零调用（死代码）——缝合后舱被 hideSparkDock
 * 永久收走，「连续吸附多件缝合」从未生效。复活语义：
 * - 缝合触发 = setSparkSticky + stashSparkDock（藏舱让位幽灵，sticky 保留）
 * - 幽灵落定（ghostActive 下落沿）= 自动 restoreSparkDock（nextTick 后弹回）
 * - 打字/光标移动不收 sticky 舱；hideSparkDock（Esc）仍是唯一完全退出
 */
import { describe, it, expect, beforeEach, vi } from 'vitest'
import { nextTick } from 'vue'
import {
  sparkDockVisible, sparkSticky, sparkParts, sparkAnchorPos,
  setSparkParts, setSparkDockGate,
  showSparkDock, hideSparkDock, stashSparkDock, restoreSparkDock, setSparkSticky,
} from '../composables/useSparkDock'
import { ghostActive } from '../composables/useGhostDraft'
import { chapterEditorHandle } from '../../chapter-editor/editorHandle'

/** 最小可用的编辑器替身：定位需要 coordsAtPos，活动钩子需要 on/off */
function mockEditor() {
  const handlers: Record<string, Array<() => void>> = {}
  return {
    on: (ev: string, fn: () => void) => { (handlers[ev] ||= []).push(fn) },
    off: (ev: string, fn: () => void) => {
      handlers[ev] = (handlers[ev] || []).filter((f) => f !== fn)
    },
    trigger: (ev: string) => { (handlers[ev] || []).forEach((f) => f()) },
    state: { selection: { $from: { pos: 2, start: () => 0, end: () => 3, after: () => 3 } } },
    view: { coordsAtPos: () => ({ top: 0, bottom: 10, left: 10 }) },
  } as any
}

const PARTS = [
  { key: 'a:1', kind: 'anchor' as const, icon: '✨', text: '老烟的血手' },
]

beforeEach(() => {
  chapterEditorHandle.value = mockEditor()
  setSparkDockGate(() => true)
  setSparkParts([...PARTS])
  hideSparkDock() // 同时清 sticky
  ghostActive.value = false
})

describe('stash / restore（缝合让位与回弹）', () => {
  it('stash 藏舱但保 sticky；restore 弹回', () => {
    showSparkDock()
    expect(sparkDockVisible.value).toBe(true)
    setSparkSticky()
    stashSparkDock()
    expect(sparkDockVisible.value).toBe(false)
    expect(sparkSticky.value).toBe(true)   // stash 不清 sticky
    restoreSparkDock()
    expect(sparkDockVisible.value).toBe(true)
  })

  it('非 sticky 时 restore 是 no-op', () => {
    showSparkDock()
    stashSparkDock() // 未 setSparkSticky
    restoreSparkDock()
    expect(sparkDockVisible.value).toBe(false)
  })

  it('hideSparkDock 完全退出（清 sticky）——Esc 仍是唯一手动出口', () => {
    showSparkDock()
    setSparkSticky()
    hideSparkDock()
    expect(sparkSticky.value).toBe(false)
    restoreSparkDock()
    expect(sparkDockVisible.value).toBe(false)
  })
})

describe('幽灵落定不自动回弹（2026-09-09 自动弹出退役）', () => {
  it('SPARK_DOCK_AUTO_POPUP=false：ghost 落沿（任何结束原因）+ sticky → 舱不弹回，Tab 是唯一入口', async () => {
    showSparkDock()
    setSparkSticky()
    stashSparkDock()
    ghostActive.value = true
    await nextTick()
    ghostActive.value = false   // 无论蒸发/采纳/失败
    await nextTick()
    await nextTick()
    expect(sparkDockVisible.value).toBe(false)
    expect(sparkSticky.value).toBe(true)   // sticky 保留：手动 restoreSparkDock 仍可弹
  })

  it('手动 restoreSparkDock 仍是可用 API（stash/restore 对不受开关影响）', () => {
    showSparkDock()
    setSparkSticky()
    stashSparkDock()
    restoreSparkDock()
    expect(sparkDockVisible.value).toBe(true)
  })
})

describe('行间锚（2026-09-09 布局重构：浮层 → WidgetDecoration）', () => {
  it('showSparkDock 设 sparkAnchorPos=$from.after()——InlineDock 立装饰的锚', () => {
    showSparkDock()
    expect(sparkDockVisible.value).toBe(true)
    expect(sparkAnchorPos.value).toBe(3)
  })

  it('锚取不到（编辑器无 after）时不开舱', () => {
    const editor = chapterEditorHandle.value as any
    const orig = editor.state.selection.$from.after
    editor.state.selection.$from.after = () => { throw new Error('no boundary') }
    showSparkDock()
    expect(sparkDockVisible.value).toBe(false)
    editor.state.selection.$from.after = orig
  })

  it('sticky 态编辑器活动按段落粒度换锚（$from.after 变了才动，打字不抖）', () => {
    const editor = chapterEditorHandle.value as any
    showSparkDock()
    setSparkSticky()
    expect(sparkAnchorPos.value).toBe(3)
    editor.trigger('update')   // 同段打字：锚不动
    expect(sparkAnchorPos.value).toBe(3)
    editor.state.selection.$from.after = () => 42   // 光标去了别的段
    editor.trigger('selectionUpdate')
    expect(sparkAnchorPos.value).toBe(42)
  })
})

describe('打字不收 sticky 舱', () => {
  it('编辑器活动（打字/光标）在 sticky 态只重定位不隐藏', () => {
    const editor = chapterEditorHandle.value as any
    showSparkDock()
    setSparkSticky()
    editor.trigger('update')     // 打字
    editor.trigger('selectionUpdate') // 光标
    expect(sparkDockVisible.value).toBe(true)
  })

  it('非 sticky 态打字即收舱（旧行为不变——首次弹出后作者继续写不需要灵感）', () => {
    const editor = chapterEditorHandle.value as any
    showSparkDock()
    editor.trigger('update')
    expect(sparkDockVisible.value).toBe(false)
  })
})
