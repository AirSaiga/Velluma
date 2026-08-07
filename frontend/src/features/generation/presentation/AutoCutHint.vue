<script setup lang="ts">
/**
 * NLE-ADF 2.0 软切淡提示（Auto-Cut Hint）。
 *
 * 无感沉淀的混合处理反馈：作者一气呵成写过头（≥1.2×拍目标）且停顿时，
 * 系统在最近句界收束本拍、余文顺延下一拍——此条极淡琥珀提示浮现 8s：
 * 「已替你在这里喘了口气 · 撤回合并」。点撤回 = back 回退但保留全部文本
 * （本拍目标临时翻倍，防立刻再切）。超时自动消隐，零打扰。
 */
import { computed } from 'vue'
import type { GenerationSession } from '../composables/useGenerationSession'

const props = defineProps<{ session: GenerationSession }>()

const notice = computed(() => props.session.autoCutNotice.value)

function onMerge() {
  props.session.mergeAutoCut()
}

function onDismiss() {
  props.session.autoCutNotice.value = null
}
</script>

<template>
  <Transition name="auto-cut">
    <div v-if="notice" class="auto-cut-hint">
      <span class="auto-cut-hint__icon">✂</span>
      <span class="auto-cut-hint__text">{{ notice.message }}</span>
      <button class="auto-cut-hint__merge" @click="onMerge">撤回合并</button>
      <button class="auto-cut-hint__dismiss" @click="onDismiss">×</button>
    </div>
  </Transition>
</template>

<style scoped>
.auto-cut-hint {
  position: fixed;
  bottom: 44px;
  left: 50%;
  transform: translateX(-50%);
  z-index: 70;
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 6px 12px;
  border-radius: 16px;
  background: var(--bg-canvas, #fefdfb);
  border: 1px solid rgba(217, 119, 6, 0.25);
  color: #b45309;
  font-size: 12px;
  opacity: 0.85;
  user-select: none;
}

.auto-cut-hint__merge {
  background: none;
  border: none;
  color: #34d399;
  font-size: 12px;
  cursor: pointer;
  padding: 0 4px;
}

.auto-cut-hint__merge:hover {
  text-decoration: underline;
}

.auto-cut-hint__dismiss {
  background: none;
  border: none;
  color: var(--text-muted, #a89e90);
  font-size: 13px;
  cursor: pointer;
  padding: 0 2px;
}

.auto-cut-enter-active {
  transition: opacity 0.25s ease, transform 0.25s ease;
}
.auto-cut-leave-active {
  transition: opacity 0.3s ease;
}
.auto-cut-enter-from,
.auto-cut-leave-to {
  opacity: 0;
  transform: translateX(-50%) translateY(6px);
}
</style>
