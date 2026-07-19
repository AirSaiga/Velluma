<template>
  <div class="expert-panel">
    <!-- 面板头部 -->
    <div class="panel-header">
      <div class="header-info">
        <div class="header-icon">
          <Icon name="settings" :size="16" />
        </div>
        <div class="header-text">
          <span class="header-title">高级微调</span>
          <span class="header-desc">覆盖基础调整中的默认值</span>
        </div>
      </div>
    </div>

    <!-- 参数列表 -->
    <div class="params-list">
      <!-- 字数覆盖 -->
      <div class="param-item">
        <div class="param-info">
          <div class="param-label">
            <span class="label-text">本章篇幅</span>
            <span class="label-hint">字</span>
          </div>
        </div>
        <div class="param-control">
          <div class="number-control">
            <button
              type="button"
              class="number-btn"
              @click="adjustWordCount(-500)"
              :disabled="overrideWordCount <= 500"
            >
              <svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="1.5">
                <path stroke-linecap="round" stroke-linejoin="round" d="M20 12H4" />
              </svg>
            </button>
            <input
              type="number"
              :min="500"
              :max="10000"
              :value="overrideWordCount"
              @input="setOverrideWordCount(Number(($event.target as HTMLInputElement).value))"
              class="number-input"
            />
            <button
              type="button"
              class="number-btn"
              @click="adjustWordCount(500)"
              :disabled="overrideWordCount >= 10000"
            >
              <svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="1.5">
                <path stroke-linecap="round" stroke-linejoin="round" d="M12 4v16m8-8H4" />
              </svg>
            </button>
          </div>
        </div>
      </div>

      <!-- 作者意图覆盖 -->
      <div class="param-item full-width">
        <div class="param-info">
          <div class="param-label">
            <span class="label-text">附加说明</span>
            <span class="label-hint">对生成内容的额外要求</span>
          </div>
        </div>
        <div class="param-control">
          <textarea
            :value="overrideAuthorIntent"
            @input="setOverrideAuthorIntent(($event.target as HTMLTextAreaElement).value)"
            class="sleek-textarea"
            placeholder="例如：增加悬疑感、强化反派气场、减少环境描写..."
            rows="3"
          ></textarea>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, watch } from 'vue'
import Icon from '@/components/Icon.vue'
import { useIntentDrivenConfig } from '../useIntentDrivenConfig'

const props = defineProps<{
  defaultWordCount: number
  defaultAuthorIntent: string
}>()

const emit = defineEmits<{
  updateWordCount: [value: number]
  updateAuthorIntent: [value: string]
}>()

const { wordCount, authorIntent } = useIntentDrivenConfig()

const overrideWordCount = ref(props.defaultWordCount)
const overrideAuthorIntent = ref(props.defaultAuthorIntent)

watch(() => props.defaultWordCount, (v) => { overrideWordCount.value = v })
watch(() => props.defaultAuthorIntent, (v) => { overrideAuthorIntent.value = v })

function adjustWordCount(delta: number) {
  const newVal = Math.max(500, Math.min(10000, overrideWordCount.value + delta))
  overrideWordCount.value = newVal
  emit('updateWordCount', newVal)
}

function setOverrideWordCount(val: number) {
  const newVal = Math.max(500, Math.min(10000, val))
  overrideWordCount.value = newVal
  emit('updateWordCount', newVal)
}

function setOverrideAuthorIntent(val: string) {
  overrideAuthorIntent.value = val
  emit('updateAuthorIntent', val)
}
</script>

<style scoped>
.expert-panel {
  padding: 1rem;
  background: var(--bg-secondary, #faf8f4);
  border-top: 1px solid var(--border-color, #e0dbd3);
}

.panel-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 0.875rem;
  padding: 0.25rem 0 0.625rem;
  border-bottom: 1px dashed var(--border-color, #e0dbd3);
}

.header-info {
  display: flex;
  align-items: center;
  gap: 0.5rem;
}

.header-icon {
  width: 1.75rem;
  height: 1.75rem;
  border-radius: 8px;
  background: rgba(124, 106, 173, 0.1);
  color: var(--accent-500, #7c6aad);
  display: inline-flex;
  align-items: center;
  justify-content: center;
}

.header-text {
  display: flex;
  flex-direction: column;
  gap: 0;
}

.header-title {
  font-size: 13px;
  font-weight: 700;
  color: var(--text-primary, #2c2c2c);
}

.header-desc {
  font-size: 11px;
  color: var(--text-muted, #a89e90);
}

.params-list {
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
}

.param-item {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 1rem;
  padding: 0.75rem 1rem;
  background: var(--bg-panel, #f0ece3);
  border: 1px solid var(--border-color, #e0dbd3);
  border-radius: 10px;
  transition: all 0.2s ease;
}

.param-item:hover {
  border-color: var(--hover-bg, #eee9df);
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.03);
}

.param-item.full-width {
  flex-direction: column;
}

.param-info {
  flex: 1;
  min-width: 0;
}

.param-label {
  display: flex;
  align-items: center;
  gap: 0.375rem;
  flex-wrap: wrap;
}

.label-text {
  font-size: 13px;
  font-weight: 500;
  color: var(--text-primary, #2c2c2c);
}

.label-hint {
  font-size: 11px;
  color: var(--text-muted, #a89e90);
}

.param-control {
  flex-shrink: 0;
}

.number-control {
  display: flex;
  align-items: center;
  background: var(--bg-canvas, #fefdfb);
  border: 1px solid var(--border-color, #e0dbd3);
  border-radius: 8px;
  overflow: hidden;
}

.number-btn {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 1.75rem;
  height: 1.75rem;
  padding: 0;
  color: var(--text-secondary, #6b6560);
  background: transparent;
  border: none;
  cursor: pointer;
  transition: all 0.15s ease;
}

.number-btn:hover:not(:disabled) {
  background: var(--accent-500, #7c6aad);
  color: white;
}

.number-btn:disabled {
  color: var(--text-muted, #a89e90);
  cursor: not-allowed;
  opacity: 0.4;
}

.number-input {
  width: 3.5rem;
  padding: 0;
  font-size: 14px;
  font-weight: 600;
  color: var(--text-primary, #2c2c2c);
  text-align: center;
  background: transparent;
  border: none;
  -moz-appearance: textfield;
}

.number-input::-webkit-outer-spin-button,
.number-input::-webkit-inner-spin-button {
  -webkit-appearance: none;
  margin: 0;
}

.number-input:focus {
  outline: none;
}

.sleek-textarea {
  width: 100%;
  padding: 0.625rem 0.875rem;
  background: var(--bg-canvas, #fefdfb);
  border: 1px solid var(--border-color, #e0dbd3);
  border-radius: 8px;
  font-size: 13px;
  color: var(--text-primary, #2c2c2c);
  resize: vertical;
  min-height: 64px;
  transition: all 0.2s ease;
  line-height: 1.5;
}

.sleek-textarea:focus {
  outline: none;
  background: white;
  border-color: var(--accent-500, #7c6aad);
  box-shadow: 0 0 0 3px rgba(124, 106, 173, 0.1);
}

.sleek-textarea::placeholder {
  color: var(--text-muted, #a89e90);
}

/* 深色模式 */
@media (prefers-color-scheme: dark) {
  .expert-panel {
    background: var(--bg-secondary, #211f1b);
    border-color: var(--border-color, #3a3530);
  }

  .panel-header {
    border-color: var(--border-color, #3a3530);
  }

  .header-icon {
    background: rgba(167, 139, 250, 0.15);
    color: var(--accent-500, #a78bfa);
  }

  .header-title {
    color: var(--text-primary, #ede8df);
  }

  .header-desc {
    color: var(--text-muted, #8a8275);
  }

  .param-item {
    background: var(--bg-panel, #2c2923);
    border-color: var(--border-color, #3a3530);
  }

  .param-item:hover {
    border-color: var(--hover-bg, #33302a);
  }

  .label-text {
    color: var(--text-primary, #ede8df);
  }

  .number-control {
    background: var(--bg-canvas, #1e1c18);
    border-color: var(--border-color, #3a3530);
  }

  .number-btn {
    color: var(--text-muted, #8a8275);
  }

  .number-btn:hover:not(:disabled) {
    background: var(--accent-500, #a78bfa);
    color: white;
  }

  .number-btn:disabled {
    color: var(--text-muted, #8a8275);
  }

  .number-input {
    color: var(--text-primary, #ede8df);
  }

  .sleek-textarea {
    background: var(--bg-canvas, #1e1c18);
    border-color: var(--border-color, #3a3530);
    color: var(--text-primary, #ede8df);
  }

  .sleek-textarea:focus {
    background: #0f0e0c;
    border-color: var(--accent-500, #a78bfa);
    box-shadow: 0 0 0 3px rgba(167, 139, 250, 0.15);
  }
}
</style>
