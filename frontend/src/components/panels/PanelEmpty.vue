<script setup lang="ts">
import Icon from '../Icon.vue'

interface Props {
  icon?: string
  title: string
  description?: string
  actionLabel?: string
}

withDefaults(defineProps<Props>(), {
  icon: 'inbox',
  description: undefined,
  actionLabel: undefined
})

const emit = defineEmits<{
  action: []
}>()

function handleAction() {
  emit('action')
}
</script>

<template>
  <div class="panel-empty">
    <div class="empty-icon">
      <Icon :name="icon" :size="32" />
    </div>
    <h4 class="empty-title">{{ title }}</h4>
    <p v-if="description" class="empty-description">{{ description }}</p>
    <button v-if="actionLabel" class="empty-action" @click="handleAction">
      {{ actionLabel }}
    </button>
  </div>
</template>

<style scoped>
.panel-empty {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 48px 24px;
  text-align: center;
}

.empty-icon {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 64px;
  height: 64px;
  margin-bottom: 16px;
  border-radius: 16px;
  background: var(--surface-overlay);
  color: var(--text-muted);
}

.empty-title {
  font-size: var(--text-base);
  font-weight: 600;
  color: var(--text-secondary);
  margin-bottom: 6px;
}

.empty-description {
  font-size: var(--text-xs);
  color: var(--text-muted);
  line-height: 1.5;
  max-width: 240px;
  margin-bottom: 16px;
}

.empty-action {
  padding: 8px 16px;
  font-size: var(--text-xs);
  font-weight: 500;
  color: var(--accent-500);
  background: transparent;
  border: 1px solid var(--accent-500);
  border-radius: var(--radius-md);
  cursor: pointer;
  transition: all var(--dur-3) var(--ease-out);
}

.empty-action:hover {
  background: var(--accent-500);
  color: var(--bg-canvas);
}
</style>
