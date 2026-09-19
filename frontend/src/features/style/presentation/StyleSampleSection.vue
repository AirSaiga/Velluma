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
import { computed, ref } from 'vue'
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

// §4.1 拆二级滚动：默认收 6 条，展开看全部（页滚动唯一）
const SAMPLE_COLLAPSED_COUNT = 6
const expanded = ref(false)
const visibleSamples = computed(() =>
  expanded.value ? props.samples : props.samples.slice(0, SAMPLE_COLLAPSED_COUNT),
)

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
      <p class="hero-sub">你的文风以这里为准——AI 学你写字、躲你圈词，都从这段字开始。</p>
      <textarea
        v-model="newSampleContent"
        rows="9"
        class="hero-textarea"
        placeholder="贴一段你自己写的字（对话、打斗、抒情都行）"
        @keydown.ctrl.enter="submit"
      ></textarea>
      <div class="hero-actions">
        <button
          class="hero-btn"
          :disabled="busy || !newSampleContent.trim()"
          @click="submit"
        >存进字帖</button>
        <button
          class="hero-link"
          :disabled="busy"
          title="从本书已发布章节自动摘字（无需手动粘贴）"
          @click="emit('importChapters')"
        >或从已发布章节自动采样</button>
      </div>
      <p class="hero-note">存好就能在「试写对比」里亲眼看 AI 学得像不像；AI 不会改你贴的字。</p>
    </div>

    <template v-else>
      <!-- 2026-09-17 重设计：分区标题退役——栏头「亲笔字帖」在容器接管（避免双标题） -->

      <!-- 上传卡 -->
      <div class="upload-card">
        <textarea
          v-model="newSampleContent"
          rows="3"
          class="upload-textarea"
          placeholder="贴一段你自己写的字（对话、打斗、抒情都行）——AI 学你写字，从这里开始"
          @keydown.ctrl.enter="submit"
        ></textarea>
        <div class="upload-row">
          <select v-model="newSampleSceneType" class="scene-select" title="这段字的类型（帮 AI 按场合挑范例）">
            <option v-for="(label, key) in sceneTypeLabels" :key="key" :value="key">{{ label }}</option>
          </select>
          <select v-model="newSampleEra" class="scene-select" title="近期的字会被 AI 挑作范例；早期的只存档备查">
            <option value="recent">近期</option>
            <option value="early">早期</option>
          </select>
          <button
            class="btn-primary"
            :disabled="busy || !newSampleContent.trim()"
            @click="submit"
          >存进字帖</button>
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
            :title="`把本书已有的 ${goldenCount} 条黄金片段收进字帖（AI 会照着学）`"
            @click="emit('importGolden')"
          >导入黄金片段</button>
          <span v-else class="upload-hint">Ctrl+Enter 快速存入</span>
        </div>
      </div>

      <!-- 样本列表（§4.1：默认 6 条 + 展开收起，拆掉二级滚动嵌套） -->
      <div class="sample-list">
        <div v-if="samples.length === 0" class="empty-note">字帖还空着——贴入第一段字，马上就能去「试写对比」看效果。</div>
        <article
          v-for="sample in visibleSamples"
          :key="sample.id"
          class="sample-card"
        >
          <div class="sample-meta">
            <button
              class="fav-btn"
              :class="{ active: sample.favorite }"
              :title="sample.favorite ? '取消收藏（AI 找范例时不再优先带这条）' : '收藏：AI 找范例时优先带这条'"
              @click="emit('update-sample', sample.id, { favorite: !sample.favorite })"
            ><Icon name="star" :size="14" /></button>
            <select
              class="badge badge-scene scene-edit"
              title="这段字的类型（帮 AI 按场合挑范例）"
              :value="sample.scene_type"
              @change="emit('update-sample', sample.id, { scene_type: ($event.target as HTMLSelectElement).value as AuthorSampleSceneType })"
            >
              <option v-for="(label, key) in sceneTypeLabels" :key="key" :value="key">{{ label }}</option>
            </select>
            <span v-if="sample.source !== 'manual'" class="badge badge-source">{{ sourceLabels[sample.source] || sample.source }}</span>
            <span v-if="sample.era === 'early'" class="badge badge-early" title="早期的字只存档备查，AI 不会挑它作范例">早期</span>
            <!-- 工坊零数字（v4）：字数等测量信息不上卡——只留场景/来源/收藏 -->
            <span class="sample-chips" />
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
              <span class="edit-hint">保存后 AI 会重新学一遍这段字 · Ctrl+Enter 保存 · Esc 取消</span>
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
            <span v-if="sample.era === 'early'" class="muted-foot">标记为早期的字不会被 AI 挑作范例——若它仍代表现在的你，可切回近期</span>
            <button
              class="era-toggle"
              @click="emit('update-sample', sample.id, { era: sample.era === 'early' ? 'recent' : 'early' })"
            >{{ sample.era === 'early' ? '标记为近期' : '标记为早期' }}</button>
          </div>
        </article>
        <button
          v-if="samples.length > SAMPLE_COLLAPSED_COUNT"
          class="list-expand-btn"
          @click="expanded = !expanded"
        >
          {{ expanded ? '收起' : `展开其余 ${samples.length - SAMPLE_COLLAPSED_COUNT} 条` }}
        </button>
      </div>
    </template>
  </section>
</template>

<style scoped>
.style-section {
  /* 2026-09-17：顶部 padding 归零——列头（容器 sec-head）正上方，与右列同顶对齐 */
  padding: 0 0 var(--space-6);
  scroll-margin-top: 4.5rem;
}
.style-section.ramp {
  width: 100%;
  padding: 0;
  border-bottom: none;
}
/* .sec-head/.sec-title 吃 style.css 全局工具类（00 期 §3.1）；
   分区标题已随 2026-09-17 重设计退役（栏头接管） */

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
  background: var(--surface-overlay);
  border: 1px solid var(--line);
  border-radius: 0.75rem;
  box-shadow: 0 1px 2px color-mix(in srgb, black 3%, transparent);
  resize: vertical;
}
.hero-textarea:focus {
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
  color: var(--bg-canvas);
  background: var(--accent-500);
  border: none;
  border-radius: var(--radius-md);
  cursor: pointer;
  transition: background var(--dur-2) var(--ease-out);
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

/* ---- 常态上传卡（2026-09-17：卡面归一 card-std 档） ---- */
.upload-card {
  padding: var(--space-3);
  background: var(--surface-card);
  border: 1px solid var(--line-faint);
  border-radius: var(--radius-md);
}
.upload-textarea {
  width: 100%;
  padding: 0.5rem 0.625rem;
  font-size: 0.8125rem;
  line-height: 1.7;
  background: transparent;
  border: 1px solid var(--line);
  border-radius: var(--radius-sm);
  resize: vertical;
}
.upload-textarea:focus {
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
  border: 1px solid var(--line);
  border-radius: var(--radius-sm);
}
.btn-primary {
  padding: 0.375rem 0.875rem;
  font-size: 0.8125rem;
  color: var(--bg-canvas);
  background: var(--accent-500);
  border: none;
  border-radius: var(--radius-sm);
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
  border-radius: var(--radius-sm);
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
  font-size: var(--text-xs);
  color: var(--text-muted);
}
.sample-list {
  /* §4.1 拆二级滚动：不设 max-height/overflow，长列表靠展开收起与页滚动 */
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
  margin-top: 0.75rem;
}
.list-expand-btn {
  min-height: 28px;
  padding: 0.375rem 0.75rem;
  font-size: var(--text-sm);
  color: var(--accent-500);
  background: transparent;
  border: 1px dashed var(--border-color);
  border-radius: var(--radius-sm);
  cursor: pointer;
}
.list-expand-btn:hover {
  background: var(--state-hover);
  border-color: var(--accent-500);
}
.empty-note {
  padding: 1rem;
  font-size: 0.75rem;
  text-align: center;
  color: var(--text-muted);
}
.sample-card {
  padding: 0.625rem var(--space-3);
  background: var(--surface-card);
  border: 1px solid var(--line-faint);
  border-radius: var(--radius-md);
  /* 04 §A2-2 可点卡统一微抬（.card-hover 规格） */
  transition: transform var(--dur-2) var(--ease-out), box-shadow var(--dur-2) var(--ease-out);
}
.sample-card:hover {
  box-shadow: var(--elev-2-shadow);
}
.sample-meta {
  display: flex;
  align-items: center;
  gap: 0.375rem;
  margin-bottom: 0.375rem;
}
.badge {
  padding: 0.0625rem 0.4375rem;
  font-size: var(--text-xs);
  border-radius: var(--radius-xs);
  white-space: nowrap;
}
.badge-scene {
  color: var(--info);
  background: var(--info-bg);
}
.badge-source {
  color: var(--ok);
  background: var(--ok-bg);
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
  font-size: var(--text-xs);
  color: var(--text-secondary);
  background: var(--bg-tertiary);
  border-radius: var(--radius-xs);
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
  border-radius: var(--radius-xs);
  cursor: pointer;
}
.icon-danger:hover {
  color: var(--danger);
  background: var(--danger-bg);
}
.icon-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  padding: 0.1875rem;
  color: var(--text-muted);
  background: transparent;
  border: none;
  border-radius: var(--radius-xs);
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
  border-radius: var(--radius-sm);
  resize: vertical;
}
.sample-edit-textarea:focus {
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
  font-size: var(--text-xs);
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
  /* 身份层①：样本正文衬线化（宋体系=字帖墨迹感），字号/行数钳制不动 */
  font-family: var(--editor-font-family);
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
  font-size: var(--text-xs);
  color: var(--text-muted);
}
.era-toggle {
  padding: 0.125rem 0.4375rem;
  font-size: var(--text-xs);
  color: var(--text-muted);
  background: transparent;
  border: 1px dashed var(--border-color);
  border-radius: var(--radius-sm);
  cursor: pointer;
}
.era-toggle:hover {
  color: var(--accent-500);
  border-color: var(--accent-400);
}
.badge-early {
  color: var(--text-secondary);
  background: var(--bg-tertiary);
}
.fav-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  width: 24px;
  height: 24px;
  color: var(--text-faint);
  background: transparent;
  border: none;
  cursor: pointer;
}
.fav-btn.active {
  color: var(--warn);
}
.fav-btn:hover {
  color: var(--warn);
}
</style>
