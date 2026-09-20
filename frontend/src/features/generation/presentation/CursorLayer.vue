<script setup lang="ts">
/**
 * 光标层（07 期 §2.5）——写中才出现的浮动层。
 *
 * 2026-09-09 行间推挤重构后本层只剩幽灵三条（疑点/返修/洗层）：卡片舱
 * （SparkDock）迁入 ProseMirror WidgetDecoration 流内区块（InlineDock.ts
 * + InlineDockHost.vue，光标段下方撑开、0% 遮挡），不再走本浮层。
 * 幽灵三条体积小（1~3 枚 chip），保持 fixed 贴幽灵尾不占排版流。
 * Teleport body / fixed / --z-dock。
 *
 * 槽位 · 幽灵三条：GHOST_DONE 帧到达时锚定幽灵尾（[data-ghost-draft]
 * 末元素实时 rect，滚动自跟随；找不到回落当帧光标），纵叠 gap 4px。
 * 槽位 · 三键阶梯渐进提示：前 3 枚幽灵在三条之下随附一行键位提示
 * （Tab 采纳 · Enter 暂留 · Esc 蒸发），看过即淡出（useProgressiveHint）。
 */
import { computed, ref, watch, onScopeDispose } from 'vue'
import GhostWarningsBar from './GhostWarningsBar.vue'
import GhostWashChip from './GhostWashChip.vue'
import GhostRepairedChip from './GhostRepairedChip.vue'
import { sparkDockPos } from '../composables/useSparkDock'
import { ghostActive, ghostStreaming, ghostWarnings, ghostWash, ghostRepaired } from '../composables/useGhostDraft'
import { useFloatingLayer } from '../../../composables/useFloatingLayer'
import { useProgressiveHint } from '../../../composables/useProgressiveHint'

const emit = defineEmits<{
  /** 洗层条「用原稿」（可逆学习，容器接线） */
  useOriginal: []
}>()

// ============================================================
// 幽灵三条（疑点 → 返修 → 洗层，纵叠）+ 三键阶梯渐进提示：
// 三条数据在 GHOST_DONE 帧到达（流式毕），挂载即锚定，天然无抖动面。
// 三键提示（Tab 采纳 · Enter 暂留 · Esc 蒸发）前 3 枚幽灵随层显示，
// 确实显示过的那枚在落沿计数，看过即淡出（useProgressiveHint）。
// ============================================================
const ghostHint = useProgressiveHint('ghost_three_keys')
const ghostHintVisible = computed(() => !ghostStreaming.value && ghostHint.visible.value)
const ghostChipsVisible = computed(
  () =>
    ghostActive.value &&
    (ghostWarnings.value.length > 0 || !!ghostRepaired.value || ghostWash.value.hits.length > 0),
)
const ghostLayerVisible = computed(
  () => ghostActive.value && (ghostChipsVisible.value || ghostHintVisible.value),
)
let _hintShownThisGhost = false
watch([ghostActive, ghostHintVisible], () => {
  if (ghostActive.value && ghostHintVisible.value) _hintShownThisGhost = true
})
watch(ghostActive, (active) => {
  if (!active && _hintShownThisGhost) {
    _hintShownThisGhost = false
    ghostHint.markSeen()
  }
})
const ghostRootEl = ref<HTMLElement | null>(null)
const ghostSize = ref({ width: 360, height: 120 })
// 锚=幽灵尾（mark 末元素实时 rect → 滚动/回流自跟随）；幽灵不在 DOM 时回落当帧光标
function ghostAnchor(): { x: number; y: number } | null {
  try {
    const marks = document.querySelectorAll('[data-ghost-draft]')
    const last = marks[marks.length - 1] as HTMLElement | undefined
    if (last) {
      const r = last.getBoundingClientRect()
      return { x: r.left, y: r.bottom }
    }
  } catch { /* 编辑器不在时回落 */ }
  const p = sparkDockPos.value
  if (!p || (!p.top && !p.left)) return null
  return { x: p.left, y: p.top - 8 }
}
const ghostLayer = useFloatingLayer({
  anchor: ghostAnchor,
  size: ghostSize,
  placement: { gap: 8, margin: 8, prefer: 'below', flip: true, align: 'start' },
  open: ghostLayerVisible,
})
watch([ghostRootEl, ghostLayerVisible], () => {
  const el = ghostRootEl.value
  if (el && ghostChipsVisible.value) {
    ghostSize.value = { width: el.offsetWidth || 360, height: el.offsetHeight || 120 }
    ghostLayer.recalc()
  }
}, { flush: 'post' })
const ghostReady = ref(false)
watch(() => ghostLayer.pos.value, (p) => { if (p.left > 0 || p.top > 0) ghostReady.value = true })
// 明细展开/收起会改变内容高度（疑点条/返修条的「明细」均内折叠）——
// 实测高度回灌浮动层重算钳位/翻转；RO 只在真实尺寸变化时触发，无回环
let ghostResize: ResizeObserver | null = null
watch(ghostRootEl, (el) => {
  ghostResize?.disconnect()
  ghostResize = null
  if (el && typeof ResizeObserver !== 'undefined') {
    ghostResize = new ResizeObserver(() => {
      ghostSize.value = { width: el.offsetWidth || 360, height: el.offsetHeight || 120 }
      ghostLayer.recalc()
    })
    ghostResize.observe(el)
  }
}, { flush: 'post' })
onScopeDispose(() => ghostResize?.disconnect())
</script>

<template>
  <Teleport to="body">
    <!-- 幽灵三条 + 三键渐进提示，纵叠贴幽灵尾 -->
    <div
      v-if="ghostLayerVisible && ghostReady"
      ref="ghostRootEl"
      class="cursor-layer cursor-layer--ghost"
      :class="{ 'cursor-layer--flipped': ghostLayer.pos.value.flipped }"
      :style="{
        top: ghostLayer.pos.value.top + 'px',
        left: ghostLayer.pos.value.left + 'px',
        maxHeight: ghostLayer.maxHeight.value ? ghostLayer.maxHeight.value + 'px' : undefined,
      }"
    >
      <GhostWarningsBar v-if="ghostWarnings.length" :warnings="ghostWarnings" />
      <GhostRepairedChip v-if="ghostRepaired" :repaired="ghostRepaired" />
      <GhostWashChip
        v-if="ghostWash.hits.length"
        :wash="ghostWash"
        @use-original="emit('useOriginal')"
      />
      <div v-if="ghostHintVisible" class="cursor-layer__hint">Tab 采纳 · Enter 暂留 · Esc 蒸发</div>
    </div>
  </Teleport>
</template>

<style scoped>
.cursor-layer {
  position: fixed;
  z-index: var(--z-dock);
  display: flex;
  flex-direction: column;
  gap: 4px;
  overflow-y: auto;
}
.cursor-layer--ghost {
  width: min(360px, 80vw);
}
/* 三键阶梯渐进提示行（与走向卡舱 hint 同款小字规格） */
.cursor-layer__hint {
  padding: 2px 6px;
  font-size: var(--text-xs);
  color: var(--text-muted);
}
/* 翻转时入场方向取反（07 期 §2.5.1：从上往下淡入改为从下往上） */
.cursor-layer--flipped :deep(.spark-dock-enter-from),
.cursor-layer--flipped :deep(.spark-dock-leave-to) {
  transform: translateY(4px);
}
</style>
