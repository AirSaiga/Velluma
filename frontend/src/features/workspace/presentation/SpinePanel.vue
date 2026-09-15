<script setup lang="ts">
/**
 * 叙事引力流面板（第四弹 UI 合流 · docs/spine-outline-merge-feasibility.md 路径 C）。
 *
 * 原「打算（SpinePanel）+ 大纲卡」上下双框是作者认知负荷的病灶——底层两字段
 * 分立是事故换来的稳态（spine.intent 走 system 温卡防冲章 / outline_text 走
 * user 就近节拍防剧透），本面板只在 **UI 层**合流为单一叙事流编辑面：
 * - 🎯 本章方向（首行高亮锚） ⇄ chapters.spine.intent.text（≤60 字，600ms
 *   防抖+失焦兜底，原有链路）；
 * - 锚点 chips/岔路/建议：spine.anchors 体系原样保留（方向与细节之间）；
 * - 📝 情节节拍（节拍推进流） ⇄ chapters.outline_text（容器侧 500ms 防抖）；
 * - 活跃节拍微标：容器传入 outline_nearby 首拍（与 stitch/dock 同一份计算）。
 * 数据分流边界=控件边界（两个物理控件一个视觉容器）——整段粘贴进方向行被
 * maxlength 截断引导到节拍区，绝不发生「整段大纲掉进意图」。
 */
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import type { ChapterSpine, SpineAnchor, SpineSuggestion } from '../../../services/api/domain/adaptive.api'
import { highlightAnchorId } from '../composables/useChapterSpine'

const props = defineProps<{
  spine: ChapterSpine | null
  suggestions: SpineSuggestion | null
  suggesting: boolean
  /** 章节未选/不可用时的禁用态 */
  disabled?: boolean
  /** 情节节拍流（chapters.outline_text；第四弹合流——容器侧防抖保存） */
  outlineText?: string
  /** 当前就近节拍（outline_nearby 首拍；空/null=无大纲或全已写=微标缺席） */
  activeBeat?: string | null
}>()

const emit = defineEmits<{
  (e: 'update-intent', text: string): void
  (e: 'add-anchor', text: string): void
  (e: 'update-anchor', id: string, patch: Partial<SpineAnchor>): void
  (e: 'remove-anchor', id: string): void
  (e: 'suggest'): void
  (e: 'adopt', part: 'intent' | 'anchors' | 'all'): void
  (e: 'discard-suggestions'): void
  (e: 'update-outline', text: string): void
  (e: 'outline-blur'): void
}>()

const intentText = computed(() => props.spine?.intent?.text || '')
const anchors = computed(() => props.spine?.anchors || [])
const addingAnchor = ref('')
const anchorFull = computed(() => anchors.value.length >= 5)

// ---- 意图草稿（2026-09-01 丢稿修复）----
// 旧绑定是单向 :value + 仅 @change：失焦才提交，期间任何重渲染（心跳回写锚点
// 状态等，几秒一次）都会把未失焦的输入重置回旧值——输入没进保存链就被清掉。
// 改本地草稿 + 输入即 600ms 防抖提交 + 失焦兜底；外部值仅在本地无未提交
// 改动时同步（作者正在打字时不被回包/心跳打断）。
const intentDraft = ref('')
const intentDirty = ref(false)
let intentCommitTimer: ReturnType<typeof setTimeout> | null = null

watch(() => props.spine?.intent?.text, (t) => {
  if (!intentDirty.value) intentDraft.value = t || ''
}, { immediate: true })

function commitIntent() {
  if (intentCommitTimer) { clearTimeout(intentCommitTimer); intentCommitTimer = null }
  if (!intentDirty.value) return
  intentDirty.value = false
  emit('update-intent', intentDraft.value)
}

function onIntentInput(e: Event) {
  intentDraft.value = (e.target as HTMLTextAreaElement).value
  intentDirty.value = true
  if (intentCommitTimer) clearTimeout(intentCommitTimer)
  intentCommitTimer = setTimeout(commitIntent, 600)
}

onBeforeUnmount(() => commitIntent())

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
  <section class="spine-panel narrative-stream" :class="{ 'spine-panel--empty': !intentText && !anchors.length && !outlineText }">
    <div class="spine-head">
      <span class="spine-title">叙事流</span>
      <span class="spine-hint">先定方向，再记节拍——写到哪一拍，AI 就跟到哪</span>
    </div>

    <!-- 🎯 本章方向（主方向锚点 ⇄ spine.intent；「不对」纠正手势在容器意图反推行） -->
    <div class="ns-direction">
      <label class="ns-tag">🎯 本章方向</label>
      <textarea
        class="spine-intent"
        rows="1"
        maxlength="60"
        :value="intentDraft"
        placeholder="一句话：这一章主要讲什么？（可空，直接开写也行）"
        @input="onIntentInput"
        @blur="commitIntent"
      ></textarea>
    </div>

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
        <button class="spine-suggest__btn spine-suggest__btn--primary btn-primary-instrument" @click="saveBranch">保存</button>
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
    <p v-else class="spine-full-hint">最多 5 条——细节留给下面的节拍，这里只记最要紧的</p>

    <!-- 📝 情节节拍（节拍推进流 ⇄ outline_text；容器侧 500ms 防抖+失焦/唤舱/续写冲刷） -->
    <div class="ns-beats">
      <div class="ns-beats-head">
        <label class="ns-tag">📝 情节节拍</label>
        <span
          v-if="activeBeat"
          class="ns-active-beat"
          :title="`续写正朝这拍走：${activeBeat}`"
        >▶ {{ activeBeat.length > 18 ? activeBeat.slice(0, 18) + '…' : activeBeat }}</span>
      </div>
      <textarea
        class="ns-beats-input"
        rows="6"
        :value="outlineText"
        placeholder="这一章具体发生什么，一行一拍（AI 续写贴着还没写的拍走）"
        @input="(e) => emit('update-outline', (e.target as HTMLTextAreaElement).value)"
        @blur="emit('outline-blur')"
      ></textarea>
    </div>

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
            <button class="spine-suggest__btn spine-suggest__btn--primary btn-primary-instrument" @click="emit('adopt', 'all')">全部收下</button>
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
  font-size: var(--text-xs);
  color: var(--text-muted);
}
.spine-intent {
  width: 100%;
  resize: none;
  border: none;
  border-bottom: 1px dashed var(--border-color);
  background: transparent;
  font-family: var(--font-heading);
  font-size: 0.8125rem;
  color: var(--text-primary);
  padding: 0.25rem 0;
  line-height: 1.5;
}
.spine-intent:focus {
  outline: none;
  border-bottom-color: var(--accent-400);
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
  font-size: var(--text-xs);
  color: var(--text-primary);
  background: var(--bg-secondary);
}
.spine-chip--dropped {
  opacity: 0.45;
  text-decoration: line-through;
}
.spine-chip--hit {
  border-color: var(--accent-400);
}
.spine-chip--branch {
  border-color: var(--cinnabar-bright);
}
.spine-chip__branch-mark {
  font-size: var(--text-xs);
  color: var(--cinnabar-bright);
}
.spine-branch-editor {
  display: flex;
  flex-direction: column;
  gap: 0.375rem;
  padding: 0.5rem;
  border: 1px solid var(--cinnabar-bright);
  border-radius: var(--radius-md);
  background: var(--bg-secondary);
}
.spine-branch-editor__head {
  font-size: var(--text-xs);
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
  border-radius: var(--radius-sm);
  background: transparent;
  font-size: 0.75rem;
  color: var(--text-primary);
  padding: 0.375rem 0.5rem;
  line-height: 1.6;
}
.spine-branch-editor__input:focus {
  outline: none;
  border-color: var(--cinnabar-bright);
}
.spine-branch-editor__actions {
  display: flex;
  gap: 0.375rem;
}
.spine-chip--flash {
  animation: spine-flash 0.5s ease 2;
  border-color: var(--accent-500);
}
@keyframes spine-flash {
  0%, 100% { background: var(--bg-secondary); }
  50% { background: var(--accent-400); color: var(--bg-canvas); }
}
.spine-chip--ghost {
  border-style: dashed;
  color: var(--text-secondary);
}
.spine-chip__btn {
  border: none;
  background: none;
  cursor: pointer;
  font-size: var(--text-xs);
  color: var(--text-muted);
  padding: 0 0.125rem;
}
.spine-chip__btn:hover {
  color: var(--text-primary);
}
.spine-anchor-count {
  font-size: var(--text-xs);
  color: var(--text-muted);
  text-align: right;
}
.spine-add__input {
  width: 100%;
  border: 1px dashed var(--border-color);
  border-radius: var(--radius-sm);
  background: transparent;
  font-size: var(--text-xs);
  color: var(--text-primary);
  padding: 0.25rem 0.5rem;
}
.spine-add__input:focus {
  outline: none;
  border-color: var(--accent-400);
}
.spine-full-hint {
  font-size: var(--text-xs);
  color: var(--text-muted);
  margin: 0;
}
.spine-hint-line {
  font-size: var(--text-xs);
  color: var(--text-muted);
  margin: 0;
  line-height: 1.5;
}
.spine-suggest__btn {
  border: 1px solid var(--border-color);
  border-radius: var(--radius-sm);
  background: var(--bg-secondary);
  color: var(--text-secondary);
  font-size: var(--text-xs);
  padding: 0.25rem 0.625rem;
  cursor: pointer;
}
.spine-suggest__btn:disabled {
  opacity: 0.5;
  cursor: default;
}
.spine-suggest__btn--primary {
}
.spine-suggest__card {
  display: flex;
  flex-direction: column;
  gap: 0.375rem;
  padding: 0.5rem;
  border: 1px solid var(--accent-400);
  border-radius: var(--radius-md);
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
  font-size: var(--text-xs);
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

/* ===== 第四弹：叙事流合流视觉（单容器/方向行高亮/节拍区无缝衔接） ===== */
.narrative-stream {
  padding: 0.5rem;
  border: 1px solid var(--border-color);
  border-radius: var(--radius-lg);
  background: var(--bg-canvas);
}
.ns-direction {
  display: flex;
  flex-direction: column;
  gap: 0.25rem;
  padding: 0.375rem 0.5rem;
  background: color-mix(in srgb, var(--accent-500) 6%, transparent);
  border-left: 3px solid var(--accent-500);
  border-radius: var(--radius-sm);
}
.ns-tag {
  font-size: var(--text-xs);
  font-weight: 600;
  letter-spacing: 0.04em;
  color: var(--text-muted);
}
.ns-direction .spine-intent {
  font-size: 0.8125rem;
}
.ns-beats {
  display: flex;
  flex-direction: column;
  gap: 0.25rem;
}
.ns-beats-head {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 0.5rem;
}
.ns-active-beat {
  font-size: var(--text-xs);
  color: var(--accent-500);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.ns-beats-input {
  width: 100%;
  min-height: 96px;
  resize: vertical;
  border: 1px dashed var(--border-color);
  border-radius: var(--radius-sm);
  background: transparent;
  font-size: 0.75rem;
  color: var(--text-primary);
  padding: 0.375rem 0.5rem;
  line-height: 1.6;
}
.ns-beats-input:focus {
  outline: none;
  border-color: var(--accent-400);
  border-style: solid;
}
</style>
