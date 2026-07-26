<script setup lang="ts">
/**
 * BS-ADF 渲染轨道选择器（V5 新建）。
 *
 * 双选 toggle：
 * - A 自动：槽位卡生成后直接渲染，无介入（全自动跑到底）
 * - B 介入：槽位卡生成后暂停，作者可编辑槽位词再渲染（HITL）
 *
 * 照搬 TierSelector 的视觉语言与 modelValue 模式，简化为两个选项。
 */
import { ref, watch } from 'vue'

type Track = 'A' | 'B'

const props = withDefaults(defineProps<{
  modelValue?: Track
}>(), {
  modelValue: 'A',
})

const emit = defineEmits<{
  (e: 'update:modelValue', value: Track): void
}>()

const inner = ref<Track>(props.modelValue)

// 同步外部 prop 变化
watch(
  () => props.modelValue,
  (v) => {
    if (v && v !== inner.value) inner.value = v
  },
)

function select(t: Track) {
  if (inner.value === t) return
  inner.value = t
  emit('update:modelValue', t)
}

const TRACK_OPTIONS: { value: Track; letter: string; label: string; title: string }[] = [
  { value: 'A', letter: 'A', label: '自动', title: '全自动：槽位卡生成后直接渲染，无介入' },
  { value: 'B', letter: 'B', label: '介入', title: '作者介入：槽位卡生成后暂停，可编辑槽位词再渲染' },
]
</script>

<template>
  <div class="track-selector flex flex-col gap-1.5 text-xs">
    <div class="flex items-center gap-1.5">
      <span class="text-gray-500">轨道：</span>
      <div class="track-options flex bg-gray-100 rounded-md p-0.5">
        <button
          v-for="opt in TRACK_OPTIONS"
          :key="opt.value"
          class="track-btn flex items-center gap-1 px-2 py-1 rounded text-xs font-medium transition-all"
          :class="{
            'bg-white text-indigo-600 shadow-sm': inner === opt.value,
            'text-gray-500 hover:text-gray-700': inner !== opt.value,
          }"
          :title="opt.title"
          @click="select(opt.value)"
        >
          <span class="track-letter font-semibold">{{ opt.letter }}</span>
          <span>{{ opt.label }}</span>
        </button>
      </div>
    </div>
  </div>
</template>
