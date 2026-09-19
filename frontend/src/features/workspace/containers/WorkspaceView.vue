<script setup lang="ts">
/**
 * 写作台（08 期「桌上一张纸」完全重构，docs/design/ux-redesign/08-writing-desk-total-redesign.md）。
 *
 * 布局：纸列（ChapterEditorContainer）是唯一常驻主角——
 * - 左边是书：左缘书签（ChapterSpine）点开目录抽屉（ChapterTocDrawer）；
 *   无选中章时纸面本体即目录页（TocPage）
 * - 右边是 AI：右缘助手栏（AssistRail，点击制）+ 浮出助手面板（InspectorPanel 单分区壳）
 * - 中间是我：纸面上只有我写的，与 AI 递到手边的（光标层卡舱 / 纸左页边批注点）
 */
import { ref, watch, computed, nextTick, onMounted, onBeforeUnmount } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import ChapterEditor from '../../../components/ChapterEditor.vue'
import PerceptionBand from '../presentation/PerceptionBand.vue'
import ChapterSpine from '../presentation/ChapterSpine.vue'
import ChapterTocDrawer from '../presentation/ChapterTocDrawer.vue'
import TocPage from '../presentation/TocPage.vue'
import AssistRail from '../presentation/AssistRail.vue'
import MarkdownImportModal from '../../import-markdown/containers/MarkdownImportModal.vue'
import ExtractionModal from '../../extraction/containers/ExtractionModal.vue'
import InspectorPanel from './InspectorPanel.vue'
import CursorLayer from '../../generation/presentation/CursorLayer.vue'
import BeatCardDock from '../../generation/presentation/BeatCardDock.vue'
import IgnitionCard from '../../generation/presentation/IgnitionCard.vue'
import ThinkingIndicator from '../../generation/presentation/ThinkingIndicator.vue'
import ShortcutsCheatsheet from '../../generation/presentation/ShortcutsCheatsheet.vue'
import { setExtraSparkParts, setSparkParts, setSparkGuests, setSparkSticky, stashSparkDock, stashGuestReturn, takeGuestReturn, getSparkPartsChapterId } from '../../generation/composables/useSparkDock'
import { hideBeatDock } from '../../generation/composables/useBeatDock'
import { ghostActive, ghostWash, useGhostOriginal, setGhostPairContext } from '../../generation/composables/useGhostDraft'
import { finalizeGhostPairs } from '../../generation/composables/useGhostPairTracker'
import { useAdaptiveAssist } from '../../generation/composables/useAdaptiveAssist'
import { dispatchCollabEvent } from '../../../composables/collabEventBus'
import { logCollabEvent } from '../../../composables/useCollabTelemetry'
import { adaptiveApi } from '../../../services/api/domain/adaptive.api'
import { styleApi } from '../../../services/api'
import { useChapterSpine } from '../composables/useChapterSpine'
import { assistEnabled, setAssistEnabled } from '../../generation/composables/useAssistEnabled'
import { chapterEditorHandle } from '../../chapter-editor/editorHandle'
import { trackChapterSave } from '../../chapter-editor/pendingSave'
import { setCanonTerms, type CanonTerm } from '../../../extensions/CanonHighlight'
import { bindInlineDockBridge } from '../../../extensions/InlineDock'
import { loadChapterDraft, clearChapterDraft } from '../../chapter-editor/useChapterDraft'
import { countChapterWords, stripHtmlToText } from '../../../shared/utils/htmlText'
import { formatGenerationError } from '../../../shared/utils/errorText'
import { useGenerationSession } from '../../generation/composables/useGenerationSession'
import { useAppStore } from '../../app/useAppStore'
import { useToast } from '../../../composables/useToast'
import { useConfirmDialog } from '../../../composables/useConfirmDialog'
import { loadUiPrefs, saveUiPrefs } from '../../../composables/useUiPrefs'
import { useEscStack } from '../../../composables/useEscStack'
import WorldContextCard from '../presentation/WorldContextCard.vue'
import QuickEventNote from '../presentation/QuickEventNote.vue'
import { OPEN_INBOX_EVENT, requestOpenInbox } from '../../world/composables/batchAccept'
import type { EntityFocusPayload } from '../../../shared/types'
import type { Chapter } from '../../../types'

const route = useRoute()
const router = useRouter()
const store = useAppStore()
const { showToast } = useToast()
const { show: showConfirm } = useConfirmDialog()

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
  // A5d 沉淀直达：settle 抽出候选 → toast 带 action，一键滑出副驾收件箱
  onCandidatesCreated: (n: number) => {
    showToast(`AI 从正文里发现 ${n} 条世界变化，待你确认`, 'info', 6000, {
      label: '去确认',
      onClick: () => requestOpenInbox(),
    })
  },
})
session.setAdaptiveContinue((mode, parts) => adaptiveAssist.requestContinue(mode, parts))
session.setAdaptiveSettle(() => adaptiveAssist.settleCurrent())
session.setAdaptiveFinish(() => adaptiveAssist.finishChapter())
session.setAdaptiveBurst((card) => adaptiveAssist.requestBurst(card))
// 03 三键「未灌完不上膛」：流式期间按键只打断不采纳——中止在飞 SSE
session.setAdaptiveAbort(() => adaptiveAssist.abortInflight())
// 卡片舱第 5 槽位·自定义镜头（第二冲程 2026-09-09）：作者一句话镜头 → 复用
// 同一条 stitch 微缝合流水线（50 字级单镜头，slot=custom 不挂视点锁——
// 作者亲笔的镜头描述本身就是契约，加锁反而可能与之矛盾）；同款 sticky+stash
// 收舱让位幽灵
function onDockCustomStitch(text: string) {
  if (ghostActive.value) return
  setSparkSticky()
  stashSparkDock()
  adaptiveAssist.requestContinue('stitch', [{ text, slot: 'custom' }])
}

// 临时在场角色建档往返（2026-09-09 涌现角色闭环）：暂存光标（SPA 模块单例，
// 无序列化无 origin 漂移）→ 世界页预填新建卡（create_entity 深链）→ 保存或
// 返回本章（from=chapter 既有返程）→ 编辑器就绪后弹射回原光标。
function onGuestRegister(name: string) {
  const chapterId = selectedChapterId.value
  const editor = chapterEditorHandle.value
  if (!chapterId || !editor) return
  const $from = editor.state.selection.$from
  stashGuestReturn(
    chapterId,
    $from.pos,
    editor.state.doc.textBetween(Math.max(0, $from.pos - 20), $from.pos, '') || '',
  )
  router.push({
    name: 'world',
    params: { bookId: String(route.params.bookId) },
    query: {
      create_entity: name,
      from: 'chapter',
      chapter: chapterId,
    },
  })
}

// 行间推挤卡舱的事件桥（2026-09-09 布局重构）：SparkDock 现居 ProseMirror
// WidgetDecoration（InlineDock.ts），不再经 CursorLayer props/emits 透传——
// 模块单例桥随挂载绑定，换书/重挂自动覆盖
onMounted(() => {
  bindInlineDockBridge({
    customStitch: onDockCustomStitch,
    guestRegister: onGuestRegister,
  })
})

// 建档返程弹射（2026-09-09）：编辑器句柄就绪且有当章往返单例 → 恢复光标。
// 韧性防线：pos 按当前文档长度钳位（离开期间自动保存可能改长度）；段头
// 指纹失配（内容被改）退文档尾——宁可落在末尾也不错位到句中
watch(chapterEditorHandle, (editor) => {
  if (!editor) return
  const trip = takeGuestReturn()
  if (!trip || trip.chapterId !== selectedChapterId.value) return
  void nextTick(() => {
    try {
      const size = editor.state.doc.content.size
      let pos = Math.max(0, Math.min(trip.pos, size))
      const head = editor.state.doc.textBetween(Math.max(0, pos - 20), pos, '') || ''
      if (trip.paraHead && head !== trip.paraHead) pos = size   // 内容漂移：退文档尾
      editor.chain().focus().setTextSelection(pos).run()
    } catch { /* 恢复失败静默——落默认光标即可 */ }
  })
})
// Tab 无缓存零件时的即点取件：未激活章节先激活（Tab 是显式召唤，等同打字意图）再取件
session.setAdaptiveSummon((forceRefresh?: boolean) => {
  const chapterId = selectedChapterId.value
  if (!chapterId) return
  _activateChapterAssist(chapterId)
  adaptiveAssist.summonParts(forceRefresh)
})

// 走向卡舱点选（鼠标路径；数字键路径在 session 键位状态机里走 setAdaptiveBurst）
function onBeatCardPick(card: { event: string; anchors?: string[]; serves_anchor?: string; is_branch?: boolean } | null) {
  hideBeatDock()
  // M3 作者声明岔路：选向即决岔——清除该锚点的岔路标记（岔路是一次性抉择）
  if (card?.is_branch && card.serves_anchor) {
    chapterSpine.updateAnchor(card.serves_anchor, { branch: undefined })
  }
  adaptiveAssist.requestBurst(card)
}
// 感知带挂载条件（2026-09-04 审计修复）：ghostStitching 态也要带在——疑点条/
// 洗层条/返修条挂在带内 #dock 槽，数据恰在幽灵在屏期间（GHOST_DONE）灌入；
// 旧条件严格 ==='composing' 使整带在幽灵落屏瞬间卸载，三条 UI 恒不可见
// （违背模板内「挂件舱自身隐藏，此位恰好空出」的设计意图）。SparkDock 自身
// 的 v-if="visible && !ghostActive" 已负责舱内避让，burst 入口仍吃原义。
const adaptiveActive = computed(() => session.adaptiveMode.value && session.authorLane.value !== 'idle')

// 学着闭嘴（2026-08-25 战略定稿）：感知带 × 收起——本地即时摘除该条 +
// hint_dismiss 埋点（后端累计同类别 ≥3 次即静音，可在副驾收件箱恢复；
// 安全类泄露/矛盾不出 ×，由 PerceptionBand 白名单保证）
function onDismissHint(payload: { kind: string; label: string }) {
  session.adaptiveSuggestions.value = session.adaptiveSuggestions.value.filter(
    (h: any) => !(h.kind === payload.kind && h.node_label === payload.label),
  )
  dispatchCollabEvent('hint_dismiss', { kind: payload.kind, label: payload.label })
}

// 「用原稿」（呈现平面 P1 可逆学习）：重灌洗前原稿 + 对每个已替换命中调降级
// 端点（blocker→warning）——作者一次肯定胜过三次否定，此书此后不再自动替换这些词
async function onUseGhostOriginal() {
  if (!useGhostOriginal()) return
  const bookId = currentBook.value?.id
  if (bookId) {
    const patterns = [...new Set(ghostWash.value.hits.filter((h) => h.replaced).map((h) => h.pattern))]
    for (const p of patterns) {
      try { await styleApi.washPreferOriginal(bookId, p) } catch { /* 降级失败不阻塞 */ }
    }
  }
  showToast('已恢复 AI 原稿，这些词以后只提醒不替换', 'info')
}

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
      // note 带矛盾详情 → 红条/玫红下划线悬停 title（2026-08-28：红条无解释被当 bug）
      terms.push({ text: h.node_label, kind: 'contradiction', note: h.detail || '' })
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
}
onMounted(() => adaptiveAssist.mount())
// 感知常驻（2026-08-29 用户拍板）：切页只 detach（解除编辑器监听/中止需要
// 活编辑器的 SSE），pending 感知计时器与舱内零件保留——感知只随应用关闭停机
onBeforeUnmount(() => adaptiveAssist.detach())

// 协作埋点桥（P0-3 → 05 瘦身后仅机制事件走此路：hint_dismiss / ghost_adopt /
// ghost_discard / ghost_discard_reason）：展示组件派发的 velluma:collab-event
// 统一转发后端本地 jsonl（机制消费方见 events.py 词表）
function _onCollabEvent(e: Event) {
  const d = (e as CustomEvent<{ kind: string; detail?: Record<string, unknown> }>).detail
  if (d?.kind) logCollabEvent(selectedChapterId.value, d.kind, d.detail || {})
}
onMounted(() => window.addEventListener('velluma:collab-event', _onCollabEvent as EventListener))
onBeforeUnmount(() => window.removeEventListener('velluma:collab-event', _onCollabEvent as EventListener))

// ---- 问书（04 下一阶段）：?? 手势 → /adaptive/ask-book → 答案回投行间胶囊 ----
// 容器只做编排（调 API + 回投事件）；呈现与出处点验在 AskNoteChip
async function _onAskBook(e: Event) {
  const d = (e as CustomEvent<{ question: string; noteId: string }>).detail
  const chId = selectedChapterId.value
  if (!d?.question || !chId) return
  let answer: import('../../../services/api/domain/adaptive.api').AskBookAnswer
  try {
    answer = await adaptiveApi.askBook(chId, d.question)
  } catch {
    answer = { kind: 'not_found', text: '没查到——问书服务没应上，稍后再试。', sources: [] }
  }
  window.dispatchEvent(new CustomEvent('velluma:ask-book-answer', {
    detail: { noteId: d.noteId, answer },
  }))
}
// 出处点验（唯一的跳走动作，只发生在作者主动点击）：章 → 就地切章；世界对象 → 深链世界页
function _onAskSource(e: Event) {
  const d = (e as CustomEvent<{ source: Record<string, string> }>).detail
  const s = d?.source
  if (!s) return
  if (s.type === 'chapter' && s.chapter_id) {
    store.selectChapter(s.chapter_id)
    return
  }
  const bookId = currentBook.value?.id
  if (!bookId) return
  const query: Record<string, string> = { from: 'chapter' }
  if (s.type === 'location' && s.location_id) query.loc = s.location_id
  else if (s.type === 'foreshadow' && s.ledger_key) query.fs = s.ledger_key
  else if (s.type === 'canon') query.panel = 'canon'
  else return
  router.push({ path: `/world/${bookId}`, query })
}
onMounted(() => {
  window.addEventListener('velluma:ask-book', _onAskBook as EventListener)
  window.addEventListener('velluma:ask-source', _onAskSource as EventListener)
})
onBeforeUnmount(() => {
  window.removeEventListener('velluma:ask-book', _onAskBook as EventListener)
  window.removeEventListener('velluma:ask-source', _onAskSource as EventListener)
})

// AI 辅助总开关（顶栏 sparkles 按钮）：关闭=纯手写模式（Space 恢复普通空格）
function toggleAssist() {
  setAssistEnabled(!assistEnabled.value)
  // 关闭时若正处于 adaptive 态，退出辅助层（车道复位，键位拦截随之解除）
  if (!assistEnabled.value && session.adaptiveMode.value) {
    // 在飞 stitch 流一并中止（2026-09-04 审计修复）：否则迟到的幽灵灌入已停用辅助的画布
    adaptiveAssist.abortInflight()
    session.exitAdaptive()
  }
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
// 展示真实原因）；各入口（retry/cancel/loadForChapter 等）已负责清空。
watch(() => session.error.value, (err) => {
  if (err) {
    console.error('[生成错误]', err)
    showToast(formatGenerationError(err), 'error')
  }
})

// 【已拔除 2026-09-12】stage='done' → 整章覆写监听随 Refinery 退役（本注释即档案）：
// 它是「未过目抛光稿直灌画布（noHistory 不可撤销）+ 跨章覆写」风险链的前端入口
// （docs/post-writing-checks-audit.md §3.5）；stage 的 done 写入点已随 confirmRefinery
// 一并消失，本监听成为不可达死代码。

// 旧 rerender-beat 落库 watch 已随 BS-ADF 步进链路归档移除（2026-08-29）

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
    } else if (!newChapterId && store.selectedChapterId.value) {
      // 08 期态A 双向一致：路由无章号 = 回目录页（浏览器后退/深链去章号可达）
      store.selectChapter(null)
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
watch(selectedChapterId, (newId, oldId) => {
  saveStatus.value = 'idle'
  if (newId) {
    session.loadForChapter(newId)
    void chapterSpine.load(newId)  // 软脉络随章加载（无脉络=null，UI 静默缺席）
  } else {
    chapterSpine.unload()
  }
  // 03 下一阶段 M1：书签寿命=整个章节会话——切章定稿（读旧章两书签间现文，
  // 有改动自动成对 + 聚合提示/按批撤销），再换上下文到新章
  if (oldId && oldId !== newId) {
    const editor = chapterEditorHandle.value
    const bookId = currentBook.value?.id || null
    if (editor) {
      void finalizeGhostPairs(oldId, bookId, (from, to) =>
        editor.state.doc.textBetween(Math.min(from, editor.state.doc.content.size), Math.min(to, editor.state.doc.content.size), '\n\n'))
    }
  }
  setGhostPairContext(newId)
  // 系统自己去读（2026-08-25 战略定稿）：离开一章即发枪——后端哈希幂等闸
  // 保证「没变不读/太短不读/超预算不读」，前端无需跟踪内容变化，静默失败不打扰
  if (oldId && oldId !== newId) {
    void adaptiveApi.autoRead(oldId).catch(() => {})
  }
  // 回场补读（02 候选回流修缮 M4）：进章也发枪——覆盖「应用关闭前未切章导致
  // 整章未读」的盲区（离开触发从未发生）。哈希幂等闸照旧兜底：读过且内容
  // 没变 → 后端 unchanged 秒回零成本；预算闸（间隔/每日上限）行为不变
  if (newId) {
    void adaptiveApi.autoRead(newId).catch(() => {})
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

// ============================================================
// 08 期「桌上一张纸」：目录抽屉 + 右缘助手栏/面板 + 打字沉浸
// ============================================================
// 目录抽屉（binder 转世）：左缘书签点开，选章即收（秒级任务，无 pin）。
const tocOpen = ref(false)

/** 左缘书签竖排标识：「第3章 · 雨夜来客」（截断在 ChapterSpine 内） */
const spineChapterLabel = computed(() => {
  const ch = selectedChapter.value
  if (!ch) return ''
  const name = ch.title || ch.chapter_name || ''
  // 章节名仍是自动档「第N章」时不重复（否则签上会读出「第2章 · 第2章」）
  return name && name !== `第${ch.chapter_number}章` ? `第${ch.chapter_number}章 · ${name}` : `第${ch.chapter_number}章`
})

/** 抽屉选章：多选模式下走勾选不收抽屉；普通模式切章即收（完成使命即收） */
function onTocSelect(ch: Chapter, ev: MouseEvent | KeyboardEvent) {
  handleChapterClick(ch, ev)
  if (!selectMode.value) tocOpen.value = false
}

// 助手面板（右缘栏点击开合，世界页「栏—面板」同构）：覆盖式不推纸；
// pin 态推挤继承既有语义，持久化沿用 uiPrefs.rightDrawerOpen 键（语义=钉住）。
// 钉住态跨会话恢复即开着（HEAD rightDrawerOpen 同义）。
const assistPinned = ref(loadUiPrefs().rightDrawerOpen ?? false)
const assistPanelOpen = ref(assistPinned.value)
/** 面板当前分区；null = 下次打开时由 InspectorPanel 按章节状态取默认 */
const activeTab = ref<'planning' | 'now' | 'review' | 'debug' | null>(null)
/** 完稿报告到达且尚未看过 → 栏上「检查」朱点 */
const reportUnread = ref(false)
const assistPanelEl = ref<HTMLElement | null>(null)

function _persistPinned(v: boolean) {
  try {
    saveUiPrefs({ ...loadUiPrefs(), rightDrawerOpen: v })
  } catch (e) {
    console.error('[Workspace] 保存面板固定态失败', e)
  }
}

/** 关闭面板：任何关闭路径都同时解 pin（pin 而不开 = 推挤残留） */
function closeAssistPanel() {
  assistPanelOpen.value = false
  if (assistPinned.value) {
    assistPinned.value = false
    _persistPinned(false)
  }
}

/** 面板头 pin 钮：开着的面板切 pin 态 */
function togglePanelPinned() {
  assistPinned.value = !assistPinned.value
  _persistPinned(assistPinned.value)
}

/** 栏点击分区：再点同区收；否则定位 + 开 */
function onRailSelectTab(tab: string) {
  if (assistPanelOpen.value && activeTab.value === tab) {
    closeAssistPanel()
    return
  }
  activeTab.value = tab as typeof activeTab.value
  assistPanelOpen.value = true
}

/** InspectorPanel 内 Ctrl+1~4 切区时同步开面板（面板开着时监听才挂，此处兜底语义） */
function onPanelActivate(tab: 'planning' | 'now' | 'review' | 'debug') {
  activeTab.value = tab
  assistPanelOpen.value = true
}

// Esc 细则（§4.6）：面板开在 window 层注册 useEscStack；焦点位于 input/textarea/
// 面板内可编辑区时不收（SpinePanel 内联编辑自带 Esc 语义，防一按两收）；
// 钉住的面板 Esc 不收（Ctrl+\ 或 × 收）。幽灵蒸发在更早注册的 session 捕获层
// 先行消费（EscStack 对 defaultPrevented 让位），逐层剥皮顺序不变。
const { push: _pushPanelEsc, remove: _removePanelEsc } = useEscStack()
let _panelEscId: symbol | null = null

function _escClosePanel() {
  if (assistPinned.value) return
  const ae = document.activeElement as HTMLElement | null
  if (ae && (ae.tagName === 'INPUT' || ae.tagName === 'TEXTAREA')) return
  if (ae?.isContentEditable && assistPanelEl.value?.contains(ae)) return
  assistPanelOpen.value = false
}

watch(assistPanelOpen, (open) => {
  if (open) {
    if (!_panelEscId) _panelEscId = _pushPanelEsc(_escClosePanel, 'assist-panel')
  } else if (_panelEscId) {
    _removePanelEsc(_panelEscId)
    _panelEscId = null
  }
})

// 外点收（未 pin 时）：点在面板/右缘栏之外且落在桌面区内——模态经 teleport 在
// 桌面区外（可能由面板内容唤起），不误收。
function _onDocPointerDownPanel(e: PointerEvent) {
  if (!assistPanelOpen.value || assistPinned.value) return
  const t = e.target as HTMLElement | null
  if (!t) return
  if (assistPanelEl.value && t instanceof Node && assistPanelEl.value.contains(t)) return
  if (t.closest?.('.assist-rail')) return
  if (!t.closest?.('.workspace-view')) return
  assistPanelOpen.value = false
}

// Ctrl+\ 三态：关 → 开并 pin / 开未 pin → pin / 已 pin → 收并解 pin。
// Ctrl+1~4：面板关时按键 = 开 + 定位（面板开时 InspectorPanel 自身监听切区，
// 两条路汇于同一 activeTab 状态，无双源）。
const PANEL_TAB_ORDER = ['planning', 'now', 'review', 'debug'] as const

function _panelKeyHandler(e: KeyboardEvent) {
  if (!(e.ctrlKey || e.metaKey)) return
  if (e.key === '\\') {
    e.preventDefault()
    if (!assistPanelOpen.value) {
      assistPanelOpen.value = true
      assistPinned.value = true
      _persistPinned(true)
    } else if (!assistPinned.value) {
      assistPinned.value = true
      _persistPinned(true)
    } else {
      closeAssistPanel()
    }
    return
  }
  if (!e.shiftKey && e.key >= '1' && e.key <= '4') {
    const tab = PANEL_TAB_ORDER[Number(e.key) - 1]
    if (!tab) return
    e.preventDefault()
    activeTab.value = tab
    assistPanelOpen.value = true
  }
}

onMounted(() => {
  window.addEventListener('keydown', _panelKeyHandler)
  window.addEventListener(OPEN_INBOX_EVENT, _onOpenInboxDrawer)
  document.addEventListener('pointerdown', _onDocPointerDownPanel, true)
})
onBeforeUnmount(() => {
  window.removeEventListener('keydown', _panelKeyHandler)
  window.removeEventListener(OPEN_INBOX_EVENT, _onOpenInboxDrawer)
  document.removeEventListener('pointerdown', _onDocPointerDownPanel, true)
  if (_panelEscId) { _removePanelEsc(_panelEscId); _panelEscId = null }
})

// 切章后面板若关着，分区复位（下次打开由 InspectorPanel 按章节状态取默认——
// 空章→打算/有正文→此刻）；开着则由 InspectorPanel 自己的切章 watch 复位。
watch(selectedChapterId, () => {
  if (!assistPanelOpen.value) activeTab.value = null
})

// 完稿审计报告到达 → 面板以「检查」滑出一次（作者手动关过则不反复弹）+ 栏上朱点；
// 面板在「检查」开过一次即灭。
let _panelAutoOpened = false
watch(() => session.finishReport.value, (report) => {
  if (report) {
    reportUnread.value = true
    if (!_panelAutoOpened && !assistPanelOpen.value) {
      activeTab.value = 'review'
      assistPanelOpen.value = true
      _panelAutoOpened = true
    }
  } else {
    _panelAutoOpened = false
  }
})
watch([assistPanelOpen, activeTab], ([open, tab]) => {
  if (open && tab === 'review') reportUnread.value = false
})

// A5d 收件箱直达（toast「去确认」）：以「此刻」开面板；
// 收件箱展开由 InspectorPanel / WorldSceneSlice 各自监听同一事件。
function _onOpenInboxDrawer() {
  activeTab.value = 'now'
  assistPanelOpen.value = true
}

// 打字沉浸 2.0（08 期 §4.9）：编辑活动期间左右两条缘签降到 35% 透明度
// （.workspace-view--typing 挂根，hover/focus-within 即复原；页面头 meta 行不淡）。
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

// 页面头 meta 行 AI 状态件（08 期 §4.1，顶栏状态丸转世，文案=07 表 A1/A2 原文）：
// 只保留与 adaptive / 润色相关的进行态。adaptive 模式下跟随 aiLane；
// 其余时间只在润色/出错时显字，平时留空不打扰（空态整件缺席）。
const aiStateLabel = computed(() => {
  if (session.adaptiveMode.value) {
    switch (session.aiLane.value) {
      case 'perceiving': return 'AI 正在看你写的'
      case 'suggesting': return '走向卡备好了 · Ctrl+Space'
      case 'assisting': return '正在往下写…'
      case 'digesting': return '正在整理新设定…'
      case 'analyzing': return '正在通读全章…'
      default: return ''
    }
  }
  switch (session.stage.value) {
    case 'refining': return '润色中…'
    case 'auditing': return '正在检查全文…'
    case 'error': return '生成失败'
    default: return ''
  }
})
const aiStateError = computed(() => session.stage.value === 'error')

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
// 据此挂载 perceive/续写/沉淀能力。旧 step 路径已随 BS-ADF 归档移除——adaptive 是唯一写作路径。
let _activatedChapterId: string | null = null

watch(selectedChapter, (ch, prev) => {
  if (!ch) return
  // remount 首跑（prev=undefined，2026-09-17 契约修复）：写作台无 keep-alive，
  // 切页往返必经此处——此前 prev?.id 恒 undefined 使条件恒真，把 detach 刻意
  // 保留的舱内零件当场清空，「感知常驻·回台秒弹」被 remount 无效化（感知链
  // 全部重跑）。现在只清「归属 ≠ 当前章」的存货（换书/换章后直落新章的首跑
  // 仍防旧件串章），同章回台保住秒弹零件。
  if (prev === undefined) {
    if (getSparkPartsChapterId() && getSparkPartsChapterId() !== ch.id) {
      setSparkParts([])
      setExtraSparkParts([])
      setSparkGuests([])
    }
    return
  }
  if (ch.id !== prev?.id) {
    _activatedChapterId = null
    // 在飞 stitch 流先断（2026-09-04 审计修复）：GHOST_START 在后端全文生成完
    // 才发出，换章窗口内旧章幽灵会以新章光标为落点灌进画布（跨章污染）
    adaptiveAssist.abortInflight()
    // 切章时若在 adaptive 模式，退出（新章需重新激活）
    if (session.adaptiveMode.value) session.exitAdaptive()
    // 切章清空缓存零件——旧章挂件是旧章上下文的产物，留着会被停顿秒弹错章节
    setSparkParts([])
    setExtraSparkParts([])
    setSparkGuests([])   // 临时通行证随章作废（guest 是本章正文的产物）
  }
}, { immediate: true })

/** 激活指定章节的 adaptive 辅助层（幂等）。打字 ≥4 字与 Tab 显式召唤共用入口。 */
function _activateChapterAssist(chapterId: string) {
  if (_activatedChapterId === chapterId) return  // 已激活
  // 旧管线在跑则不抢（作者主动选了规划模式）
  if (session.generating.value && session.stage.value !== 'idle') return
  const editor = chapterEditorHandle.value
  const typed = editor ? editor.state.doc.textContent.trim().length : 0
  if (typed < 4) return  // 够 4 字才激活（空章防误触——空章走点火卡冷启动）
  _activatedChapterId = chapterId
  session.enterAdaptive(chapterId)
}

function _onAuthorActivity() {
  if (!assistEnabled.value) return  // AI 辅助关闭：纯手写，不激活 adaptive 辅助层
  const chapterId = selectedChapterId.value
  if (!chapterId) return
  _activateChapterAssist(chapterId)
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
    const savePromise = store.updateChapter(id, updates as any)
    // 登记在飞写库：完稿体检等消费方 flush 后据此等待「库内=屏上」再发枪
    trackChapterSave(savePromise)
    await savePromise
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
  <div
    class="workspace-view"
    :class="{ 'workspace-view--drawer-pinned': assistPinned, 'workspace-view--typing': isTyping }"
  >
    <main class="editor-area">
      <!-- 编辑器（复用 ChapterEditorContainer 全套；点火卡经 page-top 槽入纸页首） -->
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
            :word-count="wordCount"
            :ai-state-label="aiStateLabel"
            :ai-state-error="aiStateError"
            @update-chapter="handleUpdateChapter"
            @refresh-characters="handleRefreshCharacters"
            @editor-entity-focus="handleEntityFocus"
          >
            <template #page-top>
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
            </template>
          </ChapterEditor>
        </div>
        <!-- 纸左页边批注（08 期 §4.7 几何迁移：圆点守行高 + 覆态读卡右开）；不占布局宽，纸列零位移 -->
        <PerceptionBand
          v-if="adaptiveActive"
          :suggestions="session.adaptiveSuggestions.value"
          :spine-progress="chapterSpine.spineProgress.value"
          @dismiss-hint="onDismissHint"
        />
        <!-- 光标层：幽灵三条（疑点/返修/洗层）随幽灵尾浮动。
             SparkDock 卡舱已迁行间推挤（InlineDock WidgetDecoration，
             2026-09-09 布局重构）——事件经 inlineDockBridge 桥接（见 onMounted） -->
        <CursorLayer
          v-if="adaptiveActive"
          @use-original="onUseGhostOriginal"
        />

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

      <!-- 态 A：无选中章 = 目录页（纸面本体即目录，§4.4） -->
      <TocPage
        v-else
        :book-title="currentBook?.title || ''"
        :chapters="sortedChapters"
        :loading="loading"
        @select="(ch) => store.selectChapter(ch.id)"
        @create="createChapter"
        @import="openImportModal"
      />

      <!-- NLE-ADF 走向卡舱（Ctrl+Space 唤起：选走向 → burst 段落级连写） -->
      <BeatCardDock @pick="(card) => onBeatCardPick(card)" />
      <!-- NLE-ADF 思考指示器（光标处脉冲点；停顿 2s 预览/后端思考中强脉冲） -->
      <ThinkingIndicator />
      <!-- 快捷键速查弹层（右缘栏 ? 按钮触发） -->
      <ShortcutsCheatsheet v-if="showShortcuts" @close="showShortcuts = false" />
    </main>

    <!-- 左缘书签（写中回目录的入口；无选中章时纸面即目录，书签缺席） -->
    <ChapterSpine
      v-if="selectedChapter"
      :chapter-label="spineChapterLabel"
      @open="tocOpen = true"
    />
    <!-- 目录抽屉（binder 转世：选章即收 / Esc / 外点 / 再点书签） -->
    <ChapterTocDrawer
      :visible="tocOpen"
      :book-title="currentBook?.title || ''"
      :chapters="sortedChapters"
      :selected-chapter-id="selectedChapterId"
      :loading="loading"
      :select-mode="selectMode"
      :checked-ids="checkedIds"
      :all-checked="allChecked"
      :batch-deleting="batchDeleting"
      :can-extract="!!selectedChapter"
      @close="tocOpen = false"
      @back="backToLibrary"
      @toggle-select-mode="toggleSelectMode"
      @toggle-check-all="toggleCheckAll"
      @select="onTocSelect"
      @delete="confirmDeleteChapter"
      @batch-delete="batchDeleteChapters"
      @exit-select-mode="exitSelectMode"
      @create="createChapter"
      @import="openImportModal"
      @extract="openExtractionModal"
    />

    <!-- 右缘助手栏（点击制；AI 辅助的唯一的家） -->
    <AssistRail
      :assist-enabled="assistEnabled"
      :active-tab="assistPanelOpen ? activeTab : null"
      :report-unread="reportUnread"
      @toggle-assist="toggleAssist"
      @select-tab="onRailSelectTab"
      @open-cheatsheet="showShortcuts = true"
    />
    <!-- 助手面板（单分区壳；贴栏左开，栏始终可点） -->
    <Transition name="inspector-drawer">
      <aside
        v-if="assistPanelOpen"
        ref="assistPanelEl"
        class="inspector-drawer inspector-drawer--beside-rail"
      >
        <InspectorPanel
          v-model:active-tab="activeTab"
          :external-session="session"
          :pinned="assistPinned"
          @activate="onPanelActivate"
          @pin="togglePanelPinned"
          @close="closeAssistPanel"
        />
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
  background: var(--surface-desk); /* 06-modern §2.1：页面根=桌面（纸列浮起） */
  /* 面板 pin 时推挤内容区：纸列在剩余空间重新居中，过渡与面板滑入同速 */
  transition: padding-right var(--dur-3) var(--ease-out);
  /* 左缘书签 / 目录抽屉 / 右缘助手栏的 absolute 定位锚 */
  position: relative;
}

/* 推挤量 = 面板宽（.inspector-drawer 380px/44vw）+ 右缘栏 44px——
   面板贴栏左开（--beside-rail），栏的占位不重复推 */
.workspace-view--drawer-pinned {
  padding-right: calc(min(380px, 44vw) + 44px);
}

/* 中栏（书桌区） */
.editor-area {
  display: flex;
  flex-direction: column;
  height: 100%;
  background: var(--bg-primary);
  overflow: hidden;
  /* 页内浮层 absolute 定位锚（teleport 到 body 的浮层不受影响） */
  position: relative;
}

.editor-host {
  flex: 1;
  display: flex;
  flex-direction: row;
  overflow: hidden;
  min-height: 0;
  position: relative;
}

/* 正文主区（ChapterEditor）：flex-grow 填满可用宽——splitpanes 时代由 Pane 给定
   宽度，flex: 0 1 auto 在单栏 flex 行里会塌缩成内容固有宽（纸列曾实测 526px，
   冻结几何 880 失守）；grow 后由 max-width 60rem 封顶、内层 max-w-880 收纸列。 */
.editor-main {
  flex: 1 1 auto;
  max-width: 60rem;
  margin: 0 auto;
  min-width: 0;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  position: relative;
}
</style>
