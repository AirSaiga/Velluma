<script setup lang="ts">
/**
 * 章节定档选择器（V3.1 新建，规格 §9.1）。
 *
 * 职责：定档选择——"章节定档：自动/手动指定"。
 * 引擎固定为 V3.2 ADF（锚点驱动流），不再暴露切换。
 *
 * 四档定义（规格 §2.1）：
 * - auto（自动，推荐）：程序自主定档
 * - climax（高潮章）：大高潮/揭盅/决裂/卷尾
 * - turn（转折章）：中等转折、重要推进
 * - progress（推进章）：小转折、日常推进
 * - transition（过渡章）：纯过渡、衔接
 */

import { ref, watch } from 'vue'

type Tier = 'auto' | 'climax' | 'turn' | 'progress' | 'transition'

const STORAGE_KEY = 'velluma_tier_selection'

const props = withDefaults(defineProps<{
  modelValue?: Tier
}>(), {
  modelValue: 'auto',
})

const emit = defineEmits<{
  (e: 'update:modelValue', value: Tier): void
}>()

// 从 localStorage 恢复定档
const tier = ref<Tier>(props.modelValue)
try {
  const saved = localStorage.getItem(STORAGE_KEY)
  if (saved === 'auto' || saved === 'climax' || saved === 'turn' || saved === 'progress' || saved === 'transition') {
    tier.value = saved
  }
} catch {
  // 忽略 localStorage 异常
}

watch(tier, (val) => {
  try {
    localStorage.setItem(STORAGE_KEY, val)
  } catch {}
  emit('update:modelValue', val)
})

// 同步外部 prop 变化
watch(
  () => props.modelValue,
  (val) => {
    if (val && val !== tier.value) {
      tier.value = val
    }
  }
)

const TIER_OPTIONS: { value: Tier; label: string; title: string }[] = [
  { value: 'auto', label: '自动', title: '程序自主定档（推荐）' },
  { value: 'climax', label: '高潮', title: '大高潮/揭盅/决裂/卷尾' },
  { value: 'turn', label: '转折', title: '中等转折、重要推进' },
  { value: 'progress', label: '推进', title: '小转折、日常推进' },
  { value: 'transition', label: '过渡', title: '纯过渡、衔接' },
]
</script>

<template>
  <div class="tier-selector flex flex-col gap-1.5 text-xs">
    <div class="flex items-center gap-1.5">
      <span class="text-gray-500">定档：</span>
      <div class="flex bg-gray-100 rounded-md p-0.5">
        <button
          v-for="opt in TIER_OPTIONS"
          :key="opt.value"
          class="px-2 py-1 rounded text-xs font-medium transition-all"
          :class="{
            'bg-white text-indigo-600 shadow-sm': tier === opt.value,
            'text-gray-500 hover:text-gray-700': tier !== opt.value,
          }"
          :title="opt.title"
          @click="tier = opt.value"
        >
          {{ opt.label }}
        </button>
      </div>
    </div>
  </div>
</template>
