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
import { highlightAnchorId } from '../composables/useChapterSpine'

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

// ---- 岔路编辑（M3：作者声明岔路——2-3 个走向短语）----
const branchEditor = ref<{ id: string; text: string; draft: string; hasExisting: boolean } | null>(null)

function openBranchEditor(a: SpineAnchor) {
  branchEditor.value = {
    id: a.id,
    text: a.text,
    draft: (a.branch?.options || []).join('\n'),
    hasExisting: !!a.branch,
  }
}

function saveBranch() {
  const be = branchEditor.value
  if (!be) return
  const options = be.draft.split('\n').map((s) => s.trim()).filter(Boolean).slice(0, 3)
  if (options.length >= 2) {
    emit('update-anchor', be.id, { branch: { options } })
  }
  branchEditor.value = null
}

function clearBranch() {
  const be = branchEditor.value
  if (!be) return
  emit('update-anchor', be.id, { branch: undefined })
  branchEditor.value = null
}
</script>

<template>
  <section class="spine-panel" :class="{ 'spine-panel--empty': !intentText && !anchors.length }">
    <div class="spine-head">
      <span class="spine-title">打算</span>
      <span class="spine-hint">写之前记两句：这章讲什么、哪些情节非写不可</span>
    </div>

    <!-- 意图：一行（autogrow 由 textarea rows=1 + CSS 承担） -->
    <textarea
      class="spine-intent"
      rows="1"
      :value="intentText"
      placeholder="一句话：这一章主要讲什么？（可空，直接开写也行）"
      @change="(e) => emit('update-intent', (e.target as HTMLTextAreaElement).value)"
    ></textarea>

    <!-- 锚点 chips -->
    <div v-if="anchors.length" class="spine-anchors">
      <span
        v-for="a in anchors"
        :key="a.id"
        class="spine-chip"
        :class="{ 'spine-chip--dropped': a.status === 'dropped', 'spine-chip--hit': a.status === 'hit', 'spine-chip--flash': highlightAnchorId === a.id, 'spine-chip--branch': !!a.branch }"
        :title="a.branch ? `可能的发展：${a.branch.options.join(' / ')}` : (a.status === 'dropped' ? '已划掉（本章不写了）' : a.status === 'hit' ? '已写到' : a.text)"
      >
        <span v-if="a.branch" class="spine-chip__branch-mark" title="这条情节你想了几种可能的发展">⚡</span>
        <span class="spine-chip__text">{{ a.text }}</span>
        <button
          class="spine-chip__btn"
          :title="a.branch ? '改改这几种发展' : '还没想好怎么发展？列几种可能'"
          @click="openBranchEditor(a)"
        >⚡</button>
        <button
          class="spine-chip__btn"
          :title="a.status === 'dropped' ? '恢复' : '划掉（写的过程中决定不写了）'"
          @click="emit('update-anchor', a.id, { status: a.status === 'dropped' ? 'pending' : 'dropped' })"
        >{{ a.status === 'dropped' ? '↺' : '✕' }}</button>
      </span>
    </div>

    <!-- 岔路编辑（M3 §5：2-3 个走向短语；临近时走向卡舱硬提示置顶，选向即决岔） -->
    <div v-if="branchEditor" class="spine-branch-editor">
      <div class="spine-branch-editor__head">
        「{{ branchEditor.text }}」可以怎么发展？（每行一种可能，2-3 种）
        <button class="spine-chip__btn" @click="branchEditor = null">✕</button>
      </div>
      <textarea
        v-model="branchEditor.draft"
        class="spine-branch-editor__input"
        rows="3"
        placeholder="当面撕破&#10;隐忍试探"
      ></textarea>
      <div class="spine-branch-editor__actions">
        <button class="spine-suggest__btn spine-suggest__btn--primary" @click="saveBranch">保存</button>
        <button v-if="branchEditor.hasExisting" class="spine-suggest__btn" @click="clearBranch">清除</button>
      </div>
    </div>
    <div v-if="anchors.length" class="spine-anchor-count">{{ anchors.length }}/5</div>

    <!-- 加锚点 -->
    <div class="spine-add" v-if="!anchorFull">
      <input
        v-model="addingAnchor"
        class="spine-add__input"
        placeholder="＋ 非写不可的情节（几个字就行，如：发现假信）"
        :disabled="disabled"
        @keydown.enter.prevent="submitAnchor"
      />
    </div>
    <p v-if="!anchorFull" class="spine-hint-line">列出来的情节，写到了会自动打勾；AI 续写时也会朝它们使劲</p>
    <p v-else class="spine-full-hint">最多 5 条——细节留给下面的大纲，这里只记最要紧的</p>

    <!-- AI 建议（D-4：未收下的不落库） -->
    <div class="spine-suggest">
      <button class="spine-suggest__btn" :disabled="suggesting || disabled" @click="emit('suggest')">
        {{ suggesting ? '思考中…' : '✨ 帮我想想这章怎么走' }}
      </button>
      <template v-if="suggestions">
        <div class="spine-suggest__card">
          <div v-if="suggestions.intent" class="spine-suggest__intent">
            <span class="spine-suggest__label">一句话</span>{{ suggestions.intent }}
            <button class="spine-chip__btn" title="收下这句" @click="emit('adopt', 'intent')">收下</button>
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
.spine-chip--branch {
  border-color: #c2725a;
}
.spine-chip__branch-mark {
  font-size: 0.625rem;
  color: #c2725a;
}
.spine-branch-editor {
  display: flex;
  flex-direction: column;
  gap: 0.375rem;
  padding: 0.5rem;
  border: 1px solid #c2725a;
  border-radius: 8px;
  background: var(--bg-secondary);
}
.spine-branch-editor__head {
  font-size: 0.6875rem;
  color: var(--text-secondary);
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 0.375rem;
}
.spine-branch-editor__input {
  width: 100%;
  resize: none;
  border: 1px dashed var(--border-color);
  border-radius: 6px;
  background: transparent;
  font-size: 0.75rem;
  color: var(--text-primary);
  padding: 0.375rem 0.5rem;
  line-height: 1.6;
}
.spine-branch-editor__input:focus {
  outline: none;
  border-color: #c2725a;
}
.spine-branch-editor__actions {
  display: flex;
  gap: 0.375rem;
}
.spine-chip--flash {
  animation: spine-flash 0.5s ease 2;
  border-color: var(--accent-500, #7c6aad);
}
@keyframes spine-flash {
  0%, 100% { background: var(--bg-secondary); }
  50% { background: var(--accent-400, #9685c2); color: #fff; }
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
.spine-hint-line {
  font-size: 0.625rem;
  color: var(--text-muted);
  margin: 0;
  line-height: 1.5;
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
