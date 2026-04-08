<script setup lang="ts">
import { computed } from 'vue'
import Icon from '../Icon.vue'

interface Props {
  title?: string
  subtitle?: string
  description?: string
  active?: boolean
  highlight?: 'none' | 'weak' | 'strong'
  clickable?: boolean
  actions?: Array<{
    icon: string
    label: string
    onClick: () => void
    variant?: 'default' | 'danger'
  }>
}

const props = withDefaults(defineProps<Props>(), {
  title: undefined,
  subtitle: undefined,
  description: undefined,
  active: false,
  highlight: 'none',
  clickable: false,
  actions: () => []
})

const emit = defineEmits<{
  click: []
}>()

const hasActions = computed(() => props.actions.length > 0)

const cardClasses = computed(() => ({
  'panel-card': true,
  'is-active': props.active,
  'is-clickable': props.clickable,
  [`highlight-${props.highlight}`]: true
}))

function handleClick() {
  if (props.clickable) {
    emit('click')
  }
}
</script>

<template>
  <div :class="cardClasses" @click="handleClick">
    <div class="card-main">
      <div class="card-content">
        <div class="card-header-row">
          <div class="card-titles">
            <h5 v-if="title" class="card-title">{{ title }}</h5>
            <span v-if="subtitle" class="card-subtitle">{{ subtitle }}</span>
          </div>
          
          <!-- 操作按钮组 -->
          <div v-if="hasActions" class="card-actions" @click.stop>
            <button
              v-for="(action, index) in actions"
              :key="index"
              class="card-action-btn"
              :class="`variant-${action.variant || 'default'}`"
              :title="action.label"
              @click="action.onClick"
            >
              <Icon :name="action.icon" :size="14" />
            </button>
          </div>
        </div>
        
        <p v-if="description" class="card-description">{{ description }}</p>
        
        <div v-if="$slots.default" class="card-body">
          <slot />
        </div>
      </div>
    </div>
    
    <div v-if="$slots.footer" class="card-footer">
      <slot name="footer" />
    </div>
  </div>
</template>

<style scoped>
.panel-card {
  position: relative;
  background: var(--bg-panel);
  border-radius: 12px;
  border: 1px solid var(--border-color);
  transition: all 0.2s ease;
  overflow: hidden;
}

.panel-card:hover {
  border-color: var(--hover-bg);
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.04);
}

/* 高亮状态 */
.panel-card.highlight-weak {
  background: rgba(124, 106, 173, 0.05);
  border-color: rgba(124, 106, 173, 0.2);
}

.panel-card.highlight-strong {
  background: rgba(124, 106, 173, 0.08);
  border-color: rgba(124, 106, 173, 0.4);
  box-shadow: 0 0 0 3px rgba(124, 106, 173, 0.1);
}

.panel-card.highlight-strong:hover {
  box-shadow: 0 0 0 3px rgba(124, 106, 173, 0.15), 0 4px 12px rgba(0, 0, 0, 0.06);
}

/* 激活状态 */
.panel-card.is-active {
  background: rgba(124, 106, 173, 0.08);
  border-color: var(--accent-500);
}

/* 可点击状态 */
.panel-card.is-clickable {
  cursor: pointer;
}

/* 卡片主体 */
.card-main {
  padding: 14px 16px;
}

.card-content {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.card-header-row {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
}

.card-titles {
  display: flex;
  flex-direction: column;
  gap: 2px;
  min-width: 0;
}

.card-title {
  font-size: 13px;
  font-weight: 600;
  color: var(--text-primary);
  line-height: 1.4;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.card-subtitle {
  font-size: 11px;
  color: var(--text-muted);
  line-height: 1.3;
}

.card-actions {
  display: flex;
  align-items: center;
  gap: 4px;
  flex-shrink: 0;
  opacity: 0;
  transition: opacity 0.2s ease;
}

.panel-card:hover .card-actions {
  opacity: 1;
}

.card-action-btn {
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
}

.card-action-btn:hover {
  background: var(--hover-bg);
  color: var(--text-primary);
}

.card-action-btn.variant-danger:hover {
  background: #fee2e2;
  color: #dc2626;
}

.card-description {
  font-size: 12px;
  color: var(--text-secondary);
  line-height: 1.5;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

.card-body {
  margin-top: 4px;
}

/* 卡片底部 */
.card-footer {
  padding: 10px 16px;
  background: rgba(0, 0, 0, 0.02);
  border-top: 1px solid var(--border-color);
  font-size: 11px;
  color: var(--text-muted);
}
</style>
