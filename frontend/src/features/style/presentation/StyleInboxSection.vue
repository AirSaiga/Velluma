<script setup lang="ts">
/**
 * 文风页「收件箱」——候选过目区（S3，复用世界页待确认分区的 ✓/✗ 契约）。
 *
 * 红线：候选绝不直接生效（写作台「这不像我」只投候选）；
 * ✓ 确认（负面候选入负面清单/样本候选入库）、✗ 忽略，均由容器调 API。
 */
import Icon from '../../../components/Icon.vue'
import type { StyleInboxItem } from '../../../types'

defineProps<{
  items: StyleInboxItem[]
}>()

const emit = defineEmits<{
  (e: 'confirm', itemId: string): void
  (e: 'dismiss', itemId: string): void
}>()

const kindLabels: Record<string, string> = {
  negative_candidate: '禁词候选',
  sample_candidate: '样本候选',
}
</script>

<template>
  <section id="style-sec-inbox" v-if="items.length > 0" class="inbox-section">
    <header class="sec-head">
      <h2 class="sec-title">
        文风收件箱
        <span class="count-badge">{{ items.length }}</span>
      </h2>
      <p class="sec-sub">写作台「这不像我」等入口攒下的候选——过目后才生效。</p>
    </header>

    <div
      v-for="item in items"
      :key="item.id"
      class="inbox-card"
    >
      <div class="inbox-meta">
        <span class="badge">{{ kindLabels[item.kind] || item.kind }}</span>
        <span v-if="item.payload.word" class="inbox-word">「{{ item.payload.word }}」</span>
        <span v-if="item.payload.alternative" class="inbox-alt">→ {{ item.payload.alternative }}</span>
        <span class="inbox-actions">
          <button class="btn-accept" title="确认：加入负面清单" @click="emit('confirm', item.id)">
            <Icon name="check-circle" :size="13" /> 收入清单
          </button>
          <button class="btn-reject" title="忽略此候选" @click="emit('dismiss', item.id)">
            <Icon name="x-mark" :size="13" />
          </button>
        </span>
      </div>
      <p v-if="item.payload.source_text" class="inbox-source">{{ item.payload.source_text }}</p>
    </div>
  </section>
</template>

<style scoped>
.inbox-section {
  padding: 1.25rem 0 1.5rem;
  scroll-margin-top: 4.5rem;
}
.sec-head {
  margin-bottom: 0.75rem;
}
.sec-title {
  display: flex;
  align-items: center;
  gap: 0.375rem;
  margin: 0;
  font-family: var(--font-heading);
  font-size: 1rem;
  font-weight: 600;
  color: var(--text-primary);
}
.count-badge {
  padding: 0.0625rem 0.4375rem;
  font-size: 0.625rem;
  color: #b45309;
  background: #fef3c7;
  border-radius: 999px;
}
.sec-sub {
  margin: 0.25rem 0 0;
  font-size: 0.75rem;
  line-height: 1.6;
  color: var(--text-muted);
}
.inbox-card {
  padding: 0.625rem 0.75rem;
  margin-bottom: 0.375rem;
  background: var(--bg-panel);
  border: 1px solid var(--border-color);
  border-radius: 0.5rem;
}
.inbox-meta {
  display: flex;
  align-items: center;
  gap: 0.5rem;
}
.badge {
  flex-shrink: 0;
  padding: 0.0625rem 0.4375rem;
  font-size: 0.625rem;
  color: #b45309;
  background: #fef3c7;
  border-radius: 0.25rem;
}
.inbox-word {
  font-size: 0.8125rem;
  font-weight: 500;
  color: var(--text-primary);
}
.inbox-alt {
  overflow: hidden;
  font-size: 0.75rem;
  white-space: nowrap;
  text-overflow: ellipsis;
  color: var(--text-muted);
}
.inbox-actions {
  display: flex;
  flex: 1;
  gap: 0.375rem;
  justify-content: flex-end;
}
.btn-accept {
  display: inline-flex;
  align-items: center;
  gap: 0.25rem;
  padding: 0.25rem 0.5625rem;
  font-size: 0.6875rem;
  color: #047857;
  background: #d1fae5;
  border: none;
  border-radius: 0.375rem;
  cursor: pointer;
}
.btn-accept:hover {
  background: #a7f3d0;
}
.btn-reject {
  display: inline-flex;
  align-items: center;
  padding: 0.25rem 0.375rem;
  color: var(--text-muted);
  background: transparent;
  border: none;
  border-radius: 0.375rem;
  cursor: pointer;
}
.btn-reject:hover {
  color: #dc2626;
  background: #fee2e2;
}
.inbox-source {
  display: -webkit-box;
  -webkit-box-orient: vertical;
  -webkit-line-clamp: 2;
  overflow: hidden;
  margin: 0.375rem 0 0;
  font-size: 0.6875rem;
  line-height: 1.6;
  color: var(--text-muted);
}
</style>
