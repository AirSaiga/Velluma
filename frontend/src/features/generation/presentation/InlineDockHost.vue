<script setup lang="ts">
/**
 * 行间推挤宿主（2026-09-09 布局重构）——ProseMirror WidgetDecoration 里的
 * Vue 岛：SparkDock 的家从 fixed 浮层改为正文流内区块（光标段下方撑开，
 * 下方正文平滑让位，0% 遮挡）。
 *
 * 高度手风琴（纯 CSS transition，不占输入线程）：
 * - 展开：0 → auto（一次性测量目标高，动画毕置 auto，舱内后续增删不再截断）；
 *   展开当帧 scrollIntoView(nearest)——光标行/卡舱/后文同屏，浏览器原生
 *   滚动锚定已在 .ProseMirror 上关闭（overflow-anchor:none），无互搏。
 * - 收折：auto → 0，transitionend 后调 requestInlineDockRemoval 摘装饰
 *   （450ms 安全超时兜底 transitionend 丢失）；舱在光标行下方，收折只
 *   上拉下方内容——光标行 y 不动，幽灵流入处零位移。
 */
import { ref, computed, watch, onMounted, onBeforeUnmount } from 'vue'
import SparkDock from './SparkDock.vue'
import { sparkDockVisible, attachedParts } from '../composables/useSparkDock'
import { ghostActive } from '../composables/useGhostDraft'
import { chapterEditorHandle } from '../../chapter-editor/editorHandle'
import { requestInlineDockRemoval, inlineDockBridge } from '../../../extensions/InlineDock'

const open = computed(
  () => (sparkDockVisible.value || attachedParts.value.length > 0) && !ghostActive.value,
)

const rootEl = ref<HTMLElement | null>(null)
let _teardown = false

function _expand(): void {
  const el = rootEl.value
  if (!el) return
  // ⚠ widget 由 PM 在 toDOM 回调里创建——render() 的 onMounted 可能先于
  // 装饰插入文档执行（实测：插入前 offsetHeight 恒 0，高度被钉死 0px 且
  // open 无翻转沿、watch 永不重测）。未连接/测得 0 高时逐帧重试（有界，
  // 连接在同一次 updateState 内完成，1~2 帧内到位）。
  let tries = 0
  const step = (): void => {
    if (_teardown || !rootEl.value || !open.value) return
    el.style.height = 'auto'
    const target = el.offsetHeight
    if (target <= 0 && tries++ < 10) {
      requestAnimationFrame(step)
      return
    }
    el.style.height = '0px'
    void el.offsetHeight // 强制回流，让 0→target 的过渡可动画
    el.style.height = `${target}px`
    el.addEventListener('transitionend', function done(ev: TransitionEvent) {
      if (ev.propertyName !== 'height') return
      el.removeEventListener('transitionend', done)
      if (open.value) el.style.height = 'auto'
    })
    // 目标高度立起来后一帧内滚到可见（nearest=最小滚动，光标行已可见时只补舱）
    requestAnimationFrame(() => el.scrollIntoView({ block: 'nearest' }))
  }
  step()
}

function _collapse(): void {
  const el = rootEl.value
  if (!el) return
  const target = el.offsetHeight
  if (target <= 0) {
    _requestRemove()
    return
  }
  el.style.height = `${target}px`
  void el.offsetHeight
  el.style.height = '0px'
  const timer = setTimeout(_requestRemove, 450)
  el.addEventListener('transitionend', function done(ev: TransitionEvent) {
    if (ev.propertyName !== 'height') return
    el.removeEventListener('transitionend', done)
    clearTimeout(timer)
    _requestRemove()
  })
}

function _requestRemove(): void {
  if (_teardown) return
  const editor = chapterEditorHandle.value
  if (editor) requestInlineDockRemoval(editor)
}

watch(open, (v) => {
  if (_teardown) return
  if (v) _expand()
  else _collapse()
})

onMounted(() => {
  if (open.value) _expand()
})

// widget 被 PM 摘除时 render(null) 直接卸载本组件——没有 transitionend，
// 摘除动作本身就是终点，无需补刀
onBeforeUnmount(() => {
  _teardown = true
})
</script>

<template>
  <div ref="rootEl" class="inline-dock-host">
    <SparkDock
      @custom-stitch="(t: string) => inlineDockBridge.customStitch(t)"
      @guest-register="(n: string) => inlineDockBridge.guestRegister(n)"
    />
  </div>
</template>

<style scoped>
/* 行间推挤容器：贴满正文列宽（880 纸面内容宽），上下 6px 让位。
   初始 0 高 + overflow hidden——展开动画期间裁切，毕后置 auto。 */
.inline-dock-host {
  width: 100%;
  height: 0;
  margin: 6px 0;
  overflow: hidden;
  transition: height 0.16s ease-out;
}
</style>
