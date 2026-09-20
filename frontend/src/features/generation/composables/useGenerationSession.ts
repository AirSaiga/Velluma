/**
 * 统一生成会话（V3.1 F3 新建，规格 §11.2）。
 *
 * 职责：adaptive 写作路径的会话状态机（键位编排/幽灵/卡舱）+ 键位工具（清脂）。
 *
 * 【已拔除 2026-09-12】V4.1 Refinery 两阶段精修（startRefinery/confirmRefinery）
 * 随写后检查收敛批整体退役——docs/reports/post-writing-checks-audit.md；其手术原语
 * 后端迁 services/text_surgery/（ADF 一致性守卫消费），读者反馈收编
 * /adaptive/reader-feedback。
 *
 * 引擎：BS-ADF 步进模式（.start，消费 BSADF_STAGE/ADF_ANCHOR_DESIGNED/... 事件）。
 * V3.1 Unified 引擎后端已剥离（/generate 端点不存在），相关死代码（startUnified 等）已删除。
 * V3.2 ADF 整章生成入口（start/startAdf/adfApi.streamGenerate）已移除，前端不再有 ADF UI 入口。
 *
 * BS-ADF 引擎（/generate-bsadf）当前只以「步进模式」运行：
 * 【已归档 2026-08-29】BS-ADF 步进链路（startBeat/advanceBeat/重渲/轮询自愈）整体退役，
 * 详见 backend/_deprecated 与 frontend 归档清单（_deprecated/README）。
 *
 * 会话状态机（stage，最小拔除后仅存 idle 写入点——旧 done/refining/auditing
 * 写入全随 Refinery 退役，字段保留供快照兼容与旧分支清理批次处理）：
 *   idle → tier_classifying → ... → done / error
 *
 * 关键产物（UI 订阅）：
 * - tierDecision：定档结果（高潮章/转折章/推进章/过渡章 + 理由）
 * - stepProgress：当前步骤（阶段名 + 进度）
 */
import { ref, computed, watch, onMounted, onUnmounted, type Ref, type ComputedRef } from 'vue'
import { chapterApi, type AdfEngine, type BeatSlot } from '../../../services/api/domain'
import { useToast } from '../../../composables/useToast'
import { chapterEditorHandle } from '../../chapter-editor/editorHandle'
import { noHistory } from '../../chapter-editor/noHistory'
import {
  ghostActive, ghostSource, ghostDirty,
  beginGhost, appendGhost, ghostText, commitGhost, evaporateGhost,
  parkGhost, discardParkedGhost, parkedContainsCursor, adoptParkedGhost,
  tryReviveGhost, ghostActionReady, ghostParked, ghostStreaming,
} from './useGhostDraft'
import {
  sparkDockVisible, attachedParts,
  setSparkDockGate, setSparkParts, sparkParts, sparkSelectedIndex,
  hideSparkDock, stashSparkDock, clearAttachedParts, attachSparkPart, setSparkSticky, moveSparkSelection,
  type SparkPart,
} from './useSparkDock'
import { beatDockVisible, beatCards, showBeatDock, hideBeatDock } from './useBeatDock'
import { assistEnabled } from './useAssistEnabled'
import { defatParagraphAtCursor } from '../../../shared/utils/defat'

// ============================================================
// localStorage 持久化层（按 chapterId 存快照，进入章节即恢复）
// ============================================================
// 设计意图：解决"切路由/刷新后侧边栏产物全丢"——
// session 的所有产物 ref（锚点/前置条件/审计/精修结果等）随 WorkspaceView 卸载而 GC，
// 此处将其序列化为 JSON 存 localStorage，进入章节时恢复。
// 警示：生成中途刷新无法恢复进行中的 LLM 调用，只能恢复已有产物；
// 恢复时中断态（generating=true / stage 非 done）强制归正为 done，避免假"生成中"。

const _STORAGE_PREFIX = 'velluma:gensess:'
const _SNAPSHOT_VERSION = 1

/** 可序列化的会话快照（ref 值的子集——排除瞬时态） */
interface SessionSnapshot {
  v: number
  chapterId: string
  stage: SessionStage
  engine: AdfEngine
  stepProgress: StepProgress | null
  // 保存时间戳（供调试/未来做过期清理）
  savedAt: number
}

/** 从 localStorage 加载某章的会话快照（无则返回 null） */
function _loadSnapshot(chapterId: string): SessionSnapshot | null {
  try {
    const raw = localStorage.getItem(_STORAGE_PREFIX + chapterId)
    if (!raw) return null
    const snap = JSON.parse(raw) as SessionSnapshot
    if (snap.v !== _SNAPSHOT_VERSION) return null  // 版本不匹配则丢弃
    return snap
  } catch {
    return null  // JSON 解析失败静默（localStorage 可能被外部污染）
  }
}

/** 保存某章的会话快照到 localStorage（失败静默，不阻塞生成） */
function _saveSnapshot(chapterId: string, snap: Omit<SessionSnapshot, 'v' | 'chapterId' | 'savedAt'>) {
  try {
    const full: SessionSnapshot = {
      ...snap,
      v: _SNAPSHOT_VERSION,
      chapterId,
      savedAt: Date.now(),
    }
    localStorage.setItem(_STORAGE_PREFIX + chapterId, JSON.stringify(full))
  } catch {
    // localStorage 满 / 序列化失败：静默，持久化是尽力而为
  }
}

/** 清除某章的快照 */
function _clearSnapshot(chapterId: string) {
  try {
    localStorage.removeItem(_STORAGE_PREFIX + chapterId)
  } catch {
    // 静默
  }
}

/** 会话阶段 */
export type SessionStage =
  | 'idle'
  | 'tier_classifying' // 定档中
  | 'tier_decided' // 定档完成，等用户确认/自动推进
  | 'setup_growing' // 铺垫结构生长中
  | 'zone_writing' // 分区写作（蓄势段 + 铺陈段）
  | 'assembling' // 组装
  | 'auditing' // 审校
  | 'refining' // 精修
  | 'beat_pending' // 槽位卡已生成，等作者编辑（Track B 单次暂停态，分支选择内嵌其中）
  | 'beat_rendering' // 作者确认后，后台顺序渲染各段
  | 'beat_stepping' // NLE-ADF：正在逐段步进（某段就绪等空格推进）
  | 'beat_branch_choosing' // NLE-ADF：步进态遇 DDE 岔路门，等作者选走向
  | 'beat_authoring' // NLE-ADF 2.0 作者模式：拍已打开，等作者写碎片/微缝合/召唤代笔
  | 'done' // 完成
  | 'error'

/** 步骤进度（驱动右栏步骤条） */
export interface StepProgress {
  /** 当前阶段标签（写作语言，如"蓄势段"/"铺陈段"/"组装"/"审校"） */
  label: string
  /** 当前段索引（如蓄势段 1/2 中的 1） */
  index?: number
  /** 总段数 */
  total?: number
  /** 所属分区（development/buildup） */
  zone?: string
}

export interface GenerationSession {
  // 状态
  stage: Ref<SessionStage>
  generating: Ref<boolean>
  error: Ref<string | null>
  stepProgress: Ref<StepProgress | null>
  engine: Ref<AdfEngine>
  // 产物
  // V3.2 ADF 专用产物
  // 派生
  isTerminal: ComputedRef<boolean>
  /** 渲染阶段「当前任务」焦点（驱动右栏焦点条；纯派生，不持久化） */
  // 控制
  cancel: () => void
  reset: () => void
  loadForChapter: (chapterId: string) => void
  persist: () => void
  // ===== NLE-ADF 3.0 双轴状态机（自适应融合写作台） =====
  /** 作者轴（前台主线）：idle/composing/ghostStitching/settling */
  authorLane: Ref<'idle' | 'composing' | 'ghostStitching' | 'settling'>
  /** AI 轴（后台）：dormant/perceiving/suggesting/assisting/digesting/analyzing */
  aiLane: Ref<'dormant' | 'perceiving' | 'suggesting' | 'assisting' | 'digesting' | 'analyzing'>
  /** 自适应模式开关：true=新流程（作者主导+辅助层），false=旧 step 路径 */
  adaptiveMode: Ref<boolean>
  /** 章节级字数目标（沉淀基准） */
  chapterTargetWords: Ref<number>
  /** adaptive 感知建议（淡提示数据源） */
  adaptiveSuggestions: Ref<any[]>
  /** adaptive 规划建议（plan-suggest 产出） */
  planSuggestions: Ref<any | null>
  /** 沉淀的动态拍记录（后验生成，DYN_ 前缀） */
  dynamicBeats: Ref<Array<{ beat_id: string; text: string; word_count: number; settled_at: number }>>
  /** 完稿审计报告（InspectorPanel 渲染） */
  finishReport: Ref<import('../../../services/api/domain/adaptive.api').FinishReport | null>
  /** 沉淀抽取结果（涌现实体 + 冲突，InspectorPanel 渲染） */
  settleResult: Ref<import('../../../services/api/domain/adaptive.api').SettleResult | null>
  /** 激活自适应写作（作者进章节打字时调；不跑整章管线，只激活辅助层） */
  enterAdaptive: (chapterId: string) => void
  /** 退出自适应模式（切回旧 step 路径或 idle） */
  exitAdaptive: () => void
  /** 注入 adaptive 续写函数（由 useAdaptiveAssist 注入，键位状态机调用） */
  setAdaptiveContinue: (fn: ((mode: 'stitch' | 'continue', parts: Array<{ text: string; direction?: string; slot?: string }>) => void) | null) => void
  /** 注入 adaptive 沉淀函数（由 useAdaptiveAssist 注入，Ctrl+Enter composing 态触发） */
  setAdaptiveSettle: (fn: (() => void) | null) => void
  /** 注入 adaptive 完稿函数（由 useAdaptiveAssist 注入，InspectorPanel 完稿按钮触发） */
  setAdaptiveFinish: (fn: (() => void) | null) => void
  /** 触发 adaptive 完稿审计 */
  triggerAdaptiveFinish: () => void
  /** 注入 adaptive 段落级连写函数（由 useAdaptiveAssist 注入，走向卡舱选定后触发） */
  setAdaptiveBurst: (fn: ((card: { event: string; anchors?: string[] } | null) => void) | null) => void
  /** 注入 adaptive 零件即点取件函数（Tab 唤起卡片舱但无缓存零件时触发） */
  setAdaptiveSummon: (fn: ((forceRefresh?: boolean) => void) | null) => void
  /** 03 三键「未灌完不上膛」：中止在飞 SSE（流式期间按键只打断不采纳） */
  setAdaptiveAbort: (fn: (() => void) | null) => void
}

export function useGenerationSession(): GenerationSession {
  const stage = ref<SessionStage>('idle')
  const generating = ref(false)
  const error = ref<string | null>(null)
  const stepProgress = ref<StepProgress | null>(null)
  const engine = ref<AdfEngine>('v3.2')

  // ===== NLE-ADF 3.0 双轴状态机 =====
  // 作者轴（前台主线）：idle（空章/未激活）→ composing（自由写作，辅助激活）
  //   → ghostStitching（幽灵草稿流入中）→ settling（沉淀锁定，短暂忙态）
  // 与 stage（旧单轴，保留为 legacy step 路径）并行，不互相阻塞。
  const authorLane = ref<'idle' | 'composing' | 'ghostStitching' | 'settling'>('idle')
  // AI 轴（后台）：dormant → perceiving/suggesting/assisting/digesting/analyzing
  const aiLane = ref<'dormant' | 'perceiving' | 'suggesting' | 'assisting' | 'digesting' | 'analyzing'>('dormant')
  // 自适应模式开关：true = 走新流程（作者主导 + 辅助层），false = 走旧 step 路径
  const adaptiveMode = ref(false)
  // 章节级字数目标（沉淀基准，作者可设定；默认 2000）
  const chapterTargetWords = ref(2000)
  // adaptive 感知产出的建议（淡提示数据源，供 UI 订阅）
  const adaptiveSuggestions = ref<any[]>([])
  // adaptive 规划建议（plan-suggest 产出，侧栏淡建议层）
  const planSuggestions = ref<any | null>(null)
  // 沉淀的动态拍记录（后验生成，beat_id 用 DYN_ 前缀）
  const dynamicBeats = ref<Array<{ beat_id: string; text: string; word_count: number; settled_at: number }>>([])
  // 完稿审计报告（finishChapter 写入，InspectorPanel 渲染）
  const finishReport = ref<import('../../../services/api/domain/adaptive.api').FinishReport | null>(null)
  // 沉淀抽取结果（涌现实体 + 冲突，settleCurrent 写入，InspectorPanel 渲染）
  const settleResult = ref<import('../../../services/api/domain/adaptive.api').SettleResult | null>(null)

  /** 最近一次完成来自哪条流程（供完成弹窗区分标题） */
  /** 本次生成开始时间戳（ms），onDone 时计算耗时；不持久化（刷新后无法准确恢复） */
  let startedAt: number | null = null

  // ============================================================
  // NLE-ADF 2.0 作者模式：拍创作（碎片 + 微缝合 + 代笔 + 锁拍）
  // ============================================================
  // 与裁决模式的分工：裁决模式是"AI 渲整段 → 人裁"（BEAT_RENDER_READY 驱动）；
  // 作者模式是"人写碎片 → AI 缝合补质感 → 人锁拍"（BEAT_AUTHORING_OPEN 驱动）。
  // 碎片与幽灵草稿是纯画布状态（真实文档文本 + GhostDraftMark），锁拍前零后端流量；
  // Ctrl+Enter 锁拍才经 advanceBeat lock_with_text 走后端（抽状态卡 + 记忆倒灌）。
  const authoringEnabled = ref(false)
  const authoringBeatId = ref<string | null>(null)
  const authoringBeatCard = ref<BeatSlot | null>(null)
  const stitching = ref(false)
  const fragmentCounts = ref<Record<string, number>>({})
  // 拍创作区基线（PM 文档位置）：AUTHORING_OPEN 时记录文档末尾位置，此后作者的
  // 所有输入/缝合/代笔稿都在此位置之后——锁拍取 [base, docEnd] 区间为 authorText。
  let authoringBasePos = 0
  // 碎片锚点：上一个已锁碎片的结束位置（下一次缝合的碎片 = [锚点, 光标] 区间文本）。
  let fragmentAnchorPos = 0
  // 拍基线栈（back 回拨恢复文档用）：{beatId, basePos}。AUTHORING_OPEN 压栈/复用。
  const beatBaseStack: Array<{ beatId: string; basePos: number }> = []
  let stitchAbort: AbortController | null = null
  // 零门槛开局基线：本拍首个 AUTHORING_OPEN 时若本章是"近空白新章"（freshCanvas），
  // 创作区基线取文档开头（0）——开局自由书写的文字全部归入拍 0，
  // 防 COMPLETE 覆盖落库时丢失开局文字。
  let _freshCanvas = false

  // Spark Dock 接线：可展示门。
  // NLE-ADF 3.0：gate 从 stage 解耦——自适应 composing 态（authorLane）也激活，
  // 让作者自由写作时就能吸附零件（零件源从 perceive 端点供给，不再依赖拍卡）。
  // 旧路径（beat_authoring/tier_classifying/setup_growing）保留兼容。
  setSparkDockGate(() => {
    if (ghostActive.value || stitching.value) return false
    // 自适应模式：composing 态激活
    if (adaptiveMode.value && authorLane.value === 'composing') return true
    // 旧路径：拍创作态激活
    if (authoringEnabled.value && (
      stage.value === 'beat_authoring'
      || stage.value === 'tier_classifying'
      || stage.value === 'setup_growing'
    )) return true
    return false
  })
  watch(authoringBeatCard, (card) => {
    const parts: SparkPart[] = []
    if (card) {
      for (const anchor of card.key_anchors || []) {
        parts.push({ key: `a:${anchor}`, kind: 'anchor', icon: '⚙️', text: anchor })
      }
      if (card.text_carrier) {
        parts.push({ key: `c:${card.text_carrier}`, kind: 'carrier', icon: '💬', text: card.text_carrier })
      }
    }
    setSparkParts(parts)
    // 换拍即清空上一拍的吸附意图（零件语境已变）
    clearAttachedParts()
    hideSparkDock()
  }, { immediate: true })

  function commitGhostFragment(): boolean {
    if (!ghostActive.value) return false
    commitGhost()
    const editor = chapterEditorHandle.value
    fragmentAnchorPos = editor ? editor.state.selection.from : fragmentAnchorPos
    const id = authoringBeatId.value
    if (id) {
      const newCount = (fragmentCounts.value[id] || 0) + 1
      fragmentCounts.value = { ...fragmentCounts.value, [id]: newCount }
      _snapshotFragment(id, newCount)
    }
    return true
  }

  /** 03 三键「上膛」判定：流式中（中止流）或灌完缓冲窗内 → 按键只打断不采纳。
   *  返回 true=事件已被吃掉（未上膛，调用方直接 return）。判据在 useGhostDraft
   *  的 ghostStreaming（begin→GHOST_DONE）——session 的 stitching 是旧路径
   *  遗物从未置真，不能当流式判据（交叉验证修正）。 */
  function ghostArmedGuard(): boolean {
    if (ghostActionReady()) return false
    if (ghostStreaming.value) _adaptiveAbortFn?.()  // 只打断：中止流式，已灌部分留待裁决
    return true
  }

  // ===== 碎片快照（幽灵时间轴回拨的数据源） =====
  // 每次碎片锁死存一份完整文档纯文本（章级体量，快照极便宜）。
  // 划轨 = 全量恢复该时刻文档——语义直白：回到那一次锁死的瞬间。
  interface FragmentSnapshot {
    beatId: string
    count: number
    text: string
  }
  const fragmentSnapshots = ref<FragmentSnapshot[]>([])

  function _snapshotFragment(beatId: string, count: number) {
    const editor = chapterEditorHandle.value
    if (!editor) return
    const text = editor.state.doc.textBetween(0, editor.state.doc.content.size, '\n\n')
    // 丢弃本拍更靠后的快照（回拨后再写是新的时间线分支）
    fragmentSnapshots.value = fragmentSnapshots.value.filter(
      (s) => !(s.beatId === beatId && s.count >= count),
    )
    fragmentSnapshots.value.push({ beatId, count, text })
  }

  

  /** 作者模式瞬时段态复位（终态/取消/切章/重置共用）。 */
  function _resetAuthoringTransient() {
    authoringBeatId.value = null
    authoringBeatCard.value = null
    stitching.value = false
    if (stitchAbort) { stitchAbort.abort(); stitchAbort = null }
    fragmentCounts.value = {}
    fragmentSnapshots.value = []
    beatBaseStack.length = 0
    // 防御：复位时幽灵草稿不该存在；存在即蒸发（AI 临时元素零残留）；
    // 暂留段同理让位（03 三键：复位=离开本章，暂留不跨章）
    if (ghostActive.value) evaporateGhost()
    if (ghostParked.value) discardParkedGhost()
  }

  let abortController: AbortController | null = null
  let currentChapterId: string | null = null  // 当前 session 绑定的章节（用于持久化 key）

  const isTerminal = computed(() => stage.value === 'done' || stage.value === 'error')

  // ---- 持久化：把当前产物序列化到 localStorage ----

  /** 收集当前 ref 值为快照（不含版本/章节/时间戳，由 _saveSnapshot 补） */
  function _collectSnapshot() {
    return {
      stage: stage.value,
      engine: engine.value,
      stepProgress: stepProgress.value,
    }
  }

  /** 持久化当前状态到 localStorage（当前绑定的章节） */
  function persist() {
    if (currentChapterId) {
      _saveSnapshot(currentChapterId, _collectSnapshot())
    }
  }

  /** 加载并恢复某章的上次会话产物（进入章节时调用）。
   *
   * 恢复语义（用户决策"按章节保留，进入即恢复"）：
   * - 有快照：恢复所有产物 ref。中断态（generating / 非 done 的 stage）强制归正：
   *   stage→done，generating 不设（保持 false），因为刷新后无法续上 LLM 调用。
   * - 无快照：reset 到 idle（新章节或从未生成过）。
   * - 切换到不同章节：先 persist 旧章，再 load 新章。
   */
  function loadForChapter(chapterId: string) {
    // 切换章节：先中止在途 SSE（2026-09-01 页面逻辑审查修复：注释一直声称
    // 「取消可能进行中的步进运行」但代码从未做——精修手术流式中途切章，旧章
    // 的流会继续往会话 ref 灌内容，新章界面显示旧章的手术进度/流文本，跨章
    // 污染窗口一直开到流跑完。abort 在 sse.ts 按非错误静默结束，不触发 onError），
    // 再把当前章的状态存下来
    if (currentChapterId && currentChapterId !== chapterId) {
      if (abortController) {
        abortController.abort()
        abortController = null
      }
      generating.value = false
      persist()
    }
    currentChapterId = chapterId
    const snap = _loadSnapshot(chapterId)
    if (!snap) {
      // 无历史：重置为干净的 idle
      _resetInternal()
      currentChapterId = chapterId
      return
    }
    // 恢复产物
    engine.value = snap.engine
    stepProgress.value = snap.stepProgress
    // 旧引擎快照字段（BS-ADF/ADF 产物）已随 2026-08-29 归档移除——旧快照里的
    // 对应数据静默丢弃；瞬时段态统一复位（run 已失效，不复位会残留到目标章）。
    _resetAuthoringTransient()
    // 中断态归正：刷新后无法续 LLM；Refinery 退役后 stage 的 done/refining 写入点
    // 已全部消失，恢复一律归 idle（旧快照里可能存着 done——其产物字段已随本批
    // 退役，恢复成 done 只会显示假状态）。stepProgress 同理清空（旧进度是失效的）。
    stepProgress.value = null
    stage.value = 'idle'
    generating.value = false
    error.value = null
  }

  /** 内部 reset（不触碰 currentChapterId，不 persist） */
  function _resetInternal() {
    stage.value = 'idle'
    generating.value = false
    error.value = null
    stepProgress.value = null
    engine.value = 'v3.2'
    // 风险3修复：清理步进轮询定时器 + 清空 steppingRunId（防止拆卸后永久轮询）
    authoringEnabled.value = false
    _resetAuthoringTransient()
  }

  

  function cancel() {
    if (abortController) {
      abortController.abort()
      abortController = null
    }
    generating.value = false
    stage.value = 'idle'
    error.value = null // 清空残留错误（取消/关闭即用户主动放弃）
  }

  // ============================================================
  // NLE-ADF 3.0 自适应融合模式（作者主导写作 + AI 柔性共生）
  // ============================================================
  // 与旧 step 路径的根本区别：不跑整章管线、不预设拍划分。
  // 作者进章节打字即激活 composing，辅助层（useAdaptiveAssist）据此挂载。
  // 双轴 authorLane/aiLane 与 stage 并行——adaptive 模式下 stage 保持 idle，
  // 旧 step 路径已随 BS-ADF 归档移除（2026-08-29）——adaptive 是唯一写作路径。

  /** 激活自适应写作模式。
   *  作者进章节开始打字时调。
   *  不跑定档/锚点/分镜管线——作者轴置 composing，辅助层据此挂载。 */
  function enterAdaptive(chapterId: string) {
    if (adaptiveMode.value && authorLane.value === 'composing') return  // 已激活
    // 若旧管线在跑，先取消（adaptive 与 step 互斥）
    if (generating.value && stage.value !== 'idle') {
      if (abortController) { abortController.abort(); abortController = null }
      generating.value = false
    }
    currentChapterId = chapterId
    adaptiveMode.value = true
    authorLane.value = 'composing'
    aiLane.value = 'dormant'
    stage.value = 'idle'  // adaptive 模式下 stage 不参与（保持 idle）
    error.value = null
    adaptiveSuggestions.value = []
    planSuggestions.value = null
  }

  /** 退出自适应模式（切回 idle 或旧 step 路径）。
   *  清空 adaptive 瞬态，保留已沉淀的动态拍记录与 emergentFacts。 */
  function exitAdaptive() {
    adaptiveMode.value = false
    authorLane.value = 'idle'
    aiLane.value = 'dormant'
    adaptiveSuggestions.value = []
    // 动态拍记录与 planSuggestions 保留（切回后仍可查看）
  }

  // P0-4 接线：幽灵生命周期 ↔ authorLane.ghostStitching（枚举此前从未赋值）。
  // 单点 watch 覆盖全部进出路径（SSE onStart / Tab 落地 / Enter 暂留 / Esc 蒸发 / 出错回滚）；
  // 只在 composing↔ghostStitching 之间往返，不触碰 idle（会话未激活不介入）。
  watch(ghostActive, (active) => {
    if (!adaptiveMode.value) return
    if (active && authorLane.value === 'composing') authorLane.value = 'ghostStitching'
    else if (!active && authorLane.value === 'ghostStitching') authorLane.value = 'composing'
  })

  // adaptive 续写注入器：由 useAdaptiveAssist 注入（解耦 session 与 API 层）。
  // session 的键位状态机在 adaptive composing 态调它触发续写，不直接 import adaptiveApi。
  let _adaptiveContinueFn: ((mode: 'stitch' | 'continue', parts: Array<{ text: string; direction?: string; slot?: string }>) => void) | null = null
  function setAdaptiveContinue(fn: ((mode: 'stitch' | 'continue', parts: Array<{ text: string; direction?: string; slot?: string }>) => void) | null) {
    _adaptiveContinueFn = fn
  }

  // adaptive 沉淀注入器：由 useAdaptiveAssist 注入（Ctrl+Enter 在 composing 态触发）
  let _adaptiveSettleFn: (() => void) | null = null
  function setAdaptiveSettle(fn: (() => void) | null) {
    _adaptiveSettleFn = fn
  }

  // adaptive 完稿注入器：由 useAdaptiveAssist 注入（InspectorPanel 完稿按钮触发）
  let _adaptiveFinishFn: (() => void) | null = null
  function setAdaptiveFinish(fn: (() => void) | null) {
    _adaptiveFinishFn = fn
  }
  /** 触发完稿审计（InspectorPanel 按钮调） */
  function triggerAdaptiveFinish() {
    _adaptiveFinishFn?.()
  }

  // adaptive 段落级连写（burst）注入器：由 useAdaptiveAssist 注入（走向卡舱选定后触发）
  let _adaptiveBurstFn: ((card: { event: string; anchors?: string[] } | null) => void) | null = null
  function setAdaptiveBurst(fn: ((card: { event: string; anchors?: string[] } | null) => void) | null) {
    _adaptiveBurstFn = fn
  }

  // adaptive 零件即点取件注入器：Tab 唤起卡片舱但无缓存零件时，由 WorkspaceView
  // 注入（未激活章节先激活——Tab 是显式召唤，等同打字意图——再走停顿级心跳取件）
  let _adaptiveSummonFn: ((forceRefresh?: boolean) => void) | null = null
  function setAdaptiveSummon(fn: ((forceRefresh?: boolean) => void) | null) {
    _adaptiveSummonFn = fn
  }

  // adaptive 在飞流中止注入器（03 三键「未灌完不上膛」：流式期间按键只打断
  // 不采纳——中止 SSE，已灌部分保持幽灵态待后续裁决）
  let _adaptiveAbortFn: (() => void) | null = null
  function setAdaptiveAbort(fn: (() => void) | null) {
    _adaptiveAbortFn = fn
  }

  function reset() {
    if (abortController) {
      abortController.abort()
      abortController = null
    }
    // 清除当前章节的持久化快照（reset = 主动放弃产物）
    if (currentChapterId) {
      _clearSnapshot(currentChapterId)
    }
    _resetInternal()
  }

  // ===== NLE-ADF 2.0 作者模式键位（捕获阶段） =====
  // 深度清脂防重入标记（LLM 洗涤期间重复按 Alt+Shift+↓ 不叠加调用）
  let _deepDefatting = false

  /** Alt+Shift+↓ 深度清脂：LLM 重洗光标所在段落（密度超阈值后端才真调 LLM）。 */
  async function _deepDefatParagraph() {
    const editor = chapterEditorHandle.value
    if (!editor) return
    const $from = editor.state.selection.$from
    if ($from.depth < 1) return
    const original = $from.parent.textContent
    if (!original.trim()) return
    _deepDefatting = true
    try {
      // S3 E3：带章节上下文，洗涤顺带处理本书负面清单禁词
      const result: any = await chapterApi.defatSelection({ text: original, chapter_id: currentChapterId || undefined })
      const washed = (result?.text || '').trim()
      if (washed && washed !== original) {
        // 整段替换（与本地清脂同款副作用：段内行内格式丢失，正文场景可接受）
        const $f = editor.state.selection.$from
        if ($f.depth >= 1 && $f.parent.textContent === original) {
          editor
            .chain()
            .command(({ tr }) => {
              tr.insertText(washed, $f.start(), $f.end())
              return true
            })
            .run()
        }
      }
    } catch (e: any) {
      error.value = `深度清脂失败：${e?.message || e}`
      setTimeout(() => { if (error.value?.startsWith('深度清脂失败')) error.value = null }, 3000)
    } finally {
      _deepDefatting = false
    }
  }

  // 静默失败提示的每会话一次闸（B4/B5，引导体系重构 2026-09-20）——
  // 不满足条件的吞键只解释一次，重按不刷屏
  let _ctrlEnterHintShown = false
  let _beatDockDeadKeyHintShown = false

  // 幽灵/缝合/锁拍快捷键在编辑器内生效——必须捕获阶段拦截（bubble 阶段
  // ProMirror 已先消费按键把 Space/Enter 插进文档，拦截失效）。
  function _authoringKeyHandler(e: KeyboardEvent) {
    // 中文输入法组合态全放行：IME 候选期的 Space/Enter/数字是选词键，拦截=灾难
    if (e.isComposing) return
    // 自定义镜头输入框（卡片舱第 5 槽位，第二冲程）聚焦时全放行：作者在舱内
    // 输入框码字，数字/空格/回车是输入本身——作者键位让位（Enter 提交与 Esc
    // 退焦由输入框自身的 keydown 处理，不进本处理器）
    const _kt = e.target as HTMLElement | null
    if (_kt && (_kt.tagName === 'INPUT' || _kt.tagName === 'TEXTAREA')) return
    // Alt+Shift+↓ 深度清脂：LLM 重洗当前段落（本地词级规则之外的深度档）
    if (e.altKey && e.shiftKey && e.code === 'ArrowDown') {
      const editor = chapterEditorHandle.value
      if (editor && !ghostActive.value && !_deepDefatting) {
        e.preventDefault()
        e.stopPropagation()
        void _deepDefatParagraph()
      }
      return
    }
    // Alt+↓ 清脂拨盘：任何阶段可用（无幽灵时），刮掉光标段落的套路修饰词。
    // 词级本地规则（宁漏勿误），Ctrl+Z 可整体撤销；深度 LLM 重洗属 v2。
    if (e.altKey && e.code === 'ArrowDown') {
      const editor = chapterEditorHandle.value
      if (editor && !ghostActive.value) {
        const removed = defatParagraphAtCursor(editor)
        if (removed > 0) {
          e.preventDefault()
          e.stopPropagation()
        }
      }
      return
    }
    // Alt+O：插入/转换细纲胶囊。有选区 → 选中文本转为速记（先打字后转换）；
    // 无选区 → 空胶囊并自动打开浮层。assistEnabled 即可用（不要求 composing 态，
    // 也不依赖步进流设施）；仅编辑器聚焦时拦截。
    if (e.altKey && !e.shiftKey && !e.ctrlKey && !e.metaKey && e.code === 'KeyO') {
      const editor = chapterEditorHandle.value
      const t = e.target as HTMLElement | null
      if (editor && t?.isContentEditable && !ghostActive.value && assistEnabled.value) {
        e.preventDefault()
        e.stopPropagation()
        editor.commands.insertOutlineNote()
      }
      return
    }
    // Tab 结构闸（先于一切状态机门禁）：AI 辅助开启且焦点在正文编辑器内时，
    // Tab 永远被消费，不走浏览器默认焦点导航——否则焦点顺序滑进副驾抽屉 tab 栏，
    // 写作流被打断（2026-08-24 实测复现：未激活/沉淀中/幽灵在屏时按 Tab，
    // 焦点跳到抽屉「打算」按钮）。焦点在编辑器外不碰（抽屉等控件键盘可达性不变）；
    // Shift+Tab 放行，给键盘党留主动退出编辑器的出口。
    if (e.key === 'Tab' && !e.shiftKey && assistEnabled.value) {
      const tabTarget = e.target as HTMLElement | null
      if (tabTarget?.isContentEditable) {
        e.preventDefault()
        e.stopPropagation()
        // 03 三键：Tab=正承诺（采纳）——幽灵在屏时转正为正文（书签开始跟踪，
        // 03 M1）；暂留段上有光标时回场转正。未上膛（流式/缓冲窗）只打断不采纳。
        if (ghostActive.value) {
          if (!ghostArmedGuard()) commitGhostFragment()
          return
        }
        if (ghostParked.value && parkedContainsCursor()) {
          adoptParkedGhost()
          return
        }
        if (!ghostActive.value) {
          // 卡片舱唯一入口（2026-09-09 用户拍板）：自动弹出全线退役
          // （SPARK_DOCK_AUTO_POPUP=false），Tab 恒**强制重算**唤醒——
          // force_refresh 跳过后端缓存命中，每次都是新鲜批次；注入的 summon
          // fn 内部先激活章节再取件（未激活章节按 Tab 也能唤醒，勿加
          // authoringCtx 门——2026-09-09 回归教训）；生成期间连按由
          // _summonInFlight 静默合并，等待期思考点亮；Esc 关舱退出
          _adaptiveSummonFn?.(true)
        }
        return
      }
    }
    // AI 辅助关闭（纯手写模式）：adaptive 分支全部不介入（Space 恢复普通空格、
    // Tab/Ctrl+Space/数字键/Ctrl+Enter 不拦截）。旧步进/创作路径（作者显式起的
    // 「规划本章」）不受影响。
    const adaptiveComposing = assistEnabled.value && adaptiveMode.value && authorLane.value === 'composing'
    const inAuthoringContext = stage.value === 'beat_authoring'
      || (stage.value === 'beat_stepping' && authoringEnabled.value)
      || ghostActive.value
      // NLE-ADF 3.0：adaptive composing 态——作者在正文编辑器里写，
      // Space（缝合/续写）/ Enter（Ctrl+沉淀）/ 数字（吸附）必须在捕获阶段拦截，
      // 否则 ProMirror 在 bubble 阶段先把 Space/Enter 插进文档，拦截失效。
      || adaptiveComposing
      // B5 静默修复（引导体系重构 2026-09-20）：走向舱开着=写作上下文——
      // 非 composing 态（如沉淀中）Esc/数字键也必须可达，否则按键死在舱上
      || beatDockVisible.value
    if (!inAuthoringContext) return
    const target = e.target as HTMLElement | null
    // 编辑器外的表单控件不拦（岔路面板自定义走向文本框等）
    if (target && !target.isContentEditable && (target.tagName === 'INPUT' || target.tagName === 'TEXTAREA')) return

    // Esc：蒸发幽灵 > 丢弃暂留段（光标在内时） > 关走向卡舱 > 关 Dock > 清空吸附
    //（逐层退出 AI 临时元素）
    if (e.key === 'Escape') {
      if (ghostActive.value) {
        e.preventDefault()
        e.stopPropagation()
        evaporateGhost()
        return
      }
      if (ghostParked.value && parkedContainsCursor()) {
        e.preventDefault()
        e.stopPropagation()
        discardParkedGhost()  // 暂留最终丢弃=「看过了但没要」强信号，喂学着闭嘴
        return
      }
      if (beatDockVisible.value) {
        e.preventDefault()
        e.stopPropagation()
        hideBeatDock()
        return
      }
      if (sparkDockVisible.value) {
        e.preventDefault()
        e.stopPropagation()
        hideSparkDock()
        return
      }
      if (attachedParts.value.length) {
        e.preventDefault()
        e.stopPropagation()
        clearAttachedParts()
        return
      }
      return
    }
    // 数字键 1~4：走向卡舱打开时选定走向卡 → 触发 burst 连写
    // （超出卡数 = 末项「自由发挥」，card=null）
    if (beatDockVisible.value && /^Digit[1-4]$/.test(e.code)) {
      e.preventDefault()
      e.stopPropagation()
      const idx = Number(e.code.slice(5)) - 1
      const card = idx < beatCards.value.length ? beatCards.value[idx] : null
      hideBeatDock()
      if (adaptiveComposing) {
        _adaptiveBurstFn?.(card)
      } else if (!_beatDockDeadKeyHintShown) {
        // B5 静默修复：非写作态数字键此前关舱无稿零反馈——明说一次
        _beatDockDeadKeyHintShown = true
        useToast().showToast('走向卡先收起了——AI 此刻不在写作态，写几个字后再试', 'info')
      }
      return
    }
    // 数字键 1~4：Dock 打开时直开单镜头（第二冲程 2026-09-09：极速单镜头
    // 展开——选中即 50 字微缝合，同款 sticky+stash 收舱让位幽灵）；非创作态
    // （含幽灵在屏）退回吸附语义（多枚同缝 + Space 的既有流由鼠标点击可达）
    if (sparkDockVisible.value && /^Digit[1-4]$/.test(e.code)) {
      e.preventDefault()
      e.stopPropagation()
      const idx = Number(e.code.slice(5)) - 1
      const part = sparkParts.value[idx]
      if (part && adaptiveComposing && !ghostActive.value) {
        _adaptiveContinueFn?.('stitch', [
          { text: part.text, direction: part.direction, slot: part.source },
        ])
        setSparkSticky()
        stashSparkDock()
      } else {
        attachSparkPart(idx)
      }
      return
    }
    // ↑↓：Dock 打开时浏览高亮碎片（纯视觉；吸附仍数字键/鼠标）。
    // sticky 态 moveSparkSelection 返回 false → 不拦默认，让 ↑↓ 移光标。
    // ↓ 到末位再按 → 焦点切入自定义镜头输入框（第 5 槽位）——零自动焦点
    // 纪律下唯一的键盘入口（另一入口是直接点击）
    if (sparkDockVisible.value && (e.code === 'ArrowUp' || e.code === 'ArrowDown')) {
      if (e.code === 'ArrowDown' && sparkSelectedIndex.value >= sparkParts.value.length - 1) {
        e.preventDefault()
        e.stopPropagation()
        window.dispatchEvent(new CustomEvent('velluma:dock-focus-custom'))
        return
      }
      if (moveSparkSelection(e.code === 'ArrowUp' ? -1 : 1)) {
        e.preventDefault()
        e.stopPropagation()
      }
      return
    }
    // Enter：幽灵在屏 = 暂留（03 三键：零承诺——最易手滑的键映射到无害动作，
    // 幽灵停在原地光标下移新行；随时回来 Tab 转正 / Esc 丢弃）
    if (e.key === 'Enter' && !e.ctrlKey && !e.metaKey && ghostActive.value) {
      e.preventDefault()
      e.stopPropagation()
      if (!ghostArmedGuard()) parkGhost()
      return
    }
    // Ctrl+Enter：锁死本拍（创作态/代笔裁决态）或沉淀当前段（adaptive composing 态）
    if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) {
      // adaptive composing 态：触发沉淀（走 useAdaptiveAssist.settleCurrent）。
      // ghostStitching 态也走沉淀（行为保持：此前幽灵在屏时 Ctrl+Enter 同样可沉淀）
      const adaptiveSettleable = adaptiveComposing
        || (adaptiveMode.value && assistEnabled.value && authorLane.value === 'ghostStitching')
      if (adaptiveSettleable) {
        e.preventDefault()
        e.stopPropagation()
        _adaptiveSettleFn?.()
        return
      }
      e.preventDefault()
      e.stopPropagation()
      // B4 吞键修复（引导体系重构 2026-09-20）：不满足沉淀条件时此前静默吞键——
      // 作者按了没反应以为坏了；明说一次（仍吞键：作者意图是沉淀，不插换行）
      if (!_ctrlEnterHintShown) {
        _ctrlEnterHintShown = true
        useToast().showToast('沉淀要 AI 辅助开着、且本章写满 4 个字后才可用', 'info')
      }
      return
    }
    // Ctrl+Space：走向卡舱（adaptive composing 态的段落级连写入口）。
    // 注意：旧版中文输入法可能占用 Ctrl+Space 切换——若用户反馈冲突，备选改 Alt+J。
    if (e.code === 'Space' && (e.ctrlKey || e.metaKey)
      && adaptiveComposing
      && !ghostActive.value && !stitching.value) {
      e.preventDefault()
      e.stopPropagation()
      showBeatDock()
      return
    }
    // Space 三分流（作者模式会话激活期才介入；普通编辑永不拦截）：
    //   吸附栏有零件 = 微缝合；创作态空段落 = 召唤代笔；有碎片 = 裸补全
    // NLE-ADF 3.0：adaptive composing 态也介入，走 adaptive 续写注入器。
    const spaceActive = !ghostActive.value && !stitching.value && (
      // 旧路径：拍创作态
      (authoringEnabled.value && (
        stage.value === 'beat_authoring'
        || stage.value === 'tier_classifying'
        || stage.value === 'setup_growing'
      ))
      // 新路径：adaptive composing 态
      || adaptiveComposing
    )
    if (e.code === 'Space' && spaceActive) {
      const editor = chapterEditorHandle.value
      if (!editor) return
      // adaptive 模式分支：零件吸附 → 缝合续写；否则顺句续写
      if (adaptiveComposing) {
        if (attachedParts.value.length) {
          e.preventDefault()
          e.stopPropagation()
          _adaptiveContinueFn?.('stitch', attachedParts.value.map((p) => ({ text: p.text, direction: p.direction, slot: p.source })))
          // 缝合触发：清吸附意图 + 藏舱让位幽灵（2026-08-28 修复：此前 hideSparkDock
          // 直接退出舱、且 setSparkSticky 全工程零调用——「连续吸附多件缝合」从未生效，
          // 打一个字舱就永久消失，每件都要重新停顿 4s/Tab 唤醒。现改为 sticky+stash：
          // 视觉上藏（避免与幽灵草稿重叠），幽灵落定（Tab/Esc）后自动弹回，
          // 打字不再收舱——Esc 关舱仍是唯一退出 sticky 的手动出口）
          clearAttachedParts()
          setSparkSticky()
          stashSparkDock()
          return
        }
        const $fromAd = editor.state.selection.$from
        if ($fromAd.parent.textContent.trim() !== '') {
          e.preventDefault()
          e.stopPropagation()
          // 03 找回窗：Esc 蒸发后短窗内重按 Space 原样重现上一枚幽灵（不重新生成）
          if (tryReviveGhost()) return
          _adaptiveContinueFn?.('continue', [])
          // 顺句续写同样藏舱让位幽灵（2026-08-29 实测事故：此分支漏了
          // sticky+stash——幽灵流式插入触发编辑器活动，非 sticky 态走
          // hideSparkDock 连 sticky 一并清掉，Space 后侧栏零件直接蒸发，
          // 幽灵落定后的回弹钩子查 sticky=false 永不弹回；缝合分支 08-28
          // 修过，顺句分支漏网，同款语义补齐）
          setSparkSticky()
          stashSparkDock()
          return
        }
        return  // 空行 + 无零件：不拦截（adaptive 模式不召唤代笔，由作者主动）
      }
      // BS-ADF 归档：旧步进路径的 Space 分支（吸附缝合/空行代笔/裸补全）已移除；
      // adaptive 分支在前已 return，此处放行默认空格
    }
  }
  onMounted(() => window.addEventListener('keydown', _authoringKeyHandler, true))
  onUnmounted(() => {
    // 卸载即中止在途 SSE：否则流继续跑到终态事件，期间 mutate 已卸载 session
    // 的 ref（有界泄漏）；主动 abort 在 sse.ts 按非错误静默结束
    if (abortController) {
      abortController.abort()
      abortController = null
    }
    window.removeEventListener('keydown', _authoringKeyHandler, true)
  })

  return {
    stage,
    generating,
    error,
    stepProgress,
    engine,
    // BS-ADF
    // NLE-ADF 步进
    // rerender-beat 成功后的待落库正文信号（WorkspaceView watch → 落库）
    // NLE-ADF 2.0 作者模式
    isTerminal,
    cancel,
    reset,
    // 持久化：进入章节时调 loadForChapter 恢复上次产物
    loadForChapter,
    persist,
    // NLE-ADF 3.0 双轴状态机（自适应融合）
    authorLane,
    aiLane,
    adaptiveMode,
    chapterTargetWords,
    adaptiveSuggestions,
    planSuggestions,
    dynamicBeats,
    finishReport,
    settleResult,
    enterAdaptive,
    exitAdaptive,
    setAdaptiveContinue,
    setAdaptiveSettle,
    setAdaptiveFinish,
    triggerAdaptiveFinish,
    setAdaptiveBurst,
    setAdaptiveSummon,
    setAdaptiveAbort,
  }
}

