/**
 * 编辑器布局跟随器（2026-08-28 绿点错位修复）。
 *
 * 背景：思考指示器/卡片舱都是 Teleport 到 body 的 position:fixed 浮层，
 * 坐标只在出现那一刻计算一次——此后任何布局位移（感知带出现挤动编辑区、
 * 滚动、侧栏开合、窗口缩放）都会让浮层悬在错误位置（实测：按 Tab 弹舱后
 * CANON 感知带出现，绿点错位悬在正文上）。
 *
 * 本模块把「位移源」收拢成四个监听，浮层可见期间挂上、隐藏即卸：
 * - window scroll（capture——捕获编辑器滚动容器等内层滚动）
 * - window resize
 * - 编辑器 selectionUpdate（光标移动——绿点文档注释承诺过「跟随光标」，
 *   此前从未接线）
 * - ResizeObserver 观察编辑器 DOM + 其父容器（布局回流：侧栏出现改变
 *   编辑区宽度/位置时触发）
 *
 * sync 全部走 passive/被动观察，coordsAtPos 是廉价测量，位移高频期
 * （滚动）每帧一次可忽略。无 window 环境（vitest node）安全 no-op。
 */
import { chapterEditorHandle } from '../../chapter-editor/editorHandle'

export function followEditorLayout(sync: () => void): () => void {
  if (typeof window === 'undefined') return () => {}  // node 测试环境 no-op

  const editor: any = chapterEditorHandle.value
  const unbinds: Array<() => void> = []

  window.addEventListener('scroll', sync, { capture: true, passive: true })
  unbinds.push(() => window.removeEventListener('scroll', sync, { capture: true } as any))

  window.addEventListener('resize', sync, { passive: true })
  unbinds.push(() => window.removeEventListener('resize', sync))

  editor?.on?.('selectionUpdate', sync)
  unbinds.push(() => editor?.off?.('selectionUpdate', sync))

  // 布局回流：观察编辑器 DOM 及其父容器——侧栏开合改变编辑区宽度/位移时触发
  let ro: ResizeObserver | null = null
  const editorEl: HTMLElement | null = editor?.view?.dom ?? null
  if (editorEl && typeof ResizeObserver !== 'undefined') {
    ro = new ResizeObserver(sync)
    ro.observe(editorEl)
    if (editorEl.parentElement) ro.observe(editorEl.parentElement)
    unbinds.push(() => ro!.disconnect())
  }

  return () => { unbinds.forEach((fn) => fn()) }
}
