import { ref, watch, nextTick, onScopeDispose, type Ref } from 'vue'

export function useFocusTrap(containerRef: Ref<HTMLElement | null>, activeRef: Ref<boolean>, options?: { onEscape?: () => void }) {
  let previouslyFocused: Element | null = null
  let cleanup = () => {}

  function getFocusableElements(): HTMLElement[] {
    if (!containerRef.value) return []
    return Array.from(
      containerRef.value.querySelectorAll(
        'button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])'
      )
    ).filter((el) => !el.hasAttribute('disabled')) as HTMLElement[]
  }

  function handleKeydown(e: KeyboardEvent) {
    // Esc 关闭栈（window capture）先行处理并 preventDefault 时让位，
    // 防同一节点上两个监听各关一层（00 期 §4.2）
    if (e.defaultPrevented) return
    // 空守卫：宿主随 v-if 卸载后 ref 置空——此时陷阱已无意义，放行事件
    // （防监听器以任何路径泄漏时在 document capture 上 stopPropagation 吞掉全页 Esc）
    if (e.key === 'Escape' && options?.onEscape && containerRef.value) {
      e.stopPropagation()
      options.onEscape()
      return
    }
    if (e.key !== 'Tab' || !containerRef.value) return

    const focusable = getFocusableElements()
    if (focusable.length === 0) return

    const first = focusable[0]
    const last = focusable[focusable.length - 1]
    const active = document.activeElement as HTMLElement

    if (e.shiftKey && active === first) {
      e.preventDefault()
      last.focus()
    } else if (!e.shiftKey && active === last) {
      e.preventDefault()
      first.focus()
    }
  }

  function handleFocusIn(e: FocusEvent) {
    if (!containerRef.value) return
    if (!containerRef.value.contains(e.target as Node)) {
      const focusable = getFocusableElements()
      if (focusable.length) {
        focusable[0].focus()
      }
    }
  }

  watch(activeRef, async (active) => {
    if (active) {
      previouslyFocused = document.activeElement
      // 等 v-if/渲染完成再查询可焦点元素（watch 默认 pre-flush，此时 DOM 未更新）
      await nextTick()
      const focusable = getFocusableElements()
      if (focusable.length) {
        focusable[0].focus()
      }
      document.addEventListener('keydown', handleKeydown, true)
      document.addEventListener('focusin', handleFocusIn)
      cleanup = () => {
        document.removeEventListener('keydown', handleKeydown, true)
        document.removeEventListener('focusin', handleFocusIn)
      }
    } else {
      cleanup()
      cleanup = () => {}
      if (previouslyFocused && 'focus' in previouslyFocused) {
        ;(previouslyFocused as HTMLElement).focus()
      }
    }
  })

  // v-if 卸载兜底（2026-09-07 审计修复）：宿主随父级 v-if 整体卸载时 active 不会翻
  // false（watch 随作用域销毁、回调不触发），document 监听器将泄漏——泄漏的 Esc 分支
  // 会 stopPropagation 吞掉全页 Esc。作用域销毁即强制清理（对 visible-prop 型宿主幂等）
  onScopeDispose(() => {
    cleanup()
    cleanup = () => {}
  })
}
