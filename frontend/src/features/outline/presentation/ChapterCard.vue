<script setup lang="ts">
/**
 * 故事线章卡：单章的规划视图行（纯展示，编辑态只透传草稿）。
 *
 * 一行装下五样规划信息：章号/标题/状态、打算一句话、关键情节兑现进度、
 * 伏笔埋收记号、真相揭示点；展开后是大纲就地编辑区（草稿与落盘由容器管）。
 * 点击行进写作台；编辑中不抢跳（避免误触丢焦点）。
 */
import Icon from '../../../components/Icon.vue'

export interface ChapterCardData {
  id: string
  number: number
  title: string
  status: string
  wordCount: number
  outline: string
  intentText: string
  anchorDone: number
  anchorTotal: number
  revealLabels: string[]
  planted: number
  resolved: number
}

defineProps<{
  chapter: ChapterCardData
  editing: boolean
  draft: string
  saveState: 'idle' | 'saving' | 'saved' | 'error'
}>()

const emit = defineEmits<{
  open: []
  'toggle-edit': []
  'draft-input': [text: string]
  'draft-blur': []
}>()

function displayTitle(ch: ChapterCardData): string {
  return ch.title || '(未命名)'
}

function anchorChipClass(done: number, total: number): string {
  if (total === 0) return ''
  return done >= total ? 'done' : ''
}
</script>

<template>
  <article :id="`oc-${chapter.id}`" class="oc-card" :class="{ editing }">
    <div class="oc-main" :class="{ clickable: !editing }" @click="!editing && emit('open')">
      <span class="oc-num">第 {{ chapter.number }} 章</span>
      <div class="oc-mid">
        <div class="oc-title-row">
          <h3 class="oc-title">{{ displayTitle(chapter) }}</h3>
          <span v-if="chapter.status" class="oc-chip">{{ chapter.status }}</span>
          <span
            v-if="chapter.anchorTotal > 0"
            class="oc-chip"
            :class="anchorChipClass(chapter.anchorDone, chapter.anchorTotal)"
            :title="`非写不可的情节：已兑现 ${chapter.anchorDone}/${chapter.anchorTotal}`"
          >关键情节 {{ chapter.anchorDone }}/{{ chapter.anchorTotal }}</span>
          <span
            v-if="chapter.revealLabels.length"
            class="oc-chip zhu"
            :title="`计划本章揭示：${chapter.revealLabels.join('；')}`"
          >真相 {{ chapter.revealLabels.length }}</span>
          <span v-if="chapter.planted" class="oc-chip" :title="`本章埋下 ${chapter.planted} 条伏笔`">埋 {{ chapter.planted }}</span>
          <span v-if="chapter.resolved" class="oc-chip" :title="`本章收拢 ${chapter.resolved} 条伏笔`">收 {{ chapter.resolved }}</span>
          <span v-if="chapter.wordCount" class="oc-words">{{ chapter.wordCount }} 字</span>
        </div>
        <p v-if="chapter.intentText" class="oc-intent">打算：{{ chapter.intentText }}</p>
        <p v-if="chapter.outline" class="oc-outline">{{ chapter.outline }}</p>
        <p v-else class="oc-outline muted">暂无大纲</p>
      </div>
      <button
        class="oc-edit-btn"
        :title="editing ? '收起大纲编辑' : '就地编辑本章大纲'"
        @click.stop="emit('toggle-edit')"
      >
        <Icon :name="editing ? 'chevron-up' : 'pencil'" :size="14" />
      </button>
    </div>

    <div v-if="editing" class="oc-editor" @click.stop>
      <textarea
        class="oc-textarea"
        :value="draft"
        placeholder="写本章大纲：这章要发生什么、走到哪……"
        rows="6"
        @input="emit('draft-input', ($event.target as HTMLTextAreaElement).value)"
        @blur="emit('draft-blur')"
      ></textarea>
      <p class="oc-save-state" :class="saveState">
        <template v-if="saveState === 'saving'">保存中…</template>
        <template v-else-if="saveState === 'saved'">已保存</template>
        <template v-else-if="saveState === 'error'">保存失败，改动未落盘（可重试：改一个字即可再存）</template>
        <template v-else>每 2 秒自动保存 · 失焦立即保存</template>
      </p>
    </div>
  </article>
</template>

<style scoped>
.oc-card {
  background: var(--bg-canvas);
  border: 1px solid var(--border-color);
  border-radius: 0.375rem;
  transition: border-color 0.15s ease;
}

.oc-card:hover {
  border-color: var(--accent-500);
}

.oc-card.editing {
  border-color: var(--accent-500);
}

.oc-main {
  display: flex;
  gap: 0.75rem;
  padding: 0.75rem 0.875rem;
  align-items: flex-start;
}

.oc-main.clickable {
  cursor: pointer;
}

.oc-num {
  flex: none;
  width: 4.25rem;
  font-size: var(--text-xs);
  color: var(--text-muted);
  font-variant-numeric: tabular-nums;
  padding-top: 0.25rem;
  white-space: nowrap;
}

.oc-mid {
  flex: 1;
  min-width: 0;
}

.oc-title-row {
  display: flex;
  align-items: center;
  gap: 0.375rem;
  flex-wrap: wrap;
}

.oc-title {
  font-family: var(--font-heading);
  font-size: 0.9375rem;
  font-weight: 600;
  color: var(--text-primary);
  margin: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  max-width: 22rem;
}

.oc-chip {
  font-size: var(--text-xs);
  padding: 0.0625rem 0.375rem;
  background: var(--bg-tertiary);
  color: var(--text-secondary);
  border-radius: 0.1875rem;
  white-space: nowrap;
}

.oc-chip.done {
  color: var(--text-primary);
}

.oc-chip.zhu {
  background: rgba(166, 62, 42, 0.12); /* 朱砂语义（真相层视觉签名） */
  color: #a63e2a;
}

.oc-words {
  margin-left: auto;
  font-size: var(--text-xs);
  color: var(--text-muted);
  font-variant-numeric: tabular-nums;
  white-space: nowrap;
}

.oc-intent {
  font-size: 0.75rem;
  color: var(--text-secondary);
  margin: 0.25rem 0 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.oc-outline {
  font-size: 0.75rem;
  color: var(--text-secondary);
  line-height: 1.5;
  margin: 0.25rem 0 0;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

.oc-outline.muted {
  color: var(--text-muted);
  font-style: italic;
}

.oc-edit-btn {
  flex: none;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 1.625rem;
  height: 1.625rem;
  background: transparent;
  border: 1px solid var(--border-color);
  border-radius: 0.25rem;
  color: var(--text-muted);
  cursor: pointer;
}

.oc-edit-btn:hover {
  background: var(--hover-bg);
  color: var(--text-primary);
}

.oc-editor {
  border-top: 1px dashed var(--border-color);
  padding: 0.625rem 0.875rem 0.625rem 5rem;
}

.oc-textarea {
  width: 100%;
  min-height: 6rem;
  max-height: 20rem;
  resize: vertical;
  font-family: var(--font-body);
  font-size: 0.8125rem;
  line-height: 1.6;
  color: var(--text-primary);
  background: var(--bg-secondary);
  border: 1px solid var(--border-color);
  border-radius: 0.25rem;
  padding: 0.5rem 0.625rem;
  box-sizing: border-box;
}

.oc-textarea:focus {
  outline: none;
  border-color: var(--accent-500);
}

.oc-save-state {
  font-size: var(--text-xs);
  color: var(--text-muted);
  margin: 0.375rem 0 0;
}

.oc-save-state.saved {
  color: var(--text-secondary);
}

.oc-save-state.error {
  color: #a63e2a;
}
</style>
