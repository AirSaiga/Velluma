/**
 * 动效偏好查询（UX 重构地基 00 期 §5.2）。
 * CSS 毯式 reduced-motion 管不到 JS 侧行为（如 scrollIntoView smooth），
 * 调用点用此函数三元切换 behavior。
 */
export function prefersReducedMotion(): boolean {
  return (
    typeof window !== 'undefined' &&
    typeof window.matchMedia === 'function' &&
    window.matchMedia('(prefers-reduced-motion: reduce)').matches
  )
}
