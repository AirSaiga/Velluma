<template>
  <div class="intent-panel">
    <PanelSection title="本章类型" icon="sparkles">
      <div class="type-grid">
        <button
          v-for="t in types"
          :key="t.id"
          type="button"
          class="type-btn"
          :class="{ active: chapterType === t.id }"
          @click="setChapterType(t.id)"
        >
          <Icon :name="t.icon" :size="16" />
          <span>{{ t.label }}</span>
        </button>
      </div>
    </PanelSection>

    <PanelSection title="本章篇幅">
      <div class="word-control">
        <button class="word-step" @click="setWordCount(Math.max(500, wordCount - 500))">
          <Icon name="minus" :size="14" />
        </button>
        <span class="word-display">{{ wordCount.toLocaleString() }}<i>字</i></span>
        <button class="word-step" @click="setWordCount(Math.min(10000, wordCount + 500))">
          <Icon name="plus" :size="14" />
        </button>
      </div>
    </PanelSection>

    <PanelSection title="补充说明">
      <textarea
        :value="authorIntent"
        @input="setAuthorIntent(($event.target as HTMLTextAreaElement).value)"
        class="intent-textarea"
        placeholder="例如：增加悬疑感、强化反派气场..."
        rows="3"
      />
    </PanelSection>

    <div class="panel-actions">
      <button class="action-primary" :disabled="!canSave" @click="handleSave">
        <Icon name="document" :size="14" />
        保存设置
      </button>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import Icon from '@/components/Icon.vue'
import PanelSection from '@/components/panels/PanelSection.vue'
import { useIntentDrivenConfig } from '../useIntentDrivenConfig'
import type { ChapterType } from '@/types/intentDriven'

const props = defineProps<{
  chapterId: string
  apiConfig: {
    api_key: string
    base_url?: string
    model?: string
  }
}>()

const emit = defineEmits<{ save: [payload: any]; generate: [payload: any] }>()

const {
  chapterType, setChapterType,
  wordCount, setWordCount,
  authorIntent, setAuthorIntent,
  buildPayload
} = useIntentDrivenConfig()

const canSave = computed(() => wordCount.value >= 500)

const types: { id: ChapterType; icon: string; label: string }[] = [
  { id: 'emotional', icon: 'heart', label: '情感内心' },
  { id: 'action', icon: 'bolt', label: '动作冲突' },
  { id: 'daily', icon: 'sun', label: '日常过渡' },
  { id: 'suspense', icon: 'magnifying-glass', label: '悬疑推理' },
  { id: 'worldbuilding', icon: 'map', label: '世界观展开' },
]

function handleSave() {
  emit('save', buildPayload({
    chapterId: props.chapterId,
    apiConfig: props.apiConfig,
    wordCount: wordCount.value,
    authorIntent: authorIntent.value
  }))
}
</script>

<style scoped>
.intent-panel {
  display: flex;
  flex-direction: column;
  gap: 16px;
  padding: 12px 16px;
  height: 100%;
  overflow-y: auto;
}

/* 类型选择 */
.type-grid {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
}

.type-btn {
  flex: 1 1 0;
  min-width: 80px;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 4px;
  padding: 10px 4px;
  font-size: 12px;
  font-weight: 500;
  color: var(--text-secondary);
  background: var(--bg-panel);
  border: 1px solid var(--border-color);
  border-radius: 8px;
  cursor: pointer;
  transition: all 0.15s ease;
}

.type-btn:hover {
  background: var(--hover-bg);
}

.type-btn.active {
  background: var(--accent-500);
  border-color: var(--accent-500);
  color: white;
}

/* 字数控制 */
.word-control {
  display: inline-flex;
  align-items: center;
  background: var(--bg-panel);
  border: 1px solid var(--border-color);
  border-radius: 8px;
  overflow: hidden;
}

.word-step {
  width: 32px;
  height: 32px;
  display: flex;
  align-items: center;
  justify-content: center;
  background: transparent;
  border: none;
  color: var(--text-secondary);
  cursor: pointer;
  transition: all 0.15s ease;
}

.word-step:hover {
  background: var(--accent-500);
  color: white;
}

.word-display {
  min-width: 72px;
  text-align: center;
  font-size: 14px;
  font-weight: 600;
  color: var(--accent-500);
  font-variant-numeric: tabular-nums;
  user-select: none;
  padding: 0 8px;
  border-left: 1px solid var(--border-color);
  border-right: 1px solid var(--border-color);
}

.word-display i {
  font-style: normal;
  font-size: 11px;
  font-weight: 400;
  color: var(--text-muted);
  margin-left: 2px;
}

/* 文本框 */
.intent-textarea {
  width: 100%;
  padding: 8px 12px;
  font-size: 13px;
  line-height: 1.5;
  color: var(--text-primary);
  background: var(--bg-panel);
  border: 1px solid var(--border-color);
  border-radius: 8px;
  resize: vertical;
  transition: all 0.2s ease;
  font-family: inherit;
}

.intent-textarea::placeholder {
  color: var(--text-muted);
}

.intent-textarea:focus {
  outline: none;
  border-color: var(--accent-500);
  background: var(--bg-primary);
}

/* 保存按钮 */
.panel-actions {
  margin-top: auto;
  padding-top: 8px;
  border-top: 1px solid var(--border-color);
}

.action-primary {
  width: 100%;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  padding: 8px 16px;
  font-size: 13px;
  font-weight: 500;
  border-radius: 8px;
  border: none;
  cursor: pointer;
  background: var(--accent-500);
  color: white;
  transition: all 0.2s ease;
}

.action-primary:hover:not(:disabled) {
  background: var(--accent-600);
}

.action-primary:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}
</style>
