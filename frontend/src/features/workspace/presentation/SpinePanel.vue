<script setup lang="ts">
/**
 * 谋篇区（章级软脉络的编辑面板，P1.4 M1——docs/chapter-planning-spine.md §3.2）。
 *
 * 度优先：意图一行（可空）+ 锚点 chips（≤5，超出文案劝阻）；AI 建议预填
 * 不过目不落库（D-4）；划掉 = dropped（写的过程中决定不写了是合法动作）。
 * 纯展示组件——状态与保存经 useChapterSpine 由容器传入/调用。
 */
import { computed, ref } from 'vue'
import type { ChapterSpine, SpineAnchor, SpineSuggestion } from '../../../services/api/domain/adaptive.api'

const props = defineProps<{
  spine: ChapterSpine | null
  suggestions: SpineSuggestion | null
  suggesting: boolean
  /** 章节未选/不可用时的禁用态 */
  disabled?: boolean
}>()

const emit = defineEmits<{
  (e: 'update-intent', text: string): void
  (e: 'add-anchor', text: string): void
  (e: 'update-anchor', id: string, patch: Partial<SpineAnchor>): void
  (e: 'remove-anchor', id: string): void
  (e: 'suggest'): void
  (e: 'adopt', part: 'intent' | 'anchors' | 'all'): void
  (e: 'discard-suggestions'): void
}>()

const intentText = computed(() => props.spine?.intent?.text || '')
const anchors = computed(() => props.spine?.anchors || [])
const addingAnchor = ref('')
const anchorFull = computed(() => anchors.value.length >= 5)

function submitAnchor() {
  const t = addingAnchor.value.trim()
  if (!t || anchorFull.value) return
  emit('add-anchor', t)
  addingAnchor.value = ''
}
</script>

<template>
  <section class="spine-panel" :class="{ 'spine-panel--empty': !intentText && !anchors.length }">
    <div class="spine-head">
      <span class="spine-title">谋篇</span>
      <span class="spine-hint">本章要去哪 · 一句话就够</span>
    </div>

    <!-- 意图：一行（autogrow 由 textarea rows=1 + CSS 承担） -->
    <textarea
      class="spine-intent"
      rows="1"
      :value="intentText"
      placeholder="一句话：本章要去哪？（可空，直接开写也行）"
      @change="(e) => emit('update-intent', (e.target as HTMLTextAreaElement).value)"
    ></textarea>

    <!-- 锚点 chips -->
    <div v-if="anchors.length" class="spine-anchors">
      <span
        v-for="a in anchors"
        :key="a.id"
        class="spine-chip"
        :class="{ 'spine-chip--dropped': a.status === 'dropped', 'spine-chip--hit': a.status === 'hit' }"
        :title="a.status === 'dropped' ? '已划掉（本章不写了）' : a.status === 'hit' ? '已写到' : a.text"
      >
        <span class="spine-chip__text">{{ a.text }}</span>
        <button
          class="spine-chip__btn"
          :title="a.status === 'dropped' ? '恢复' : '划掉（写的过程中决定不写了）'"
          @click="emit('update-anchor', a.id, { status: a.status === 'dropped' ? 'pending' : 'dropped' })"
        >{{ a.status === 'dropped' ? '↺' : '✕' }}</button>
      </span>
    </div>
    <div v-if="anchors.length" class="spine-anchor-count">{{ anchors.length }}/5</div>

    <!-- 加锚点 -->
    <div class="spine-add" v-if="!anchorFull">
      <input
        v-model="addingAnchor"
        class="spine-add__input"
        placeholder="＋ 锚点（2-12 字短语，如「发现假信」）"
        :disabled="disabled"
        @keydown.enter.prevent="submitAnchor"
      />
    </div>
    <p v-else class="spine-full-hint">锚点已满 5 个——细节留给大纲，谋篇只记方向</p>

    <!-- AI 建议（D-4：未收下的不落库） -->
    <div class="spine-suggest">
      <button class="spine-suggest__btn" :disabled="suggesting || disabled" @click="emit('suggest')">
        {{ suggesting ? '谋篇建议生成中…' : '✨ AI 谋篇建议' }}
      </button>
      <template v-if="suggestions">
        <div class="spine-suggest__card">
          <div v-if="suggestions.intent" class="spine-suggest__intent">
            <span class="spine-suggest__label">意图</span>{{ suggestions.intent }}
            <button class="spine-chip__btn" title="收下这条意图" @click="emit('adopt', 'intent')">收下</button>
          </div>
          <div v-if="suggestions.anchors?.length" class="spine-suggest__anchors">
            <span
              v-for="(a, i) in suggestions.anchors"
              :key="'sa' + i"
              class="spine-chip spine-chip--ghost"
            >{{ a }}</span>
          </div>
          <div class="spine-suggest__actions">
            <button class="spine-suggest__btn spine-suggest__btn--primary" @click="emit('adopt', 'all')">全部收下</button>
            <button class="spine-suggest__btn" @click="emit('discard-suggestions')">不用</button>
          </div>
        </div>
      </template>
    </div>
  </section>
</template>

<style scoped>
.spine-panel {
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
}
.spine-head {
  display: flex;
  align-items: baseline;
  gap: 0.5rem;
}
.spine-title {
  font-size: 0.75rem;
  font-weight: 600;
  color: var(--text-primary);
}
.spine-hint {
  font-size: 0.6875rem;
  color: var(--text-muted);
}
.spine-intent {
  width: 100%;
  resize: none;
  border: none;
  border-bottom: 1px dashed var(--border-color);
  background: transparent;
  font-family: var(--font-heading, inherit);
  font-size: 0.8125rem;
  color: var(--text-primary);
  padding: 0.25rem 0;
  line-height: 1.5;
}
.spine-intent:focus {
  outline: none;
  border-bottom-color: var(--accent-400, #9685c2);
}
.spine-anchors {
  display: flex;
  flex-wrap: wrap;
  gap: 0.375rem;
}
.spine-chip {
  display: inline-flex;
  align-items: center;
  gap: 0.25rem;
  padding: 0.125rem 0.5rem;
  border: 1px solid var(--border-color);
  border-radius: 999px;
  font-size: 0.6875rem;
  color: var(--text-primary);
  background: var(--bg-secondary);
}
.spine-chip--dropped {
  opacity: 0.45;
  text-decoration: line-through;
}
.spine-chip--hit {
  border-color: var(--accent-400, #9685c2);
}
.spine-chip--ghost {
  border-style: dashed;
  color: var(--text-secondary);
}
.spine-chip__btn {
  border: none;
  background: none;
  cursor: pointer;
  font-size: 0.625rem;
  color: var(--text-muted);
  padding: 0 0.125rem;
}
.spine-chip__btn:hover {
  color: var(--text-primary);
}
.spine-anchor-count {
  font-size: 0.625rem;
  color: var(--text-muted);
  text-align: right;
}
.spine-add__input {
  width: 100%;
  border: 1px dashed var(--border-color);
  border-radius: 6px;
  background: transparent;
  font-size: 0.6875rem;
  color: var(--text-primary);
  padding: 0.25rem 0.5rem;
}
.spine-add__input:focus {
  outline: none;
  border-color: var(--accent-400, #9685c2);
}
.spine-full-hint {
  font-size: 0.625rem;
  color: var(--text-muted);
  margin: 0;
}
.spine-suggest__btn {
  border: 1px solid var(--border-color);
  border-radius: 6px;
  background: var(--bg-secondary);
  color: var(--text-secondary);
  font-size: 0.6875rem;
  padding: 0.25rem 0.625rem;
  cursor: pointer;
}
.spine-suggest__btn:disabled {
  opacity: 0.5;
  cursor: default;
}
.spine-suggest__btn--primary {
  background: var(--accent-500, #7c6aad);
  border-color: var(--accent-500, #7c6aad);
  color: #fff;
}
.spine-suggest__card {
  display: flex;
  flex-direction: column;
  gap: 0.375rem;
  padding: 0.5rem;
  border: 1px solid var(--accent-400, #9685c2);
  border-radius: 8px;
  background: var(--bg-secondary);
}
.spine-suggest__intent {
  font-size: 0.75rem;
  color: var(--text-primary);
  display: flex;
  align-items: baseline;
  gap: 0.375rem;
}
.spine-suggest__label {
  font-size: 0.625rem;
  color: var(--text-muted);
  flex-shrink: 0;
}
.spine-suggest__anchors {
  display: flex;
  flex-wrap: wrap;
  gap: 0.375rem;
}
.spine-suggest__actions {
  display: flex;
  gap: 0.375rem;
}
</style>
