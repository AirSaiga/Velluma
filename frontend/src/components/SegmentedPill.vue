<script setup lang="ts">
/**
 * SegmentedPill（05-visual-modernization-plan §8.7 共享控件首批）：
 * pill 轨道（--surface-sunken 底 + --radius-lg 全圆角）+ 滑动 thumb
 * （--surface-float + .elev-1；transform/width 过渡 var(--dur-2) var(--ease-out)）。
 * 选中文字 --text-primary（600），未选 --text-secondary。
 *
 * 用法：<SegmentedPill v-model="mode" :options="[{ label, value }]" />
 * thumb 位置由激活按钮的 offsetLeft/offsetWidth 实测——选项文案变化/字体加载
 * 后用 nextTick 重测；窗口 resize 同步跟。
 */
import { onBeforeUnmount, onMounted, ref, watch, nextTick } from 'vue'

const props = defineProps<{
  options: ReadonlyArray<{ label: string; value: string }>
  modelValue: string
}>()

const emit = defineEmits<{
  'update:modelValue': [value: string]
}>()

const trackRef = ref<HTMLElement | null>(null)
const thumbStyle = ref<{ transform: string; width: string }>({
  transform: 'translateX(3px)',
  width: '0px',
})

function measure() {
  const track = trackRef.value
  if (!track) return
  const idx = props.options.findIndex((o) => o.value === props.modelValue)
  // children[0] 是 thumb，按钮从 children[1] 起
  const btn = idx >= 0 ? (track.children[idx + 1] as HTMLElement | undefined) : undefined
  if (!btn) return
  thumbStyle.value = {
    transform: `translateX(${btn.offsetLeft}px)`,
    width: `${btn.offsetWidth}px`,
  }
}

function onResize() {
  measure()
}

/** N1 §3.4：键盘导航（roving tabindex + ←→/Home/End）——可访问性补齐 */
function onKeydown(e: KeyboardEvent, idx: number) {
  const n = props.options.length
  let next = -1
  if (e.key === 'ArrowRight' || e.key === 'ArrowDown') next = (idx + 1) % n
  else if (e.key === 'ArrowLeft' || e.key === 'ArrowUp') next = (idx - 1 + n) % n
  else if (e.key === 'Home') next = 0
  else if (e.key === 'End') next = n - 1
  else return
  e.preventDefault()
  const v = props.options[next].value
  emit('update:modelValue', v)
  const btns = trackRef.value?.querySelectorAll('.seg-pill__btn')
  ;(btns?.[next] as HTMLElement | undefined)?.focus()
}

onMounted(() => {
  measure()
  window.addEventListener('resize', onResize)
})
watch(() => [props.modelValue, props.options], () => nextTick(measure), { deep: true })
onBeforeUnmount(() => {
  window.removeEventListener('resize', onResize)
})
</script>

<template>
  <div ref="trackRef" class="seg-pill" role="radiogroup">
    <span class="seg-pill__thumb elev-1" :style="thumbStyle" aria-hidden="true"></span>
    <button
      v-for="(opt, i) in options"
      :key="opt.value"
      type="button"
      class="seg-pill__btn"
      :class="{ 'is-on': opt.value === modelValue }"
      role="radio"
      :aria-checked="opt.value === modelValue"
      :tabindex="opt.value === modelValue ? 0 : -1"
      @click="emit('update:modelValue', opt.value)"
      @keydown="onKeydown($event, i)"
    >{{ opt.label }}</button>
  </div>
</template>

<style scoped>
.seg-pill {
  position: relative;
  display: inline-flex;
  width: 100%;
  padding: 3px;
  background: var(--surface-sunken);
  border-radius: 999px; /* 06-modern §6.5：轨道 pill 钉死（radius-lg 升 16 后非全圆） */
}
.seg-pill__thumb {
  position: absolute;
  top: 3px;
  bottom: 3px;
  left: 0;
  border-radius: 999px; /* 同上：thumb 钉全圆 */
  background: var(--surface-float);
  /* transform/width 双过渡，滑动 thumb（§8.7 规格） */
  transition: transform var(--dur-2) var(--ease-out), width var(--dur-2) var(--ease-out);
  pointer-events: none;
}
.seg-pill__btn {
  position: relative;
  z-index: 1;
  flex: 1;
  min-height: calc(var(--control-h-md) - 6px); /* N1 §3.4：轨道高归 --control-h-md（padding 3px） */
  padding: 0 10px;
  font-size: var(--text-xs);
  font-family: inherit;
  border: none;
  background: transparent;
  color: var(--text-secondary);
  cursor: pointer;
  white-space: nowrap;
  transition: color var(--dur-2) var(--ease-out);
}
.seg-pill__btn:hover {
  color: var(--text-primary);
}
.seg-pill__btn.is-on {
  color: var(--text-primary);
  font-weight: 600;
}
</style>
