<script setup lang="ts">
/**
 * 助手面板（08 期 §4.6 去 tab 化改造：壳只渲染当前分区，栏位在 AssistRail）。
 *
 * 五分区（栏图标 / Ctrl+1~5 定位，按写作流程排序）：
 * - 打算：写前规划——章级软脉络（SpinePanel）+ 大纲 + 意图反推
 * - 此刻：世界切片「此刻此地」+ 候选回流收件箱（WorldSceneSlice，与生成上下文同源）
 * - 本章：统计 / 本章文风 / Canon 真相账本跳转——章节档案
 * - 检查：完稿体检（按钮 + 报告）、沉淀抽取、读者反馈——按 检查→修改→反馈 三组排布（润色 Refinery 已于 2026-09-12 写后检查收敛批拔除）
 * - AI 视角（原调试，09 期重设计 docs/design/ux-redesign/09-ai-view-redesign.md）：
 *   健康横幅（有错置顶）→ AI 此刻读到的（分组折叠+保字排版）→ 世界模型快照（结构化摘要）
 *
 * 默认分区逻辑（空章→打算/有正文→此刻/用户切过即尊重）与 Ctrl+1~5 监听原样保留；
 * activeTab 以 v-model:active-tab 与 WorkspaceView 双向同步（面板关闭时容器持 null）。
 */
import { ref, computed, onMounted, onBeforeUnmount, watch } from 'vue'
import { useRouter } from 'vue-router'
import Icon from '../../../components/Icon.vue'
import { useAppStore } from '../../app/useAppStore'
import WorldSceneSlice from '../presentation/WorldSceneSlice.vue'
import SpinePanel from '../presentation/SpinePanel.vue'
import ContextPreviewSection from '../presentation/ContextPreviewSection.vue'
import { useChapterSpine } from '../composables/useChapterSpine'
import { styleApi } from '../../../services/api/domain'
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
  /** 当前分区（v-model:active-tab；null=按章节状态取默认） */
  activeTab?: InspectorTab | null
  /** pin 态（面板头图钉高亮；pin 语义与持久化在 WorkspaceView） */
  pinned?: boolean
}>(), {
  externalSession: null,
  activeTab: null,
  pinned: false,
})
const emit = defineEmits<{
  (e: 'update:activeTab', v: InspectorTab): void
  /** 面板内 Ctrl+1~5 切区（容器收到即确保面板开着） */
  (e: 'activate', key: InspectorTab): void
  (e: 'pin'): void
  (e: 'close'): void
}>()
const session = props.externalSession || useGenerationSession()

// 字数口径：剥 HTML 标签后计字符（此前 .length 把 <p>/mark 标签计入，虚高）
const wordCount = computed(() => countChapterWords(selectedChapter.value?.content_text || ''))

/** 本章有正文：润色/读者反馈的启用门槛（取代旧 stage==='done' 门控） */
const chapterHasContent = computed(() => wordCount.value > 0)

// 按写作流程排序：写前打算 → 写中此刻 → 本章档案 → 写后检查；AI 视角排末位。
// 栏图标（AssistRail）消费同一份标签/图标——零图标映射变化。
const tabs: TabDef[] = [
  { key: 'planning', label: '打算', icon: 'light-bulb' },
  { key: 'now', label: '此刻', icon: 'map' },
  { key: 'chapter', label: '本章', icon: 'document' },
  { key: 'review', label: '检查', icon: 'check-circle' },
  { key: 'debug', label: 'AI 视角', icon: 'magnifying-glass' },
]

// 默认分区按章节状态：空章落「打算」（写前），有正文落「此刻」（写中参考）。
// 正文可能异步到达——wordCount 由 0 转正且用户尚未手动切分区时补切到「此刻」；
// 用户手动切过一次后即尊重其选择，不再代切。
// activeTab 经 v-model 与容器双向同步：get 在容器持 null 时按默认推导，set 即 emit。
const userPickedTab = ref(false)
const activeTab = computed<InspectorTab>({
  get: () => props.activeTab ?? (wordCount.value > 0 ? 'now' : 'planning'),
  set: (v) => emit('update:activeTab', v),
})
/** 面板头分区名 */
const activeTabLabel = computed(() => tabs.find((t) => t.key === activeTab.value)?.label || '')

onMounted(() => {
  // 容器持 null（首次打开/切章后复位）→ 以默认分区回填，栏高亮与面板一致
  if (!props.activeTab) emit('update:activeTab', activeTab.value)
})

watch(selectedChapterId, () => {
  userPickedTab.value = false
  activeTab.value = wordCount.value > 0 ? 'now' : 'planning'
})
watch(wordCount, (n) => {
  if (n > 0 && !userPickedTab.value && activeTab.value === 'planning') activeTab.value = 'now'
})

// 诊断完成（问题清单就绪）/ 完稿报告 / 沉淀结果到达时切到审校 tab
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
      emit('activate', tabs[idx].key)
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

/** 更新情节节拍（第四弹合流：大纲 textarea 迁入叙事流面板；500ms 防抖不动）。
 *  draft 只记作者最后一次输入（冲刷消费）；textarea 仍直绑 store 值——
 *  OutlineView 全书大纲页编辑后经 store 响应式回流，绝不覆盖意图行 */
let outlineTimer: ReturnType<typeof setTimeout> | undefined
const outlineDraft = ref('')
function updateOutline(value: string) {
  if (!selectedChapterId.value) return
  outlineDraft.value = value
  clearTimeout(outlineTimer)
  outlineTimer = setTimeout(() => {
    outlineTimer = undefined
    store.updateChapter(selectedChapterId.value!, { outline_text: outlineDraft.value })
  }, 500)
}
/** 节拍冲刷：失焦/唤舱/续写时立即落库（防抖在途作废） */
function flushOutline() {
  if (!outlineTimer) return
  clearTimeout(outlineTimer)
  outlineTimer = undefined
  // outlineDraft 可为空串——清空也是有效写入，真值守卫会丢清空动作
  if (selectedChapterId.value) {
    store.updateChapter(selectedChapterId.value, { outline_text: outlineDraft.value })
  }
}

/** 叙事流整体冲刷（velluma:flush-planning：Tab 唤舱/Space 续写前同步派发）——
 *  spine 2s 防抖（flushNow）+ 大纲 500ms 防抖（flushOutline）一起清账，
 *  保证生成请求吃到最新鲜方向（心跳上行字段是第二重保险） */
function flushPlanning() {
  chapterSpine.flushNow()
  flushOutline()
}
onMounted(() => window.addEventListener('velluma:flush-planning', flushPlanning))
onBeforeUnmount(() => window.removeEventListener('velluma:flush-planning', flushPlanning))

/** 活跃节拍微标（第四弹）：就近节拍=stitch/dock 同一份计算（后端 active-beats
 *  端点纯算法零 LLM）；大纲/正文变化防抖 800ms 拉一次，切章复位 */
const activeBeat = ref('')
let activeBeatTimer: ReturnType<typeof setTimeout> | undefined
async function refreshActiveBeat() {
  const chapterId = selectedChapterId.value
  if (!chapterId) return
  try {
    const r = await adaptiveApi.activeBeats(chapterId)
    if (selectedChapterId.value === chapterId) activeBeat.value = r.beats?.[0] || ''
  } catch {
    activeBeat.value = ''
  }
}
function scheduleActiveBeat() {
  clearTimeout(activeBeatTimer)
  activeBeatTimer = setTimeout(refreshActiveBeat, 800)
}
watch([() => selectedChapter.value?.outline_text, () => wordCount.value], () => {
  if (activeTab.value === 'planning') scheduleActiveBeat()
})
watch(selectedChapterId, () => {
  activeBeat.value = ''
  clearTimeout(activeBeatTimer)
})
onMounted(() => { if (activeTab.value === 'planning') scheduleActiveBeat() })
watch(activeTab, (tab) => {
  if (tab === 'planning') scheduleActiveBeat()
})

/** 获取读者反馈（AI 扮演读者写叙述性感受）。门槛：本章有正文。 */
const readerFeedback = ref('')
const loadingFeedback = ref(false)
async function handleReaderFeedback() {
  if (!selectedChapterId.value || !chapterHasContent.value) return
  loadingFeedback.value = true
  readerFeedback.value = ''
  try {
    const result = await adaptiveApi.readerFeedback(selectedChapterId.value)
    readerFeedback.value = result.feedback
  } catch (e: any) {
    readerFeedback.value = `获取失败：${e.message}`
  } finally {
    loadingFeedback.value = false
  }
}

/** 跳世界页真相账本（C1 Canon 融合；检查报告改设定 / 章节 tab 入口共用） */
const router = useRouter()
function handleEditCanon() {
  const bookId = store.currentBookId.value
  if (!bookId) return
  router.push({ name: 'world', params: { bookId }, query: { panel: 'canon' } })
}

// ===== 世界模型快照（P0-5：/adaptive/model 调试入口，展开即拉一次；09 期结构化摘要）=====
const worldModelOpen = ref(false)
interface WorldModelSummary {
  hasIntent: boolean
  intentSource: string
  intentArc: string
  facts: string[]
  factCount: number
  projections: string[]
  totalWords: number
}
const worldModel = ref<WorldModelSummary | null>(null)
const worldModelLoading = ref(false)
const worldModelError = ref('')

// ===== AI 辅助组件健康状况（P3-1/C5：最近失败的组件，心跳带回）=====
// 空 = 一切正常，整块不渲染；成功即清（后端语义），恢复后自动消失
// 09 期：横幅置顶（有错才出现），默认折叠为一行计数，点开见明细
const compErrorsOpen = ref(false)
const COMPONENT_LABELS: Record<string, string> = {
  intent_inference: '方向猜测',
  future_projection: '走向推测',
  dock_generator: '卡舱供件',
  canon_watch: '世界感知',
  sediment: '设定整理',
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

// ===== AI 此刻所见预览（P5 B2；09 期重设计：分区常开，进区自动装配一次）=====
type PreviewMode = 'stitch' | 'continue' | 'burst' | 'outline' | 'open'
const contextPreviewMode = ref<PreviewMode>('continue')
const contextPreviewData = ref<ContextPreview | null>(null)
const contextPreviewLoading = ref(false)
const contextPreviewError = ref('')

/**
 * 光标窗口（2026-09-15 FIM 真切片）：光标前 500 字 / 后 150 字——预览按光标
 * 现场装配（中插不再读到章节尾部语境）。编辑器不在场（切页/未进章）发空串，
 * 后端回退落库路径。取窗口径与 useAdaptiveAssist._anchorRecentText 同角色。
 */
function _previewCursorWindow(): { before: string; after: string } {
  const ed = chapterEditorHandle.value
  if (!ed) return { before: '', after: '' }
  const $from = ed.state.selection.$from
  const docEnd = ed.state.doc.content.size
  const before = ed.state.doc
    .textBetween(Math.max(0, $from.pos - 500), $from.pos, '\n\n')
    .trim().slice(-500)
  const after = ed.state.doc
    .textBetween($from.pos, Math.min($from.pos + 150, docEnd), '\n\n')
    .trim().slice(0, 150)
  return { before, after }
}

async function loadContextPreview() {
  const chapterId = selectedChapterId.value
  if (!chapterId || contextPreviewLoading.value) return
  contextPreviewLoading.value = true
  contextPreviewError.value = ''
  try {
    contextPreviewData.value = await adaptiveApi.contextPreview(
      chapterId, contextPreviewMode.value, _previewCursorWindow(),
    )
  } catch (e: any) {
    contextPreviewError.value = e?.message || '读取失败'
  } finally {
    contextPreviewLoading.value = false
  }
}

function switchContextPreviewMode(mode: PreviewMode) {
  if (mode === contextPreviewMode.value) return
  contextPreviewMode.value = mode
  if (contextPreviewData.value || contextPreviewError.value) loadContextPreview()
}

// 进「AI 视角」分区且尚无数据 → 自动装配一次（拉过即不再自动拉，之后靠手动刷新）
watch(activeTab, (tab) => {
  if (tab === 'debug' && selectedChapterId.value && !contextPreviewData.value && !contextPreviewLoading.value) {
    loadContextPreview()
  }
}, { immediate: true })

// 切章复位（旧章预览不再示人；仍在本分区则自动重拉一次=旧「重开重装配」语义）
watch(selectedChapterId, () => {
  contextPreviewData.value = null
  contextPreviewError.value = ''
  worldModelOpen.value = false
  worldModel.value = null
  worldModelError.value = ''
  if (activeTab.value === 'debug' && !contextPreviewLoading.value) loadContextPreview()
})

/** 意图来源人话标签（世界模型摘要行消费） */
const INTENT_SOURCE_LABELS: Record<string, string> = {
  inferred: 'AI 猜的',
  author: '你写的',
  outline: '大纲',
  baton: '上一章接力',
  none: '无',
}

async function toggleWorldModelDebug() {
  worldModelOpen.value = !worldModelOpen.value
  if (!worldModelOpen.value) return
  const chapterId = selectedChapterId.value
  if (!chapterId) return
  // 摘要口径与旧版逐行同源：意图 + 事实最近 5 条（各截 50 字）+ 走向 3 条 + 整理字数
  worldModelLoading.value = true
  worldModelError.value = ''
  try {
    const snap = await adaptiveApi.model(chapterId)
    const intent = snap.intent || {}
    const facts = (snap.facts || []).slice(-5).map((f: any) => String(f.text || '').slice(0, 50))
    const projections = (snap.projections || [])
      .filter((p: any) => !p.__dock__ && !p.__canon_watch__)
      .map((p: any) => {
        const beat = p.possible_beats?.[0]
        return String(beat?.event || '').slice(0, 50)
      })
      .slice(0, 3)
    worldModel.value = {
      hasIntent: Boolean(intent.source) && intent.source !== 'none',
      intentSource: INTENT_SOURCE_LABELS[intent.source] || intent.source || '',
      intentArc: String(intent.arc || '').slice(0, 40),
      facts,
      factCount: snap.fact_count ?? 0,
      projections,
      totalWords: snap.total_words ?? 0,
    }
  } catch (e: any) {
    worldModelError.value = e?.message || '读取失败'
  } finally {
    worldModelLoading.value = false
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

// ===== 本章一键收为文风范例（2026-09-14 装填通道）=====
// 去参数化后的两根支柱之一：亲笔样本 few-shot 是质量杠杆最大的一环，但样本库
// 零库存曾让它全程空转（7 次生成 sample_ids 全空）——把「收本章为范例」放在
// 作者看得见的地方，亲笔正文秒级入库（摘开头至句界，幂等：已收编过 409 提示）。
const harvestingSample = ref(false)
async function harvestChapterSample() {
  const bookId = store.currentBookId.value
  if (!bookId || !selectedChapterId.value || harvestingSample.value) return
  harvestingSample.value = true
  try {
    const created = await styleApi.createSamplesFromChapters(bookId, { chapter_id: selectedChapterId.value })
    showToast(`已收为文风范例（摘 ${created[0]?.word_count ?? 0} 字）——续写会用你的字当示范`, 'success')
  } catch (e: any) {
    const msg = String(e?.message || '')
    if (e?.status === 409 || msg.includes('已收编')) showToast('本章已收编过范例——样本库里能找到它', 'info')
    else if (e?.status === 422 || msg.includes('正文')) showToast('本章还没有可收编的正文', 'warning')
    else showToast('收录失败: ' + msg, 'error')
  } finally {
    harvestingSample.value = false
  }
}

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

// ---- 意图纠正手势（2026-09-03 意图入舱批次） ----
// 「AI 目前的猜测」行的「不对」：一句话修正 → 落 spine 打算（生成链立即
// 按作者方向走，dock 源链作者层压过猜测层）+ intent_correct 埋点（纠正史
// 回喂意图反推 prompt——口味校准的 few-shot 教材）
const correctingIntent = ref(false)
const correctionDraft = ref('')

function startCorrectIntent() {
  correctionDraft.value = session.planSuggestions?.value?.arc || ''
  correctingIntent.value = true
}

function confirmCorrectIntent() {
  const text = correctionDraft.value.trim()
  correctingIntent.value = false
  if (!text) return
  const guessed = session.planSuggestions?.value?.arc || ''
  chapterSpine.correctIntent(text, guessed)
  // 本地即时反馈（下一次心跳会以后端层 2 快照为准刷新）
  if (session.planSuggestions?.value) {
    session.planSuggestions.value = { source: 'author', arc: text, confidence: 1 }
  }
}

// 切章即退出纠正态（草稿是旧章的猜测，带过去必误导）
watch(selectedChapterId, () => { correctingIntent.value = false })
</script>

<template>
  <aside class="inspector">
    <!-- 面板头：分区名 + 固定钮 + 收起钮（栏位在 AssistRail，面板壳只渲染当前分区） -->
    <div class="panel-head">
      <span class="panel-head__title">{{ activeTabLabel }}</span>
      <button
        class="panel-head__btn icon-btn-instrument"
        :class="{ 'panel-head__btn--on': pinned }"
        :title="pinned ? '取消固定' : '固定面板（Ctrl+\\）'"
        @click="emit('pin')"
      >
        <Icon name="pin" :size="13" />
      </button>
      <button class="panel-head__btn icon-btn-instrument" title="收起面板" @click="emit('close')">
        <Icon name="x-mark" :size="14" />
      </button>
    </div>

    <!-- 分区内容 -->
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
          <!-- 叙事引力流（第四弹 UI 合流 · 路径 C）：方向行+锚点+节拍流单卡 ——
               数据层双字段分立不动（spine 走温卡/outline 走就近节拍），只是
               作者眼里只有一个连贯编辑面 -->
          <SpinePanel
            :spine="chapterSpine.spine.value"
            :suggestions="chapterSpine.spineSuggestions.value"
            :suggesting="chapterSpine.spineSuggesting.value"
            :outline-text="selectedChapter.outline_text"
            :active-beat="activeBeat"
            @update-intent="chapterSpine.setIntent"
            @add-anchor="chapterSpine.addAnchor"
            @update-anchor="(id, patch) => chapterSpine.updateAnchor(id, patch)"
            @remove-anchor="chapterSpine.removeAnchor"
            @suggest="chapterSpine.suggest"
            @adopt="(part) => chapterSpine.adoptSuggestion(part)"
            @discard-suggestions="chapterSpine.discardSuggestions"
            @update-outline="updateOutline"
            @outline-blur="flushOutline"
          />

          <!-- 意图反推（心跳带回的后台规划淡建议；降级为打算区下方一行小字，不占独立小节） -->
          <!-- 只在 AI 真推测时出现（2026-09-03 实测修正）：来源是作者大纲/打算时
               不回显——作者自己的话就在上方打算区，端回来标「AI 猜测」只有怪异感。
               纠正手势「不对」：一句话修正 → 落 spine 打算（生成链随即按作者方向走）
               + intent_correct 埋点（纠正史是意图反推的口味校准教材）。 -->
          <div v-if="session.planSuggestions?.value?.arc && session.planSuggestions.value.source === 'inferred'" class="plan-guess">
            <template v-if="!correctingIntent">
              AI 目前的猜测：{{ session.planSuggestions.value.arc }}
              <button
                class="guess-correct-btn"
                title="猜得不对？一句话告诉它这章要写什么——卡舱和续写马上按你的方向来"
                @click="startCorrectIntent"
              >不对</button>
            </template>
            <div v-else class="guess-correct-row">
              <input
                v-model="correctionDraft"
                class="guess-correct-input"
                maxlength="60"
                placeholder="这章其实是要写……（一句话）"
                @keydown.enter.prevent="confirmCorrectIntent"
                @keydown.esc.prevent="correctingIntent = false"
              />
              <button class="guess-correct-btn" @click="confirmCorrectIntent">好</button>
              <button class="guess-correct-btn guess-correct-cancel" @click="correctingIntent = false">算了</button>
            </div>
          </div>

          <!-- 大纲卡已并入上方叙事流的「情节节拍」区（第四弹合流，2026-09-14） -->
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
                <span v-if="chapterStyleOverride" class="style-override-badge">本章专属</span>
                <span v-else class="muted">跟随全书文风</span>
                <button
                  v-if="chapterStyleOverride"
                  class="btn-mini-reset"
                  title="删掉本章专属，改回跟随全书文风"
                  @click="handleResetChapterStyle"
                >改回全书文风</button>
              </template>
            </div>
            <button class="btn-refinery" @click="handleEditChapterStyle">
              <Icon name="paint-brush" :size="14" />
              <span>{{ chapterStyleOverride ? '编辑本章专属文风' : '给本章单独定个文风' }}</span>
            </button>
            <!-- 装填通道（2026-09-14）：亲笔正文一键入库为 few-shot 示范——
                 样本库空转的根治入口，比任何参数都管用 -->
            <button
              class="btn-refinery secondary"
              :disabled="!chapterHasContent || harvestingSample"
              :title="chapterHasContent ? '把本章开头摘为文风范例——AI 续写时用它当你的笔迹示范' : '本章写了字才能收'"
              @click="harvestChapterSample"
            >
              <Icon name="heart" :size="14" />
              <span>{{ harvestingSample ? '收录中…' : '收本章为文风范例' }}</span>
            </button>
            <p class="hint">回忆章想换个腔调？本章专属只管这一章，其他章节不受影响。</p>
          </section>

          <!-- 跳世界页真相账本（C1：Canon 融入世界页） -->
          <section>
            <button class="btn-refinery" @click="handleEditCanon">
              <Icon name="truth" :size="14" />
              <span>在世界页查看真相</span>
            </button>
            <p class="hint">表（读者所见）与里（作者真相）的账本——秘密设定 / 揭示计划</p>
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
              :title="session.adaptiveMode?.value && session.authorLane?.value === 'composing' ? '让 AI 通读全章，出一份检查报告' : '在本章写满 4 个字后可用'"
              @click="session.triggerAdaptiveFinish()"
            >
              <Icon :name="session.aiLane?.value === 'analyzing' ? 'loader' : 'check-circle'" :size="14" />
              <span>{{ session.aiLane?.value === 'analyzing' ? '通读中…' : '完稿体检' }}</span>
            </button>
            <p class="hint">AI 通读全章做检查：没写完的句子、关键情节写没写到、秘密穿帮、编辑意见、世界账本对不对得上、能抖什么信息差，并更新前情记忆。</p>
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
                    <button class="btn-mini-reset btn-mini-reset--primary btn-primary-instrument" @click="adoptFix(i, d)">采纳</button>
                    <button class="btn-mini-reset" @click="dismissFix(i)">放弃</button>
                  </div>
                </template>
                <span v-else class="fix-status">未能修复（{{ fixStates[i].reason }}）</span>
              </div>
            </div>
            <!-- 疑似 AI 味变体（语义扫描：embedding 相似度抓「换字逃逸」改写变体；只提示，作者裁决） -->
            <div v-if="session.finishReport.value.semantic_hits?.length" class="report-block report-block--warn">
              <div class="report-block-label">疑似 AI 味的句子（{{ session.finishReport.value.semantic_hits.length }}）</div>
              <div
                v-for="(hit, i) in session.finishReport.value.semantic_hits.slice(0, 5)"
                :key="'sem' + i"
                class="report-item"
              >
                <div class="fix-sent">{{ hit.segment }}</div>
                <div class="fix-desc">
                  ≈「{{ hit.pattern }}」<template v-if="hit.alternative"> · 可改为：{{ hit.alternative }}</template>
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
            <!-- B5 现实校验（Phase D 2026-09-12 盘活）：知识视图生死论断回查 fresh fold，
                 mismatches 非空 = 世界账本与推演派生物在说谎——回世界页核对 -->
            <div v-if="session.finishReport.value.reality_check?.mismatches?.length" class="report-block report-block--warn">
              <div class="report-block-label">世界账本对不上（{{ session.finishReport.value.reality_check.mismatches.length }} 处）</div>
              <div
                v-for="(m, i) in session.finishReport.value.reality_check.mismatches.slice(0, 5)"
                :key="'rc' + i"
                class="report-item"
              >{{ m.claim }}<template v-if="m.detail"> —— {{ m.detail }}</template></div>
              <p class="hint">这些是世界推演（谁在场/谁死了）与真实事件账本的冲突，去世界页核对后重算。</p>
            </div>
            <!-- B9 认知浮现（Phase D 盘活）：反讽机会=在场者不知道的信息差 + 戏剧资本 -->
            <div
              v-if="session.finishReport.value.cognition_surface && ((session.finishReport.value.cognition_surface.irony?.length ?? 0) > 0 || (session.finishReport.value.cognition_surface.capital_count ?? 0) > 0)"
              class="report-block"
            >
              <div class="report-block-label">可以抖出来的信息差（{{ session.finishReport.value.cognition_surface.irony?.length ?? 0 }} 个机会）</div>
              <div
                v-for="(s, i) in (session.finishReport.value.cognition_surface.irony || []).slice(0, 3)"
                :key="'irony' + i"
                class="report-item"
              >{{ s }}</div>
              <div v-if="(session.finishReport.value.cognition_surface.capital_count ?? 0) > 0" class="report-item">
                戏剧资本 {{ session.finishReport.value.cognition_surface.capital_count }} 条（读者知道、人物不知道的事，可攒着引爆）
              </div>
            </div>
            <!-- A5c① 收件箱积压（book 级 pending 计数，>0 才显示）：一键直达「此刻」tab 裁决 -->
            <div v-if="(session.finishReport.value.candidates_pending ?? 0) > 0" class="report-block report-block--inbox">
              <div class="report-block-label">收件箱</div>
              <div class="report-item report-item--inbox">
                {{ session.finishReport.value.candidates_pending }} 条世界变化待确认
                <button class="btn-mini-reset btn-mini-reset--primary btn-primary-instrument" title="打开右侧「此刻」页的候选收件箱" @click="requestOpenInbox">去处理</button>
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

          <!-- 【润色 Refinery 已拔除 2026-09-12】组二的「AI 从正文发现」（沉淀）仍在上方 -->

          <!-- 组三：反馈（读者反馈 + 审校结论；本章无正文且无论断时整组缺席） -->
          <div v-if="chapterHasContent" class="group-title">反馈</div>
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

        </template>
      </div>

      <!-- ====== AI 视角（原调试 tab，09 期重设计）：健康横幅 → 所见预览 → 世界模型 ====== -->
      <div v-else-if="activeTab === 'debug'" class="panel debug-panel">
        <div v-if="!selectedChapter" class="empty">
          <p>从左侧选择一个章节。</p>
        </div>
        <template v-else>
          <!-- 组件健康状况（置顶横幅；有错才渲染，默认折叠为一行计数） -->
          <section v-if="componentErrors.length" class="comp-errors">
            <button class="comp-toggle" @click="compErrorsOpen = !compErrorsOpen">
              <Icon name="exclamation-circle" :size="13" class="comp-icon" />
              <span class="comp-toggle-title">{{ componentErrors.length }} 个辅助功能最近出错</span>
              <Icon :name="compErrorsOpen ? 'chevron-down' : 'chevron-up'" :size="12" class="comp-chev" />
            </button>
            <template v-if="compErrorsOpen">
              <div v-for="err in componentErrors" :key="err.component" class="comp-error-row">
                <span class="comp-error-name">{{ componentLabelOf(err.component) }}</span>
                <span class="comp-error-time">{{ relTimeOf(err.ts) }}</span>
                <span class="comp-error-detail" :title="err.error">{{ err.error }}</span>
              </div>
              <p class="hint">只记最近一次，恢复了会自动消失。</p>
            </template>
          </section>

          <!-- AI 此刻读到的（主件：分组折叠 + 保字排版，分区常开） -->
          <ContextPreviewSection
            :loading="contextPreviewLoading"
            :error="contextPreviewError"
            :preview="contextPreviewData"
            :mode="contextPreviewMode"
            @refresh="loadContextPreview"
            @update:mode="switchContextPreviewMode"
          />

          <!-- 世界模型快照（底部折叠卡，结构化摘要） -->
          <section class="world-model">
            <button class="wm-toggle" @click="toggleWorldModelDebug">
              <Icon name="magnifying-glass" :size="14" />
              <span class="wm-toggle-title">AI 眼中的世界</span>
              <Icon :name="worldModelOpen ? 'chevron-down' : 'chevron-up'" :size="12" class="wm-chev" />
            </button>
            <div v-if="worldModelOpen" class="wm-body">
              <div v-if="worldModelLoading" class="wm-status">读取中…</div>
              <div v-else-if="worldModelError" class="wm-status wm-status--err">读取失败：{{ worldModelError }}</div>
              <template v-else-if="worldModel">
                <div class="wm-row">
                  <span class="wm-k">方向</span>
                  <span class="wm-v">{{ worldModel.hasIntent ? `${worldModel.intentSource} · ${worldModel.intentArc}` : '（无）' }}</span>
                </div>
                <div class="wm-row">
                  <span class="wm-k">事实</span>
                  <span class="wm-v">{{ worldModel.factCount }} 条（最近 {{ worldModel.facts.length }} 条）</span>
                </div>
                <div v-for="(f, i) in worldModel.facts" :key="'wmf' + i" class="wm-sub">· {{ f }}</div>
                <div class="wm-row">
                  <span class="wm-k">走向</span>
                  <span class="wm-v">{{ worldModel.projections.length }} 条</span>
                </div>
                <div v-for="(p, i) in worldModel.projections" :key="'wmp' + i" class="wm-sub">· {{ p }}</div>
                <div class="wm-row">
                  <span class="wm-k">已整理</span>
                  <span class="wm-v">{{ worldModel.totalWords }} 字</span>
                </div>
              </template>
            </div>
          </section>
        </template>
      </div>
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

/* 面板头（08 期 §4.6）：分区名 + 固定/收起钮 */
.panel-head {
  display: flex;
  align-items: center;
  gap: 0.375rem;
  padding: 0.5rem 0.625rem 0.5rem 0.875rem;
  border-bottom: 1px solid var(--border-color);
  background: var(--bg-tertiary);
  flex-shrink: 0;
}

.panel-head__title {
  flex: 1;
  /* N3 §5.2：chrome 字号归位 12/13/14 阶——15px(--text-md) 档回收 */
  font-size: var(--text-sm);
  font-weight: 600;
  color: var(--text-primary);
}

/* N3：皮肤由 .icon-btn-instrument（style.css 组件层）提供；本类仅保留固定态覆盖 */
.panel-head__btn--on {
  color: var(--accent-500);
}

/* 检查 tab 流程组标题（检查→修改→反馈），层级高于 .section-label */
.group-title {
  font-size: var(--text-xs);
  font-weight: 600;
  color: var(--text-secondary);
  letter-spacing: 0.08em;
  padding-bottom: 0.25rem;
  border-bottom: 1px solid var(--border-color);
}

/* 打算 tab：意图反推降级小字行 */
.plan-guess {
  font-size: var(--text-xs); /* 11px→12px 最低可读档 */
  color: var(--text-secondary);
  line-height: 1.5;
  padding: 0 0.125rem;
}

/* 意图纠正手势（2026-09-03 意图入舱）：「不对」按钮 + 行内修正输入 */
.guess-correct-btn {
  margin-left: 0.375rem;
  padding: 0 0.375rem;
  font-size: var(--text-xs); /* 10px→12px 最低可读档 */
  line-height: 1.4;
  color: var(--text-muted);
  background: transparent;
  border: 1px solid var(--border-color);
  border-radius: var(--radius-xs);
  cursor: pointer;
}

.guess-correct-btn:hover {
  color: var(--accent-500, var(--text-secondary));
  border-color: var(--accent-400, var(--border-color));
}

.guess-correct-row {
  display: flex;
  align-items: center;
  gap: 0.25rem;
  margin-top: 0.25rem;
}

.guess-correct-input {
  flex: 1;
  min-width: 0;
  padding: 0.125rem 0.375rem;
  font-size: var(--text-xs); /* 11px→12px 最低可读档 */
  color: var(--text-primary);
  background: var(--bg-secondary);
  border: 1px solid var(--border-color);
  border-radius: var(--radius-xs);
  outline: none;
}

.guess-correct-input:focus {
  border-color: var(--accent-400, var(--text-muted));
}

.guess-correct-cancel {
  opacity: 0.7;
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
  border-radius: var(--radius-xs);
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
  font-size: var(--text-sm);
  line-height: 1.7;
}

/* 大纲卡样式已随第四弹合流退役（节拍区样式在 SpinePanel 叙事流） */

.section-label {
  display: flex;
  align-items: center;
  gap: 0.375rem;
  font-size: var(--text-xs); /* 11px→12px 最低可读档 */
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
  border-radius: var(--radius-md);
  padding: 0.5rem;
  transition: border-color var(--dur-2) var(--ease-out);
}
.stat:hover {
  border-color: color-mix(in srgb, var(--accent-500) 40%, transparent);
}

.stat-num {
  font-family: var(--font-heading);
  font-variant-numeric: tabular-nums;
  font-size: var(--text-xl);
  font-weight: 600;
  color: var(--accent-500);
  line-height: 1;
}

.stat-label {
  font-size: var(--text-xs); /* 10px→12px 最低可读档 */
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
  border-radius: var(--radius-md);
  font-size: var(--text-xs);
  font-weight: 500;
  cursor: pointer;
  transition: all var(--dur-2) var(--ease-out);
}

.btn-refinery:hover {
  background: var(--accent-500);
  color: var(--bg-canvas);
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
  font-size: var(--text-xs); /* 10px→12px 最低可读档 */
  color: var(--warn);
  background: var(--warn-bg);
  border-radius: var(--radius-xs);
}

.btn-mini-reset {
  padding: 0.1875rem 0.5rem;
  font-size: var(--text-xs); /* 10px→12px 最低可读档 */
  color: var(--text-muted);
  background: var(--bg-tertiary);
  border: none;
  border-radius: var(--radius-sm);
  cursor: pointer;
}

.btn-mini-reset:hover {
  color: var(--danger);
  background: var(--danger-bg);
}

.style-status-section .btn-refinery {
  margin-top: 0.125rem;
}
.btn-refinery.secondary:hover {
  background: var(--state-hover);
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
  background: color-mix(in srgb, var(--warn) 10%, transparent);
  border-left: 3px solid var(--warn);
  border-radius: var(--radius-md);
}
.rf-header {
  font-size: var(--text-xs); /* 11px→12px 最低可读档 */
  color: var(--warn);
  margin-bottom: 0.375rem;
  font-weight: 600;
}
.rf-text {
  font-size: var(--text-xs);
  line-height: 1.6;
  color: var(--text-primary);
  margin: 0;
  white-space: pre-wrap;
}

.hint {
  font-size: var(--text-xs); /* 11px→12px 最低可读档 */
  color: var(--text-muted);
  line-height: 1.5;
  margin: 0.375rem 0 0;
}

/* 健康横幅（09 期置顶；折叠为一行计数，点开见明细） */
.comp-toggle {
  display: flex;
  align-items: center;
  gap: 0.375rem;
  width: 100%;
  padding: 0.375rem 0.5rem;
  background: color-mix(in srgb, var(--warn) 8%, transparent);
  border: 1px solid color-mix(in srgb, var(--warn) 35%, transparent);
  border-radius: var(--radius-sm);
  cursor: pointer;
  text-align: left;
}
.comp-toggle:hover {
  background: color-mix(in srgb, var(--warn) 14%, transparent);
}
.comp-icon {
  color: var(--warn);
  flex-shrink: 0;
}
.comp-toggle-title {
  flex: 1;
  font-size: var(--text-xs);
  font-weight: 600;
  color: var(--text-primary);
}
.comp-chev {
  color: var(--text-muted);
  flex-shrink: 0;
}
.comp-errors .comp-error-row {
  margin-top: 0.375rem;
}
.comp-errors .hint {
  margin-bottom: 0;
}

/* 世界模型快照（底部折叠卡，结构化定义行） */
.wm-toggle {
  display: flex;
  align-items: center;
  gap: 0.375rem;
  width: 100%;
  padding: 0.4375rem 0.5rem;
  color: var(--text-secondary);
  background: var(--bg-canvas);
  border: 1px solid var(--border-color);
  border-radius: var(--radius-md);
  font-size: var(--text-xs);
  cursor: pointer;
  transition: border-color var(--dur-2) var(--ease-out);
}
.wm-toggle:hover {
  border-color: var(--accent-400);
  color: var(--text-primary);
}
.wm-toggle-title {
  flex: 1;
  text-align: left;
  font-weight: 600;
}
.wm-chev {
  color: var(--text-muted);
}
.wm-body {
  margin-top: 0.375rem;
  padding: 0.4375rem 0.625rem;
  background: var(--bg-canvas);
  border: 1px solid var(--border-color);
  border-radius: var(--radius-md);
}
.wm-status {
  font-size: var(--text-xs); /* 11px→12px 最低可读档 */
  color: var(--text-muted);
}
.wm-status--err {
  color: var(--danger);
}
.wm-row {
  display: flex;
  gap: 0.5rem;
  align-items: baseline;
  padding: 0.125rem 0;
}
.wm-k {
  flex: 0 0 3.5em;
  font-size: var(--text-xs); /* 11px→12px 最低可读档 */
  font-weight: 600;
  color: var(--text-muted);
}
.wm-v {
  flex: 1;
  min-width: 0;
  font-size: var(--text-xs);
  color: var(--text-primary);
}
.wm-sub {
  margin-left: 4em;
  font-size: var(--text-xs); /* 11px→12px 最低可读档 */
  color: var(--text-secondary);
  line-height: 1.6;
  word-break: break-all;
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
  font-size: var(--text-xs);
  line-height: 1.5;
  background: color-mix(in srgb, var(--warn) 5%, transparent);
  border: 1px solid color-mix(in srgb, var(--warn) 30%, transparent);
  border-radius: var(--radius-sm);
  margin-bottom: 0.375rem;
}
.comp-error-name {
  font-weight: 600;
  color: var(--text-primary);
  flex-shrink: 0;
}
.comp-error-time {
  font-size: var(--text-xs); /* 11px→12px 最低可读档 */
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
  font-size: var(--text-xs);
  line-height: 1.5;
  color: var(--text-primary);
}
.fix-sent--result {
  padding: 0.375rem 0.5rem;
  background: var(--bg-secondary);
  border: 1px solid var(--accent-400);
  border-radius: var(--radius-sm);
}
.fix-desc {
  font-size: var(--text-xs); /* 11px→12px 最低可读档 */
  color: var(--text-muted);
}
.fix-status {
  font-size: var(--text-xs); /* 11px→12px 最低可读档 */
  color: var(--text-muted);
}
.fix-status--ok { color: var(--ok); }
.fix-status--err { color: var(--danger); }
.fix-actions {
  display: flex;
  gap: 0.375rem;
}
.btn-mini-reset--primary {
  min-height: var(--control-h-sm);
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
  border-radius: var(--radius-sm);
}

.settle-block--warn,
.report-block--warn {
  border-color: color-mix(in srgb, var(--warn) 40%, transparent);
  background: color-mix(in srgb, var(--warn) 5%, transparent);
}

.settle-block-label,
.report-block-label {
  font-size: var(--text-xs); /* 11px→12px 最低可读档 */
  font-weight: 600;
  color: var(--text-primary);
  margin-bottom: 0.25rem;
}

.settle-item,
.report-item {
  font-size: var(--text-xs);
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
  color: var(--warn);
}

.report-item--miss {
  color: var(--warn);
}
.report-item--warn {
  color: var(--danger);
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
  font-size: var(--text-xs); /* 10px→12px 最低可读档 */
  padding: 0 0.25rem;
  border-radius: var(--radius-xs);
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
  border-radius: var(--radius-sm);
  background: var(--accent-500);
  color: var(--bg-canvas);
  font-size: var(--text-sm);
  font-weight: 500;
  cursor: pointer;
  transition: opacity var(--dur-2) var(--ease-out);
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
  font-size: var(--text-xs); /* 11px→12px 最低可读档 */
  margin-top: 0.375rem;
  opacity: 0.8;
}
@keyframes refine-spin {
  0% { transform: scale(1) rotate(0deg); opacity: 0.7; }
  50% { transform: scale(1.15) rotate(180deg); opacity: 1; }
  100% { transform: scale(1) rotate(360deg); opacity: 0.7; }
}

.empty .muted {
  font-size: var(--text-xs); /* 11px→12px 最低可读档 */
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
  border-radius: var(--radius-md);
  padding: 0.4375rem 0.5rem;
  transition: border-color var(--dur-2) var(--ease-out), box-shadow var(--dur-2) var(--ease-out);
}
.char-item:hover {
  border-color: color-mix(in srgb, var(--accent-500) 45%, transparent);
  box-shadow: var(--shadow-sm);
}

.char-name {
  font-size: var(--text-sm);
  font-weight: 600;
  color: var(--text-primary);
  display: block;
}

.char-state {
  font-size: var(--text-xs); /* 11px→12px 最低可读档 */
  color: var(--text-muted);
  display: block;
  margin-top: 0.125rem;
}

.empty-inline {
  font-size: var(--text-xs); /* 11px→12px 最低可读档 */
  color: var(--text-muted);
  padding: 0.5rem;
  background: var(--bg-canvas);
  border: 1px dashed var(--border-color);
  border-radius: var(--radius-xs);
  line-height: 1.5;
}

/* ===== 审校结论 ===== */
.audit-block {
  background: var(--bg-canvas);
  border: 1px solid var(--border-color);
  border-radius: var(--radius-md);
  padding: 0.5rem 0.625rem;
  margin-bottom: 0.5rem;
}

.audit-row {
  display: flex;
  justify-content: space-between;
  align-items: baseline;
  gap: 0.5rem;
  font-size: var(--text-xs);
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
  color: var(--warn);
  font-weight: 400;
}

.audit-value.verdict-pass { color: var(--ok); }
.audit-value.verdict-pass_with_fixes { color: var(--ok); }
.audit-value.verdict-needs_refinement,
.audit-value.verdict-needs_final_touch { color: var(--warn); }
.audit-value.verdict-fail { color: var(--danger); }
.audit-value.verdict-unaudited { color: var(--text-muted); }

/* ===== 润色记录 ===== */
.surgery-row {
  display: flex;
  gap: 0.375rem;
  font-size: var(--text-xs);
  padding: 0.375rem 0.5rem;
  background: var(--bg-canvas);
  border: 1px solid var(--border-color);
  border-radius: var(--radius-md);
  margin-bottom: 0.375rem;
}

.surgery-status {
  flex-shrink: 0;
  color: var(--ok);
}

.surgery-row.failed .surgery-status {
  color: var(--danger);
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
