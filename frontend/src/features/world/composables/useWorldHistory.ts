import { ref } from 'vue'

/**
 * undo/redo 命令栈（照搬世界绘卷 history.ts，纯 TS + Vue ref 暴露状态）。
 *
 * 设计要点：
 * - 栈是模块级单例（past/future 数组），不放进 ref 避免响应式重建；只把
 *   canUndo/canRedo/lastDesc 作为 ref 暴露给 UI
 * - pushCommand 清空 future（分支后旧 redo 失效）
 * - undo/redo 执行命令不 push 新命令
 * - 上限 50 步，超出 shift 最旧
 *
 * 逆命令由调用方（useWorld 的写动作）闭包提供，含快照数据。
 * 注意：Velluma 后端 id 用 generate_uuid（不可重现），redo 重建会生成新 id——
 * M1 接受（单机设定，引用断裂罕见）；后续可让后端 create 支持传 id 保证引用不断。
 */

export interface Command {
  description: string
  undo: () => Promise<void>
  redo: () => Promise<void>
}

const MAX = 50
const past: Command[] = []
const future: Command[] = []

const canUndo = ref(false)
const canRedo = ref(false)
const lastDesc = ref('')

function syncState() {
  canUndo.value = past.length > 0
  canRedo.value = future.length > 0
  lastDesc.value = past.length > 0 ? past[past.length - 1].description : ''
}

export function pushCommand(cmd: Command) {
  past.push(cmd)
  if (past.length > MAX) past.shift()
  future.length = 0
  syncState()
}

export async function undo() {
  const cmd = past.pop()
  if (!cmd) return
  await cmd.undo()
  future.push(cmd)
  syncState()
}

export async function redo() {
  const cmd = future.pop()
  if (!cmd) return
  await cmd.redo()
  past.push(cmd)
  syncState()
}

export function clearHistory() {
  past.length = 0
  future.length = 0
  syncState()
}

export function useWorldHistory() {
  return { canUndo, canRedo, lastDesc, pushCommand, undo, redo, clearHistory }
}

function isInInput(t: EventTarget | null): boolean {
  const el = t as HTMLElement | null
  if (!el) return false
  const tag = el.tagName
  return tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT' || el.isContentEditable
}

/**
 * Ctrl+Z = undo，Ctrl+Y / Ctrl+Shift+Z = redo。
 * 焦点在 input/textarea/select/contentEditable 内放行（让浏览器原生文本 undo/redo）。
 * 返回卸载函数。
 */
export function useUndoShortcut(onUndo: () => void, onRedo: () => void) {
  function handler(e: KeyboardEvent) {
    const mod = e.ctrlKey || e.metaKey
    if (!mod) return
    if (e.key === 'z' && !e.shiftKey) {
      if (isInInput(e.target)) return
      e.preventDefault()
      onUndo()
    } else if ((e.key === 'z' && e.shiftKey) || e.key === 'y') {
      // redo 与 undo 对齐：输入框内放行浏览器原生文本 redo
      if (isInInput(e.target)) return
      e.preventDefault()
      onRedo()
    }
  }
  window.addEventListener('keydown', handler)
  return () => window.removeEventListener('keydown', handler)
}
