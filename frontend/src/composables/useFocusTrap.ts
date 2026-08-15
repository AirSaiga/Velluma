import { ref, watch, nextTick, type Ref } from 'vue'

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
    if (e.key === 'Escape' && options?.onEscape) {
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
}
