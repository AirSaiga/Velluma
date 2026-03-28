<template>
  <div class="expert-panel" v-if="isExpanded">
    <div class="panel-header">
      <h4 class="panel-title">专家模式覆盖</h4>
      <button class="reset-btn" @click="clearAllOverrides">重置所有</button>
    </div>
    
    <div class="override-list">
      <div v-for="field in overridableFields" :key="field.key" class="override-item">
        <div class="override-label">
          <span>{{ field.label }}</span>
          <span class="override-hint">{{ field.hint }}</span>
        </div>
        
        <div class="override-control">
          <select 
            v-if="field.type === 'select'"
            :value="getOverrideValue(field.key)"
            @change="handleOverride(field.key, ($event.target as HTMLSelectElement).value)"
          >
            <option v-for="opt in field.options" :key="opt.value" :value="opt.value">
              {{ opt.label }}
            </option>
          </select>
          
          <input
            v-else-if="field.type === 'number'"
            type="number"
            :min="field.min"
            :max="field.max"
            :value="getOverrideValue(field.key)"
            @input="handleOverride(field.key, Number(($event.target as HTMLInputElement).value))"
          />
          
          <label v-else-if="field.type === 'boolean'" class="switch">
            <input
              type="checkbox"
              :checked="getOverrideValue(field.key)"
              @change="handleOverride(field.key, ($event.target as HTMLInputElement).checked)"
            />
            <span class="slider"></span>
          </label>
        </div>
        
        <div class="override-status" v-if="isOverridden(field.key)">
          <span class="modified-badge">已修改</span>
          <button class="revert-btn" @click="clearOverride(field.key)">还原</button>
        </div>
      </div>
    </div>
    
    <div class="warning-banner" v-if="hasOverrides">
      ⚠️ 您已手动覆盖 {{ overrideCount }} 个参数，这可能影响系统推荐的意图效果。
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { useIntentDrivenConfig } from '../useIntentDrivenConfig'
import type { GenerationPolicy } from '@/types/intentDriven'

const props = defineProps<{
  isExpanded: boolean
  recommendedPolicy: GenerationPolicy | null
}>()

const { userOverrides, hasOverrides, overrideCount, setOverride, clearOverride, clearAllOverrides } = useIntentDrivenConfig()

const overridableFields = computed(() => [
  {
    key: 'tension_level',
    label: '张力等级',
    hint: '1-5',
    type: 'number',
    min: 1,
    max: 5
  },
  {
    key: 'pacing_style',
    label: '节奏偏好',
    hint: '',
    type: 'select',
    options: [
      { value: 'slow_burn', label: '慢热' },
      { value: 'balanced', label: '平衡' },
      { value: 'fast_paced', label: '快节奏' }
    ]
  },
  {
    key: 'memory_span',
    label: '记忆跨度',
    hint: '',
    type: 'select',
    options: [
      { value: 'recent_only', label: '仅看近期' },
      { value: 'balanced_reference', label: '正常参考' },
      { value: 'deep_dive', label: '深挖伏笔' }
    ]
  },
  {
    key: 'creativity_level',
    label: '创作自由度',
    hint: '',
    type: 'select',
    options: [
      { value: 'strict_prompt', label: '紧扣提示词' },
      { value: 'balanced_creation', label: '均衡发展' },
      { value: 'wild_imagination', label: '天马行空' }
    ]
  },
  {
    key: 'refinement_depth',
    label: '精修深度',
    hint: '',
    type: 'select',
    options: [
      { value: 'light', label: '轻度' },
      { value: 'standard', label: '标准' },
      { value: 'deep', label: '深度' }
    ]
  },
  {
    key: 'enable_dual_track',
    label: '启用双轨生成',
    hint: '提高连贯性',
    type: 'boolean'
  }
])

function getOverrideValue(key: string): any {
  if (userOverrides.value[key]) {
    return userOverrides.value[key].current
  }
  return props.recommendedPolicy?.[key as keyof GenerationPolicy] ?? null
}

function handleOverride(key: string, value: any): void {
  const original = props.recommendedPolicy?.[key as keyof GenerationPolicy]
  setOverride(key, value, original)
}

function isOverridden(key: string): boolean {
  return !!userOverrides.value[key]
}
</script>

<style scoped>
.expert-panel {
  margin-top: 1rem;
  padding: 1rem;
  background: #f9fafb;
  border-radius: 0.5rem;
  border: 1px solid #e5e7eb;
}

.panel-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 1rem;
}

.panel-title {
  font-size: 0.875rem;
  font-weight: 600;
  color: #374151;
}

.reset-btn {
  font-size: 0.75rem;
  color: #3b82f6;
  background: none;
  border: none;
  cursor: pointer;
}

.reset-btn:hover {
  text-decoration: underline;
}

.override-list {
  display: flex;
  flex-direction: column;
  gap: 0.75rem;
}

.override-item {
  display: flex;
  align-items: center;
  gap: 1rem;
}

.override-label {
  flex: 1;
}

.override-label span:first-child {
  font-size: 0.875rem;
  font-weight: 500;
  color: #374151;
}

.override-hint {
  margin-left: 0.5rem;
  font-size: 0.75rem;
  color: #9ca3af;
}

.override-control select,
.override-control input[type="number"] {
  width: 8rem;
  padding: 0.375rem 0.5rem;
  font-size: 0.875rem;
  border: 1px solid #d1d5db;
  border-radius: 0.375rem;
}

.override-control input[type="number"] {
  width: 5rem;
}

.override-status {
  display: flex;
  align-items: center;
  gap: 0.5rem;
}

.modified-badge {
  font-size: 0.75rem;
  padding: 0.125rem 0.375rem;
  background: #fef3c7;
  color: #92400e;
  border-radius: 0.25rem;
}

.revert-btn {
  font-size: 0.75rem;
  color: #6b7280;
  background: none;
  border: none;
  cursor: pointer;
}

.revert-btn:hover {
  color: #3b82f6;
}

.warning-banner {
  margin-top: 1rem;
  padding: 0.5rem;
  background: #fef3c7;
  border: 1px solid #fcd34d;
  border-radius: 0.375rem;
  font-size: 0.75rem;
  color: #92400e;
}

.switch {
  position: relative;
  display: inline-block;
  width: 2.5rem;
  height: 1.25rem;
}

.switch input {
  opacity: 0;
  width: 0;
  height: 0;
}

.slider {
  position: absolute;
  cursor: pointer;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  background-color: #d1d5db;
  border-radius: 1.25rem;
  transition: 0.3s;
}

.slider::before {
  position: absolute;
  content: "";
  height: 1rem;
  width: 1rem;
  left: 0.125rem;
  bottom: 0.125rem;
  background-color: white;
  border-radius: 50%;
  transition: 0.3s;
}

.switch input:checked + .slider {
  background-color: #3b82f6;
}

.switch input:checked + .slider::before {
  transform: translateX(1.25rem);
}
</style>
