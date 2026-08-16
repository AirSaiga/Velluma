/**
 * v-autogrow：textarea 随内容自动长高，替代固定 rows + 内部滚动条。
 * rows 属性仍作下限；超 CSS max-height 上限后才恢复滚动。
 * blur 存盘后外部值回流（updated 钩子）也会重新量高。
 */
import type { Directive } from 'vue'

function fit(el: HTMLTextAreaElement) {
  el.style.height = 'auto'
  // border-box 下 scrollHeight 不含边框，补上防末行被裁
  const borders = el.offsetHeight - el.clientHeight
  const h = el.scrollHeight + borders
  const max = parseFloat(getComputedStyle(el).maxHeight)
  const clamped = Number.isFinite(max) && h > max
  el.style.height = `${h}px`
  el.style.overflowY = clamped ? 'auto' : 'hidden'
}

export const vAutogrow: Directive<HTMLTextAreaElement> = {
  mounted: fit,
  updated: fit,
}
