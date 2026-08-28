/**
 * NLE-ADF 3.0 思考指示器状态（useThinkingIndicator）。
 *
 * 解决「不知道 AI 什么时候会弹 / 不知道是思考太长还是没触发」的可观测性问题。
 * 作者停顿写作时，编辑器光标下方显示一个脉冲点，三态演化：
 *
 *   idle（隐藏）
 *     └─ 停顿 2s（活跃心跳已 reset，但未发停顿心跳）
 *        → waiting（淡灰小点：预览态，「再停一下 AI 要凑过来了」）
 *           → 停顿心跳 / stitch 已发出（后端在算）
 *              → perceiving（彩色强脉冲：「AI 正在读你的文字 / 生发灵感」）
 *                 └─ 挂件返回 / 缝合完成 / 任何打字
 *                    → idle
 *
 * 定位：位于光标下方 6px。2026-08-28 修复：此前坐标只在阶段切换时算一次
 * （文档注释声称跟随 selectionUpdate，实际从未接线）——按 Tab 弹舱后感知带
 * 出现挤动编辑区，绿点悬在旧坐标上错位。现在指示器可见期间挂
 * followEditorLayout（scroll/resize/selectionUpdate/ResizeObserver），位移即重算。
 * 与 SparkDock 互斥显示——Dock 弹出时指示器隐藏（避免光标下叠两层浮窗）。
 *
 * 全局单例 ref（同 ghostActive / sparkDockVisible 风格）。
 */
import { ref, watch } from 'vue'
import { chapterEditorHandle } from '../../chapter-editor/editorHandle'
import { followEditorLayout } from './editorLayoutFollower'

export type ThinkingPhase = 'idle' | 'waiting' | 'perceiving'

/** 当前阶段（idle=不显示） */
export const thinkingPhase = ref<ThinkingPhase>('idle')
/** 光标屏幕坐标（px）；phase≠idle 时有效 */
export const thinkingPos = ref({ top: 0, left: 0 })

/** 更新光标坐标（编辑器 selectionUpdate / 阶段切换前 / 布局跟随器调用） */
export function updateThinkingPos(): boolean {
  const editor = chapterEditorHandle.value
  if (!editor) return false
  try {
    const { $from } = editor.state.selection
    const cursorCoords = editor.view.coordsAtPos($from.pos)
    const next = {
      top: cursorCoords.bottom + 6,
      left: cursorCoords.left,
    }
    // 位移 ≥0.5px 才写 ref：跟随器高频触发（滚动/回流）时避免每帧无谓重渲染
    if (Math.abs(next.top - thinkingPos.value.top) >= 0.5
      || Math.abs(next.left - thinkingPos.value.left) >= 0.5) {
      thinkingPos.value = next
    }
    return true
  } catch {
    return false
  }
}

/** 切换阶段（自动重算坐标；切到 idle 不需要坐标） */
export function setThinkingPhase(phase: ThinkingPhase): void {
  if (phase !== 'idle') {
    if (!updateThinkingPos()) return  // 拿不到光标坐标就不显示
  }
  thinkingPhase.value = phase
}

/** 直接隐藏（打字活动 / Dock 弹出 / 幽灵出现时调用） */
export function hideThinking(): void {
  thinkingPhase.value = 'idle'
}

// ============================================================
// 布局跟随（2026-08-28 绿点错位修复）
// ============================================================
// 指示器可见期间挂 followEditorLayout，隐藏即卸；编辑器实例热换（切章）时
// 若指示器在屏则重挂（跟随器闭包持有旧实例的 selectionUpdate/ResizeObserver）。
let _unfollow: (() => void) | null = null

function _syncPos(): void {
  if (thinkingPhase.value !== 'idle') updateThinkingPos()
}

watch(thinkingPhase, (phase) => {
  if (phase !== 'idle' && !_unfollow) _unfollow = followEditorLayout(_syncPos)
  else if (phase === 'idle' && _unfollow) { _unfollow(); _unfollow = null }
})

watch(chapterEditorHandle, () => {
  if (_unfollow) { _unfollow(); _unfollow = null }
  if (thinkingPhase.value !== 'idle') _unfollow = followEditorLayout(_syncPos)
})
