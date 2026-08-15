<script setup lang="ts">
/**
 * NLE-ADF 点火卡（Ignition Card）——空章冷启动入口。
 *
 * 显示时机（由 WorkspaceView 编排）：章内容为空白 + 无生成进行中 + 无幽灵草稿。
 * 定位是"破纸"：把作者从空白页捞出来，产出开篇引子（2-5 段幽灵草稿），
 * 不是整章生成。采纳语法沿用幽灵草稿全家桶（Enter 落地 / Esc 蒸发 / 可重 roll）。
 *
 * 有大纲 → 提供「写个开头」；无大纲 → 只给引导文案（大纲是点火的唯一燃料）。
 */
defineProps<{
  hasOutline: boolean
}>()

const emit = defineEmits<{
  /** 点击「写个开头」→ 触发点火生成 */
  ignite: []
  /** 点击「我自己写」→ 本章内关闭（切章重置） */
  dismiss: []
}>()
</script>

<template>
  <div class="ignition-card" @mousedown.prevent>
    <template v-if="hasOutline">
      <div class="ignition-card__title">本章还是白纸</div>
      <div class="ignition-card__sub">大纲已就绪，可以让 AI 帮你开个头</div>
      <div class="ignition-card__actions">
        <button class="ignition-card__btn ignition-card__btn--primary" @click="emit('ignite')">
          ⚡ 写个开头
        </button>
        <button class="ignition-card__btn" @click="emit('dismiss')">我自己写</button>
      </div>
      <div class="ignition-card__hint">生成的是幽灵草稿：Enter 落地 · Esc 蒸发 · 落地后随时可改</div>
    </template>
    <template v-else>
      <div class="ignition-card__title">本章还是白纸</div>
      <div class="ignition-card__sub">先去「规划」写两句大纲，就能让 AI 帮你开个头</div>
      <div class="ignition-card__actions">
        <button class="ignition-card__btn" @click="emit('dismiss')">我自己写</button>
      </div>
    </template>
  </div>
</template>

<style scoped>
/* 画布中央淡卡（与 Spark/Beat Dock 同族磨砂风格，Cyber-Parchment Dark 双主题） */
.ignition-card {
  position: absolute;
  left: 50%;
  top: 38%;
  transform: translate(-50%, -50%);
  z-index: 10;
  width: min(360px, 80%);
  border-radius: 12px;
  background: var(--bg-canvas, #fefdfb);
  border: 1px solid var(--border-color, #e0dbd3);
  box-shadow: 0 8px 28px rgba(0, 0, 0, 0.08);
  padding: 18px 20px 14px;
  text-align: center;
  user-select: none;
}

:root.dark .ignition-card {
  background: rgba(30, 32, 37, 0.92);
  border-color: #2a2d35;
  backdrop-filter: blur(8px);
  box-shadow: 0 8px 28px rgba(0, 0, 0, 0.3);
}

.ignition-card__title {
  font-size: 14px;
  font-weight: 600;
  color: var(--text-primary, #2c2c2c);
}

.ignition-card__sub {
  margin-top: 4px;
  font-size: 12px;
  color: var(--text-muted, #a89e90);
}

.ignition-card__actions {
  margin-top: 12px;
  display: flex;
  justify-content: center;
  gap: 8px;
}

.ignition-card__btn {
  padding: 6px 14px;
  border: 1px solid var(--border-color, #e0dbd3);
  border-radius: 8px;
  background: var(--bg-secondary, #faf8f4);
  color: var(--text-secondary, #6b6560);
  font-size: 12.5px;
  cursor: pointer;
  transition: background 0.12s ease, border-color 0.12s ease;
}

.ignition-card__btn:hover {
  background: var(--hover-bg, #eee9df);
}

.ignition-card__btn--primary {
  background: var(--accent-500, #7c6aad);
  border-color: var(--accent-500, #7c6aad);
  color: #fff;
}

.ignition-card__btn--primary:hover {
  background: var(--accent-600, #6d5dab);
}

.ignition-card__hint {
  margin-top: 10px;
  font-size: 10.5px;
  color: var(--text-muted, #a89e90);
}
</style>
