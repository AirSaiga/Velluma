<script setup lang="ts">
import { computed } from 'vue'
import Icon from '../Icon.vue'

interface Props {
  title: string
  icon?: string
  description?: string
  loading?: boolean
  closable?: boolean
  headerActions?: Array<{
    icon?: string
    label: string
    onClick: () => void
    variant?: 'default' | 'primary' | 'danger'
    disabled?: boolean
  }>
}

const props = withDefaults(defineProps<Props>(), {
  icon: undefined,
  description: undefined,
  loading: false,
  closable: true,
  headerActions: () => []
})

const emit = defineEmits<{
  close: []
}>()

const hasHeaderActions = computed(() => props.headerActions.length > 0)

function handleClose() {
  emit('close')
}
</script>

<template>
  <div class="panel-container">
    <!-- 面板头部 -->
    <div class="panel-header">
      <div class="panel-header-main">
        <div class="panel-title-wrapper">
          <Icon v-if="icon" :name="icon" :size="16" class="panel-title-icon" />
          <div class="panel-title-group">
            <h3 class="panel-title">{{ title }}</h3>
            <p v-if="description" class="panel-description">{{ description }}</p>
          </div>
        </div>
        
        <div class="panel-header-actions">
          <!-- 加载状态 -->
          <div v-if="loading" class="panel-loading">
            <div class="loading-spinner" />
            <span>加载中...</span>
          </div>
          
          <!-- 自定义操作按钮 -->
          <template v-if="hasHeaderActions">
            <button
              v-for="(action, index) in headerActions"
              :key="index"
              class="panel-action-btn"
              :class="`variant-${action.variant || 'default'}`"
              :disabled="action.disabled"
              @click="action.onClick"
            >
              <Icon v-if="action.icon" :name="action.icon" :size="14" />
              <span>{{ action.label }}</span>
            </button>
          </template>
          
          <!-- 关闭按钮 -->
          <button v-if="closable" class="panel-close-btn" @click="handleClose">
            <Icon name="close" :size="16" />
          </button>
        </div>
      </div>
    </div>
    
    <!-- 面板内容区域 -->
    <div class="panel-content">
      <slot />
    </div>
    
    <!-- 面板底部（可选） -->
    <div v-if="$slots.footer" class="panel-footer">
      <slot name="footer" />
    </div>
  </div>
</template>

<style scoped>
.panel-container {
  display: flex;
  flex-direction: column;
  height: 100%;
  background: var(--bg-primary);
  overflow: hidden;
}

/* 头部样式 */
.panel-header {
  flex-shrink: 0;
  padding: 14px 16px;
  border-bottom: 1px solid var(--border-color);
  background: var(--bg-primary);
}

.panel-header-main {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.panel-title-wrapper {
  display: flex;
  align-items: flex-start;
  gap: 10px;
  min-width: 0;
  flex: 1;
}

.panel-title-icon {
  flex-shrink: 0;
  color: var(--accent-500);
  margin-top: 1px;
}

.panel-title-group {
  display: flex;
  flex-direction: column;
  gap: 2px;
  min-width: 0;
  flex: 1;
}

.panel-title {
  font-size: 14px;
  font-weight: 600;
  color: var(--text-primary);
  line-height: 1.3;
}

.panel-description {
  font-size: 11px;
  color: var(--text-muted);
  line-height: 1.4;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

/* 头部操作区 */
.panel-header-actions {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-shrink: 0;
}

.panel-loading {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 12px;
  color: var(--accent-500);
}

.loading-spinner {
  width: 14px;
  height: 14px;
  border: 2px solid var(--bg-panel);
  border-top-color: var(--accent-500);
  border-radius: 50%;
  animation: spin 0.8s linear infinite;
}

@keyframes spin {
  to { transform: rotate(360deg); }
}

.panel-action-btn {
  display: flex;
  align-items: center;
  gap: 4px;
  padding: 5px 10px;
  font-size: 11px;
  font-weight: 500;
  border-radius: 6px;
  border: none;
  cursor: pointer;
  transition: all 0.2s ease;
  white-space: nowrap;
}

.panel-action-btn.variant-default {
  background: var(--bg-panel);
  color: var(--text-secondary);
}

.panel-action-btn.variant-default:hover:not(:disabled) {
  background: var(--hover-bg);
  color: var(--text-primary);
}

.panel-action-btn.variant-primary {
  background: var(--accent-500);
  color: white;
}

.panel-action-btn.variant-primary:hover:not(:disabled) {
  background: var(--accent-600);
  transform: translateY(-1px);
  box-shadow: 0 4px 12px rgba(124, 106, 173, 0.25);
}

.panel-action-btn.variant-danger {
  background: #fee2e2;
  color: #dc2626;
}

.panel-action-btn.variant-danger:hover:not(:disabled) {
  background: #fecaca;
}

.panel-action-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.panel-close-btn {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 26px;
  height: 26px;
  border-radius: 6px;
  border: none;
  background: transparent;
  color: var(--text-muted);
  cursor: pointer;
  transition: all 0.2s ease;
  margin-left: 4px;
}

.panel-close-btn:hover {
  background: var(--bg-panel);
  color: var(--text-primary);
}

/* 内容区域 */
.panel-content {
  flex: 1;
  overflow-y: auto;
  overflow-x: hidden;
  padding: 12px 16px;
}

/* 自定义滚动条 */
.panel-content::-webkit-scrollbar {
  width: 6px;
}

.panel-content::-webkit-scrollbar-track {
  background: transparent;
}

.panel-content::-webkit-scrollbar-thumb {
  background: var(--scrollbar-thumb);
  border-radius: 3px;
}

.panel-content::-webkit-scrollbar-thumb:hover {
  background: var(--scrollbar-thumb-hover);
}

/* 底部区域 */
.panel-footer {
  flex-shrink: 0;
  padding: 12px 20px;
  border-top: 1px solid var(--border-color);
  background: var(--bg-secondary);
}
</style>
