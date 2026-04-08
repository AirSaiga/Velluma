<template>
  <div v-if="isExpanded" class="expert-panel">
    <!-- 面板头部 -->
    <div class="panel-header">
      <div class="header-info">
        <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 6V4m0 2a2 2 0 100 4m0-4a2 2 0 110 4m-6 8a2 2 0 100-4m0 4a2 2 0 110-4m0 4v2m0-6V4m6 6v10m6-2a2 2 0 100-4m0 4a2 2 0 110-4m0 4v2m0-6V4" />
        </svg>
        <span>参数覆盖</span>
      </div>
      <button 
        v-if="hasOverrides"
        type="button"
        class="reset-btn" 
        @click="clearAllOverrides"
      >
        <svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" />
        </svg>
        重置所有
      </button>
    </div>
    
    <!-- 参数列表 -->
    <div class="params-list">
      <div 
        v-for="field in overridableFields" 
        :key="field.key" 
        class="param-item"
        :class="{ 'is-overridden': isOverridden(field.key) }"
      >
        <div class="param-info">
          <div class="param-label">
            <span class="label-text">{{ field.label }}</span>
            <span v-if="field.hint" class="label-hint">{{ field.hint }}</span>
          </div>
          <div v-if="isOverridden(field.key)" class="param-status">
            <span class="status-badge">已修改</span>
            <button 
              type="button"
              class="revert-btn" 
              @click="clearOverride(field.key)"
              title="恢复默认值"
            >
              <svg class="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M3 10h10a8 8 0 018 8v2M3 10l6 6m-6-6l6-6" />
              </svg>
              恢复
            </button>
          </div>
        </div>
        
        <div class="param-control">
          <!-- 下拉选择 -->
          <div v-if="field.type === 'select'" class="select-wrapper">
            <select 
              :value="getOverrideValue(field.key)"
              @change="handleOverride(field.key, ($event.target as HTMLSelectElement).value)"
            >
              <option 
                v-for="opt in field.options" 
                :key="opt.value" 
                :value="opt.value"
              >
                {{ opt.label }}
              </option>
            </select>
            <svg class="select-arrow" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 9l-7 7-7-7" />
            </svg>
          </div>
          
          <!-- 数字输入 -->
          <div v-else-if="field.type === 'number'" class="number-control">
            <button 
              type="button"
              class="number-btn"
              @click="adjustNumber(field, -1)"
              :disabled="(getOverrideValue(field.key) as number) <= (field.min || 1)"
            >
              <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M20 12H4" />
              </svg>
            </button>
            <input
              type="number"
              :min="field.min"
              :max="field.max"
              :value="getOverrideValue(field.key)"
              @input="handleOverride(field.key, Number(($event.target as HTMLInputElement).value))"
              class="number-input"
            />
            <button 
              type="button"
              class="number-btn"
              @click="adjustNumber(field, 1)"
              :disabled="(getOverrideValue(field.key) as number) >= (field.max || 5)"
            >
              <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 4v16m8-8H4" />
              </svg>
            </button>
          </div>
          
          <!-- 开关 -->
          <label v-else-if="field.type === 'boolean'" class="toggle-switch">
            <input
              type="checkbox"
              :checked="getOverrideValue(field.key)"
              @change="handleOverride(field.key, ($event.target as HTMLInputElement).checked)"
            />
            <span class="toggle-slider">
              <span class="toggle-thumb">
                <svg v-if="getOverrideValue(field.key)" class="w-3 h-3 check-icon" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path stroke-linecap="round" stroke-linejoin="round" stroke-width="3" d="M5 13l4 4L19 7" />
                </svg>
              </span>
            </span>
          </label>
        </div>
      </div>
    </div>
    
    <!-- 警告提示 -->
    <Transition name="slide-down">
      <div v-if="hasOverrides" class="warning-banner">
        <div class="warning-icon">
          <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z" />
          </svg>
        </div>
        <div class="warning-content">
          <span class="warning-title">参数已覆盖</span>
          <span class="warning-desc">您已手动修改 {{ overrideCount }} 个参数，这可能会影响系统推荐的意图效果。</span>
        </div>
      </div>
    </Transition>
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
      { value: 'slow_burn', label: '慢热铺垫' },
      { value: 'balanced', label: '均衡发展' },
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
      { value: 'light', label: '轻度润色' },
      { value: 'standard', label: '标准精修' },
      { value: 'deep', label: '深度打磨' }
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

function adjustNumber(field: any, delta: number) {
  const current = getOverrideValue(field.key) as number
  const newValue = Math.max(field.min || 1, Math.min(field.max || 5, current + delta))
  handleOverride(field.key, newValue)
}
</script>

<style scoped>
.expert-panel {
  padding: 1.25rem;
  background: var(--bg-primary, white);
  border-top: 1px solid var(--border-color, #e2e8f0);
}

/* 面板头部 */
.panel-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 1rem;
}

.header-info {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  font-size: 0.875rem;
  font-weight: 600;
  color: var(--text-secondary, #64748b);
}

.header-info svg {
  color: var(--accent-500, #6366f1);
}

.reset-btn {
  display: flex;
  align-items: center;
  gap: 0.375rem;
  padding: 0.375rem 0.75rem;
  font-size: 0.75rem;
  font-weight: 500;
  color: var(--text-muted, #94a3b8);
  background: var(--bg-canvas, #f1f5f9);
  border: 1px solid var(--border-color, #e2e8f0);
  border-radius: 0.375rem;
  cursor: pointer;
  transition: all 0.2s ease;
}

.reset-btn:hover {
  color: var(--accent-600, #4f46e5);
  background: var(--accent-50, #eef2ff);
  border-color: var(--accent-300, #a5b4fc);
}

/* 参数列表 */
.params-list {
  display: flex;
  flex-direction: column;
  gap: 0.625rem;
}

.param-item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 1rem;
  padding: 0.875rem 1rem;
  background: var(--bg-canvas, #f8fafc);
  border: 1px solid var(--border-color, #e2e8f0);
  border-radius: 0.625rem;
  transition: all 0.2s ease;
}

.param-item:hover {
  background: var(--bg-primary, white);
  border-color: var(--accent-200, #c7d2fe);
}

.param-item.is-overridden {
  background: linear-gradient(135deg, #fefce8 0%, #fef9c3 100%);
  border-color: #fbbf24;
}

/* 参数信息 */
.param-info {
  flex: 1;
  min-width: 0;
}

.param-label {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  flex-wrap: wrap;
}

.label-text {
  font-size: 0.875rem;
  font-weight: 500;
  color: var(--text-primary, #1e293b);
}

.label-hint {
  font-size: 0.75rem;
  color: var(--text-muted, #94a3b8);
}

.param-status {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  margin-top: 0.375rem;
}

.status-badge {
  padding: 0.125rem 0.5rem;
  font-size: 0.6875rem;
  font-weight: 600;
  color: #b45309;
  background: #fef3c7;
  border-radius: 9999px;
}

.revert-btn {
  display: flex;
  align-items: center;
  gap: 0.25rem;
  padding: 0.125rem 0.375rem;
  font-size: 0.6875rem;
  color: var(--text-muted, #94a3b8);
  background: transparent;
  border: none;
  border-radius: 0.25rem;
  cursor: pointer;
  transition: all 0.15s ease;
}

.revert-btn:hover {
  color: var(--accent-600, #4f46e5);
  background: rgba(99, 102, 241, 0.1);
}

/* 参数控制 */
.param-control {
  flex-shrink: 0;
}

/* 下拉选择 */
.select-wrapper {
  position: relative;
}

.select-wrapper select {
  appearance: none;
  padding: 0.5rem 2rem 0.5rem 0.875rem;
  font-size: 0.8125rem;
  color: var(--text-primary, #1e293b);
  background: var(--bg-primary, white);
  border: 1px solid var(--border-color, #cbd5e1);
  border-radius: 0.5rem;
  cursor: pointer;
  min-width: 7rem;
  transition: all 0.2s ease;
}

.select-wrapper select:hover {
  border-color: var(--accent-300, #a5b4fc);
}

.select-wrapper select:focus {
  outline: none;
  border-color: var(--accent-400, #818cf8);
  box-shadow: 0 0 0 3px rgba(99, 102, 241, 0.1);
}

.select-arrow {
  position: absolute;
  right: 0.625rem;
  top: 50%;
  transform: translateY(-50%);
  width: 1rem;
  height: 1rem;
  color: var(--text-muted, #94a3b8);
  pointer-events: none;
}

/* 数字控制 */
.number-control {
  display: flex;
  align-items: center;
  background: var(--bg-primary, white);
  border: 1px solid var(--border-color, #cbd5e1);
  border-radius: 0.5rem;
  overflow: hidden;
}

.number-btn {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 2rem;
  height: 2rem;
  padding: 0;
  color: var(--text-secondary, #64748b);
  background: transparent;
  border: none;
  cursor: pointer;
  transition: all 0.15s ease;
}

.number-btn:hover:not(:disabled) {
  background: var(--accent-50, #eef2ff);
  color: var(--accent-600, #4f46e5);
}

.number-btn:disabled {
  color: var(--text-muted, #cbd5e1);
  cursor: not-allowed;
}

.number-input {
  width: 2.5rem;
  padding: 0;
  font-size: 0.9375rem;
  font-weight: 600;
  color: var(--text-primary, #1e293b);
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

/* 开关 */
.toggle-switch {
  position: relative;
  display: inline-block;
  width: 3rem;
  height: 1.75rem;
  cursor: pointer;
}

.toggle-switch input {
  opacity: 0;
  width: 0;
  height: 0;
}

.toggle-slider {
  position: absolute;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  background: var(--border-color, #cbd5e1);
  border-radius: 9999px;
  transition: all 0.3s ease;
}

.toggle-slider::before {
  content: '';
  position: absolute;
  top: 0.25rem;
  left: 0.25rem;
  width: 1.25rem;
  height: 1.25rem;
  background: white;
  border-radius: 50%;
  transition: all 0.3s ease;
  box-shadow: 0 2px 4px rgba(0,0,0,0.1);
}

.toggle-switch input:checked + .toggle-slider {
  background: var(--accent-500, #6366f1);
}

.toggle-switch input:checked + .toggle-slider::before {
  transform: translateX(1.25rem);
}

.toggle-thumb {
  position: absolute;
  top: 0.25rem;
  left: 0.25rem;
  width: 1.25rem;
  height: 1.25rem;
  display: flex;
  align-items: center;
  justify-content: center;
  background: white;
  border-radius: 50%;
  transition: all 0.3s ease;
}

.toggle-switch input:checked + .toggle-slider .toggle-thumb {
  transform: translateX(1.25rem);
}

.check-icon {
  color: var(--accent-500, #6366f1);
}

/* 警告横幅 */
.warning-banner {
  display: flex;
  align-items: flex-start;
  gap: 0.75rem;
  margin-top: 1rem;
  padding: 0.875rem 1rem;
  background: linear-gradient(135deg, #fef3c7 0%, #fde68a 100%);
  border: 1px solid #fbbf24;
  border-radius: 0.625rem;
}

.warning-icon {
  flex-shrink: 0;
  width: 1.75rem;
  height: 1.75rem;
  display: flex;
  align-items: center;
  justify-content: center;
  background: white;
  color: #d97706;
  border-radius: 50%;
}

.warning-content {
  display: flex;
  flex-direction: column;
  gap: 0.25rem;
}

.warning-title {
  font-size: 0.8125rem;
  font-weight: 600;
  color: #92400e;
}

.warning-desc {
  font-size: 0.75rem;
  color: #b45309;
  line-height: 1.5;
}

/* 动画 */
.slide-down-enter-active,
.slide-down-leave-active {
  transition: all 0.3s ease;
}

.slide-down-enter-from,
.slide-down-leave-to {
  opacity: 0;
  transform: translateY(-8px);
}

/* 深色模式 */
@media (prefers-color-scheme: dark) {
  .expert-panel {
    background: #1e293b;
    border-color: #334155;
  }
  
  .header-info {
    color: #94a3b8;
  }
  
  .reset-btn {
    background: #334155;
    border-color: #475569;
    color: #64748b;
  }
  
  .reset-btn:hover {
    background: #312e81;
    border-color: #4f46e5;
    color: #a5b4fc;
  }
  
  .param-item {
    background: #0f172a;
    border-color: #334155;
  }
  
  .param-item:hover {
    background: #1e293b;
    border-color: #4f46e5;
  }
  
  .param-item.is-overridden {
    background: linear-gradient(135deg, #78350f 0%, #92400e 100%);
    border-color: #fbbf24;
  }
  
  .label-text {
    color: #f1f5f9;
  }
  
  .status-badge {
    background: #fcd34d;
    color: #92400e;
  }
  
  .revert-btn {
    color: #64748b;
  }
  
  .revert-btn:hover {
    color: #a5b4fc;
    background: rgba(99, 102, 241, 0.2);
  }
  
  .select-wrapper select,
  .number-control {
    background: #1e293b;
    border-color: #475569;
    color: #f1f5f9;
  }
  
  .select-wrapper select:hover {
    border-color: #4f46e5;
  }
  
  .select-wrapper select:focus {
    border-color: #6366f1;
    box-shadow: 0 0 0 3px rgba(99, 102, 241, 0.2);
  }
  
  .number-btn {
    color: #94a3b8;
  }
  
  .number-btn:hover:not(:disabled) {
    background: #312e81;
    color: #a5b4fc;
  }
  
  .number-btn:disabled {
    color: #475569;
  }
  
  .number-input {
    color: #f1f5f9;
  }
  
  .toggle-slider {
    background: #475569;
  }
  
  .toggle-switch input:checked + .toggle-slider {
    background: #4f46e5;
  }
  
  .warning-banner {
    background: linear-gradient(135deg, #78350f 0%, #92400e 100%);
    border-color: #fbbf24;
  }
  
  .warning-icon {
    background: #1e293b;
    color: #fbbf24;
  }
  
  .warning-title {
    color: #fcd34d;
  }
  
  .warning-desc {
    color: #fde68a;
  }
}
</style>
