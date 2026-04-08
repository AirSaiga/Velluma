<script setup lang="ts">
import { computed } from 'vue'
import Icon from '../Icon.vue'

interface Props {
  title?: string
  icon?: string
  collapsible?: boolean
  collapsed?: boolean
  badge?: string | number
  actions?: Array<{
    icon?: string
    label: string
    onClick: () => void
    variant?: 'default' | 'primary'
  }>
}

const props = withDefaults(defineProps<Props>(), {
  title: undefined,
  icon: undefined,
  collapsible: false,
  collapsed: false,
  badge: undefined,
  actions: () => []
})

const emit = defineEmits<{
  'update:collapsed': [value: boolean]
}>()

const isCollapsed = computed({
  get: () => props.collapsed,
  set: (value) => emit('update:collapsed', value)
})

const hasActions = computed(() => props.actions.length > 0)
const hasHeader = computed(() => props.title || hasActions.value || props.collapsible)

function toggleCollapse() {
  if (props.collapsible) {
    isCollapsed.value = !isCollapsed.value
  }
}
</script>

<template>
  <div class="panel-section" :class="{ 'is-collapsed': isCollapsed }">
    <!-- 分区块头部 -->
    <div v-if="hasHeader" class="section-header" :class="{ 'is-collapsible': collapsible }" @click="toggleCollapse">
      <div class="section-title-wrapper">
        <Icon v-if="icon" :name="icon" :size="14" class="section-icon" />
        <h4 v-if="title" class="section-title">{{ title }}</h4>
        <span v-if="badge !== undefined" class="section-badge">{{ badge }}</span>
      </div>
      
      <div class="section-actions">
        <!-- 自定义操作 -->
        <template v-if="hasActions && !isCollapsed">
          <button
            v-for="(action, index) in actions"
            :key="index"
            class="section-action-btn"
            :class="`variant-${action.variant || 'default'}`"
            @click.stop="action.onClick"
          >
            <Icon v-if="action.icon" :name="action.icon" :size="12" />
            <span>{{ action.label }}</span>
          </button>
        </template>
        
        <!-- 折叠按钮 -->
        <button v-if="collapsible" class="collapse-toggle" :class="{ 'is-collapsed': isCollapsed }">
          <Icon name="chevron-down" :size="14" />
        </button>
      </div>
    </div>
    
    <!-- 分区块内容 -->
    <div v-show="!isCollapsed" class="section-content">
      <slot />
    </div>
  </div>
</template>

<style scoped>
.panel-section {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.panel-section.is-collapsed {
  gap: 0;
}

/* 分区块头部 */
.section-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  padding: 4px 0;
}

.section-header.is-collapsible {
  cursor: pointer;
  user-select: none;
}

.section-title-wrapper {
  display: flex;
  align-items: center;
  gap: 8px;
  min-width: 0;
}

.section-icon {
  flex-shrink: 0;
  color: var(--text-muted);
}

.section-title {
  font-size: 13px;
  font-weight: 600;
  color: var(--text-secondary);
  letter-spacing: 0.01em;
}

.section-badge {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-width: 18px;
  height: 18px;
  padding: 0 6px;
  font-size: 11px;
  font-weight: 500;
  color: var(--accent-500);
  background: rgba(124, 106, 173, 0.1);
  border-radius: 9px;
}

.section-actions {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-shrink: 0;
}

.section-action-btn {
  display: flex;
  align-items: center;
  gap: 4px;
  padding: 4px 10px;
  font-size: 11px;
  font-weight: 500;
  border-radius: 6px;
  border: none;
  cursor: pointer;
  transition: all 0.2s ease;
}

.section-action-btn.variant-default {
  background: var(--bg-panel);
  color: var(--text-secondary);
}

.section-action-btn.variant-default:hover {
  background: var(--hover-bg);
  color: var(--text-primary);
}

.section-action-btn.variant-primary {
  background: var(--accent-500);
  color: white;
}

.section-action-btn.variant-primary:hover {
  background: var(--accent-600);
}

.collapse-toggle {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 22px;
  height: 22px;
  border-radius: 6px;
  border: none;
  background: transparent;
  color: var(--text-muted);
  cursor: pointer;
  transition: all 0.2s ease;
}

.collapse-toggle:hover {
  background: var(--bg-panel);
  color: var(--text-primary);
}

.collapse-toggle.is-collapsed {
  transform: rotate(-90deg);
}

/* 分区块内容 */
.section-content {
  display: flex;
  flex-direction: column;
  gap: 12px;
}
</style>
