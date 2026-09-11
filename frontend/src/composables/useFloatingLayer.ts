/**
 * 浮层响应式包装（UX 重构地基 00 期 §4.1B，docs/design/ux-redesign/）。
 *
 * 行为契约：open=true 挂 window resize + scroll(capture) 监听并重算；
 * open=false 摘净。浮层本体 position:fixed，消费 pos/maxHeight。
 * 几何算法见 shared/utils/floatGeometry.ts（纯函数，可测）。
 */
import { ref, watch, onScopeDispose, type Ref } from 'vue'
import {
  placeFloating,
  type FloatAnchorRect,
  type FloatPoint,
  type FloatPlacement,
} from '../shared/utils/floatGeometry'

export interface FloatingLayerOptions {
  /** 每次重算时取锚；返回 null 表示锚不可用（跳过重算，浮层保持原位/由调用方关闭） */
  anchor: () => FloatAnchorRect | FloatPoint | null
  size: { width: number; height: number } | Ref<{ width: number; height: number }>
  placement?: Omit<FloatPlacement, 'width' | 'height'>
  /** 开时挂监听，关时摘 */
  open: Ref<boolean>
}

export function useFloatingLayer(options: FloatingLayerOptions) {
  const pos = ref({ top: 0, left: 0, flipped: false })
  const maxHeight = ref<number | null>(null)

  const resolveSize = (): { width: number; height: number } => {
    const s = options.size as { width: number; height: number } | Ref<{ width: number; height: number }>
    return (s as Ref<{ width: number; height: number }>).value ?? (s as { width: number; height: number })
  }

  const recalc = () => {
    const anchor = options.anchor()
    if (!anchor) return
    const { width, height } = resolveSize()
    const result = placeFloating(
      anchor,
      { ...(options.placement ?? {}), width, height },
      { width: window.innerWidth, height: window.innerHeight },
    )
    pos.value = { top: result.top, left: result.left, flipped: result.flipped }
    maxHeight.value = result.maxHeight
  }

  const detach = () => {
    window.removeEventListener('resize', recalc)
    window.removeEventListener('scroll', recalc, true)
  }
  const attach = () => {
    detach()
    window.addEventListener('resize', recalc)
    window.addEventListener('scroll', recalc, true)
  }

  watch(
    () => options.open.value,
    (open) => {
      if (open) {
        recalc()
        attach()
      } else {
        detach()
      }
    },
    { immediate: true },
  )

  onScopeDispose(detach)

  return { pos, maxHeight, recalc }
}
