/**
 * 浮层视口夹紧纯函数（UX 重构地基 00 期 §4.1A，docs/design/ux-redesign/）。
 *
 * 确定序算法：clamp(left) → prefer 方向贴锚 → 越界翻转 → 仍越界双边夹紧并给 maxHeight。
 * 零 DOM 依赖：viewport 由调用方注入，保证可在 vitest 对拍。
 * 消费方：composables/useFloatingLayer.ts（响应式包装）。
 * 例外：Spark/Beat Dock 不接（00 期 §6.1 冻结写作台几何，底缘修复排第 3 期）。
 */

export interface FloatAnchorRect {
  top: number
  left: number
  bottom: number
  right: number
}

/** 光标/点击点锚 */
export interface FloatPoint {
  x: number
  y: number
}

export interface FloatPlacement {
  /** 浮层实际宽（未知时传上限） */
  width: number
  /** 浮层实际高（未知时传上限） */
  height: number
  /** 与锚的间距 */
  gap?: number
  /** 视口安全边距 */
  margin?: number
  /** 首选方向 */
  prefer?: 'below' | 'above'
  /** 底部不足时翻到锚上方 */
  flip?: boolean
  /** 水平对齐锚的哪条边 */
  align?: 'start' | 'center' | 'end'
}

export interface FloatResult {
  top: number
  left: number
  /** 是否发生了翻转（供箭头朝向/动画起点用） */
  flipped: boolean
  /** 垂直空间仍不足时给出的可用高度（浮层须应用为 max-height） */
  maxHeight: number | null
}

const clamp = (v: number, lo: number, hi: number): number => {
  // 退化区间（hi < lo，浮层比视口还高）时优先钉在 lo（视口安全边距）——
  // 由 maxHeight 承担截断语义
  return Math.max(lo, Math.min(v, hi))
}

export function placeFloating(
  anchor: FloatAnchorRect | FloatPoint,
  opts: FloatPlacement,
  viewport: { width: number; height: number },
): FloatResult {
  const gap = opts.gap ?? 8
  const margin = opts.margin ?? 8
  const prefer = opts.prefer ?? 'below'
  const flip = opts.flip ?? true
  const align = opts.align ?? 'start'
  const { width, height } = opts

  // 点锚按零宽高矩形处理
  const rect: FloatAnchorRect =
    'x' in anchor
      ? { top: anchor.y, left: anchor.x, bottom: anchor.y, right: anchor.x }
      : anchor

  // 1. 水平：按 align 贴锚，再双边夹紧
  let left: number
  if (align === 'center') left = (rect.left + rect.right) / 2 - width / 2
  else if (align === 'end') left = rect.right - width
  else left = rect.left
  left = clamp(left, margin, viewport.width - width - margin)

  // 2. 垂直：首选方向贴锚；越界且允许翻转 → 翻到另一侧
  let top: number
  let flipped = false
  if (prefer === 'below') top = rect.bottom + gap
  else top = rect.top - gap - height

  const overflows = top + height > viewport.height - margin || top < margin
  if (overflows && flip) {
    top = prefer === 'below' ? rect.top - gap - height : rect.bottom + gap
    flipped = true
  }

  // 3. 仍越界（锚居中视口/浮层过高）→ 双边夹紧并给出可用高度
  let maxHeight: number | null = null
  if (top + height > viewport.height - margin || top < margin) {
    top = clamp(top, margin, viewport.height - margin - height)
    maxHeight = Math.max(viewport.height - 2 * margin, 0)
  }

  return { top, left, flipped, maxHeight }
}
