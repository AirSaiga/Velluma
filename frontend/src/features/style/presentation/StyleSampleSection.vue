<script setup lang="ts">
/**
 * 文风页 ①「你的字」——样本库分区（文风的事实源，一切从这里长出来）。
 *
 * 职责：上传新样本（粘贴作者原文）/ 展示样本列表（含轻量指纹速览）/ 收编入口 /
 * 样本就地编辑（正文 / 场景类型 / 时期 / 收藏）。
 * 纯展示：数据与操作全部经 props/emits 与容器交互（分层规范 presentation → 容器）。
 *
 * 零状态坡道（设计稿 §6.3）由容器切换：无样本时整页只显示本组件的 hero 邀请形态——
 * 「整页只有一个邀请」，用户唯一付出的劳动是复制粘贴，不做任何分类选择
 * （场景类型/时期默认 general/recent，入库后可在样本卡上改）。
 */
import { ref } from 'vue'
import Icon from '../../../components/Icon.vue'
import type { AuthorSample, AuthorSampleSceneType, TextFingerprint } from '../../../types'

const props = defineProps<{
  samples: AuthorSample[]
  /** 逐样本轻量指纹（sample_id → fingerprint），加载中可为空对象 */
  fingerprintBySample: Record<string, TextFingerprint>
  /** 零状态邀请形态：隐藏列表与次要动作，整页只剩一个 hero 输入区 */
  ramp?: boolean
  busy?: boolean
  /** 存量黄金片段数（>0 显示「导入黄金片段」入口） */
  goldenCount?: number
}>()

const emit = defineEmits<{
  (e: 'upload', content: string, sceneType: AuthorSampleSceneType, era: 'recent' | 'early'): void
  (e: 'delete', sampleId: string): void
  (e: 'importChapters'): void
  (e: 'importGolden'): void
  (e: 'update-sample', sampleId: string, patch: { era?: 'recent' | 'early'; favorite?: boolean; scene_type?: AuthorSampleSceneType; content?: string }): void
}>()

const newSampleContent = ref('')
const newSampleSceneType = ref<AuthorSampleSceneType>('general')
const newSampleEra = ref<'recent' | 'early'>('recent')

const sceneTypeLabels: Record<string, string> = {
  dialogue: '对话',
  action: '动作',
  lyrical: '抒情',
  suspense: '悬念',
  general: '通用',
}

const sourceLabels: Record<string, string> = {
  manual: '手写',
  golden_snippet: '黄金片段',
  published_chapter: '章节收编',
}

function submit() {
  const content = newSampleContent.value.trim()
  if (!content) return
  emit('upload', content, newSampleSceneType.value, newSampleEra.value)
  newSampleContent.value = ''
}

// ---- 样本就地编辑（正文） ----
const editingId = ref<string | null>(null)
const editingContent = ref('')

function startEdit(sample: AuthorSample) {
  editingId.value = sample.id
  editingContent.value = sample.content
}

function cancelEdit() {
  editingId.value = null
  editingContent.value = ''
}

function saveEdit(sample: AuthorSample) {
  const content = editingContent.value.trim()
  if (!content || content === sample.content.trim()) {
    cancelEdit()
    return
  }
  emit('update-sample', sample.id, { content })
  cancelEdit()
}
</script>

<template>
  <section id="style-sec-samples" class="style-section" :class="{ ramp }">
    <!-- 零状态 hero：整页只有一个邀请（设计稿 §6.3 第一幕） -->
    <div v-if="ramp" class="ramp-hero">
      <h2 class="hero-title">贴一段你写过的字</h2>
      <p class="hero-sub">你的文风以这里为准——指纹、画像、负面清单，都从这里长出来。</p>
      <textarea
        v-model="newSampleContent"
        rows="9"
        class="hero-textarea"
        placeholder="粘贴你写过的原文（建议 200–2000 字，对话/动作/抒情各来一段更好）"
        @keydown.ctrl.enter="submit"
      ></textarea>
      <div class="hero-actions">
        <button
          class="hero-btn"
          :disabled="busy || !newSampleContent.trim()"
          @click="submit"
        >开始测量我的笔迹</button>
        <button
          class="hero-link"
          :disabled="busy"
          title="从本书已发布章节自动摘取样本（无需手动粘贴）"
          @click="emit('importChapters')"
        >或从已发布章节自动采样</button>
      </div>
      <p class="hero-note">贴入后几秒（纯算法测量，不创作不改写）就能看到你的句长分布。</p>
    </div>

    <template v-else>
      <header class="sec-head">
        <h2 class="sec-title">你的字</h2>
        <p class="sec-sub">
          贴一段你写过的文字——你的文风以这里为准，指纹与画像都从这里长出来。
        </p>
      </header>

      <!-- 上传卡 -->
      <div class="upload-card">
        <textarea
          v-model="newSampleContent"
          rows="3"
          class="upload-textarea"
          placeholder="粘贴你写过的原文（建议 200-2000 字，对话/动作/抒情各来一段更好）"
          @keydown.ctrl.enter="submit"
        ></textarea>
        <div class="upload-row">
          <select v-model="newSampleSceneType" class="scene-select">
            <option v-for="(label, key) in sceneTypeLabels" :key="key" :value="key">{{ label }}</option>
          </select>
          <select v-model="newSampleEra" class="scene-select" title="近期的样本参与统计和检索；早期的只存档">
            <option value="recent">近期</option>
            <option value="early">早期</option>
          </select>
          <button
            class="btn-primary"
            :disabled="busy || !newSampleContent.trim()"
            @click="submit"
          >存入样本库</button>
          <button
            class="btn-ghost"
            :disabled="busy"
            title="从本书已发布章节自动摘取样本（无需手动粘贴）"
            @click="emit('importChapters')"
          >从章节收编</button>
          <button
            v-if="goldenCount && goldenCount > 0"
            class="btn-ghost"
            :disabled="busy"
            :title="`把本书已有的 ${goldenCount} 条黄金片段导入样本库（AI 照着范例学，也进统计）`"
            @click="emit('importGolden')"
          >导入黄金片段（{{ goldenCount }}）</button>
          <span v-else class="upload-hint">Ctrl+Enter 快速存入</span>
        </div>
      </div>

      <!-- 样本列表 -->
      <div class="sample-list">
        <div v-if="samples.length === 0" class="empty-note">暂无样本——贴入第一段字，三秒后就能看到你的句长分布。</div>
        <article
          v-for="sample in samples"
          :key="sample.id"
          class="sample-card"
        >
          <div class="sample-meta">
            <button
              class="fav-btn"
              :class="{ active: sample.favorite }"
              :title="sample.favorite ? '取消收藏（AI 找范例时不再优先带这条）' : '收藏：AI 找范例时优先带这条'"
              @click="emit('update-sample', sample.id, { favorite: !sample.favorite })"
            >{{ sample.favorite ? '★' : '☆' }}</button>
            <select
              class="badge badge-scene scene-edit"
              title="场景类型（统计与检索按此分类）"
              :value="sample.scene_type"
              @change="emit('update-sample', sample.id, { scene_type: ($event.target as HTMLSelectElement).value as AuthorSampleSceneType })"
            >
              <option v-for="(label, key) in sceneTypeLabels" :key="key" :value="key">{{ label }}</option>
            </select>
            <span v-if="sample.source !== 'manual'" class="badge badge-source">{{ sourceLabels[sample.source] || sample.source }}</span>
            <span v-if="sample.era === 'early'" class="badge badge-early" title="早期样本只存档，不参与统计">早期</span>
            <span class="sample-chips">
              <template v-if="fingerprintBySample[sample.id]">
                <span class="chip">句均 {{ fingerprintBySample[sample.id].sentence_len_mean }} 字</span>
                <span class="chip">对话 {{ Math.round((fingerprintBySample[sample.id].dialogue_ratio || 0) * 100) }}%</span>
                <span class="chip">起伏 {{ fingerprintBySample[sample.id].sentence_len_cv }}</span>
              </template>
              <span class="chip chip-dim">{{ sample.word_count }} 字</span>
            </span>
            <button
              v-if="editingId !== sample.id"
              class="icon-btn"
              title="编辑样本正文"
              @click="startEdit(sample)"
            >
              <Icon name="pencil-square" :size="12" />
            </button>
            <button class="icon-danger" title="删除样本" @click="emit('delete', sample.id)">
              <Icon name="x-mark" :size="12" />
            </button>
          </div>

          <!-- 就地编辑态：正文可改，保存后后端重算字数并重向量化 -->
          <template v-if="editingId === sample.id">
            <textarea
              v-model="editingContent"
              class="sample-edit-textarea"
              rows="6"
              @keydown.ctrl.enter="saveEdit(sample)"
              @keydown.esc="cancelEdit"
            ></textarea>
            <div class="sample-edit-actions">
              <span class="edit-hint">保存后将重新测量指纹并重算向量 · Ctrl+Enter 保存 · Esc 取消</span>
              <button class="era-toggle" @click="cancelEdit">取消</button>
              <button
                class="btn-primary btn-sm"
                :disabled="busy || !editingContent.trim()"
                @click="saveEdit(sample)"
              >保存</button>
            </div>
          </template>
          <p v-else class="sample-content">{{ sample.content }}</p>

          <div v-if="editingId !== sample.id" class="sample-foot">
            <span v-if="sample.era === 'early'" class="muted-foot">早期样本不参与统计——若仍代表现在的你，可切回近期</span>
            <button
              class="era-toggle"
              @click="emit('update-sample', sample.id, { era: sample.era === 'early' ? 'recent' : 'early' })"
            >{{ sample.era === 'early' ? '标记为近期' : '标记为早期' }}</button>
          </div>
        </article>
      </div>
    </template>
  </section>
</template>

<style scoped>
.style-section {
  padding: 1.25rem 0 1.5rem;
  scroll-margin-top: 4.5rem;
}
.style-section.ramp {
  width: 100%;
  padding: 0;
  border-bottom: none;
}
.sec-head {
  margin-bottom: 0.75rem;
}
.sec-title {
  margin: 0;
  font-family: var(--font-heading);
  font-size: 1rem;
  font-weight: 600;
  color: var(--text-primary);
}
.sec-sub {
  margin: 0.25rem 0 0;
  font-size: 0.75rem;
  line-height: 1.6;
  color: var(--text-muted);
}

/* ---- 零状态 hero（整页唯一邀请） ---- */
.ramp-hero {
  width: 100%;
  max-width: 38rem;
  margin: 0 auto;
  text-align: center;
}
.hero-title {
  margin: 0;
  font-family: var(--font-heading);
  font-size: 1.875rem;
  font-weight: 600;
  letter-spacing: 0.02em;
  color: var(--text-primary);
}
.hero-sub {
  margin: 0.625rem 0 1.5rem;
  font-size: 0.875rem;
  line-height: 1.7;
  color: var(--text-muted);
}
.hero-textarea {
  width: 100%;
  padding: 1rem 1.125rem;
  font-size: 0.9375rem;
  line-height: 1.9;
  text-align: left;
  background: var(--bg-panel);
  border: 1px solid var(--border-color);
  border-radius: 0.75rem;
  box-shadow: 0 1px 2px color-mix(in srgb, black 3%, transparent);
  resize: vertical;
}
.hero-textarea:focus {
  outline: none;
  border-color: var(--accent-400);
  box-shadow: 0 0 0 3px color-mix(in srgb, var(--accent-500) 10%, transparent);
}
.hero-actions {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 0.5rem;
  margin-top: 1rem;
}
.hero-btn {
  padding: 0.625rem 2rem;
  font-size: 0.9375rem;
  color: white;
  background: var(--accent-500);
  border: none;
  border-radius: 0.5rem;
  cursor: pointer;
  transition: background 0.15s ease;
}
.hero-btn:hover:not(:disabled) {
  background: var(--accent-600);
}
.hero-btn:disabled {
  opacity: 0.45;
  cursor: not-allowed;
}
.hero-link {
  padding: 0.25rem 0.5rem;
  font-size: 0.8125rem;
  color: var(--text-muted);
  background: transparent;
  border: none;
  cursor: pointer;
}
.hero-link:hover:not(:disabled) {
  color: var(--accent-500);
  text-decoration: underline;
}
.hero-link:disabled {
  opacity: 0.5;
}
.hero-note {
  margin: 1.25rem 0 0;
  font-size: 0.75rem;
  line-height: 1.7;
  color: var(--text-muted);
}

/* ---- 常态上传卡 ---- */
.upload-card {
  padding: 0.75rem;
  background: var(--bg-panel);
  border: 1px solid var(--border-color);
  border-radius: 0.5rem;
}
.upload-textarea {
  width: 100%;
  padding: 0.5rem 0.625rem;
  font-size: 0.8125rem;
  line-height: 1.7;
  background: transparent;
  border: 1px solid var(--border-color);
  border-radius: 0.375rem;
  resize: vertical;
}
.upload-textarea:focus {
  outline: none;
  border-color: var(--accent-400);
}
.upload-row {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 0.5rem;
  margin-top: 0.5rem;
}
.scene-select {
  padding: 0.3rem 0.5rem;
  font-size: 0.75rem;
  background: transparent;
  border: 1px solid var(--border-color);
  border-radius: 0.375rem;
}
.btn-primary {
  padding: 0.375rem 0.875rem;
  font-size: 0.8125rem;
  color: white;
  background: var(--accent-500);
  border: none;
  border-radius: 0.375rem;
  cursor: pointer;
}
.btn-primary:hover:not(:disabled) {
  background: var(--accent-600);
}
.btn-primary:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}
.btn-ghost {
  padding: 0.375rem 0.75rem;
  font-size: 0.75rem;
  color: var(--text-secondary);
  background: transparent;
  border: 1px dashed var(--border-color);
  border-radius: 0.375rem;
  cursor: pointer;
}
.btn-ghost:hover:not(:disabled) {
  color: var(--accent-500);
  border-color: var(--accent-400);
}
.btn-ghost:disabled {
  opacity: 0.5;
}
.upload-hint {
  font-size: 0.6875rem;
  color: var(--text-muted);
}
.sample-list {
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
  max-height: 24rem;
  padding-right: 0.25rem;
  margin-top: 0.75rem;
  overflow-y: auto;
}
.empty-note {
  padding: 1rem;
  font-size: 0.75rem;
  text-align: center;
  color: var(--text-muted);
}
.sample-card {
  padding: 0.625rem 0.75rem;
  background: var(--bg-panel);
  border: 1px solid var(--border-color);
  border-radius: 0.5rem;
}
.sample-meta {
  display: flex;
  align-items: center;
  gap: 0.375rem;
  margin-bottom: 0.375rem;
}
.badge {
  padding: 0.0625rem 0.4375rem;
  font-size: 0.625rem;
  border-radius: 0.25rem;
  white-space: nowrap;
}
.badge-scene {
  color: #1d4ed8;
  background: #dbeafe;
}
.badge-source {
  color: #047857;
  background: #d1fae5;
}
.sample-chips {
  display: flex;
  flex: 1;
  gap: 0.375rem;
  align-items: center;
  overflow: hidden;
}
.chip {
  padding: 0.0625rem 0.4375rem;
  font-size: 0.625rem;
  color: var(--text-secondary);
  background: var(--bg-tertiary);
  border-radius: 0.25rem;
  white-space: nowrap;
}
.chip-dim {
  color: var(--text-muted);
}
.icon-danger {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  padding: 0.1875rem;
  color: var(--text-muted);
  background: transparent;
  border: none;
  border-radius: 0.25rem;
  cursor: pointer;
}
.icon-danger:hover {
  color: #dc2626;
  background: #fee2e2;
}
.icon-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  padding: 0.1875rem;
  color: var(--text-muted);
  background: transparent;
  border: none;
  border-radius: 0.25rem;
  cursor: pointer;
}
.icon-btn:hover {
  color: var(--accent-500);
  background: var(--bg-tertiary);
}
.scene-edit {
  border: none;
  cursor: pointer;
  font-family: inherit;
}
.scene-edit:hover {
  filter: brightness(0.96);
}
.scene-edit:focus {
  outline: 1px solid var(--accent-400);
}
.sample-edit-textarea {
  width: 100%;
  padding: 0.5rem 0.625rem;
  font-size: 0.8125rem;
  line-height: 1.7;
  color: var(--text-primary);
  background: var(--bg-primary);
  border: 1px solid var(--accent-400);
  border-radius: 0.375rem;
  resize: vertical;
}
.sample-edit-textarea:focus {
  outline: none;
  box-shadow: 0 0 0 3px color-mix(in srgb, var(--accent-500) 10%, transparent);
}
.sample-edit-actions {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: 0.5rem;
  margin-top: 0.375rem;
}
.edit-hint {
  flex: 1;
  font-size: 0.625rem;
  color: var(--text-muted);
}
.btn-sm {
  padding: 0.25rem 0.75rem;
  font-size: 0.75rem;
}
.sample-content {
  display: -webkit-box;
  -webkit-box-orient: vertical;
  -webkit-line-clamp: 3;
  overflow: hidden;
  margin: 0;
  font-size: 0.75rem;
  line-height: 1.7;
  color: var(--text-secondary);
}
.sample-foot {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: 0.5rem;
  margin-top: 0.25rem;
}
.muted-foot {
  flex: 1;
  font-size: 0.625rem;
  color: var(--text-muted);
}
.era-toggle {
  padding: 0.125rem 0.4375rem;
  font-size: 0.625rem;
  color: var(--text-muted);
  background: transparent;
  border: 1px dashed var(--border-color);
  border-radius: 0.375rem;
  cursor: pointer;
}
.era-toggle:hover {
  color: var(--accent-500);
  border-color: var(--accent-400);
}
.badge-early {
  color: #6b7280;
  background: #f3f4f6;
}
.fav-btn {
  flex-shrink: 0;
  padding: 0;
  font-size: 0.875rem;
  line-height: 1;
  color: #d1d5db;
  background: transparent;
  border: none;
  cursor: pointer;
}
.fav-btn.active {
  color: #f59e0b;
}
.fav-btn:hover {
  color: #f59e0b;
}
</style>
