<script setup lang="ts">
/**
 * 故事基础信息面板
 * 
 * 职责：
 * - 收集书名、类型、风格等基础信息
 * - 提供故事类型模板快捷选择
 * - 专家模式下显示核心主题与禁忌
 */
import { computed } from 'vue'
import type { StoryBasics, StoryTemplate, ValidationError } from '../types/wizard.types'

// =------------- Props & Emits -------------=

const props = defineProps<{
  formData: { story: StoryBasics }
  isExpertMode: boolean
  errors: ValidationError[]
  storyTemplates: StoryTemplate[]
}>()

const emit = defineEmits<{
  (e: 'update:story', updates: Partial<StoryBasics>): void
  (e: 'apply-template', template: StoryTemplate): void
}>()

// =------------- 计算属性 -------------=

const story = computed(() => props.formData.story)

const fieldErrors = computed(() => {
  const map = new Map<string, string>()
  for (const err of props.errors) {
    if (err.field.startsWith('story.')) {
      map.set(err.field.replace('story.', ''), err.message)
    }
  }
  return map
})

// =------------- 方法 -------------=

function updateField(field: keyof StoryBasics, value: string) {
  emit('update:story', { [field]: value })
}

function applyTemplate(template: StoryTemplate) {
  emit('apply-template', template)
}
</script>

<template>
  <div class="story-basics-panel h-full overflow-y-auto p-6">
    <div class="max-w-2xl mx-auto space-y-6">
      
      <!-- 标题 -->
      <div class="text-center mb-8">
        <h2 class="text-2xl font-heading font-semibold text-[var(--text-primary)] mb-2">
          让我们开始创作吧 🎉
        </h2>
        <p class="text-sm text-[var(--text-muted)]">
          填写故事的基本信息，帮助 AI 更好地理解你的创作意图
        </p>
      </div>
      
      <!-- 快速模板选择 -->
      <div class="mb-6">
        <label class="block text-sm font-medium text-[var(--text-primary)] mb-2">
          快速开始：选择故事类型
        </label>
        <div class="grid grid-cols-3 gap-2">
          <button
            v-for="template in storyTemplates"
            :key="template.id"
            @click="applyTemplate(template)"
            :class="[
              'px-3 py-2 rounded-xl text-sm transition-all border',
              story.genre === template.genre
                ? 'bg-accent-500/15 border-accent-500 text-accent-700'
                : 'bg-[var(--bg-panel)] border-[var(--border-color)]/50 text-[var(--text-primary)] hover:border-accent-500/50'
            ]"
          >
            {{ template.name }}
          </button>
        </div>
        <p class="text-xs text-[var(--text-muted)] mt-2">
          点击可快速应用类型预设（风格、节奏等）
        </p>
      </div>
      
      <!-- 书名 -->
      <div>
        <label class="block text-sm font-medium text-[var(--text-primary)] mb-2">
          书名 <span class="text-rose-500">*</span>
        </label>
        <input
          :value="story.title"
          @input="updateField('title', ($event.target as HTMLInputElement).value)"
          type="text"
          placeholder="你的故事叫什么名字？"
          class="w-full px-4 py-3 bg-[var(--bg-panel)] rounded-xl text-[var(--text-primary)] placeholder-[var(--text-muted)] text-base focus:outline-none ring-1 ring-[var(--border-color)] focus:ring-2 focus:ring-[var(--accent-500)]/40"
          :class="{ 'ring-rose-500': fieldErrors.get('title') }"
        />
        <p v-if="fieldErrors.get('title')" class="text-xs text-rose-500 mt-1">
          {{ fieldErrors.get('title') }}
        </p>
      </div>
      
      <!-- 故事类型 -->
      <div>
        <label class="block text-sm font-medium text-[var(--text-primary)] mb-2">
          故事类型 <span class="text-rose-500">*</span>
        </label>
        <div class="flex gap-2">
          <input
            :value="story.genre"
            @input="updateField('genre', ($event.target as HTMLInputElement).value)"
            type="text"
            placeholder="如：奇幻、科幻、都市、悬疑..."
            class="flex-1 px-4 py-3 bg-[var(--bg-panel)] rounded-xl text-[var(--text-primary)] placeholder-[var(--text-muted)] text-base focus:outline-none ring-1 ring-[var(--border-color)] focus:ring-2 focus:ring-[var(--accent-500)]/40"
            :class="{ 'ring-rose-500': fieldErrors.get('genre') }"
          />
          <select
            :value="story.genre"
            @change="updateField('genre', ($event.target as HTMLSelectElement).value)"
            class="px-3 py-3 bg-[var(--bg-panel)] rounded-xl text-[var(--text-primary)] focus:outline-none ring-1 ring-[var(--border-color)] focus:ring-2 focus:ring-[var(--accent-500)]/40"
          >
            <option value="">选择类型</option>
            <option v-for="t in storyTemplates" :key="t.id" :value="t.genre">{{ t.genre }}</option>
          </select>
        </div>
        <p v-if="fieldErrors.get('genre')" class="text-xs text-rose-500 mt-1">
          {{ fieldErrors.get('genre') }}
        </p>
      </div>
      
      <!-- 写作风格指南已退役（2026-09-05）：原写 books.global_sys_prompt，
           消费方全部不在活路；文风意图请到文风页配置（样本/旋钮/画像） -->

      <!-- 核心主题与禁忌（仅专家模式） -->
      <Transition name="expand">
        <div v-if="isExpertMode" class="pt-4 border-t border-[var(--border-color)]/30">
          <label class="block text-sm font-medium text-[var(--text-primary)] mb-2">
            <span class="flex items-center gap-1.5">
              <span class="px-1.5 py-0.5 text-[10px] bg-amber-500/10 text-amber-600 rounded">专家</span>
              核心主题与禁忌
            </span>
          </label>
          <textarea
            :value="story.themesAndTaboos"
            @input="updateField('themesAndTaboos', ($event.target as HTMLTextAreaElement).value)"
            rows="4"
            placeholder="列出本书的核心主题、反复出现的意象，以及绝对不能出现的情节或风格...&#10;&#10;示例：&#10;核心主题：成长与救赎&#10;禁忌：不要出现过于血腥的暴力描写"
            class="w-full px-4 py-3 bg-[var(--bg-panel)] rounded-xl text-[var(--text-primary)] placeholder-[var(--text-muted)] text-sm focus:outline-none ring-1 ring-[var(--border-color)] focus:ring-2 focus:ring-[var(--accent-500)]/40 resize-none"
          />
          <p class="text-xs text-[var(--text-muted)] mt-1">
            <strong class="text-amber-600">内部字段：</strong>core_motifs_taboos — 定义故事的深层主题和创作边界
          </p>
        </div>
      </Transition>
      
      <!-- 提示信息 -->
      <div class="bg-accent-500/5 rounded-xl p-4 mt-6">
        <div class="flex items-start gap-3">
          <span class="text-lg">💡</span>
          <div class="text-sm text-[var(--text-secondary)]">
            <p class="font-medium mb-1">小贴士</p>
            <p class="text-xs text-[var(--text-muted)]">
              故事类型和风格指南会影响 AI 的生成方向。如果不确定如何填写，
              可以先选择一个类型模板，后续再根据需要调整。
            </p>
          </div>
        </div>
      </div>
      
    </div>
  </div>
</template>

<style scoped>
.expand-enter-active,
.expand-leave-active {
  transition: all 0.3s ease;
  overflow: hidden;
}

.expand-enter-from,
.expand-leave-to {
  opacity: 0;
  max-height: 0;
}

.expand-enter-to,
.expand-leave-from {
  max-height: 500px;
}
</style>
