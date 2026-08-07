<script setup lang="ts">
/**
 * NLE-ADF 3.0 思考指示器——光标处脉冲点。
 *
 * 三态（phase）：
 * - idle：不渲染
 * - waiting：停顿 ≥2s 但停顿心跳未发——淡灰小点，预示「再停一下 AI 要凑过来了」
 * - perceiving：停顿心跳 / stitch 已发，后端在算——彩色（薄荷）强脉冲
 *
 * 形态：光标正下方一个 8px 圆点，跟随光标坐标（thinkingPos）定位。
 * 与 SparkDock / GhostDraft 互斥（Dock 弹出或幽灵出现时组件层不显示）。
 */
import { computed } from 'vue'
import {
  thinkingPhase,
  thinkingPos,
} from '../composables/useThinkingIndicator'
import { sparkDockVisible } from '../composables/useSparkDock'
import { ghostActive } from '../composables/useGhostDraft'

const visible = computed(() =>
  thinkingPhase.value !== 'idle'
  && !sparkDockVisible.value
  && !ghostActive.value,
)

const style = computed(() => ({
  top: `${thinkingPos.value.top}px`,
  left: `${thinkingPos.value.left}px`,
}))

const isPerceiving = computed(() => thinkingPhase.value === 'perceiving')
</script>

<template>
  <Teleport to="body">
    <Transition name="thinking-dot">
      <div
        v-if="visible"
        class="thinking-dot"
        :class="{ 'thinking-dot--strong': isPerceiving }"
        :style="style"
        aria-hidden="true"
      >
        <span class="thinking-dot__core"></span>
        <span class="thinking-dot__ring"></span>
      </div>
    </Transition>
  </Teleport>
</template>

<style scoped>
.thinking-dot {
  position: fixed;
  z-index: 89;  /* 略低于 spark-dock(90)，Dock 弹出会盖住 */
  width: 8px;
  height: 8px;
  pointer-events: none;
  /* 圆点中心对齐光标 left（光标 left 是字符左边缘，圆点视觉中心略偏右一点更贴合） */
  transform: translate(-1px, 0);
}

.thinking-dot__core {
  position: absolute;
  inset: 0;
  border-radius: 50%;
  background: var(--text-muted, #a89e90);
  opacity: 0.5;
  transition: background 0.2s ease, opacity 0.2s ease;
}

/* 弱态呼吸（淡灰）：缓慢明暗，暗示「等待中」 */
.thinking-dot:not(.thinking-dot--strong) .thinking-dot__core {
  animation: thinking-breathe 1.6s ease-in-out infinite;
}

.thinking-dot__ring {
  position: absolute;
  inset: -3px;
  border-radius: 50%;
  border: 1.5px solid transparent;
  opacity: 0;
}

/* 强态（perceiving）：薄荷色 + 扩散环 */
.thinking-dot--strong .thinking-dot__core {
  background: #34d399;  /* mint-400，与幽灵草稿同语义色 */
  opacity: 1;
  animation: thinking-pulse 1s ease-in-out infinite;
}

.thinking-dot--strong .thinking-dot__ring {
  border-color: rgba(52, 211, 153, 0.5);
  animation: thinking-ring 1.4s ease-out infinite;
}

:root.dark .thinking-dot:not(.thinking-dot--strong) .thinking-dot__core {
  background: #6b7280;
}

@keyframes thinking-breathe {
  0%, 100% { opacity: 0.35; }
  50% { opacity: 0.65; }
}

@keyframes thinking-pulse {
  0%, 100% { transform: scale(1); }
  50% { transform: scale(1.25); }
}

@keyframes thinking-ring {
  0% { transform: scale(0.8); opacity: 0.6; }
  100% { transform: scale(1.8); opacity: 0; }
}

/* 淡入（120ms，比 spark-dock 略快——指示器要立刻可见） */
.thinking-dot-enter-active {
  transition: opacity 0.12s ease;
}
.thinking-dot-leave-active {
  transition: opacity 0.15s ease;
}
.thinking-dot-enter-from,
.thinking-dot-leave-to {
  opacity: 0;
}
</style>
