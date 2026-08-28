<script setup lang="ts">
/**
 * 副驾抽屉（NLE-ADF 3.0「纸面优先」写作台重构）。
 *
 * 四 tab（Ctrl+1~4 切换，按写作流程排序）+ 底部「AI 视角」入口（Ctrl+5，引擎观测降级位）：
 * - 打算：写前规划——章级软脉络（SpinePanel）+ 大纲 + 意图反推
 * - 此刻：世界切片「此刻此地」+ 候选回流收件箱（WorldSceneSlice，与生成上下文同源）
 * - 本章：统计 / 出场角色速查 / 本章文风 / Canon 真相账本跳转——章节档案
 * - 检查：完稿体检（按钮 + 报告）、沉淀抽取、润色（Refinery）、读者反馈——按 检查→修改→反馈 三组排布
 * - AI 视角（原调试 tab）：AI 此刻所见预览 + 世界模型快照——引擎内部观测
 *
 * 旧 BS-ADF 步进工作台（节拍/聚焦/生成主控/Stepper）已随写作台重构移除；
 * 润色与读者反馈的门控从 stage==='done' 改为「本章有正文」——adaptive 模式 stage 恒 idle，
 * 旧门控使手写章节永远进不了润色/反馈（已知洞的修复）。
 */
import { ref, computed, onMounted, onBeforeUnmount, watch } from 'vue'
import { useRouter } from 'vue-router'
import Icon from '../../../components/Icon.vue'
import { useAppStore } from '../../app/useAppStore'
import ChapterBadges from '../presentation/ChapterBadges.vue'
import RefineryIssuesPanel from '../../generation/presentation/RefineryIssuesPanel.vue'
import RefineryProgress from '../../generation/presentation/RefineryProgress.vue'
import WorldSceneSlice from '../presentation/WorldSceneSlice.vue'
import SpinePanel from '../presentation/SpinePanel.vue'
import ContextPreviewSection from '../presentation/ContextPreviewSection.vue'
import { useChapterSpine } from '../composables/useChapterSpine'
import type { IssueDecision, RefineryIssue } from '../../../services/api/domain'
import { refineryApi, styleApi } from '../../../services/api/domain'
import { adaptiveApi } from '../../../services/api/domain/adaptive.api'
import type { ContextPreview } from '../../../services/api/domain/adaptive.api'
import { componentErrors } from '../../generation/composables/useAdaptiveAssist'
import { useGenerationSession } from '../../generation/composables/useGenerationSession'
import { chapterEditorHandle } from '../../chapter-editor/editorHandle'
import { dispatchCollabEvent } from '../../../composables/collabEventBus'
import { useToast } from '../../../composables/useToast'
import { requestOpenInbox, OPEN_INBOX_EVENT, inboxAutoOpen } from '../../world/composables/batchAccept'
import { countChapterWords } from '../../../shared/utils/htmlText'

type InspectorTab = 'now' | 'planning' | 'chapter' | 'review' | 'debug'

interface TabDef {
  key: InspectorTab
  label: string
  icon: string
}

const store = useAppStore()
// 章级谋篇（P1.4 M1：与 WorkspaceView 复合谋篇卡共享同一单例状态）
const chapterSpine = useChapterSpine()
const selectedChapter = store.selectedChapter
const characters = store.characters
const selectedChapterId = store.selectedChapterId

// session 从外部传入（由 WorkspaceView 创建并与画布辅助层共享）；独立使用时自建兜底
const props = withDefaults(defineProps<{
  externalSession?: ReturnType<typeof useGenerationSession> | null
}>(), {
  externalSession: null,
})
const session = props.externalSession || useGenerationSession()

// 字数口径：剥 HTML 标签后计字符（此前 .length 把 <p>/mark 标签计入，虚高）
const wordCount = computed(() => countChapterWords(selectedChapter.value?.content_text || ''))

/** 本章有正文：润色/读者反馈的启用门槛（取代旧 stage==='done' 门控） */
const chapterHasContent = computed(() => wordCount.value > 0)

// 按写作流程排序：写前打算 → 写中此刻 → 本章档案 → 写后检查；debug 排末位但不进 tab 栏（底部「AI 视角」入口）
const tabs: TabDef[] = [
  { key: 'planning', label: '打算', icon: 'light-bulb' },
  { key: 'now', label: '此刻', icon: 'map' },
  { key: 'chapter', label: '本章', icon: 'document' },
  { key: 'review', label: '检查', icon: 'check-circle' },
  { key: 'debug', label: 'AI 视角', icon: 'magnifying-glass' },
]
/** tab 栏只渲染前四格；debug 走抽屉底部小按钮 */
const visibleTabs = tabs.slice(0, 4)

/** 每 tab 一行用途副标题（新手第一眼解释，随激活 tab 切换） */
const TAB_SUBTITLES: Record<InspectorTab, string> = {
  planning: '写之前想一想：这章讲什么、哪些情节非写不可——AI 会照着帮你',
  now: '故事里现在是什么时间、谁在哪——AI 写作时看到的就是这份',
  chapter: '这章的档案：字数、文风、出场角色、真相',
  review: '写完后的体检、润色与读者反馈',
  debug: 'AI 续写时实际读到的内容（引擎观测）',
}

// 默认 tab 按章节状态：空章落「打算」（写前），有正文落「此刻」（写中参考）。
// 正文可能异步到达——wordCount 由 0 转正且用户尚未手动切 tab 时补切到「此刻」；
// 用户手动切过一次后即尊重其选择，不再代切。
const userPickedTab = ref(false)
const activeTab = ref<InspectorTab>(wordCount.value > 0 ? 'now' : 'planning')

watch(selectedChapterId, () => {
  userPickedTab.value = false
  activeTab.value = wordCount.value > 0 ? 'now' : 'planning'
})
watch(wordCount, (n) => {
  if (n > 0 && !userPickedTab.value && activeTab.value === 'planning') activeTab.value = 'now'
})

// 诊断完成（问题清单就绪）/ 完稿报告 / 沉淀结果到达时切到审校 tab
watch(
  () => session.stage.value,
  (newStage) => {
    if (newStage === 'refining' && session.refineryIssues.value.length > 0) {
      activeTab.value = 'review'
    }
  }
)
watch(() => session.finishReport?.value, (report) => {
  if (report) activeTab.value = 'review'
  fixStates.value = {}  // 新一轮审计 → 残句修复裁决态复位
  semanticSent.value = {}  // 语义命中回流态同步复位（新报告可重新投递）
})
watch(() => session.settleResult?.value, (result) => {
  if (result) activeTab.value = 'review'
})

function handleKeydown(e: KeyboardEvent) {
  if ((e.ctrlKey || e.metaKey) && !e.shiftKey && e.key >= '1' && e.key <= String(tabs.length)) {
    e.preventDefault()
    const idx = parseInt(e.key) - 1
    if (idx < tabs.length) {
      activeTab.value = tabs[idx].key
      userPickedTab.value = true
    }
  }
}

// A5d 沉淀直达：toast「去确认」→ 切「此刻」tab（与 Ctrl+2 同一 activeTab 通路）。
// 抽屉关闭时本面板是 v-if 卸载态，事件发出瞬间监听器未挂——挂载后消费旗标补位。
if (inboxAutoOpen.value) activeTab.value = 'now'
function _onOpenInbox() {
  activeTab.value = 'now'
}

onMounted(() => {
  window.addEventListener('keydown', handleKeydown)
  window.addEventListener(OPEN_INBOX_EVENT, _onOpenInbox)
})
onBeforeUnmount(() => {
  window.removeEventListener('keydown', handleKeydown)
  window.removeEventListener(OPEN_INBOX_EVENT, _onOpenInbox)
})

/** 审校 verdict 中文标签（ADF 审计与 Refinery 回读共用） */
const VERDICT_LABELS: Record<string, string> = {
  pass: '通过',
  pass_with_fixes: '修改后通过',
  needs_refinement: '需要精修',
  needs_final_touch: '需要再修',
  fail: '未通过',
  unaudited: '未审校',
}
function verdictLabel(v?: string | null) {
  return (v && VERDICT_LABELS[v]) || v || '—'
}

/** 更新章节大纲，带简易防抖避免每次按键写库（标题编辑在纸面页面头） */
let outlineTimer: ReturnType<typeof setTimeout> | undefined
function updateOutline(value: string) {
  if (!selectedChapterId.value) return
  clearTimeout(outlineTimer)
  outlineTimer = setTimeout(() => {
    store.updateChapter(selectedChapterId.value!, { outline_text: value })
  }, 500)
}

/** 启动润色（诊断阶段）。门槛：本章有正文（手写章节亦可，不再要求走完生成管线）。 */
function handleStartRefinery() {
  if (!selectedChapterId.value || !chapterHasContent.value) return
  session.startRefinery(selectedChapterId.value, { mode: 'deep', enablePolish: true })
}

/** 作者确认问题清单后，执行手术+回读+抛光 */
function handleRefineryConfirm(payload: { run_id: string; decisions: IssueDecision[]; custom_issues: RefineryIssue[] }) {
  if (!selectedChapterId.value) return
  session.confirmRefinery(selectedChapterId.value, payload.decisions, payload.custom_issues)
}

/** 取消润色（清空 refinery 状态，stage 回 idle——adaptive 模式 stage 恒 idle 的约定不被打破） */
function handleRefineryCancel() {
  session.refineryIssues.value = []
  session.refineryRunId.value = null
  session.stage.value = 'idle'
}

/** 获取读者反馈（AI 扮演读者写叙述性感受）。门槛：本章有正文。 */
const readerFeedback = ref('')
const loadingFeedback = ref(false)
async function handleReaderFeedback() {
  if (!selectedChapterId.value || !chapterHasContent.value) return
  loadingFeedback.value = true
  readerFeedback.value = ''
  try {
    const result = await refineryApi.getReaderFeedback(selectedChapterId.value)
    readerFeedback.value = result.feedback
  } catch (e: any) {
    readerFeedback.value = `获取失败：${e.message}`
  } finally {
    loadingFeedback.value = false
  }
}

/** 跳世界页真相账本（C1 Canon 融合；RefineryIssuesPanel 改设定 / 章节 tab 入口共用） */
const router = useRouter()
function handleEditCanon() {
  const bookId = store.currentBookId.value
  if (!bookId) return
  router.push({ name: 'world', params: { bookId }, query: { panel: 'canon' } })
}

// ===== 世界模型快照（P0-5：/adaptive/model 调试入口，展开即拉一次）=====
const worldModelOpen = ref(false)
const worldModelText = ref('')

// ===== AI 辅助组件健康状况（P3-1/C5：最近失败的组件，心跳带回）=====
// 空 = 一切正常，整块不渲染；成功即清（后端语义），恢复后自动消失
const COMPONENT_LABELS: Record<string, string> = {
  intent_inference: '方向猜测',
  future_projection: '走向推测',
  dock_generator: '挂件生发',
  canon_watch: '世界感知',
  sediment: '沉淀整理',
  post_process: '完稿体检',
  event_scout: '世界发现',
}
function componentLabelOf(name: string) {
  return COMPONENT_LABELS[name] || name
}
function relTimeOf(ts: number) {
  if (!ts) return ''
  const diff = Math.max(0, Date.now() / 1000 - ts)
  if (diff < 60) return '刚刚'
  if (diff < 3600) return `${Math.floor(diff / 60)} 分钟前`
  if (diff < 86400) return `${Math.floor(diff / 3600)} 小时前`
  return new Date(ts * 1000).toLocaleDateString()
}

// ===== AI 此刻所见预览（P5 B2：/adaptive/context-preview，展开即装配一次）=====
type PreviewMode = 'stitch' | 'continue' | 'burst' | 'outline' | 'open'
const contextPreviewOpen = ref(false)
const contextPreviewMode = ref<PreviewMode>('continue')
const contextPreviewData = ref<ContextPreview | null>(null)
const contextPreviewLoading = ref(false)
const contextPreviewError = ref('')

async function loadContextPreview() {
  const chapterId = selectedChapterId.value
  if (!chapterId || contextPreviewLoading.value) return
  contextPreviewLoading.value = true
  contextPreviewError.value = ''
  try {
    contextPreviewData.value = await adaptiveApi.contextPreview(chapterId, contextPreviewMode.value)
  } catch (e: any) {
    contextPreviewError.value = e?.message || '读取失败'
  } finally {
    contextPreviewLoading.value = false
  }
}

function toggleContextPreview() {
  contextPreviewOpen.value = !contextPreviewOpen.value
  if (contextPreviewOpen.value && !contextPreviewData.value) {
    loadContextPreview()
  }
}

function switchContextPreviewMode(mode: PreviewMode) {
  if (mode === contextPreviewMode.value) return
  contextPreviewMode.value = mode
  if (contextPreviewOpen.value) loadContextPreview()
}

// 切章复位（旧章预览不再示人；重开重装配）
watch(selectedChapterId, () => {
  contextPreviewOpen.value = false
  contextPreviewData.value = null
  contextPreviewError.value = ''
})

async function toggleWorldModelDebug() {
  worldModelOpen.value = !worldModelOpen.value
  if (!worldModelOpen.value) return
  const chapterId = selectedChapterId.value
  if (!chapterId) return
  worldModelText.value = '读取中…'
  try {
    const snap = await adaptiveApi.model(chapterId)
    // 摘要视图：意图 + 事实条数 + 投影标题（原文太长，调试只看骨架）
    const intent = snap.intent || {}
    const facts = (snap.facts || []).slice(-5).map((f: any) => `· ${String(f.text || '').slice(0, 50)}`)
    const projections = (snap.projections || [])
      .filter((p: any) => !p.__dock__ && !p.__canon_watch__)
      .map((p: any) => {
        const beat = p.possible_beats?.[0]
        return `· ${String(beat?.event || '').slice(0, 50)}`
      })
      .slice(0, 3)
    worldModelText.value = [
      `方向：${intent.source === 'none' ? '（无）' : `${intent.source} · ${(intent.arc || '').slice(0, 40)}`}`,
      `事实：${snap.fact_count ?? 0} 条（最近 ${facts.length} 条）`,
      ...facts,
      `走向：${projections.length} 条`,
      ...projections,
      `字数（沉淀）：${snap.total_words ?? 0}`,
    ].join('\n')
  } catch (e: any) {
    worldModelText.value = `读取失败：${e.message}`
  }
}

// ===== 残句定点修复（P1.2 作者裁决式：修复句过目 → 采纳才替换正文）=====
interface SentenceFixState { loading?: boolean; fixed?: string; error?: string; reason?: string; adopted?: boolean }
const fixStates = ref<Record<number, SentenceFixState>>({})

async function handleFixSentence(i: number, d: any) {
  const chapterId = selectedChapterId.value
  const sentence = typeof d === 'string' ? d : d?.sentence
  if (!chapterId || !sentence) return
  fixStates.value = { ...fixStates.value, [i]: { loading: true } }
  dispatchCollabEvent('sentence_fix', { action: 'propose' })
  try {
    const r = await adaptiveApi.fixSentence(chapterId, {
      sentence,
      defect_type: d?.type || '',
      description: d?.description || '',
    })
    fixStates.value = {
      ...fixStates.value,
      [i]: r.fixed ? { fixed: r.fixed } : { reason: r.reason },
    }
  } catch (e: any) {
    fixStates.value = { ...fixStates.value, [i]: { error: e?.message || '修复失败' } }
  }
}

/** 在文档中定位原句并替换（逐 textblock 搜索；编辑器自身的 update-chapter 机制落库） */
function replaceSentenceInDoc(editor: any, original: string, fixed: string): boolean {
  let done = false
  editor.state.doc.descendants((node: any, pos: number) => {
    if (done || !node.isTextblock) return true
    const idx = node.textContent.indexOf(original)
    if (idx < 0) return true
    const from = pos + 1 + idx
    editor.chain().insertText(fixed, from, from + original.length).run()
    done = true
    return false
  })
  return done
}

function adoptFix(i: number, d: any) {
  const original = typeof d === 'string' ? d : d?.sentence
  const fixed = fixStates.value[i]?.fixed
  const editor = chapterEditorHandle.value
  if (!editor || !original || !fixed) return
  if (!replaceSentenceInDoc(editor, original, fixed)) {
    fixStates.value = { ...fixStates.value, [i]: { error: '未在正文中定位到该句（可能已改动）' } }
    return
  }
  fixStates.value = { ...fixStates.value, [i]: { fixed, adopted: true } }
  dispatchCollabEvent('sentence_fix', { action: 'adopt' })
}

function dismissFix(i: number) {
  fixStates.value = { ...fixStates.value, [i]: {} }
  dispatchCollabEvent('sentence_fix', { action: 'reject' })
}

// ===== 语义命中 → 文风收件箱（Phase 3 F：疑似 AI 味变体逐条回流）=====
// 只投候选不直接生效（红线同「这不像我」）；word 取片段前 20 字，过目时可再改。
const { showToast } = useToast()
const currentBookId = computed(() => store.currentBookId.value)
type SemanticSentState = 'sending' | 'sent' | 'error'
const semanticSent = ref<Record<number, SemanticSentState>>({})

async function collectSemanticHit(i: number, hit: { segment: string; alternative?: string | null }) {
  const bookId = currentBookId.value
  if (!bookId || semanticSent.value[i] === 'sending' || semanticSent.value[i] === 'sent') return
  semanticSent.value = { ...semanticSent.value, [i]: 'sending' }
  try {
    await styleApi.addInboxItem(
      bookId,
      'negative_candidate',
      { word: hit.segment.slice(0, 20), alternative: hit.alternative ?? null, source_text: hit.segment },
      'semantic_scan',
    )
    semanticSent.value = { ...semanticSent.value, [i]: 'sent' }
    showToast('已投进文风收件箱——去文风页过目后再收入清单', 'success')
  } catch (e: any) {
    semanticSent.value = { ...semanticSent.value, [i]: 'error' }
    showToast('投递失败: ' + (e?.message || ''), 'error')
  }
}

// ===== 本章文风卡（S3：章级特例状态 + 跳文风页深链）=====
const chapterStyleOverride = ref<any>(null)
const chapterStyleLoading = ref(false)

watch(selectedChapterId, async (chapterId) => {
  chapterStyleOverride.value = null
  const bookId = store.currentBookId.value
  if (!chapterId || !bookId) return
  chapterStyleLoading.value = true
  try {
    const card = await styleApi.get(bookId, chapterId).catch(() => null)
    // 后端无章级覆盖时回退返回书级卡（回退是特性）——
    // 判「本章有特例」必须看 chapter_id 非空，否则书级卡会被误报成章级特例
    chapterStyleOverride.value = card?.chapter_id ? card : null
  } finally {
    chapterStyleLoading.value = false
  }
}, { immediate: true })

function handleEditChapterStyle() {
  const bookId = store.currentBookId.value
  if (!bookId || !selectedChapterId.value) return
  router.push({ name: 'style', params: { bookId }, query: { chapter: selectedChapterId.value } })
}

async function handleResetChapterStyle() {
  const bookId = store.currentBookId.value
  if (!bookId || !selectedChapterId.value || !chapterStyleOverride.value) return
  try {
    await styleApi.deleteChapterOverride(bookId, selectedChapterId.value)
    chapterStyleOverride.value = null
  } catch (e: any) {
    console.warn('恢复继承失败:', e)
  }
}
</script>

<template>
  <aside class="inspector">
    <!-- tab 头（四格：打算/此刻/本章/检查；AI 视角在底部入口） -->
    <div class="tab-bar">
      <button
        v-for="t in visibleTabs"
        :key="t.key"
        class="tab-btn"
        :class="{ active: activeTab === t.key }"
        :title="`${t.label} (Ctrl+${tabs.indexOf(t) + 1})`"
        @click="activeTab = t.key; userPickedTab = true"
      >
        <Icon :name="t.icon" :size="15" />
        <span class="tab-label">{{ t.label }}</span>
      </button>
    </div>
    <!-- 当前 tab 用途副标题（新手第一眼解释） -->
    <div class="tab-subtitle">{{ TAB_SUBTITLES[activeTab] }}</div>

    <!-- tab 内容 -->
    <div class="tab-content">
      <!-- ====== 此刻 tab：此刻此地世界切片 + 候选收件箱 ====== -->
      <div v-if="activeTab === 'now'" class="panel now-panel">
        <WorldSceneSlice :chapter-id="selectedChapterId" />
      </div>

      <!-- ====== 打算 tab：章级软脉络 + 大纲 + 意图反推（写前规划） ====== -->
      <div v-else-if="activeTab === 'planning'" class="panel planning-panel">
        <div v-if="!selectedChapter" class="empty">
          <p>从左侧选择一个章节。</p>
        </div>
        <template v-else>
          <!-- 谋篇区（P1.4 M1：章级软脉络——方向先于情节，永远在最上） -->
          <SpinePanel
            :spine="chapterSpine.spine.value"
            :suggestions="chapterSpine.spineSuggestions.value"
            :suggesting="chapterSpine.spineSuggesting.value"
            @update-intent="chapterSpine.setIntent"
            @add-anchor="chapterSpine.addAnchor"
            @update-anchor="(id, patch) => chapterSpine.updateAnchor(id, patch)"
            @remove-anchor="chapterSpine.removeAnchor"
            @suggest="chapterSpine.suggest"
            @adopt="(part) => chapterSpine.adoptSuggestion(part)"
            @discard-suggestions="chapterSpine.discardSuggestions"
          />

          <!-- 意图反推（心跳带回的后台规划淡建议；降级为打算区下方一行小字，不占独立小节） -->
          <div v-if="session.planSuggestions?.value?.arc" class="plan-guess">
            AI 目前的猜测：{{ session.planSuggestions.value.arc }}
            <span class="muted">（{{ session.planSuggestions.value.source === 'author' ? '来自你写的那句话' : 'AI 推测' }}）</span>
          </div>

          <!-- 大纲卡（剧情层规划，与上方方向一句话分工：打算=要去哪，大纲=发生什么；标题编辑在纸面页面头） -->
          <section class="card-strip">
            <header class="strip-header">
              <span class="strip-num">第 {{ selectedChapter.chapter_number }} 章 · 详细大纲</span>
              <ChapterBadges :chapter="selectedChapter" />
            </header>
            <textarea
              class="strip-outline-input"
              :value="selectedChapter.outline_text"
              placeholder="这一章具体发生什么（AI 辅助写作会参考）"
              rows="6"
              @input="(e) => updateOutline((e.target as HTMLTextAreaElement).value)"
            ></textarea>
            <p class="hint">与上方「打算」分工：打算=一句话方向，这里=剧情细节备忘；两者 AI 辅助写作都会参考。</p>
          </section>
        </template>
      </div>

      <!-- ====== 本章 tab：统计 + 出场角色 + 本章文风 + Canon 跳转（章节档案） ====== -->
      <div v-else-if="activeTab === 'chapter'" class="panel chapter-panel">
        <div v-if="!selectedChapter" class="empty">
          <p>从左侧选择一个章节。</p>
        </div>
        <template v-else>
          <!-- 统计（出场角色卡已退役 2026-08-29：旧 chapter_entities 表口径，
               世界页「此刻·在场」推演取代——统计恒 0 还会误导） -->
          <section class="stats-section">
            <div class="stat">
              <span class="stat-num">{{ wordCount }}</span>
              <span class="stat-label">字</span>
            </div>
          </section>

          <!-- 本章文风（S3：章级特例状态一眼可见） -->
          <section class="style-status-section">
            <div class="section-label">本章文风</div>
            <div class="style-status-row">
              <span v-if="chapterStyleLoading" class="muted">读取中…</span>
              <template v-else>
                <span v-if="chapterStyleOverride" class="style-override-badge">章级特例</span>
                <span v-else class="muted">继承书级文风</span>
                <button
                  v-if="chapterStyleOverride"
                  class="btn-mini-reset"
                  title="删除本章特例，恢复继承书级文风"
                  @click="handleResetChapterStyle"
                >恢复继承</button>
              </template>
            </div>
            <button class="btn-refinery" @click="handleEditChapterStyle">
              <Icon name="paint-brush" :size="14" />
              <span>{{ chapterStyleOverride ? '编辑本章文风特例' : '为本章设文风特例' }}</span>
            </button>
            <p class="hint">回忆章换个腔调？章级特例只影响这一章的生成，其余章节仍用书级文风。</p>
          </section>

          <!-- 跳世界页真相账本（C1：Canon 融入世界页） -->
          <section>
            <button class="btn-refinery" @click="handleEditCanon">
              <Icon name="truth" :size="14" />
              <span>在世界页查看真相</span>
            </button>
            <p class="hint">表（读者所见）与里（作者真相）的账本——秘密设定 / 揭示计划 / 因果图谱</p>
          </section>
        </template>
      </div>

      <!-- ====== 检查 tab：完稿体检 + 沉淀 + 润色 + 读者反馈（按 检查→修改→反馈 三组排布） ====== -->
      <div v-else-if="activeTab === 'review'" class="panel review-panel">
        <div v-if="!selectedChapter" class="empty">
          <p>从左侧选择一个章节。</p>
        </div>
        <template v-else>
          <!-- 组一：检查 -->
          <div class="group-title">检查</div>
          <!-- 完稿审计 -->
          <section class="adaptive-finish">
            <div class="section-label">完稿体检</div>
            <button
              class="btn-finish"
              :disabled="session.aiLane?.value === 'analyzing' || !(session.adaptiveMode?.value && session.authorLane?.value === 'composing')"
              :title="session.adaptiveMode?.value && session.authorLane?.value === 'composing' ? '触发全章检查' : '在章节内写满 4 字激活 AI 辅助后可用'"
              @click="session.triggerAdaptiveFinish()"
            >
              <Icon :name="session.aiLane?.value === 'analyzing' ? 'loader' : 'check-circle'" :size="14" />
              <span>{{ session.aiLane?.value === 'analyzing' ? '通读中…' : '完稿体检' }}</span>
            </button>
            <p class="hint">AI 通读全章做检查：没写完的句子、关键情节写没写到、秘密穿帮、编辑意见，并更新前情记忆。</p>
          </section>

          <!-- 完稿审计报告 -->
          <section v-if="session.finishReport?.value?.report" class="adaptive-report">
            <div class="section-label">检查报告</div>
            <!-- 残句（P1.2：每条可定点修复——修复句过目，采纳才落正文） -->
            <div v-if="session.finishReport.value.report.sentence_defects?.length" class="report-block report-block--warn">
              <div class="report-block-label">没写完的句子（{{ session.finishReport.value.report.sentence_defects.length }}）</div>
              <div
                v-for="(d, i) in session.finishReport.value.report.sentence_defects.slice(0, 5)"
                :key="'sd' + i"
                class="report-item report-item--fixable"
              >
                <template v-if="typeof d === 'string'">{{ d }}</template>
                <template v-else>
                  <div class="fix-sent">{{ d.sentence }}</div>
                  <div v-if="d.description" class="fix-desc">{{ d.description }}</div>
                </template>
                <!-- 修复流：修复中 → 失败原因 / 修复句+采纳·放弃 / 已采纳 -->
                <button v-if="!fixStates[i]" class="btn-mini-reset" title="AI 补全这句，过目后决定采不采纳" @click="handleFixSentence(i, d)">修复</button>
                <span v-else-if="fixStates[i].loading" class="fix-status">修复中…</span>
                <span v-else-if="fixStates[i].error" class="fix-status fix-status--err">{{ fixStates[i].error }}</span>
                <span v-else-if="fixStates[i].adopted" class="fix-status fix-status--ok">✓ 已采纳</span>
                <template v-else-if="fixStates[i].fixed">
                  <div class="fix-sent fix-sent--result">{{ fixStates[i].fixed }}</div>
                  <div class="fix-actions">
                    <button class="btn-mini-reset btn-mini-reset--primary" @click="adoptFix(i, d)">采纳</button>
                    <button class="btn-mini-reset" @click="dismissFix(i)">放弃</button>
                  </div>
                </template>
                <span v-else class="fix-status">未能修复（{{ fixStates[i].reason }}）</span>
              </div>
            </div>
            <!-- 疑似 AI 味变体（语义扫描：embedding 相似度抓「换字逃逸」改写变体；只提示，作者裁决） -->
            <div v-if="session.finishReport.value.semantic_hits?.length" class="report-block report-block--warn">
              <div class="report-block-label">疑似 AI 味变体（{{ session.finishReport.value.semantic_hits.length }}）</div>
              <div
                v-for="(hit, i) in session.finishReport.value.semantic_hits.slice(0, 5)"
                :key="'sem' + i"
                class="report-item"
              >
                <div class="fix-sent">{{ hit.segment }}</div>
                <div class="fix-desc">
                  ≈「{{ hit.pattern }}」（相似度 {{ hit.similarity }}）<template v-if="hit.alternative"> · 可改为：{{ hit.alternative }}</template>
                </div>
                <!-- 回流收件箱（Phase 3 F）：投候选过目，不直接入清单；无书上下文不渲染 -->
                <div v-if="currentBookId" class="fix-actions">
                  <button
                    v-if="!semanticSent[i] || semanticSent[i] === 'error'"
                    class="btn-mini-reset"
                    title="把这条片段投进文风收件箱——去文风页过目后再收入清单"
                    @click="collectSemanticHit(i, hit)"
                  >收入收件箱</button>
                  <span v-else-if="semanticSent[i] === 'sending'" class="fix-status">投递中…</span>
                  <span v-else-if="semanticSent[i] === 'sent'" class="fix-status fix-status--ok">✓ 已投递</span>
                </div>
              </div>
            </div>
            <!-- 关键情节完成度（打算页列的情节写没写到） -->
            <div v-if="session.finishReport.value.report.coverage?.checked" class="report-block">
              <div class="report-block-label">
                关键情节 {{ session.finishReport.value.report.coverage.hit_count }}/{{ session.finishReport.value.report.coverage.hit_count + session.finishReport.value.report.coverage.miss_count }} 已写到
              </div>
              <div v-if="session.finishReport.value.report.coverage.misses?.length" class="report-item report-item--miss">
                还没写到：{{ session.finishReport.value.report.coverage.misses.join('；') }}
              </div>
            </div>
            <!-- 打算附注（P1.4 §3.5：仅提示不阻塞） -->
            <div v-if="session.finishReport.value.report.spine_note" class="report-block">
              <div class="report-block-label">打算</div>
              <div class="report-item">{{ session.finishReport.value.report.spine_note }}</div>
            </div>
            <!-- Canon 泄露 -->
            <div v-if="session.finishReport.value.report.canon_check?.private_breaches?.length" class="report-block report-block--warn">
              <div class="report-block-label">⚠️ 秘密穿帮</div>
              <div
                v-for="(b, i) in session.finishReport.value.report.canon_check.private_breaches"
                :key="'cb' + i"
                class="report-item"
              >{{ b }}</div>
            </div>
            <!-- LLM 审阅 -->
            <div v-if="session.finishReport.value.report.critique?.issues?.length" class="report-block">
              <div class="report-block-label">编辑意见（{{ session.finishReport.value.report.critique.verdict === 'pass' ? '通过' : '需修改' }}）</div>
              <div
                v-for="(iss, i) in session.finishReport.value.report.critique.issues.slice(0, 5)"
                :key="'iss' + i"
                class="report-item"
                :class="{ 'report-item--warn': iss.severity === 'warning' }"
              >
                <span class="issue-cat">{{ iss.category }}</span>
                {{ iss.detail }}
              </div>
            </div>
            <!-- 记忆倒灌：本章已入向量记忆（供后续章节前情召回）；memory_indexed 在响应顶层，与 candidates_pending 同层 -->
            <div v-if="session.finishReport.value.memory_indexed" class="report-block">
              <div class="report-item">前情记忆新增 {{ session.finishReport.value.memory_indexed }} 段（后面的章节能想起这些细节）</div>
            </div>
            <!-- A5c① 收件箱积压（book 级 pending 计数，>0 才显示）：一键直达「此刻」tab 裁决 -->
            <div v-if="(session.finishReport.value.candidates_pending ?? 0) > 0" class="report-block report-block--inbox">
              <div class="report-block-label">收件箱</div>
              <div class="report-item report-item--inbox">
                {{ session.finishReport.value.candidates_pending }} 条世界变化待确认
                <button class="btn-mini-reset btn-mini-reset--primary" title="打开副驾「此刻」tab 的候选收件箱" @click="requestOpenInbox">去处理</button>
              </div>
            </div>
          </section>

          <!-- 组二：修改（沉淀抽取 + 润色全流程） -->
          <div class="group-title">修改</div>
          <!-- 沉淀抽取结果（涌现实体 + 冲突；作者主权：冲突不自动改） -->
          <section v-if="session.settleResult?.value?.emergent_facts || session.settleResult?.value?.conflicts?.length" class="adaptive-settle">
            <div class="section-label">AI 从正文发现</div>
            <!-- 新面孔 -->
            <div v-if="session.settleResult.value.emergent_facts?.new_entities?.length" class="settle-block">
              <div class="settle-block-label">新出现的角色·事物</div>
              <div
                v-for="(ent, i) in session.settleResult.value.emergent_facts.new_entities.slice(0, 5)"
                :key="'ent' + i"
                class="settle-item"
              >{{ ent.name }}<span v-if="ent.description" class="muted"> · {{ ent.description }}</span></div>
            </div>
            <!-- 冲突（设定矛盾——浮给作者确认，不自动改） -->
            <div v-if="session.settleResult.value.conflicts?.length" class="settle-block settle-block--warn">
              <div class="settle-block-label">⚠️ 设定冲突（待你确认）</div>
              <div
                v-for="(c, i) in session.settleResult.value.conflicts.slice(0, 5)"
                :key="'conf' + i"
                class="settle-item settle-item--conflict"
              >
                <span class="conflict-entity">{{ c.entity }}</span>
                <span class="muted">已有：{{ c.existing }}</span>
                <span class="muted">正文：{{ c.new }}</span>
              </div>
            </div>
          </section>

          <!-- 润色（Refinery：诊断 → 确认 → 手术 + 回读 + 抛光） -->
          <section class="refine-entry">
            <div class="section-label">润色</div>
            <!-- 无正文空态 -->
            <div v-if="!chapterHasContent" class="empty-inline">
              本章还没有正文。写一段之后，这里可以启动 AI 润色与读者反馈。
            </div>
            <!-- 诊断进行中（stage='auditing'）：过渡态，避免"空白没反应"观感 -->
            <div v-else-if="session.stage.value === 'auditing' && session.generating.value" class="refine-loading">
              <div class="empty-icon spinning"><Icon name="sparkles" :size="32" /></div>
              <p>正在通读全文找问题…</p>
              <p class="muted">检查 + 归类需要一点时间，请稍候。</p>
            </div>
            <!-- 可启动（有正文且不在润色流程中） -->
            <template v-else-if="session.stage.value !== 'refining'">
              <button
                v-if="!session.refineryRunId.value"
                class="btn-refinery"
                @click="handleStartRefinery"
              >
                <Icon name="sparkles" :size="14" />
                <span>启动润色（检查 + 修改）</span>
              </button>
              <p class="hint">
                AI 通读全文找问题 → 你确认 → 逐处修改 → 通读检查 → 定稿润色。
              </p>
            </template>
          </section>

          <!-- 润色问题清单（诊断完成、等作者确认） -->
          <RefineryIssuesPanel
            v-if="session.stage.value === 'refining' && session.refineryIssues.value.length > 0 && session.refineryRunId.value"
            :issues="session.refineryIssues.value"
            :run-id="session.refineryRunId.value"
            @confirm="handleRefineryConfirm"
            @cancel="handleRefineryCancel"
            @edit-canon="handleEditCanon"
          />

          <!-- 润色手术进度 -->
          <RefineryProgress
            v-if="session.stage.value === 'refining' && session.refineryRunId.value === null && (session.generating.value || session.refinerySurgeries.value.length > 0)"
            :surgeries="session.refinerySurgeries.value"
            :holistic-verdict="session.refineryHolisticVerdict.value"
            :stage-label="session.stepProgress.value?.label || ''"
            :stage="session.stage.value"
          />

          <!-- 润色完成后的手术历史 -->
          <section v-if="session.refinerySurgeries.value.length && session.stage.value !== 'refining' && session.stage.value !== 'auditing'" class="refine-history">
            <div class="section-label">润色记录（{{ session.refinerySurgeries.value.filter(s => s.applied).length }}/{{ session.refinerySurgeries.value.length }} 成功）</div>
            <div v-for="s in session.refinerySurgeries.value" :key="s.operation_id" class="surgery-row" :class="{ failed: !s.applied }">
              <span class="surgery-status">{{ s.applied ? '✓' : '✗' }}</span>
              <span class="surgery-diff">{{ s.diff_summary }}</span>
            </div>
            <button class="btn-refinery" @click="handleStartRefinery">
              <Icon name="arrow-path" :size="14" />
              <span>再次润色</span>
            </button>
          </section>

          <!-- 组三：反馈（读者反馈 + 审校结论；本章无正文且无论断时整组缺席） -->
          <div v-if="chapterHasContent || session.refineryHolisticVerdict.value" class="group-title">反馈</div>
          <!-- 读者反馈 -->
          <section v-if="chapterHasContent" class="feedback-section">
            <div class="section-label">读者反馈</div>
            <button
              class="btn-refinery secondary"
              :disabled="loadingFeedback"
              title="AI 扮演读者写叙述性感受"
              @click="handleReaderFeedback"
            >
              <Icon name="chat" :size="14" />
              <span>{{ loadingFeedback ? '读者阅读中…' : '获取读者反馈' }}</span>
            </button>
            <div v-if="readerFeedback" class="reader-feedback-card">
              <div class="rf-header">📖 读者反馈</div>
              <p class="rf-text">{{ readerFeedback }}</p>
            </div>
            <p v-else class="hint">
              AI 扮演读者写叙述性感受（不是检查清单）。
            </p>
          </section>

          <!-- 检查结论（润色回读；有数据才显示。旧 ADF 结构检查块已随引擎归档移除） -->
          <section v-if="session.refineryHolisticVerdict.value" class="audit-section">
            <div class="section-label">检查结论</div>
            <div class="audit-block">
              <div class="audit-row">
                <span class="audit-label">通读检查</span>
                <span class="audit-value" :class="`verdict-${session.refineryHolisticVerdict.value.verdict}`">
                  {{ session.refineryHolisticVerdict.value.verdict === 'pass' ? '✓ 通过' : '⚠ 需要再修' }}
                </span>
              </div>
            </div>
          </section>
        </template>
      </div>

      <!-- ====== AI 视角（原调试 tab）：AI 所见预览 + 世界模型快照（引擎内部观测，底部入口进入） ====== -->
      <div v-else-if="activeTab === 'debug'" class="panel debug-panel">
        <div v-if="!selectedChapter" class="empty">
          <p>从左侧选择一个章节。</p>
        </div>
        <template v-else>
          <!-- AI 此刻所见（P5 B2：stitch-ghost 真实注入的上下文块预览——与 stitch_context 同源，默认折叠） -->
          <ContextPreviewSection
            :open="contextPreviewOpen"
            :loading="contextPreviewLoading"
            :error="contextPreviewError"
            :preview="contextPreviewData"
            :mode="contextPreviewMode"
            @toggle="toggleContextPreview"
            @refresh="loadContextPreview"
            @update:mode="switchContextPreviewMode"
          />

          <!-- AI 辅助组件健康状况（P3-1/C5：最近失败记录；空 = 一切正常，整块不渲染） -->
          <section v-if="componentErrors.length" class="comp-errors">
            <div class="section-label">AI 辅助遇到的问题</div>
            <div v-for="err in componentErrors" :key="err.component" class="comp-error-row">
              <span class="comp-error-name">{{ componentLabelOf(err.component) }}</span>
              <span class="comp-error-time">{{ relTimeOf(err.ts) }}</span>
              <span class="comp-error-detail">{{ err.error }}</span>
            </div>
            <p class="hint">都是最近一次的记录，恢复了会自动消失，不影响写作。</p>
          </section>

          <!-- 世界模型快照（P0-5：/adaptive/model 的调试入口） -->
          <section>
            <button class="btn-refinery" @click="toggleWorldModelDebug">
              <Icon name="magnifying-glass" :size="14" />
              <span>{{ worldModelOpen ? '收起' : 'AI 眼中的世界' }}</span>
            </button>
            <pre v-if="worldModelOpen" class="world-model-debug">{{ worldModelText }}</pre>
          </section>
        </template>
      </div>
    </div>

    <!-- 底部：AI 视角（引擎观测降级入口，不占 tab 格；Ctrl+5） -->
    <div class="drawer-foot">
      <button
        class="foot-btn"
        :class="{ active: activeTab === 'debug' }"
        title="AI 续写时实际读到的内容（引擎观测）(Ctrl+5)"
        @click="activeTab = 'debug'; userPickedTab = true"
      >
        <Icon name="magnifying-glass" :size="13" />
        <span>AI 视角</span>
      </button>
    </div>
  </aside>
</template>

<style scoped>
.inspector {
  display: flex;
  flex-direction: column;
  width: 100%;
  flex-shrink: 0;
  background: var(--bg-secondary);
  border-left: 1px solid var(--border-color);
  height: 100%;
  overflow: hidden;
}

/* tab 头 */
.tab-bar {
  display: flex;
  align-items: stretch;
  gap: 0.125rem;
  padding: 0.375rem 0.375rem 0;
  border-bottom: 1px solid var(--border-color);
  background: var(--bg-tertiary);
}

.tab-btn {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 0.1875rem;
  padding: 0.4375rem 0.25rem;
  background: transparent;
  border: none;
  border-radius: 0.375rem 0.375rem 0 0;
  color: var(--text-muted);
  cursor: pointer;
  transition: all 0.15s ease;
}

.tab-btn:hover {
  background: var(--hover-bg);
  color: var(--text-primary);
}

.tab-btn.active {
  color: var(--accent-500);
  background: var(--bg-secondary);
  box-shadow: inset 0 -2px 0 var(--accent-500);
}

.tab-label {
  font-size: 0.6875rem;
  font-weight: 500;
}

/* 当前 tab 用途副标题（tab 栏下方一行小字） */
.tab-subtitle {
  padding: 0.375rem 0.75rem;
  font-size: 0.6875rem;
  color: var(--text-muted);
  line-height: 1.5;
  border-bottom: 1px solid var(--border-color);
  background: var(--bg-tertiary);
}

/* 底部降级入口条（AI 视角） */
.drawer-foot {
  display: flex;
  align-items: center;
  padding: 0.25rem 0.5rem;
  border-top: 1px solid var(--border-color);
  background: var(--bg-tertiary);
  flex-shrink: 0;
}

.foot-btn {
  display: flex;
  align-items: center;
  gap: 0.25rem;
  padding: 0.25rem 0.5rem;
  background: transparent;
  border: none;
  border-radius: 0.25rem;
  font-size: 0.6875rem;
  color: var(--text-muted);
  cursor: pointer;
  transition: all 0.15s ease;
}

.foot-btn:hover {
  background: var(--hover-bg);
  color: var(--text-primary);
}

.foot-btn.active {
  color: var(--accent-500);
}

/* 检查 tab 流程组标题（检查→修改→反馈），层级高于 .section-label */
.group-title {
  font-size: 0.75rem;
  font-weight: 600;
  color: var(--text-secondary);
  letter-spacing: 0.08em;
  padding-bottom: 0.25rem;
  border-bottom: 1px solid var(--border-color);
}

/* 打算 tab：意图反推降级小字行 */
.plan-guess {
  font-size: 0.6875rem;
  color: var(--text-secondary);
  line-height: 1.5;
  padding: 0 0.125rem;
}

/* section-label 内的补充说明（非强调） */
.label-note {
  font-weight: 400;
  letter-spacing: normal;
  color: var(--text-muted);
  opacity: 0.85;
}

/* tab 内容 */
.tab-content {
  flex: 1;
  overflow-y: auto;
  padding: 0.875rem;
}

/* 内容区滚动条（细滚动条） */
.tab-content::-webkit-scrollbar {
  width: 6px;
}
.tab-content::-webkit-scrollbar-track {
  background: transparent;
}
.tab-content::-webkit-scrollbar-thumb {
  background: var(--scrollbar-thumb);
  border-radius: 3px;
}
.tab-content::-webkit-scrollbar-thumb:hover {
  background: var(--scrollbar-thumb-hover);
}

.panel {
  display: flex;
  flex-direction: column;
  gap: 0.875rem;
}
/* 此刻 tab 的世界切片自带满高布局 */
.now-panel {
  height: 100%;
}
/* 谋篇 tab 撑满高度，大纲卡（flex:1）伸缩填满剩余空间 */
.planning-panel {
  height: 100%;
}

.empty {
  padding: 2.5rem 1rem;
  text-align: center;
  color: var(--text-muted);
  font-size: 0.8125rem;
  line-height: 1.7;
}

/* 章节卡（大纲编辑，撑满谋篇 tab 剩余空间） */
.card-strip {
  background: var(--bg-canvas);
  border: 1px solid var(--border-color);
  border-radius: 0.5rem;
  padding: 0.625rem 0.75rem;
  flex: 1;
  min-height: 0;
  display: flex;
  flex-direction: column;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.03);
}

.strip-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 0.25rem;
}

.strip-num {
  font-size: 0.6875rem;
  color: var(--text-muted);
  font-variant-numeric: tabular-nums;
}

.strip-outline-input {
  width: 100%;
  flex: 1;
  min-height: 72px;
  font-size: 0.75rem;
  color: var(--text-secondary);
  line-height: 1.6;
  background: transparent;
  border: 1px solid transparent;
  border-radius: 0.25rem;
  padding: 0.375rem;
  margin-top: 0.375rem;
  font-family: inherit;
  resize: none;
  transition: border-color 0.15s ease, background 0.15s ease;
}
.strip-outline-input:hover {
  border-color: var(--border-color);
  background: var(--bg-primary);
}
.strip-outline-input:focus {
  outline: none;
  border-color: var(--accent-500);
  background: var(--bg-primary);
}

.section-label {
  display: flex;
  align-items: center;
  gap: 0.375rem;
  font-size: 0.6875rem;
  font-weight: 600;
  color: var(--text-muted);
  letter-spacing: 0.05em;
  margin-bottom: 0.375rem;
}

/* 小节标题前的强调条，提升信息层级 */
.section-label::before {
  content: '';
  width: 3px;
  height: 0.625rem;
  border-radius: 2px;
  background: var(--accent-500);
  opacity: 0.55;
  flex-shrink: 0;
}

.stats-section {
  display: flex;
  gap: 0.75rem;
  flex-shrink: 0;
}

.stat {
  display: flex;
  flex-direction: column;
  align-items: center;
  flex: 1;
  background: var(--bg-canvas);
  border: 1px solid var(--border-color);
  border-radius: 0.5rem;
  padding: 0.5rem;
  transition: border-color 0.15s ease;
}
.stat:hover {
  border-color: rgba(124, 106, 173, 0.4);
}

.stat-num {
  font-family: var(--font-heading);
  font-size: 1.125rem;
  font-weight: 600;
  color: var(--accent-500);
  line-height: 1;
}

.stat-label {
  font-size: 0.625rem;
  color: var(--text-muted);
  margin-top: 0.125rem;
}

.btn-refinery {
  display: inline-flex;
  align-items: center;
  gap: 0.375rem;
  width: 100%;
  justify-content: center;
  padding: 0.5rem;
  background: var(--bg-secondary);
  color: var(--accent-500);
  border: 1px solid var(--accent-500);
  border-radius: 0.5rem;
  font-size: 0.75rem;
  font-weight: 500;
  cursor: pointer;
  transition: all 0.15s ease;
}

.btn-refinery:hover {
  background: var(--accent-500);
  color: white;
}

.btn-refinery.secondary {
  margin-top: 0.5rem;
  color: var(--text-secondary);
  border-color: var(--border-color);
  background: var(--bg-secondary);
}

/* ===== 本章文风卡（S3）===== */
.style-status-section {
  display: flex;
  flex-direction: column;
  gap: 0.375rem;
}

.style-status-row {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  min-height: 1.5rem;
}

.style-override-badge {
  padding: 0.0625rem 0.4375rem;
  font-size: 0.625rem;
  color: #b45309;
  background: #fef3c7;
  border-radius: 0.25rem;
}

.btn-mini-reset {
  padding: 0.1875rem 0.5rem;
  font-size: 0.625rem;
  color: var(--text-muted);
  background: var(--bg-tertiary);
  border: none;
  border-radius: 0.375rem;
  cursor: pointer;
}

.btn-mini-reset:hover {
  color: #dc2626;
  background: #fee2e2;
}

.style-status-section .btn-refinery {
  margin-top: 0.125rem;
}
.btn-refinery.secondary:hover {
  background: var(--hover-bg);
  color: var(--text-primary);
  border-color: var(--accent-500);
}
.btn-refinery:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.reader-feedback-card {
  margin-top: 0.625rem;
  padding: 0.625rem;
  /* 半透明琥珀底：浅色/深色主题下均可读 */
  background: rgba(202, 138, 4, 0.1);
  border-left: 3px solid #ca8a04;
  border-radius: 0.5rem;
}
.rf-header {
  font-size: 0.6875rem;
  color: #d97706;
  margin-bottom: 0.375rem;
  font-weight: 600;
}
.rf-text {
  font-size: 0.75rem;
  line-height: 1.6;
  color: var(--text-primary);
  margin: 0;
  white-space: pre-wrap;
}

.hint {
  font-size: 0.6875rem;
  color: var(--text-muted);
  line-height: 1.5;
  margin: 0.375rem 0 0;
}

/* 世界模型调试快照（P0-5）：等宽小字摘要视图 */
.world-model-debug {
  margin: 0.5rem 0 0;
  padding: 0.5rem 0.625rem;
  font-family: var(--font-mono, monospace);
  font-size: 0.6875rem;
  line-height: 1.6;
  color: var(--text-secondary);
  background: var(--bg-secondary);
  border: 1px solid var(--border-color);
  border-radius: 6px;
  white-space: pre-wrap;
  word-break: break-all;
  max-height: 16rem;
  overflow-y: auto;
}

/* AI 辅助组件健康状况（P3-1/C5）：最近失败记录行 */
.comp-errors {
  flex-shrink: 0;
}
.comp-error-row {
  display: flex;
  flex-wrap: wrap;
  align-items: baseline;
  gap: 0.375rem;
  padding: 0.25rem 0.5rem;
  font-size: 0.75rem;
  line-height: 1.5;
  background: rgba(245, 158, 11, 0.05);
  border: 1px solid rgba(245, 158, 11, 0.3);
  border-radius: 0.375rem;
  margin-bottom: 0.375rem;
}
.comp-error-name {
  font-weight: 600;
  color: var(--text-primary);
  flex-shrink: 0;
}
.comp-error-time {
  font-size: 0.6875rem;
  color: var(--text-muted);
  flex-shrink: 0;
}
.comp-error-detail {
  color: var(--text-secondary);
  word-break: break-all;
}

/* 残句定点修复（P1.2）：句子 + 描述 + 修复裁决流 */
.report-item--fixable {
  display: flex;
  flex-direction: column;
  gap: 0.25rem;
}
.fix-sent {
  font-size: 0.75rem;
  line-height: 1.5;
  color: var(--text-primary);
}
.fix-sent--result {
  padding: 0.375rem 0.5rem;
  background: var(--bg-secondary);
  border: 1px solid var(--accent-400, #9685c2);
  border-radius: 6px;
}
.fix-desc {
  font-size: 0.6875rem;
  color: var(--text-muted);
}
.fix-status {
  font-size: 0.6875rem;
  color: var(--text-muted);
}
.fix-status--ok { color: var(--ok, #4a9); }
.fix-status--err { color: var(--danger, #c66); }
.fix-actions {
  display: flex;
  gap: 0.375rem;
}
.btn-mini-reset--primary {
  color: #fff;
  background: var(--accent-500, #7c6aad);
  border-color: var(--accent-500, #7c6aad);
}

/* ====== 完稿审计 / 沉淀抽取 ===== */
.adaptive-settle,
.adaptive-report,
.adaptive-finish {
  flex-shrink: 0;
}

.adaptive-settle .settle-block,
.adaptive-report .report-block {
  margin-top: 0.5rem;
  padding: 0.5rem 0.625rem;
  background: var(--bg-canvas);
  border: 1px solid var(--border-color);
  border-radius: 0.375rem;
}

.settle-block--warn,
.report-block--warn {
  border-color: rgba(245, 158, 11, 0.4);
  background: rgba(245, 158, 11, 0.05);
}

.settle-block-label,
.report-block-label {
  font-size: 0.6875rem;
  font-weight: 600;
  color: var(--text-primary);
  margin-bottom: 0.25rem;
}

.settle-item,
.report-item {
  font-size: 0.75rem;
  line-height: 1.5;
  color: var(--text-primary);
  padding: 0.125rem 0;
}

.settle-item .muted,
.report-item .muted {
  color: var(--text-muted);
}

.settle-item--conflict {
  display: flex;
  flex-direction: column;
  padding: 0.25rem 0;
  border-bottom: 1px dashed var(--border-color);
}
.settle-item--conflict:last-child {
  border-bottom: none;
}
.conflict-entity {
  font-weight: 600;
  color: #f59e0b;
}

.report-item--miss {
  color: #f59e0b;
}
.report-item--warn {
  color: #ef4444;
}
/* A5c① 收件箱积压行：文案 + 「去处理」同行 */
.report-item--inbox {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 0.5rem;
}
.issue-cat {
  display: inline-block;
  font-size: 0.625rem;
  padding: 0 0.25rem;
  border-radius: 0.1875rem;
  background: var(--border-color);
  color: var(--text-muted);
  margin-right: 0.25rem;
}

.btn-finish {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 0.375rem;
  width: 100%;
  padding: 0.5rem 0.75rem;
  border: none;
  border-radius: 0.375rem;
  background: var(--accent, #6366f1);
  color: #fff;
  font-size: 0.8125rem;
  font-weight: 500;
  cursor: pointer;
  transition: opacity 0.15s ease;
}
.btn-finish:hover:not(:disabled) {
  opacity: 0.9;
}
.btn-finish:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}

.empty .empty-icon {
  margin: 0 auto 0.75rem;
  opacity: 0.6;
}

/* 润色诊断过渡态：避免点击后"空白没反应"观感 */
.refine-loading {
  text-align: center;
  padding: 1.5rem 1rem;
  color: var(--text-secondary);
}
.refine-loading .empty-icon {
  margin: 0 auto 0.75rem;
  opacity: 0.7;
}
.refine-loading .empty-icon.spinning {
  animation: refine-spin 1.4s ease-in-out infinite;
}
.refine-loading .muted {
  font-size: 0.6875rem;
  margin-top: 0.375rem;
  opacity: 0.8;
}
@keyframes refine-spin {
  0% { transform: scale(1) rotate(0deg); opacity: 0.7; }
  50% { transform: scale(1.15) rotate(180deg); opacity: 1; }
  100% { transform: scale(1) rotate(360deg); opacity: 0.7; }
}

.empty .muted {
  font-size: 0.6875rem;
  margin-top: 0.375rem;
  opacity: 0.8;
}

/* 出场角色速查 */
.char-list {
  display: flex;
  flex-direction: column;
  gap: 0.375rem;
}

.char-item {
  background: var(--bg-canvas);
  border: 1px solid var(--border-color);
  border-radius: 0.5rem;
  padding: 0.4375rem 0.5rem;
  transition: border-color 0.15s ease, box-shadow 0.15s ease;
}
.char-item:hover {
  border-color: rgba(124, 106, 173, 0.45);
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.04);
}

.char-name {
  font-size: 0.8125rem;
  font-weight: 600;
  color: var(--text-primary);
  display: block;
}

.char-state {
  font-size: 0.6875rem;
  color: var(--text-muted);
  display: block;
  margin-top: 0.125rem;
}

.empty-inline {
  font-size: 0.6875rem;
  color: var(--text-muted);
  padding: 0.5rem;
  background: var(--bg-canvas);
  border: 1px dashed var(--border-color);
  border-radius: 0.25rem;
  line-height: 1.5;
}

/* ===== 审校结论 ===== */
.audit-block {
  background: var(--bg-canvas);
  border: 1px solid var(--border-color);
  border-radius: 0.5rem;
  padding: 0.5rem 0.625rem;
  margin-bottom: 0.5rem;
}

.audit-row {
  display: flex;
  justify-content: space-between;
  align-items: baseline;
  gap: 0.5rem;
  font-size: 0.75rem;
  padding: 0.125rem 0;
}

.audit-label {
  color: var(--text-muted);
  flex-shrink: 0;
}

.audit-value {
  color: var(--text-primary);
  font-weight: 500;
  text-align: right;
}

.audit-value.warn {
  color: #d97706;
  font-weight: 400;
}

.audit-value.verdict-pass { color: #16a34a; }
.audit-value.verdict-pass_with_fixes { color: #65a30d; }
.audit-value.verdict-needs_refinement,
.audit-value.verdict-needs_final_touch { color: #d97706; }
.audit-value.verdict-fail { color: #dc2626; }
.audit-value.verdict-unaudited { color: var(--text-muted); }

/* ===== 润色记录 ===== */
.surgery-row {
  display: flex;
  gap: 0.375rem;
  font-size: 0.75rem;
  padding: 0.375rem 0.5rem;
  background: var(--bg-canvas);
  border: 1px solid var(--border-color);
  border-radius: 0.5rem;
  margin-bottom: 0.375rem;
}

.surgery-status {
  flex-shrink: 0;
  color: #16a34a;
}

.surgery-row.failed .surgery-status {
  color: #dc2626;
}

.surgery-diff {
  color: var(--text-secondary);
  line-height: 1.5;
}

.surgery-row.failed .surgery-diff {
  color: var(--text-muted);
}

.refine-history .btn-refinery {
  margin-top: 0.375rem;
}
</style>
