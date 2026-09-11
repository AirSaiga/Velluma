<script setup lang="ts">
/**
 * NLE-ADF 3.0 思考指示器——光标处脉冲点。
 *
 * 两态（phase）：
 * - idle：不渲染
 * - perceiving：显式动作（Space/Tab/burst/点火/细纲扩写）已发，后端在算——
 *   薄荷色强脉冲。停顿自动亮灯已退役（2026-09-10，Tab 唯一入口）：
 *   后台感知保持安静，不再在光标处亮「AI 要凑过来了」的承诺点。
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
</script>

<template>
  <Teleport to="body">
    <Transition name="thinking-dot">
      <div
        v-if="visible"
        class="thinking-dot"
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
  background: #34d399;  /* mint-400，与幽灵草稿同语义色 */
  opacity: 1;
  animation: thinking-pulse 1s ease-in-out infinite;
}

.thinking-dot__ring {
  position: absolute;
  inset: -3px;
  border-radius: 50%;
  border: 1.5px solid transparent;
  opacity: 0;
  border-color: rgba(52, 211, 153, 0.5);
  animation: thinking-ring 1.4s ease-out infinite;
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
