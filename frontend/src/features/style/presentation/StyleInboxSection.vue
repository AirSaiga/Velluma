<script setup lang="ts">
/**
 * 文风页「收件箱」——候选过目区（S3，复用世界页待确认分区的 ✓/✗ 契约）。
 *
 * 红线：候选绝不直接生效（写作台「这不像我」只投候选）；
 * ✓ 确认（负面候选入负面清单/样本候选入库）、✗ 忽略，均由容器调 API。
 * Phase 3：禁词候选的词块确认前可就地改写（点击词/✎ 进编辑，Enter/失焦定稿、
 * Esc 取消）——只改本地副本，确认时经 overrides 覆盖字段随请求生效。
 */
import { ref, watch, nextTick } from 'vue'
import Icon from '../../../components/Icon.vue'
import type { StyleInboxItem } from '../../../types'

const props = defineProps<{
  items: StyleInboxItem[]
}>()

const emit = defineEmits<{
  (e: 'confirm', itemId: string, overrides?: { word?: string; alternative?: string | null }): void
  (e: 'dismiss', itemId: string): void
}>()

const kindLabels: Record<string, string> = {
  negative_candidate: '禁词候选',
  sample_candidate: '样本候选',
}

// ---- 就地编辑（仅 negative_candidate 的词块）----
const editingId = ref<string | null>(null)
const editDraft = ref('')
/** 已定稿的本地改写（itemId → 改后词）；确认时作为 overrides 发给后端 */
const editedWords = ref<Record<string, string>>({})
const editInputEl = ref<HTMLInputElement | null>(null)

function displayWord(item: StyleInboxItem): string {
  return editedWords.value[item.id] ?? item.payload.word ?? ''
}

function startEdit(item: StyleInboxItem) {
  if (item.kind !== 'negative_candidate' || !item.payload.word) return
  editingId.value = item.id
  editDraft.value = displayWord(item)
  void nextTick(() => editInputEl.value?.focus())
}

function commitEdit(item: StyleInboxItem) {
  if (editingId.value !== item.id) return
  const word = editDraft.value.trim()
  if (word && word !== (item.payload.word || '')) editedWords.value[item.id] = word
  else delete editedWords.value[item.id]
  editingId.value = null
}

function cancelEdit() {
  editingId.value = null
}

/** 样本候选摘录预览（前 140 字——够判断「这是不是我的字」，全文确认后入库再看） */
function excerpt(item: StyleInboxItem): string {
  const c = String(item.payload.content || '')
  return c.length > 140 ? c.slice(0, 140) + '…' : c
}

/** 确认按钮文案/提示按候选类型分（禁词入负面清单 vs 样本入样本库） */
function acceptLabel(item: StyleInboxItem): string {
  return item.kind === 'sample_candidate' ? '收进样本库' : '收入清单'
}

function acceptTitle(item: StyleInboxItem): string {
  if (item.kind === 'sample_candidate') return '确认：这段作为「你的字」的示范收进样本库（AI 学它的语感）'
  return editedWords.value[item.id] ? `确认：按改后的「${editedWords.value[item.id]}」加入负面清单` : '确认：加入负面清单'
}

/** 确认：改写过的词块走 overrides 覆盖（后端不带则维持原候选入清单） */
function confirmItem(item: StyleInboxItem) {
  if (editingId.value === item.id) commitEdit(item)
  const edited = editedWords.value[item.id]
  emit('confirm', item.id, edited ? { word: edited } : undefined)}

// 候选列表刷新后清掉已不在场的本地改写，防止串到同 id 新候选
watch(() => props.items, (list) => {
  const ids = new Set(list.map(i => i.id))
  for (const id of Object.keys(editedWords.value)) {
    if (!ids.has(id)) delete editedWords.value[id]
  }
  if (editingId.value && !ids.has(editingId.value)) editingId.value = null
})
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
        <!-- 禁词候选词块：确认前可就地改写（编辑态输入框 ↔ 展示态可点词/✎） -->
        <span v-if="item.kind === 'negative_candidate' && editingId === item.id" class="word-edit">
          <input
            ref="editInputEl"
            v-model="editDraft"
            class="edit-input"
            placeholder="禁用词/句式"
            @keydown.enter.prevent="commitEdit(item)"
            @keydown.esc.prevent="cancelEdit"
            @blur="commitEdit(item)"
          >
        </span>
        <template v-else>
          <span
            v-if="item.payload.word"
            class="inbox-word"
            :class="{ 'inbox-word--editable': item.kind === 'negative_candidate' }"
            :title="item.kind === 'negative_candidate' ? '点一下可改写——确认时按改后的词入清单' : undefined"
            @click="item.kind === 'negative_candidate' && startEdit(item)"
          >「{{ displayWord(item) }}」</span>
          <button
            v-if="item.kind === 'negative_candidate' && item.payload.word"
            class="btn-edit-word"
            title="改写词块——确认时按改后的词入清单"
            @click="startEdit(item)"
          >✎</button>
        </template>
        <span v-if="item.payload.alternative" class="inbox-alt">→ {{ item.payload.alternative }}</span>
        <span class="inbox-actions">
          <button
            class="btn-accept"
            :title="acceptTitle(item)"
            @click="confirmItem(item)"
          >
            <Icon name="check-circle" :size="13" /> {{ acceptLabel(item) }}
          </button>
          <button class="btn-reject" title="忽略此候选" @click="emit('dismiss', item.id)">
            <Icon name="x-mark" :size="13" />
          </button>
        </span>
      </div>
      <!-- 样本候选（2026-09-03 质感批次）：摘录全文预览 + 来源说明（质感密度） -->
      <template v-if="item.kind === 'sample_candidate'">
        <p v-if="item.payload.content" class="inbox-excerpt">{{ excerpt(item) }}</p>
        <p v-if="item.payload.note" class="inbox-source">{{ item.payload.note }}</p>
      </template>
      <p v-if="item.payload.source_text" class="inbox-source">{{ item.payload.source_text }}</p>
    </div>
  </section>
</template>

<style scoped>
.inbox-section {
  padding: 1.25rem 0 1.5rem;
  scroll-margin-top: 4.5rem;
}
/* .sec-head/.sec-title 吃 style.css 全局工具类（00 期 §3.1），此处仅保留 flex 布局增量 */
.sec-title {
  display: flex;
  align-items: center;
  gap: 0.375rem;
}
.count-badge {
  padding: 0.0625rem 0.4375rem;
  font-size: var(--text-xs);
  color: var(--warn);
  background: var(--warn-bg);
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
  font-size: var(--text-xs);
  color: var(--warn);
  background: var(--warn-bg);
  border-radius: 0.25rem;
}
.inbox-word {
  font-size: 0.8125rem;
  font-weight: 500;
  color: var(--text-primary);
}
/* 可编辑词块（禁词候选）：点词/✎ 进编辑 */
.inbox-word--editable {
  cursor: text;
  border-bottom: 1px dashed var(--border-color);
}
.inbox-word--editable:hover {
  color: var(--accent-500);
  border-bottom-color: var(--accent-400);
}
.btn-edit-word {
  flex-shrink: 0;
  padding: 0.125rem 0.25rem;
  font-size: var(--text-xs);
  color: var(--text-muted);
  background: transparent;
  border: none;
  border-radius: 0.25rem;
  cursor: pointer;
}
.btn-edit-word:hover {
  color: var(--accent-500);
  background: var(--hover-bg);
}
.word-edit {
  display: inline-flex;
  min-width: 0;
}
.edit-input {
  width: 9rem;
  max-width: 100%;
  padding: 0.2rem 0.4rem;
  font-size: 0.75rem;
  background: transparent;
  border: 1px solid var(--accent-400);
  border-radius: 0.375rem;
}
.edit-input:focus {
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
  font-size: var(--text-xs);
  color: var(--ok);
  background: var(--ok-bg);
  border: none;
  border-radius: 0.375rem;
  cursor: pointer;
}
.btn-accept:hover {
  background: var(--ok-bg);
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
  color: var(--danger);
  background: var(--danger-bg);
}
.inbox-source {
  display: -webkit-box;
  -webkit-box-orient: vertical;
  -webkit-line-clamp: 2;
  overflow: hidden;
  margin: 0.375rem 0 0;
  font-size: var(--text-xs);
  line-height: 1.6;
  color: var(--text-muted);
}

/* 样本候选摘录（质感批次）：正文大小的衬线预览，与来源说明拉开层级 */
.inbox-excerpt {
  margin: 0.375rem 0 0;
  font-family: var(--font-heading);
  font-size: 0.8125rem;
  line-height: 1.75;
  color: var(--text-primary);
  white-space: pre-wrap;
}
</style>
