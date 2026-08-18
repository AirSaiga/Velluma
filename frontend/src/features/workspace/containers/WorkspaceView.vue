<script setup lang="ts">
/**
 * 写作台（NLE-ADF 3.0「纸面优先」重构）。
 *
 * 布局：
 * - 左栏 Binder：章节导航（列表 + 状态徽标 + 新建/导入/分析）
 * - 中栏：纸面画布（ChapterEditorContainer）+ 超薄顶栏（状态文案 + AI 辅助/快捷键/抽屉）
 *   + 底部状态栏（字数 + 保存状态）；作者写的即真实文档，无生成预览投影
 * - 右缘副驾抽屉：此刻 / 章节 / 审校 三 tab（InspectorPanel）
 *
 * splitpanes 提供可拖拽分隔（依赖已装）。
 */
import { ref, watch, computed, onMounted, onBeforeUnmount } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { Splitpanes, Pane } from 'splitpanes'
import 'splitpanes/dist/splitpanes.css'
import Icon from '../../../components/Icon.vue'
import ChapterEditor from '../../../components/ChapterEditor.vue'
import ChapterBadges from '../presentation/ChapterBadges.vue'
import PerceptionBand from '../presentation/PerceptionBand.vue'
import MarkdownImportModal from '../../import-markdown/containers/MarkdownImportModal.vue'
import ExtractionModal from '../../extraction/containers/ExtractionModal.vue'
import InspectorPanel from './InspectorPanel.vue'
import SparkDock from '../../generation/presentation/SparkDock.vue'
import BeatCardDock from '../../generation/presentation/BeatCardDock.vue'
import IgnitionCard from '../../generation/presentation/IgnitionCard.vue'
import ThinkingIndicator from '../../generation/presentation/ThinkingIndicator.vue'
import ShortcutsCheatsheet from '../../generation/presentation/ShortcutsCheatsheet.vue'
import { setExtraSparkParts } from '../../generation/composables/useSparkDock'
import { showBeatDock, hideBeatDock } from '../../generation/composables/useBeatDock'
import { ghostActive } from '../../generation/composables/useGhostDraft'
import { useAdaptiveAssist } from '../../generation/composables/useAdaptiveAssist'
import { dispatchCollabEvent } from '../../../composables/collabEventBus'
import { logCollabEvent } from '../../../composables/useCollabTelemetry'
import { useChapterSpine } from '../composables/useChapterSpine'
import { assistEnabled, setAssistEnabled } from '../../generation/composables/useAssistEnabled'
import { chapterEditorHandle } from '../../chapter-editor/editorHandle'
import { setCanonTerms, type CanonTerm } from '../../../extensions/CanonHighlight'
import { loadChapterDraft, clearChapterDraft } from '../../chapter-editor/useChapterDraft'
import { countChapterWords, stripHtmlToText } from '../../../shared/utils/htmlText'
import { formatGenerationError } from '../../../shared/utils/errorText'
import { useGenerationSession } from '../../generation/composables/useGenerationSession'
import { useAppStore } from '../../app/useAppStore'
import { useToast } from '../../../composables/useToast'
import { useConfirmDialog } from '../../../composables/useConfirmDialog'
import { useNotifyPrefs } from '../../../composables/useNotifyPrefs'
import { loadUiPrefs, saveUiPrefs } from '../../../composables/useUiPrefs'
import WorldContextCard from '../presentation/WorldContextCard.vue'
import QuickEventNote from '../presentation/QuickEventNote.vue'
import type { EntityFocusPayload } from '../../../shared/types'
import type { Chapter } from '../../../types'

const route = useRoute()
const router = useRouter()
const store = useAppStore()
const { showToast } = useToast()
const { show: showConfirm } = useConfirmDialog()
const { prefs: notifyPrefs } = useNotifyPrefs()

// 解构 ref 供模板使用
const currentBook = store.currentBook
const chapters = store.chapters
const sortedChapters = store.sortedChapters
const selectedChapterId = store.selectedChapterId
const selectedChapter = store.selectedChapter
const loading = store.loading
const characters = store.characters
const apiConfig = store.apiConfig

const bookIdFromRoute = computed(() => (route.params.bookId as string) || null)
const chapterIdFromRoute = computed(() => (route.params.chapterId as string) || null)

// W2 情境浮卡：编辑器选中文本（1-12 字）/点击 @/# 提及 → 三秒查明底细。
// cursor 事件（光标周边词/选区塌缩）既不触发也不关闭浮卡——任何点击都会塌缩选区
// 并派发 cursor，若据此关闭会把「点击提及/点击卡内按钮」的浮卡一起误杀；
// 关闭职责由浮卡自身的「外点关闭」与「新选区替换」承担。
const contextCardState = ref<EntityFocusPayload | null>(null)
function handleEntityFocus(payload: EntityFocusPayload) {
  if (payload.source === 'cursor') return
  const kw = payload.keyword || ''
  if (payload.source === 'selection' && (!kw || kw.length > 12)) {
    contextCardState.value = null
    return
  }
  if (!kw && !payload.entityId) {
    contextCardState.value = null
    return
  }
  contextCardState.value = payload
}

// V4.x 重构：共享 session（Inspector 和中栏覆盖面板都用同一个）
const session = useGenerationSession()

// NLE-ADF 3.0 自适应辅助层：挂载在 composing 态，驱动 perceive/续写/沉淀/岔路。
// 注入续写函数到 session（键位状态机在 adaptive composing 态调它触发续写）。
const adaptiveAssist = useAdaptiveAssist({
  getChapterId: () => selectedChapterId.value,
  getOutline: () => selectedChapter.value?.outline_text || '',
  suggestionsRef: session.adaptiveSuggestions,
  planSuggestionsRef: session.planSuggestions,
  dynamicBeatsRef: session.dynamicBeats,
  aiLaneRef: session.aiLane,
  authorLaneRef: session.authorLane,
  finishReportRef: session.finishReport,
  settleResultRef: session.settleResult,
  // adaptive 路径失败统一出口：toast 告知（此前全线静默失败，作者按 Space 无反应）
  reportError: (msg: string) => showToast(msg, 'error'),
  reportWarn: (msg: string) => showToast(msg, 'warning'),
})
session.setAdaptiveContinue((mode, parts) => adaptiveAssist.requestContinue(mode, parts))
session.setAdaptiveSettle(() => adaptiveAssist.settleCurrent())
session.setAdaptiveFinish(() => adaptiveAssist.finishChapter())
session.setAdaptiveBurst((card) => adaptiveAssist.requestBurst(card))

// 走向卡舱点选（鼠标路径；数字键路径在 session 键位状态机里走 setAdaptiveBurst）
function onBeatCardPick(card: { event: string; anchors?: string[] } | null) {
  hideBeatDock()
  adaptiveAssist.requestBurst(card)
}
// adaptive composing 态才显示「多写几段」入口（SparkDock props 注入）
const adaptiveComposing = computed(() => session.adaptiveMode.value && session.authorLane.value === 'composing')

// NLE-ADF 3.0 Canon 词高亮词表：本章绑定角色名 + 感知 hints 的角色/伏笔标签
// 词表变化 → setCanonTerms dispatch 空 tr 触发 ProseMirror decorations 重算
const canonMarkTerms = computed<CanonTerm[]>(() => {
  const terms: CanonTerm[] = []
  const seen = new Set<string>()
  const ch = selectedChapter.value as any
  // 本章绑定角色名（chapter.character_ids 过滤）
  const ids: string[] = Array.isArray(ch?.character_ids) ? ch.character_ids : []
  const charList = characters.value as any[] | undefined
  if (ids.length && charList) {
    for (const c of charList) {
      const name = c?.name
      if (name && name.length >= 2 && ids.includes(c?.id) && !seen.has(name)) {
        seen.add(name)
        terms.push({ text: name, kind: 'character' })
      }
    }
  }
  // 感知 hints 的角色/伏笔/矛盾 label（停顿心跳后才来，补充动态词）
  for (const h of session.adaptiveSuggestions.value) {
    if (!h.node_label || h.node_label.length < 2 || seen.has(h.node_label)) continue
    if (h.kind === 'appearance') {
      seen.add(h.node_label)
      terms.push({ text: h.node_label, kind: 'character' })
    } else if (h.kind === 'callback') {
      seen.add(h.node_label)
      terms.push({ text: h.node_label, kind: 'hook' })
    } else if (h.kind === 'contradiction') {
      seen.add(h.node_label)
      terms.push({ text: h.node_label, kind: 'contradiction' })
    }
  }
  return terms
})
// 词表或编辑器实例变化时注入（编辑器后挂载的情况也能补上）
watch([canonMarkTerms, chapterEditorHandle], () => {
  setCanonTerms(chapterEditorHandle.value, canonMarkTerms.value)
})

// ===== 点火路线（冷启动：空章 + 大纲 → AI 写开头）=====
// 正文判空：content_text/draft_text 可能是空 HTML（<p></p>），strip 标签后再 trim
const chapterTextEmpty = computed(() => {
  const ch = selectedChapter.value
  if (!ch) return false
  const raw = (ch.content_text || ch.draft_text || '').replace(/<[^>]*>/g, '').trim()
  return raw.length === 0
})
// 「我自己写」的本章内记忆（切章重置）
const dismissedIgnitionChapterId = ref<string | null>(null)
watch(selectedChapterId, () => { dismissedIgnitionChapterId.value = null })

const showIgnition = computed(() =>
  assistEnabled.value  // AI 辅助关闭（纯手写模式）时不弹点火卡
  && !!selectedChapter.value
  && chapterTextEmpty.value
  && !session.generating.value
  && !ghostActive.value
  && session.aiLane.value === 'dormant'
  && dismissedIgnitionChapterId.value !== selectedChapter.value.id
)

function onIgnite() {
  adaptiveAssist.requestOpening()
}

// 章级谋篇·软脉络（P1.4 M1：复合谋篇卡与副驾谋篇区共享的单例状态）
const chapterSpine = useChapterSpine()
function onIgnitionDismiss() {
  dismissedIgnitionChapterId.value = selectedChapter.value?.id || null
  dispatchCollabEvent('ignition_dismiss')
}
onMounted(() => adaptiveAssist.mount())
onBeforeUnmount(() => adaptiveAssist.unmount())

// 协作埋点桥（P0-3）：展示组件派发的 velluma:collab-event 统一转发后端本地 jsonl
function _onCollabEvent(e: Event) {
  const d = (e as CustomEvent<{ kind: string; detail?: Record<string, unknown> }>).detail
  if (d?.kind) logCollabEvent(selectedChapterId.value, d.kind, d.detail || {})
}
onMounted(() => window.addEventListener('velluma:collab-event', _onCollabEvent as EventListener))
onBeforeUnmount(() => window.removeEventListener('velluma:collab-event', _onCollabEvent as EventListener))

// AI 辅助总开关（顶栏 sparkles 按钮）：关闭=纯手写模式（Space 恢复普通空格）
function toggleAssist() {
  setAssistEnabled(!assistEnabled.value)
  // 关闭时若正处于 adaptive 态，退出辅助层（车道复位，键位拦截随之解除）
  if (!assistEnabled.value && session.adaptiveMode.value) session.exitAdaptive()
  showToast(
    assistEnabled.value ? 'AI 辅助已开启' : 'AI 辅助已关闭：可安静手写，Space 恢复普通空格',
    'info',
  )
}

// 快捷键速查弹层
const showShortcuts = ref(false)

// 画布即事实源：作者写的即真实文档，无生成预览投影（旧预览链已随步进 UI 移除）。

// 保存状态（底栏 + 编辑器标题行显示；实际写库在下方 handleUpdateChapter）
const saveStatus = ref<'idle' | 'saving' | 'saved' | 'error'>('idle')
const lastSavedAt = ref<Date | null>(null)

// 生成/精修失败：统一弹 error toast（技术原文经 formatGenerationError 归类为可读文案）。
// 不再消费后即清空——error 原文需存活到 stage 离开 error（Overlay/Stepper 错误卡据此
// 展示真实原因）；各入口（retry/cancel/startBeat/loadForChapter 等）已负责清空。
watch(() => session.error.value, (err) => {
  if (err) {
    console.error('[生成错误]', err)
    showToast(formatGenerationError(err), 'error')
  }
})

// 生成完成时自动把正文写入章节
// 警示：必须用 oldStage 区分"真正的生成完成"vs"恢复/切章"——
// loadForChapter 恢复快照时会把 stage 设为 'done'（中断态有正文也强制 done），
// 若不过滤 oldStage，每次切回已完成章节/刷新首屏都会重触发 handleGenerated，
// 导致重复写库 + 误弹完成弹窗 + 误发系统通知。
// 真正完成：oldStage 是生成中的状态（非 idle/done）；恢复：oldStage 是 idle/done。
watch(() => session.stage.value, (newStage, oldStage) => {
  if (newStage === 'done' && oldStage !== 'idle' && oldStage !== 'done' && session.streamText.value) {
    handleGenerated(session.streamText.value)
  }
})

// rerender-beat 单段重渲成功后落库（修复"重写本段"结果不进正文的 stub）。
// stage 已是 done、上面的 watch 不会重触发，故由 session.pendingSaveText 信号驱动。
// 非空 = 有新正文待落库；落库后清空信号。
watch(() => session.pendingSaveText.value, async (text) => {
  if (text && selectedChapter.value) {
    try {
      saveStatus.value = 'saving'
      await store.updateChapter(selectedChapter.value.id, { content_text: text, draft_text: text })
      saveStatus.value = 'saved'
      lastSavedAt.value = new Date()
      clearChapterDraft(selectedChapter.value.id)
      showToast('已更新该段正文并保存', 'success')
    } catch (e: any) {
      saveStatus.value = 'error'
      showToast('写入失败：' + e.message, 'error')
    } finally {
      session.pendingSaveText.value = null
    }
  }
})

// 同步路由 bookId 到 store
watch(
  bookIdFromRoute,
  (newBookId) => {
    if (newBookId && newBookId !== store.currentBookId.value) {
      store.selectBook(newBookId)
    } else if (newBookId && store.books.value.length === 0) {
      store.loadBooks().then(() => {
        if (newBookId !== store.currentBookId.value) store.selectBook(newBookId)
      }).catch((e: any) => {
        showToast('加载书籍失败：' + (e?.message || '未知错误'), 'error')
      })
    }
  },
  { immediate: true }
)

// 同步路由 chapterId 到 store
watch(
  chapterIdFromRoute,
  (newChapterId) => {
    if (newChapterId && newChapterId !== store.selectedChapterId.value) {
      store.selectChapter(newChapterId)
    }
  },
  { immediate: true }
)

// store.selectedChapterId 变化时同步回路由
watch(selectedChapterId, (newId) => {
  if (!bookIdFromRoute.value) return
  const currentRouteChapter = chapterIdFromRoute.value
  if (newId !== currentRouteChapter) {
    router.replace({
      name: 'workspace',
      params: { bookId: bookIdFromRoute.value, chapterId: newId || undefined },
    })
  }
})

// 章节切换/进入：恢复该章的上次生成产物（localStorage 持久化）
// immediate=true 确保刷新后首屏即恢复；切章时 loadForChapter 内部会先 persist 旧章
watch(selectedChapterId, (newId) => {
  saveStatus.value = 'idle'
  if (newId) {
    session.loadForChapter(newId)
    void chapterSpine.load(newId)  // 软脉络随章加载（无脉络=null，UI 静默缺席）
  } else {
    chapterSpine.unload()
  }
}, { immediate: true })

// 本地草稿恢复：章节对象可用时检查未落库草稿（保存失败/断网/关窗残留）。
// 与库内正文一致 = 已落库过的残留，静默清除；不一致才弹确认。
watch(() => selectedChapter.value?.id, (newId) => {
  if (newId) void _checkDraftRecovery(newId)
})

async function _checkDraftRecovery(chapterId: string) {
  const draft = loadChapterDraft(chapterId)
  if (!draft) return
  const currentText = stripHtmlToText(selectedChapter.value?.content_text || '').trim()
  if (stripHtmlToText(draft.content).trim() === currentText) {
    clearChapterDraft(chapterId)
    return
  }
  const time = new Date(draft.savedAt).toLocaleString('zh-CN', {
    month: 'numeric', day: 'numeric', hour: '2-digit', minute: '2-digit',
  })
  const ok = await showConfirm({
    title: '发现未保存的草稿',
    message: `本章有一份 ${time} 的本地草稿（上次保存失败或窗口意外关闭时留下的）。`,
    warning: '选择「恢复」将用草稿覆盖本章正文；选择「放弃」将丢弃草稿。',
    confirmText: '恢复草稿',
    cancelText: '放弃',
  })
  if (ok) {
    await handleUpdateChapter(chapterId, { content_text: draft.content, draft_text: draft.content })
  }
  clearChapterDraft(chapterId)
}

// 两栏分栏宽度（持久化数组保持 3 元结构兼容旧 prefs，第三元为历史右栏值不再使用）
const splitSizes = ref<number[]>(loadUiPrefs().splitSizes || [20, 55, 25])
// 警示：splitpanes v4 的 resized 载荷是对象 { event, index, panes: [{min,max,size}] }（v3 才是数组）。
// 且 resized 在 document mouseup 监听器内同步 emit——这里一旦抛异常，库的 mousemove/mouseup
// 监听器永远不会被移除，拖拽会"卡住停不下来"，因此必须容错、绝不能向上抛。
function onResize(payload: { panes?: { size: number }[] }) {
  try {
    const panes = payload?.panes
    if (!Array.isArray(panes)) return
    const next = panes.map((p) => p.size)
    // 防御：splitpanes 偶发返回空数组（两栏布局：binder + 画布）
    if (next.length === 2 && next.every((n) => typeof n === 'number' && n > 0)) {
      splitSizes.value = [next[0], next[1], splitSizes.value[2] ?? 25]
      saveUiPrefs({ ...loadUiPrefs(), splitSizes: splitSizes.value })
    }
  } catch (e) {
    console.error('[Workspace] 保存分栏宽度失败', e)
  }
}

// ============================================================
// NLE-ADF 2.0 画布化：右缘隐形抽屉 + 打字沉浸 + 微观状态栏
// ============================================================
// 抽屉：顶栏按钮 / Ctrl+\ 固定切换；右缘触发条 hover 瞥看；覆盖式（不推挤画布）。
// pinned 态持久化到 uiPrefs（rightDrawerOpen 字段）。
const drawerHover = ref(false)
const drawerPinned = ref(loadUiPrefs().rightDrawerOpen ?? false)
const drawerOpen = computed(() => drawerHover.value || drawerPinned.value)

function toggleDrawerPinned() {
  drawerPinned.value = !drawerPinned.value
  if (drawerPinned.value) drawerHover.value = false
  try {
    saveUiPrefs({ ...loadUiPrefs(), rightDrawerOpen: drawerPinned.value })
  } catch (e) {
    console.error('[Workspace] 保存抽屉固定态失败', e)
  }
}

function _drawerKeyHandler(e: KeyboardEvent) {
  if ((e.ctrlKey || e.metaKey) && e.key === '\\') {
    e.preventDefault()
    toggleDrawerPinned()
  }
}
onMounted(() => window.addEventListener('keydown', _drawerKeyHandler))
onBeforeUnmount(() => window.removeEventListener('keydown', _drawerKeyHandler))

// 完稿审计报告到达时自动滑出抽屉一次（报告在抽屉「审校」tab；作者手动关过则不反复弹）。
// 用 hover 态弹出（不 pin、不推挤画布）。
let _drawerAutoOpened = false
watch(() => session.finishReport.value, (report) => {
  if (report && !_drawerAutoOpened && !drawerOpen.value) {
    drawerHover.value = true
    _drawerAutoOpened = true
  } else if (!report) {
    _drawerAutoOpened = false
  }
})

// 打字沉浸：编辑活动期间顶栏/时间轴降到极低透明度（设计稿"打字时 10%"）。
const isTyping = ref(false)
let _typingTimer: ReturnType<typeof setTimeout> | null = null
function _onTypingActivity() {
  isTyping.value = true
  if (_typingTimer) clearTimeout(_typingTimer)
  _typingTimer = setTimeout(() => { isTyping.value = false }, 1200)
}
watch(chapterEditorHandle, (editor, prev) => {
  prev?.off('update', _onTypingActivity)
  editor?.on('update', _onTypingActivity)
}, { immediate: true })

// 顶栏状态文案：只保留与 adaptive / 精修相关的进行态（旧步进管线各阶段的标签已随其 UI 移除）。
// adaptive 模式下跟随 aiLane；其余时间只在精修/出错时显字，平时留空不打扰。
const nleStateLabel = computed(() => {
  if (session.adaptiveMode.value) {
    switch (session.aiLane.value) {
      case 'perceiving': return '感知中'
      case 'suggesting': return '走向已备好'
      case 'assisting': return '续写中'
      case 'digesting': return '沉淀中'
      case 'analyzing': return '审计中'
      default: return ''
    }
  }
  switch (session.stage.value) {
    case 'refining': return '精修中'
    case 'auditing': return '审校中'
    case 'error': return '生成失败'
    default: return ''
  }
})

// Spark Dock 兜底件已移除：原注入的是角色名（"林尘"），与卡片舱"镜头特写碎片"
// 定位冲突（碎片应是 6-12 字画面，非角色名）。卡片舱现仅显示后端 dock_generator
// 生发的 LLM 灵感碎片（生成时已参考角色/资产/设定 nutrients，不需要前端再注入）。
// 切章时清空旧章残留的挂件缓存。
watch(
  () => selectedChapter.value?.id,
  () => { setExtraSparkParts([]) },
  { immediate: true },
)

// ============================================================
// NLE-ADF 2.0 零门槛冷启动（隐形预生成）
// ============================================================
// 设计契约：作者在新章节直接开写，不需要点任何"生成"按钮——停顿 1.5s 后
// 后台自动起生成管线（Phase 1-4b 与打字并行），拍打开时 Spark Dock 自然亮起。
// 门禁（防误触/防烧调用）：
//   1) 仅"新章开写"场景：载入时正文 < 50 字（既有章节的修订不触发）
//   2) stage=idle 且无进行中任务（已有会话/已完成章节不触发）
//   3) 确有一定量新输入（≥4 字，防载入即触发）
//   4) 每章每次会话至多自动起一次
// NLE-ADF 3.0：作者进章节打字即激活自适应写作模式（取代旧冷启动跑整章管线）。
// 不跑定档/锚点/分镜——只把 authorLane 置 composing，辅助层（useAdaptiveAssist）
// 据此挂载 perceive/续写/沉淀能力。旧 step 路径（startBeat）保留为「规划本章」入口。
let _activatedChapterId: string | null = null

watch(selectedChapter, (ch, prev) => {
  if (ch && ch.id !== prev?.id) {
    _activatedChapterId = null
    // 切章时若在 adaptive 模式，退出（新章需重新激活）
    if (session.adaptiveMode.value) session.exitAdaptive()
  }
}, { immediate: true })

function _onAuthorActivity() {
  if (!assistEnabled.value) return  // AI 辅助关闭：纯手写，不激活 adaptive 辅助层
  const chapterId = selectedChapterId.value
  if (!chapterId) return
  if (_activatedChapterId === chapterId) return  // 已激活
  // 旧管线在跑则不抢（作者主动选了规划模式）
  if (session.generating.value && session.stage.value !== 'idle') return
  const editor = chapterEditorHandle.value
  const typed = editor ? editor.state.doc.textContent.trim().length : 0
  if (typed < 4) return  // 作者刚开始打字，够 4 字才激活（防误触）
  _activatedChapterId = chapterId
  session.enterAdaptive(chapterId)
}
watch(chapterEditorHandle, (editor, prev) => {
  prev?.off('update', _onAuthorActivity)
  editor?.on('update', _onAuthorActivity)
}, { immediate: true })

const chapterEditorRef = ref<any>(null)

async function createChapter() {
  const maxNumber =
    chapters.value.length > 0
      ? Math.max(...chapters.value.map((c) => c.chapter_number))
      : 0
  try {
    await store.createChapter({
      chapter_number: maxNumber + 1,
      chapter_name: `第${maxNumber + 1}章`,
      title: '',
      outline_text: '',
      content_text: '',
      status: 'draft',
    })
    showToast('已新建章节', 'success')
  } catch (e: any) {
    showToast('新建失败：' + e.message, 'error')
  }
}

// Markdown 批量导入章节（复用 import-markdown feature）
const showImportModal = ref(false)
function openImportModal() {
  if (!currentBook.value?.id) {
    showToast('请先选择书籍', 'warning')
    return
  }
  showImportModal.value = true
}

// 正文逆向提取（复用 extraction feature）
const showExtractionModal = ref(false)
function openExtractionModal() {
  if (!selectedChapter.value?.id) {
    showToast('请先选择章节', 'warning')
    return
  }
  showExtractionModal.value = true
}
function onExtractionCompleted() {
  // 刷新章节列表（角色/关联可能已更新）
  store.loadCurrentBookData().catch((e: any) => {
    showToast('刷新书籍数据失败：' + (e?.message || '未知错误'), 'error')
  })
}

// 多选删除章节
const selectMode = ref(false) // 是否处于多选模式
const checkedIds = ref<Set<string>>(new Set()) // 勾选中的章节 ID
const batchDeleting = ref(false)

function toggleSelectMode() {
  selectMode.value = !selectMode.value
  if (!selectMode.value) {
    checkedIds.value.clear()
    lastCheckedId.value = null
  }
}

function exitSelectMode() {
  selectMode.value = false
  checkedIds.value.clear()
  lastCheckedId.value = null
}

// 上次勾选的章节 ID（用于 Shift+点击范围选择）
const lastCheckedId = ref<string | null>(null)

/** 单击章节行的处理（随模式切换行为） */
function handleChapterClick(ch: Chapter, event: MouseEvent | KeyboardEvent) {
  if (selectMode.value) {
    toggleCheck(ch.id, event.shiftKey)
  } else {
    store.selectChapter(ch.id)
  }
}

/** 切换某章的勾选状态；Shift+点击时区间勾选 */
function toggleCheck(id: string, shiftKey: boolean) {
  const ids = sortedChapters.value.map((c) => c.id)
  if (shiftKey && lastCheckedId.value && lastCheckedId.value !== id) {
    // 范围选择：从上次到当前，全部置为「选中」
    const from = ids.indexOf(lastCheckedId.value)
    const to = ids.indexOf(id)
    if (from !== -1 && to !== -1) {
      const [lo, hi] = from < to ? [from, to] : [to, from]
      for (let i = lo; i <= hi; i++) {
        checkedIds.value.add(ids[i])
      }
      // 触发响应式更新（Set mutation 需重新赋值）
      checkedIds.value = new Set(checkedIds.value)
      return
    }
  }
  // 普通切换
  const next = new Set(checkedIds.value)
  if (next.has(id)) next.delete(id)
  else next.add(id)
  checkedIds.value = next
  lastCheckedId.value = id
}

/** 全选 / 取消全选 */
const allChecked = computed(
  () => sortedChapters.value.length > 0 && checkedIds.value.size === sortedChapters.value.length,
)
function toggleCheckAll() {
  if (allChecked.value) {
    checkedIds.value = new Set()
    lastCheckedId.value = null
  } else {
    checkedIds.value = new Set(sortedChapters.value.map((c) => c.id))
    lastCheckedId.value = null
  }
}

/** 批量删除已勾选章节 */
async function batchDeleteChapters() {
  const ids = [...checkedIds.value]
  if (ids.length === 0) return
  const ok = await showConfirm({
    title: '批量删除章节',
    message: `确定删除选中的 ${ids.length} 个章节吗？`,
    warning: '章节正文将一并删除，不可恢复。',
  })
  if (!ok) return
  batchDeleting.value = true
  let okCount = 0
  let failCount = 0
  // 串行删除，避免后端竞态
  for (const id of ids) {
    try {
      await store.deleteChapter(id)
      okCount++
    } catch {
      failCount++
    }
  }
  batchDeleting.value = false
  if (failCount === 0) {
    showToast(`已删除 ${okCount} 章`, 'success')
  } else {
    showToast(`删除 ${okCount} 章成功，${failCount} 章失败`, 'warning')
  }
  exitSelectMode()
}

function backToLibrary() {
  router.push({ name: 'library' })
}

async function handleUpdateChapter(id: string, updates: Record<string, unknown>) {
  saveStatus.value = 'saving'
  try {
    await store.updateChapter(id, updates as any)
    saveStatus.value = 'saved'
    lastSavedAt.value = new Date()
    // 正文落库成功 → 清本地草稿兜底（失败则保留，下次输入自动重试/进章弹恢复）
    if ('content_text' in updates) clearChapterDraft(id)
  } catch (e: any) {
    saveStatus.value = 'error'
    showToast('保存失败：' + e.message + '（内容已存本地草稿，不会丢失）', 'error')
  }
}

function handleRefreshCharacters() {
  store.refreshCharacters().catch((e: any) => {
    showToast('刷新角色失败：' + (e?.message || '未知错误'), 'error')
  })
}

// 生成完成：把正文灌入编辑器（通过 chapterEditorRef）+ 弹完成弹窗
async function handleGenerated(text: string) {
  if (selectedChapter.value && text) {
    try {
      await store.updateChapter(selectedChapter.value.id, { content_text: text, draft_text: text })
      showToast('已生成并写入章节', 'success')
      // 系统通知（受开关控制；主进程会再次判断窗口焦点兜底分层）
      if (notifyPrefs.value.system && window.electronAPI) {
        const isRefinery = session.lastDoneMode.value === 'refinery'
        window.electronAPI.showCompletionNotification({
          title: isRefinery ? '精修完成' : '章节生成完成',
          body: `《${selectedChapter.value.title || selectedChapter.value.chapter_name || '未命名'}》已就绪`,
        })
      }
    } catch (e: any) {
      showToast('写入失败：' + e.message, 'error')
    }
  }
}

// 字数口径：content_text 是富文本 HTML，剥标签后计字符（此前直接 .length 把标签计入，虚高）
const wordCount = computed(() => countChapterWords(selectedChapter.value?.content_text || ''))

// 删除章节（悬停章节行出现入口，确认后调用 store.deleteChapter）
async function confirmDeleteChapter(ch: Chapter) {
  const ok = await showConfirm({
    title: '删除章节',
    message: `确定删除第 ${ch.chapter_number} 章「${ch.title || ch.chapter_name || '未命名'}」吗？`,
    warning: '章节正文将一并删除，不可恢复。',
  })
  if (!ok) return
  try {
    await store.deleteChapter(ch.id)
    showToast('章节已删除', 'success')
  } catch (e: any) {
    showToast('删除章节失败: ' + (e.message || '未知错误'), 'error')
  }
}
</script>

<template>
  <div class="workspace-view" :class="{ 'workspace-view--drawer-pinned': drawerPinned }">
    <Splitpanes class="workspace-split" @resized="onResize">
      <!-- 左栏：章节导航 Binder -->
      <Pane :size="splitSizes[0]" :min-size="14" :max-size="32" class="binder-pane">
        <aside class="binder">
          <div class="binder-header">
            <button class="icon-btn" @click="backToLibrary" title="返回书架">
              <Icon name="arrow-left" :size="15" />
            </button>
            <span class="binder-title" :title="currentBook?.title">{{
              currentBook?.title || '未选择书籍'
            }}</span>
            <button
              class="icon-btn select-toggle"
              :class="{ active: selectMode }"
              :title="selectMode ? '退出多选' : '多选删除'"
              @click="toggleSelectMode"
            >
              <Icon name="check-badge" :size="15" />
            </button>
          </div>

          <!-- 多选模式：全选栏 -->
          <div v-if="selectMode && !loading" class="select-all-bar" @click="toggleCheckAll">
            <span class="select-checkbox" :class="{ checked: allChecked }">
              <Icon v-if="allChecked" name="check" :size="12" />
            </span>
            <span class="select-all-label">全选（{{ checkedIds.size }}/{{ sortedChapters.length }}）</span>
          </div>

          <div v-if="loading" class="binder-loading">加载中…</div>
          <div v-else class="chapter-list">
            <div
              v-for="ch in sortedChapters"
              :key="ch.id"
              class="chapter-item"
              :class="{ active: !selectMode && ch.id === selectedChapterId, checked: selectMode && checkedIds.has(ch.id) }"
              role="button"
              tabindex="0"
              @click="handleChapterClick(ch, $event)"
              @keydown.enter="handleChapterClick(ch, $event)"
            >
              <!-- 多选模式：复选框 -->
              <span v-if="selectMode" class="select-checkbox" :class="{ checked: checkedIds.has(ch.id) }">
                <Icon v-if="checkedIds.has(ch.id)" name="check" :size="12" />
              </span>
              <span class="ch-num">{{ ch.chapter_number }}</span>
              <span class="ch-name">{{ ch.title || ch.chapter_name || '(未命名)' }}</span>
              <ChapterBadges v-if="!selectMode" :chapter="ch" />
              <button
                v-if="!selectMode"
                class="ch-delete"
                title="删除章节"
                @click.stop="confirmDeleteChapter(ch)"
              >
                <Icon name="trash" :size="12" />
              </button>
            </div>
          </div>

          <!-- 多选模式：批量操作栏（替换底部按钮区） -->
          <div v-if="selectMode" class="batch-actions">
            <span class="batch-count">已选 {{ checkedIds.size }} 章</span>
            <div class="batch-btns">
              <button
                class="batch-delete-btn"
                :disabled="checkedIds.size === 0 || batchDeleting"
                @click="batchDeleteChapters"
              >
                <Icon name="trash" :size="14" />
                <span>{{ batchDeleting ? '删除中…' : '删除选中' }}</span>
              </button>
              <button class="batch-cancel-btn" @click="exitSelectMode">
                <span>取消</span>
              </button>
            </div>
          </div>

          <div v-if="!selectMode" class="binder-actions">
            <button class="new-chapter-btn" @click="createChapter">
              <Icon name="plus" :size="14" />
              <span>新建章节</span>
            </button>
            <button class="import-btn" title="从 .md 文件批量导入章节" @click="openImportModal">
              <Icon name="arrow-up-tray" :size="14" />
              <span>导入 .md</span>
            </button>
            <button
              class="analyze-btn"
              title="从当前章节正文逆向提取角色/地点/伏笔等"
              :disabled="!selectedChapter"
              @click="openExtractionModal"
            >
              <Icon name="sparkles" :size="14" />
              <span>分析</span>
            </button>
          </div>
        </aside>
      </Pane>

      <!-- 中栏：编辑器 + 状态栏 -->
      <Pane :size="100 - splitSizes[0]" :min-size="30" class="editor-pane">
        <main class="editor-area">
          <!-- 超薄顶栏：进行态状态文案 + 显性入口三件套（AI 辅助 / 快捷键 / 副驾抽屉）。
               打字时降到 10% 透明（沉浸）；章节名与标题在纸列页面头展示。 -->
          <div
            v-if="selectedChapter"
            class="nle-topbar"
            :class="{ 'nle-topbar--dim': isTyping }"
          >
            <span v-if="nleStateLabel" class="nle-topbar__state">{{ nleStateLabel }}</span>
            <button
              class="nle-topbar__btn"
              :class="{ 'nle-topbar__btn--active': assistEnabled }"
              :title="assistEnabled ? 'AI 辅助已开启（点击关闭：Space 恢复普通空格，停顿感知/卡片舱停用）' : 'AI 辅助已关闭（纯手写模式，点击开启）'"
              @click="toggleAssist"
            >
              <Icon name="sparkles" :size="13" />
            </button>
            <button
              class="nle-topbar__btn"
              title="快捷键一览"
              @click="showShortcuts = true"
            >
              <Icon name="question-mark-circle" :size="13" />
            </button>
            <button
              class="nle-topbar__btn"
              :class="{ 'nle-topbar__btn--active': drawerOpen }"
              title="副驾面板（Ctrl+\ 固定）"
              @click="toggleDrawerPinned"
            >
              <Icon name="panel-right" :size="13" />
            </button>
          </div>
          <!-- 编辑器（复用 ChapterEditorContainer 全套） -->
          <div v-if="selectedChapter" class="editor-host">
            <div class="editor-main">
            <ChapterEditor
              ref="chapterEditorRef"
              :selected-chapter="selectedChapter"
              :characters="characters"
              :api-config="apiConfig"
              :book-id="currentBook?.id"
              :save-status="saveStatus"
              :last-saved-at="lastSavedAt"
              @update-chapter="handleUpdateChapter"
              @refresh-characters="handleRefreshCharacters"
              @editor-entity-focus="handleEntityFocus"
            />
            </div>
            <!-- 左缘感知带：写中常驻，Canon 感知（角色/伏笔/矛盾）；放正文左侧避开右边抽屉 -->
            <PerceptionBand
              v-if="adaptiveComposing"
              :suggestions="session.adaptiveSuggestions.value"
              :spine-progress="chapterSpine.spineProgress.value"
            >
              <template #dock>
                <SparkDock :show-burst-entry="adaptiveComposing" @burst-entry="showBeatDock()" />
              </template>
            </PerceptionBand>

            <!-- W2 情境浮卡（Teleport 到 body；未解析到时组件自行关闭） -->
            <WorldContextCard
              v-if="contextCardState && currentBook?.id && selectedChapterId"
              :key="`${contextCardState.source}:${contextCardState.entityId || contextCardState.keyword}`"
              :book-id="currentBook.id"
              :chapter-id="selectedChapterId"
              :x="contextCardState.x || 0"
              :y="contextCardState.y || 0"
              :keyword="contextCardState.keyword"
              :entity-id="contextCardState.entityId || null"
              :entity-kind="contextCardState.entityKind || null"
              @close="contextCardState = null"
            />

            <!-- W3 速记框（Alt+N / 浮卡「记一笔」唤起；Teleport 模态 + 撤销胶囊） -->
            <QuickEventNote :book-id="currentBook?.id || null" :chapter-id="selectedChapterId" />
          </div>

          <!-- 空状态 -->
          <div v-else class="empty-editor">
            <div class="empty-icon"><Icon name="pencil-square" :size="48" /></div>
            <h2>选择一个章节开始写作</h2>
            <p>从左侧选择章节，或新建一个章节。</p>
            <button class="btn-primary" @click="createChapter">
              <Icon name="plus" :size="15" />
              <span>新建章节</span>
            </button>
          </div>

          <!-- 状态栏 -->
          <footer v-if="selectedChapter" class="status-bar" :class="{ 'status-bar--dim': isTyping }">
            <span>{{ wordCount }} 字</span>
            <span v-if="saveStatus === 'saving'">保存中…</span>
            <span v-else-if="saveStatus === 'saved'" class="muted">已保存</span>
            <span v-else-if="saveStatus === 'error'" class="status-error">保存失败（已存本地草稿）</span>
          </footer>
          <!-- NLE-ADF 灵感悬浮舱（镜头碎片竖排）已迁入右缘感知带 PerceptionBand #dock slot -->
          <!-- NLE-ADF 走向卡舱（Ctrl+Space 唤起：选走向 → burst 段落级连写） -->
          <BeatCardDock @pick="(card) => onBeatCardPick(card)" />
          <!-- NLE-ADF 点火卡 → 复合谋篇卡（P1.4 M1：一句话意图 + AI 谋篇建议 + 点火） -->
          <IgnitionCard
            v-if="showIgnition"
            :has-outline="!!(selectedChapter?.outline_text || '').trim()"
            :spine="chapterSpine.spine.value"
            :suggestions="chapterSpine.spineSuggestions.value"
            :suggesting="chapterSpine.spineSuggesting.value"
            @update-intent="chapterSpine.setIntent"
            @suggest="chapterSpine.suggest"
            @adopt="(part) => chapterSpine.adoptSuggestion(part)"
            @discard-suggestions="chapterSpine.discardSuggestions"
            @ignite="onIgnite"
            @dismiss="onIgnitionDismiss"
          />
          <!-- NLE-ADF 思考指示器（光标处脉冲点；停顿 2s 预览/后端思考中强脉冲） -->
          <ThinkingIndicator />
          <!-- 快捷键速查弹层（顶栏 ? 按钮触发） -->
          <ShortcutsCheatsheet v-if="showShortcuts" @close="showShortcuts = false" />
        </main>
      </Pane>

    </Splitpanes>

    <!-- NLE-ADF 2.0 右缘隐形抽屉：hover 触发条滑出 / Ctrl+\ 固定（覆盖式不推画布） -->
    <div
      class="drawer-edge"
      :class="{ 'drawer-edge--active': drawerOpen }"
      title="副驾抽屉（Ctrl+\ 固定）"
      @mouseenter="drawerHover = true"
    ></div>
    <Transition name="inspector-drawer">
      <aside
        v-if="drawerOpen"
        class="inspector-drawer"
        @mouseleave="drawerHover = false"
      >
        <InspectorPanel :external-session="session" />
      </aside>
    </Transition>

    <!-- Markdown 批量导入 Modal -->
    <MarkdownImportModal v-if="showImportModal" @close="showImportModal = false" />

    <!-- 正文逆向提取 Modal -->
    <ExtractionModal
      v-if="showExtractionModal && selectedChapter"
      :chapter-id="selectedChapter.id"
      @close="showExtractionModal = false"
      @completed="onExtractionCompleted"
    />
  </div>
</template>

<style scoped>
.workspace-view {
  width: 100%;
  height: 100%;
  overflow: hidden;
  background: var(--bg-primary);
  /* 抽屉固定（Ctrl+\）时推挤内容区：编辑列在剩余空间重新居中，过渡与抽屉滑入同速 */
  transition: padding-right 0.22s ease;
}

/* 推挤量与 .inspector-drawer 宽度同一公式（width:380px; max-width:44vw）。
   仅 pinned 推挤——hover 瞥看仍是覆盖式，避免鼠标划过右缘时内容反复重排。 */
.workspace-view--drawer-pinned {
  padding-right: min(380px, 44vw);
}

.workspace-split {
  height: 100%;
}

/* splitpanes 主题适配 */
.workspace-split :deep(.splitpanes__splitter) {
  background: var(--border-color);
  position: relative;
}
.workspace-split :deep(.splitpanes__splitter::before) {
  content: '';
  position: absolute;
  left: 0;
  top: 0;
  right: 0;
  bottom: 0;
  background: transparent;
  transition: background 0.15s ease;
}
.workspace-split :deep(.splitpanes__splitter:hover::before) {
  background: var(--accent-500);
  opacity: 0.2;
}

/* Binder */
.binder {
  display: flex;
  flex-direction: column;
  height: 100%;
  background: var(--bg-secondary);
  overflow: hidden;
}

.binder-header {
  display: flex;
  align-items: center;
  gap: 0.375rem;
  padding: 0.5rem 0.625rem;
  border-bottom: 1px solid var(--border-color);
}

.binder-title {
  flex: 1;
  font-size: 0.8125rem;
  font-weight: 600;
  color: var(--text-primary);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.icon-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 1.5rem;
  height: 1.5rem;
  background: transparent;
  border: none;
  border-radius: 0.25rem;
  color: var(--text-secondary);
  cursor: pointer;
  transition: all 0.15s ease;
}
.icon-btn:hover {
  background: var(--hover-bg);
  color: var(--text-primary);
}

.binder-loading {
  padding: 1rem;
  font-size: 0.75rem;
  color: var(--text-muted);
  text-align: center;
}

.chapter-list {
  flex: 1;
  overflow-y: auto;
  padding: 0.375rem;
  display: flex;
  flex-direction: column;
  gap: 0.125rem;
}

.chapter-item {
  display: flex;
  align-items: center;
  gap: 0.375rem;
  width: 100%;
  padding: 0.4375rem 0.5rem;
  background: transparent;
  border: none;
  border-radius: 0.25rem;
  text-align: left;
  cursor: pointer;
  transition: background 0.15s ease;
}

.chapter-item:hover {
  background: var(--hover-bg);
}

.chapter-item.active {
  background: var(--hover-bg);
}

.chapter-item.checked {
  background: rgba(var(--accent-500-rgb, 124, 58, 237), 0.08);
}

.select-toggle.active {
  color: var(--accent-500);
  background: rgba(var(--accent-500-rgb, 124, 58, 237), 0.1);
}

/* 多选：全选栏 */
.select-all-bar {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  padding: 0.4375rem 0.625rem;
  border-bottom: 1px solid var(--border-color);
  font-size: 0.75rem;
  color: var(--text-secondary);
  cursor: pointer;
  flex-shrink: 0;
  transition: background 0.15s ease;
}

.select-all-bar:hover {
  background: var(--hover-bg);
}

.select-all-label {
  user-select: none;
}

/* 复选框（全选栏和章节行共用） */
.select-checkbox {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 1rem;
  height: 1rem;
  border: 1.5px solid var(--border-color);
  border-radius: 0.1875rem;
  background: var(--bg-canvas);
  color: white;
  flex-shrink: 0;
  transition: all 0.15s ease;
}

.select-checkbox.checked {
  border-color: var(--accent-500);
  background: var(--accent-500);
}

/* 多选：批量操作栏 */
.batch-actions {
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
  padding: 0.75rem;
  border-top: 1px solid var(--border-color);
  background: var(--bg-tertiary);
  flex-shrink: 0;
}

.batch-count {
  font-size: 0.75rem;
  color: var(--text-secondary);
  text-align: center;
}

.batch-btns {
  display: flex;
  gap: 0.375rem;
}

.batch-delete-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 0.375rem;
  flex: 1;
  padding: 0.4375rem;
  background: #dc2626;
  color: white;
  border: none;
  border-radius: 0.25rem;
  font-size: 0.75rem;
  cursor: pointer;
  transition: background 0.15s ease;
}

.batch-delete-btn:hover:not(:disabled) {
  background: #b91c1c;
}

.batch-delete-btn:disabled {
  opacity: 0.4;
  cursor: not-allowed;
}

.batch-cancel-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  padding: 0.4375rem 0.75rem;
  background: transparent;
  color: var(--text-secondary);
  border: 1px solid var(--border-color);
  border-radius: 0.25rem;
  font-size: 0.75rem;
  cursor: pointer;
  transition: all 0.15s ease;
}

.batch-cancel-btn:hover {
  background: var(--hover-bg);
  color: var(--text-primary);
}

.ch-num {
  font-size: 0.6875rem;
  color: var(--text-muted);
  font-variant-numeric: tabular-nums;
  flex-shrink: 0;
  min-width: 1.25rem;
}

.ch-delete {
  flex-shrink: 0;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 1.25rem;
  height: 1.25rem;
  padding: 0;
  background: transparent;
  border: none;
  border-radius: 0.25rem;
  color: var(--text-muted);
  cursor: pointer;
  opacity: 0;
  transition: opacity 0.15s ease, color 0.15s ease, background 0.15s ease;
}

.chapter-item:hover .ch-delete {
  opacity: 1;
}

.ch-delete:hover {
  color: #dc2626;
  background: rgba(220, 38, 38, 0.08);
}

.chapter-item.active .ch-num {
  color: var(--accent-500);
  font-weight: 600;
}

.ch-name {
  flex: 1;
  font-size: 0.75rem;
  color: var(--text-primary);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.chapter-item.active .ch-name {
  color: var(--accent-500);
  font-weight: 500;
}

.binder-actions {
  display: flex;
  gap: 0.25rem;
  margin: 0.375rem;
  flex-shrink: 0;
}

.new-chapter-btn,
.import-btn,
.analyze-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 0.375rem;
  flex: 1;
  padding: 0.4375rem;
  background: transparent;
  border: 1px dashed var(--border-color);
  border-radius: 0.25rem;
  font-size: 0.75rem;
  color: var(--text-secondary);
  cursor: pointer;
  transition: all 0.15s ease;
}

.new-chapter-btn:hover {
  border-color: var(--accent-500);
  color: var(--accent-500);
}

.import-btn:hover {
  border-color: var(--accent-500);
  color: var(--accent-500);
}

.analyze-btn:hover:not(:disabled) {
  border-color: var(--accent-500);
  color: var(--accent-500);
}

.analyze-btn:disabled {
  opacity: 0.4;
  cursor: not-allowed;
}

/* 中栏 */
.editor-area {
  display: flex;
  flex-direction: column;
  height: 100%;
  background: var(--bg-primary);
  overflow: hidden;
  /* 点火卡 absolute 居中的定位锚（teleport 到 body 的浮层不受影响） */
  position: relative;
}

.editor-host {
  flex: 1;
  display: flex;
  flex-direction: row; /* 正文主区 + 右缘感知带并列 */
  overflow: hidden;
  min-height: 0;
  position: relative;
}

/* 正文主区（ChapterEditor）；感知带在其右侧并列 */
.editor-main {
  flex: 0 1 auto;
  max-width: 60rem;
  margin: 0 auto;
  min-width: 0;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  position: relative;
}

/* 空状态 */
.empty-editor {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  color: var(--text-muted);
  text-align: center;
  padding: 2rem;
}

.empty-icon {
  margin-bottom: 1rem;
  opacity: 0.7;
}

.empty-editor h2 {
  font-family: var(--font-heading);
  font-size: 1.0625rem;
  font-weight: 500;
  color: var(--text-secondary);
  margin: 0 0 0.375rem;
}

.empty-editor p {
  font-size: 0.8125rem;
  margin: 0 0 1.25rem;
}

.btn-primary {
  display: inline-flex;
  align-items: center;
  gap: 0.375rem;
  padding: 0.4375rem 0.875rem;
  font-size: 0.8125rem;
  font-weight: 500;
  background: var(--accent-500);
  color: white;
  border: none;
  border-radius: 0.375rem;
  cursor: pointer;
  transition: background 0.15s ease;
}
.btn-primary:hover {
  background: var(--accent-600);
}

/* 状态栏 */
.status-bar {
  flex-shrink: 0;
  display: flex;
  align-items: center;
  gap: 0.75rem;
  padding: 0.25rem 0.875rem;
  background: var(--bg-tertiary);
  border-top: 1px solid var(--border-color);
  font-size: 0.6875rem;
  color: var(--text-muted);
  font-variant-numeric: tabular-nums;
}

.status-bar .active {
  color: var(--accent-500);
}

.status-bar .muted {
  opacity: 0.7;
}

.status-bar .status-error {
  color: #dc2626;
}

/* 顶栏显性入口按钮（AI 辅助开关 / 快捷键 / 副驾抽屉） */
.nle-topbar__btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 1.375rem;
  height: 1.375rem;
  background: transparent;
  border: none;
  border-radius: 0.25rem;
  color: var(--text-muted);
  cursor: pointer;
  transition: all 0.15s ease;
}
.nle-topbar__btn:hover {
  background: var(--hover-bg);
  color: var(--text-primary);
}
.nle-topbar__btn--active {
  color: var(--accent-500);
}
/* 状态文案缺席时把按钮组推到右侧 */
.nle-topbar__btn:first-of-type {
  margin-left: auto;
}
</style>
