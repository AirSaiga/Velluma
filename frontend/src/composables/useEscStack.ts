/**
 * 全局唯一 Esc 关闭栈（UX 重构地基 00 期 §4.2，docs/design/ux-redesign/）。
 *
 * 治三病：Esc 依赖「焦点恰在层内」、叠层时一次 Esc 同关多层、window capture 抢跑。
 * 纪律：
 * - 模块级单例栈 + window 上唯一一个 keydown capture 监听（首次 push 挂，栈空即摘）；
 * - 一次 Esc 只关栈顶一层：preventDefault 后调栈顶 close()；
 * - 调用方契约：打开时 push、关闭时 remove（open watch 内幂等）；close() 不自动弹栈，
 *   由调用方状态流转触发 remove——remove 幂等，迟到的 remove 是无害 no-op；
 * - 入栈顺序=打开顺序，后开者在顶，栈序即视觉层序；
 * - defaultPrevented 让位（useFocusTrap 同款纪律）：会话写作键处理器与本栈同是
 *   window capture 监听，stopPropagation 挡不住同节点监听——会话侧已消费 Esc
 *   （蒸发幽灵/关卡舱）时本栈必须让位，否则一次 Esc 同关两层。
 */
import { ref } from 'vue'

interface EscLayer {
  id: symbol
  close: () => void
  label?: string
}

const stack: EscLayer[] = []
const depth = ref(0)
let listenerAttached = false

function handleKeydown(e: KeyboardEvent) {
  if (e.key !== 'Escape' || stack.length === 0) return
  // 会话写作 Esc 已消费（先注册的 window capture 监听先行）→ 本栈让位不剥皮
  if (e.defaultPrevented) return
  e.preventDefault()
  stack[stack.length - 1].close()
}

function attach() {
  if (listenerAttached) return
  window.addEventListener('keydown', handleKeydown, true)
  listenerAttached = true
}

function detach() {
  if (!listenerAttached) return
  window.removeEventListener('keydown', handleKeydown, true)
  listenerAttached = false
}

export function useEscStack() {
  /** 入栈并挂监听；返回层 id（供 remove）。重复 push 由调用方防（open watch 内幂等）。 */
  function push(close: () => void, label?: string): symbol {
    const id = Symbol(label ?? 'esc-layer')
    stack.push({ id, close, label })
    depth.value = stack.length
    attach()
    return id
  }

  /** 幂等摘除；栈空即摘全局监听。 */
  function remove(id: symbol) {
    const idx = stack.findIndex((l) => l.id === id)
    if (idx !== -1) stack.splice(idx, 1)
    depth.value = stack.length
    if (stack.length === 0) detach()
  }

  function isTop(id: symbol): boolean {
    return stack.length > 0 && stack[stack.length - 1].id === id
  }

  return { push, remove, isTop, depth }
}
