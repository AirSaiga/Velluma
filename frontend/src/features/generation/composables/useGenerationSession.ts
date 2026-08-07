/**
 * 统一生成会话（V3.1 F3 新建，规格 §11.2）。
 *
 * 职责：封装 V3.2 ADF（/generate-adf）生成链路，
 * 外加 V4.1 Refinery 精修（/refinery/diagnose + /refinery/confirm）的两阶段 SSE，
 * 把原始事件流解析为会话状态机供 UI 订阅。
 *
 * 引擎：BS-ADF 步进模式（bsadfApi.start，消费 BSADF_STAGE/ADF_ANCHOR_DESIGNED/... 事件）。
 * V3.1 Unified 引擎后端已剥离（/generate 端点不存在），相关死代码（startUnified 等）已删除。
 * V3.2 ADF 整章生成入口（start/startAdf/adfApi.streamGenerate）已移除，前端不再有 ADF UI 入口。
 *
 * BS-ADF 引擎（/generate-bsadf）当前只以「步进模式」运行：
 * startBeat(enable_stepping=true) → 槽位卡就绪 → 逐段渲染/裁决 → COMPLETE。
 * Track A/B 全章自动/单次暂停路径为历史兼容，前端不再调用 confirmBeats 入口。
 *
 * V4.1 Refinery 两阶段（独立于 start，生成完成后调用）：
 * - startRefinery：诊断阶段，产出问题清单后停在 refining 等作者确认
 * - confirmRefinery：作者决策后执行手术 + 回读 + 抛光
 *
 * 会话状态机（stage）：
 *   idle → tier_classifying → ... → done / error
 *
 * 关键产物（UI 订阅）：
 * - tierDecision：定档结果（高潮章/转折章/推进章/过渡章 + 理由）
 * - stepProgress：当前步骤（阶段名 + 进度）
 * - streamText：流式正文
 * - adfAnchor/preconditions/emotionCurve/audit：V3.2 ADF 专用产物
 * - refineryIssues/surgeries/holisticVerdict：V4.1 精修产物
 * - degraded：降级事件
 */
import { ref, computed, watch, onMounted, onUnmounted, type Ref, type ComputedRef } from 'vue'
import { refineryApi, bsadfApi, chapterApi, type AdfEngine, type AdfAuditResult, type RefineryIssue, type RefinerySurgery, type RefineryHolisticVerdict, type IssueDecision, type BeatSlot, type RenderProgress, type DegradedBeat, type ChapterDecisionSet, type RescueNeededItem } from '../../../services/api/domain'
import { formatDegradedReason } from '../../../shared/constants/degradation'
import { chapterEditorHandle } from '../../chapter-editor/editorHandle'
import {
  ghostActive, ghostSource, ghostDirty,
  beginGhost, appendGhost, ghostText, commitGhost, evaporateGhost,
} from './useGhostDraft'
import {
  sparkDockVisible, attachedParts,
  setSparkDockGate, setSparkParts,
  showSparkDock, hideSparkDock, clearAttachedParts, attachSparkPart, setSparkSticky,
  type SparkPart,
} from './useSparkDock'
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

/** 可序列化的会话快照（ref 值的子集——排除瞬时态，如 inflightEvents / refineryRunId） */
interface SessionSnapshot {
  v: number
  chapterId: string
  stage: SessionStage
  engine: AdfEngine
  stepProgress: StepProgress | null
  tierDecision: TierDecision | null
  streamText: string
  climaxScore: number | null
  auditVerdict: string | null
  auditFindings: AuditFinding[]
  degraded: any[]
  finalStats: Record<string, any> | null
  // V3.2 ADF 产物
  adfAnchor: any | null
  adfPreconditions: any[]
  adfEmotionCurve: any[]
  adfAudit: any | null
  // V4.1 Refinery 产物
  refineryIssues: RefineryIssue[]
  refinerySurgeries: RefinerySurgery[]
  refineryHolisticVerdict: RefineryHolisticVerdict | null
  refineryStats: Record<string, any> | null
  // BS-ADF 产物（beatRunId 是临时凭证，不持久化，故不在此）
  beatSlots?: BeatSlot[]
  renderProgress?: RenderProgress[]
  degradedBeats?: DegradedBeat[]
  decisionSet?: ChapterDecisionSet | null
  rescueNeeded?: RescueNeededItem[]
  /** 步进段态：各段正文 + 已锁集合。刷新恢复后 done 态单段重渲（rerenderBeat）
   *  靠 segmentTexts 重建终稿——不持久化则刷新后重建只剩刚重渲的一段，
   *  落库把全章覆盖成单段（真实数据丢失事故）。 */
  segmentTexts?: Record<string, string>
  lockedBeatIds?: string[]
  /** 引擎守卫与渲染期进度视图分工标记（恢复快照时一并还原，防切章残留） */
  bsadfTrack?: 'A' | 'B' | null
  steppingEnabled?: boolean
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

/**
 * 当前任务焦点（渲染阶段「当前任务」焦点条的派生数据）。
 *
 * 职责：把散落的渲染阶段引导收敛成"作者此刻只需做一件事"的单一焦点。
 * 这是纯派生 computed，不引入新状态、不改 action，只读现有 ref。
 */
export interface CurrentTask {
  /** 焦点类型，决定焦点条渲染哪个形态 */
  kind:
    | 'edit-beats' // 渲染前：分镜卡就绪，等作者检查后开始渲染（Track B 单次暂停）
    | 'rendering' // 渲染中：某段正在渲染，纯进度无按钮
    | 'advance' // 裁决态：某段已就绪，等作者三选一（接受/改/重写）
    | 'post-rescue' // 完成但有降级/救援段需复查
    | 'done' // 全部完成，无待处理
    | 'idle' // 非渲染阶段 / 岔路门（决策在 BranchDecisionPanel，焦点条不渲染）
  /** 焦点条主标题（作者语言，如"第 2 段已生成 · 1180 字"） */
  title: string
  /** 副标题/提示（作者语言，如"这段写了「与守卫正面对峙」"） */
  hint?: string
  /**
   * 当前段是否渲染降级（advance 态专用）。
   * 降级段正文为空、终稿会消失，焦点条据此重组按钮：把「重写本段」提为
   * 主操作、弱化「接受」并明示后果、隐藏 Space 快捷键栏，避免作者按
   * 习惯按 Space 导致该段默默丢失（降级引导事故）。
   */
  degraded?: boolean
  /** 当前段号（1-based），用于"第 N/M 段" */
  segIndex?: number
  /** 总段数 */
  segTotal?: number
  /**
   * 当前段是否末段（advance 态专用）。
   * 后端靠循环退出触发 COMPLETE、不传 is_last 标志，前端以
   * segment_index === total-1 自行判断。用于把"进入下一段"措辞
   * 改为"完成本章"，避免末段按钮显示"进入第 N+1 段"（误导事故）。
   */
  isLast?: boolean
  /**
   * 主行动按钮（最多 1 个；rendering 态为 undefined 表示无按钮纯等待）。
   * action 决定父级调哪个 session 方法。
   */
  primary?: {
    label: string
    hint?: string // 右侧小字（如"Space"）
    action: 'accept' // accept→advanceBeat('pass')；start-render 已移除（见 beat_pending 分支注释）
  }
}

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

/** 定档决策 */
export interface TierDecision {
  tier: 'climax' | 'turn' | 'progress' | 'transition'
  reason: string
  climax_score?: number | null
  forced_by_user: boolean
  max_depth: number
  development_ratio: number
}

/** 飞行中调节事件 */
export interface InflightEvent {
  type: string
  [k: string]: any
}

/** 审校问题（F4 点击定位用，带 offset） */
export interface AuditFinding {
  severity?: string
  category?: string
  quote?: string
  offset?: [number, number]
  detail?: string
  suggestion?: string
}

export interface GenerationSession {
  // 状态
  stage: Ref<SessionStage>
  generating: Ref<boolean>
  error: Ref<string | null>
  stepProgress: Ref<StepProgress | null>
  engine: Ref<AdfEngine>
  // 产物
  tierDecision: Ref<TierDecision | null>
  streamText: Ref<string>
  climaxScore: Ref<number | null>
  inflightEvents: Ref<InflightEvent[]>
  auditFindings: Ref<AuditFinding[]>
  auditVerdict: Ref<string | null>
  degraded: Ref<any[]>
  finalStats: Ref<Record<string, any> | null>
  /** 最近一次完成来自 ADF 还是 Refinery 还是 BS-ADF（弹窗标题用） */
  lastDoneMode: Ref<'adf' | 'refinery' | 'bsadf' | null>
  // V3.2 ADF 专用产物
  adfAnchor: Ref<any | null>
  adfPreconditions: Ref<any[]>
  adfEmotionCurve: Ref<any[]>
  adfAudit: Ref<any | null>
  // V4.1 Refinery 精修产物
  refineryIssues: Ref<RefineryIssue[]>
  refineryRunId: Ref<string | null>
  refinerySurgeries: Ref<RefinerySurgery[]>
  refineryHolisticVerdict: Ref<RefineryHolisticVerdict | null>
  refineryStats: Ref<Record<string, any> | null>
  // BS-ADF 产物
  beatSlots: Ref<BeatSlot[]>
  beatRunId: Ref<string | null>
  renderProgress: Ref<RenderProgress[]>
  degradedBeats: Ref<DegradedBeat[]>
  /** 本次 BS-ADF 生成选择的轨道；null = 当前会话未跑过 BS-ADF（引擎守卫用） */
  bsadfTrack: Ref<'A' | 'B' | null>
  /** 本次 BS-ADF 是否步进模式（渲染期进度视图分工用） */
  steppingEnabled: Ref<boolean>
  /** 正在单卡重渲染（/rerender-beat）的 beat_id；null = 无进行中重渲染 */
  rerenderingBeatId: Ref<string | null>
  /** DDE 章节级剧情分叉决策集（Track A 由 DDE_AUTO_APPLIED 给；Track B 随 BEAT_SLOTS_BUILT 内嵌） */
  decisionSet: Ref<ChapterDecisionSet | null>
  /** 救援标记：审计判核心转折未落地的节拍（RESCUE_NEEDED 事件 / COMPLETE 载荷） */
  rescueNeeded: Ref<RescueNeededItem[]>
  // NLE-ADF 步进产物
  /** 各段已渲染文本（按 beat_id 索引） */
  segmentTexts: Ref<Record<string, string>>
  /** 当前已就绪等空格推进的 beat_id；null = 无段在等推进 */
  readyBeatId: Ref<string | null>
  /** 就绪段对应的卡片快照（advanceBeat 可带 editedSlot 编辑） */
  readyBeatCard: Ref<BeatSlot | null>
  /** 已锁死的 beat_id 集合 */
  lockedBeatIds: Ref<Set<string>>
  /** 正在渲染的 beat_id；null = 无段在渲染 */
  renderingBeatId: Ref<string | null>
  /** Loop1 大纲自检结果（hard_facts/gaps/critique_pass/violations） */
  loop1Result: Ref<{ hard_facts: any[]; gaps: any[]; critique_pass: boolean; violations: any[] } | null>
  /** 步进会话 run_id（advanceBeat 推进用，来自 BEAT_SLOTS_BUILT） */
  steppingRunId: Ref<string | null>
  /** 各段抽取的涌现事实（Loop3 记忆注入产物，按 beat_id 索引） */
  emergentFacts: Ref<Record<string, any>>
  /** 步进态待作者选择的 DDE 岔路门（null = 无待决策岔路） */
  branchChoicePending: Ref<{
    beat_id: string
    segment_index: number
    node: { beat_id: string; node_title: string; options: { option_id: string; label: string; plot_impact: string }[]; default_option: string; source?: 'dde' | 'loop1_gap' }
    card: BeatSlot | null
  } | null>
  /** 当前就绪段是否渲染降级（BEAT_RENDER_READY.degraded 载荷；裁决焦点条据
   *  此显示降级警告 + 引导「重写本段/跳过本段」） */
  readyBeatDegraded: Ref<{
    beat_id?: string
    segment_index?: number
    reason?: string
    attempts?: number
  } | null>
  /** rerender-beat 成功后的待落库正文（非空 = 待落库；落库后消费方清空） */
  pendingSaveText: Ref<string | null>
  /** 主编辑器直改：作者是否改过当前就绪段（dirty → 接受时走 lock_with_text） */
  readySegmentDirty: Ref<boolean>
  /** 主编辑器直改：裁决期作者输入实时回写当前就绪段文本 */
  setReadySegmentText: (text: string) => void
  /** 主编辑器直改：放弃作者改动，还原为 LLM 原文 */
  revertReadySegment: () => void
  /** 裁决「接受」路由：dirty 走 lock_with_text（作者文本定稿），否则 pass */
  acceptReadySegment: (chapterId: string) => void
  // ===== NLE-ADF 2.0 作者模式 =====
  /** 本次 BS-ADF 是否作者模式（拍不自动渲染：作者写碎片微缝合 / 空行 Space 召唤代笔） */
  authoringEnabled: Ref<boolean>
  /** 当前开放创作的拍（BEAT_AUTHORING_OPEN；null = 无创作中的拍） */
  authoringBeatId: Ref<string | null>
  /** 创作拍卡快照（Spark Dock 零件与导演意图数据源） */
  authoringBeatCard: Ref<BeatSlot | null>
  /** 微缝合进行中（Space 触发 → STITCH_DONE/ERROR） */
  stitching: Ref<boolean>
  /** 各拍已锁碎片数（幽灵时间轴 ● 节点数据源，按 beat_id 索引） */
  fragmentCounts: Ref<Record<string, number>>
  /** 微缝合：取光标处作者碎片 + 点选零件 → 幽灵草稿流式灌入画布 */
  requestStitch: (pickedParts: string[]) => void
  /** Ctrl+Enter 锁死本拍：创作区全部文本走 lock_with_text（空 = skip） */
  lockAuthoringBeat: () => void
  /** Enter 锁死当前幽灵碎片：摘 mark 变正文（幽灵时间轴 ●+1） */
  commitGhostFragment: () => boolean
  /** 空行 Space = 召唤 AI 整段代笔（advanceBeat action=render） */
  summonGhostRender: () => void
  /** 时间轴回拨：恢复当前创作拍到第 count 个碎片锁死时的文档（v1 仅当前拍内） */
  scrubToFragment: (beatId: string, count: number) => boolean
  /** 软切淡提示（AutoCutHint 数据源；非空 = 展示中） */
  autoCutNotice: Ref<{ beatId: string; message: string } | null>
  /** 软切撤回合并：back 回退本拍但保留全部文档文本 */
  mergeAutoCut: () => void
  // 派生
  isTerminal: ComputedRef<boolean>
  /** 渲染阶段「当前任务」焦点（驱动右栏焦点条；纯派生，不持久化） */
  currentTask: ComputedRef<CurrentTask>
  // 控制
  cancel: () => void
  reset: () => void
  /** 失败重试：再次触发最近一次入口（精修诊断 startRefinery / BS-ADF startBeat） */
  retry: () => void
  // V4.1 Refinery 控制
  startRefinery: (chapterId: string, opts?: { mode?: 'deep' | 'light'; enablePolish?: boolean; rawText?: string | null }) => void
  confirmRefinery: (chapterId: string, decisions: IssueDecision[], customIssues?: RefineryIssue[]) => void
  // BS-ADF 控制
  startBeat: (chapterId: string, tier: string, opts?: { track?: 'A' | 'B'; targetWordCount?: number | null; maxSegments?: number; authorIntent?: string; expectationActions?: Record<string, string>; steppingEnabled?: boolean; enableAuthoring?: boolean; freshCanvas?: boolean; enableOutlineSelfCheck?: boolean; enableMemoryIngestion?: boolean }) => void
  confirmBeats: (chapterId: string, editedSlots: BeatSlot[], opts?: { branchChoices?: Record<string, string>; skipped?: boolean }) => void
  cancelBeat: () => void
  /** BS-ADF：降级/救援单卡重渲染（调 /rerender-beat，同步 JSON；editedSlot 携带作者编辑后的整卡） */
  rerenderBeat: (chapterId: string, beatId: string, editedSlot: BeatSlot) => Promise<any>
  /** NLE-ADF：步进锁死推进（每段就绪后作者按 Space 推进下一段）。
   *  P2/P3 新增 action：lock_with_text（作者文本定稿）/ back（回退上一段） */
  advanceBeat: (
    chapterId: string,
    action: 'pass' | 'edit' | 'branch' | 'skip' | 'lock_with_text' | 'back' | 'render',
    opts: {
      beatId: string
      editedSlot?: BeatSlot
      branchChoice?: { option_id: string; label: string; plot_impact: string }
      authorText?: string
    },
  ) => void
  /** NLE-ADF：提交步进岔路选择（optionId=null 表示接受默认走向） */
  submitBranchChoice: (optionId: string | null) => void
  // 持久化：进入章节时恢复上次会话产物（localStorage）
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
  setAdaptiveContinue: (fn: ((mode: 'stitch' | 'continue', parts: Array<{ text: string; direction?: string }>) => void) | null) => void
  /** 注入 adaptive 沉淀函数（由 useAdaptiveAssist 注入，Ctrl+Enter composing 态触发） */
  setAdaptiveSettle: (fn: (() => void) | null) => void
  /** 注入 adaptive 完稿函数（由 useAdaptiveAssist 注入，InspectorPanel 完稿按钮触发） */
  setAdaptiveFinish: (fn: (() => void) | null) => void
  /** 触发 adaptive 完稿审计 */
  triggerAdaptiveFinish: () => void
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


  const tierDecision = ref<TierDecision | null>(null)
  const streamText = ref('')
  const climaxScore = ref<number | null>(null)
  const inflightEvents = ref<InflightEvent[]>([])
  const auditFindings = ref<AuditFinding[]>([])
  const auditVerdict = ref<string | null>(null)
  const degraded = ref<any[]>([])
  const finalStats = ref<Record<string, any> | null>(null)
  /** 最近一次完成来自哪条流程（供完成弹窗区分标题） */
  const lastDoneMode = ref<'adf' | 'refinery' | 'bsadf' | null>(null)
  /** 本次生成开始时间戳（ms），onDone 时计算耗时；不持久化（刷新后无法准确恢复） */
  let startedAt: number | null = null

  // V3.2 ADF 专用产物
  const adfAnchor = ref<any | null>(null)
  const adfPreconditions = ref<any[]>([])
  const adfEmotionCurve = ref<any[]>([])
  const adfAudit = ref<any | null>(null)

  // V4.1 Refinery 精修产物
  const refineryIssues = ref<RefineryIssue[]>([])
  const refineryRunId = ref<string | null>(null)
  const refinerySurgeries = ref<RefinerySurgery[]>([])
  const refineryHolisticVerdict = ref<RefineryHolisticVerdict | null>(null)
  const refineryStats = ref<Record<string, any> | null>(null)

  // BS-ADF 产物
  const beatSlots = ref<BeatSlot[]>([])
  const beatRunId = ref<string | null>(null)
  // rerender 上下文 run_id：完成态下 beatRunId 已清空，但 /rerender-beat 需要它
  // 从 _PENDING_BEAT_SLOTS 取完整渲染上下文（专名表/场景设定/canon）。
  // Track A：onDone 时存 COMPLETE 的 generation_run_id；
  // Track B：confirmBeats 时存原始暂停 run_id（pending 的 key 是它，不是 confirm 的新 run_id）。
  const rerenderRunId = ref<string | null>(null)
  const renderProgress = ref<RenderProgress[]>([])
  const degradedBeats = ref<DegradedBeat[]>([])
  const bsadfTrack = ref<'A' | 'B' | null>(null)
  /** 本次 BS-ADF 是否步进模式（P5：步进态逐段列表与卡状态灯重叠，按此隐藏 BeatProgress 列表） */
  const steppingEnabled = ref(false)
  const rerenderingBeatId = ref<string | null>(null)
  // DDE 章节级剧情分叉（Track A：DDE_AUTO_APPLIED；Track B：BEAT_SLOTS_BUILT 内嵌）
  const decisionSet = ref<ChapterDecisionSet | null>(null)
  // 救援标记：核心转折未落地的节拍（路线 C 内联救援卡数据源）
  const rescueNeeded = ref<RescueNeededItem[]>([])

  // ===== NLE-ADF 步进状态 =====
  const segmentTexts = ref<Record<string, string>>({})
  /**
   * 待落库正文信号：rerender-beat 成功重渲单段后，新正文需写回章节库（步进模式
   * 后端不自动落库，落库责任在前端）。stage 已是 done、watch stage→done 不会重触发，
   * 故在此置新正文，由 WorkspaceView watch 本字段 → store.updateChapter 落库。
   * null = 无待落库；非空 = 待落库的完整正文（落库后由消费方清空）。
   */
  const pendingSaveText = ref<string | null>(null)
  const readyBeatId = ref<string | null>(null)
  const readyBeatCard = ref<BeatSlot | null>(null)
  const lockedBeatIds = ref<Set<string>>(new Set())
  const renderingBeatId = ref<string | null>(null)
  const loop1Result = ref<{
    hard_facts: any[]
    gaps: any[]
    critique_pass: boolean
    violations: any[]
  } | null>(null)
  const steppingRunId = ref<string | null>(null)
  // 风险3修复：轮询定时器变量提前声明（避免 TDZ：_resetInternal 调用 _stopSteppingPoll）
  let _steppingPollTimer: ReturnType<typeof setTimeout> | null = null
  let _steppingPollCount = 0
  const _STEPPING_POLL_MAX = 90  // 最多 90 次（约 3 分钟）
  const emergentFacts = ref<Record<string, any>>({})
  // NLE-ADF 步进岔路门：当前待作者选择的 DDE 节点（null = 无待决策岔路）
  const branchChoicePending = ref<{
    beat_id: string
    segment_index: number
    node: { beat_id: string; node_title: string; options: { option_id: string; label: string; plot_impact: string }[]; default_option: string; source?: 'dde' | 'loop1_gap' }
    card: BeatSlot | null
  } | null>(null)
  // 当前就绪段是否渲染降级（BEAT_RENDER_READY.degraded 载荷）。
  // 步进模式下后端不发 BEAT_DOWNGRADED 事件，降级信息只挂在 READY 上——
  // 此前被丢弃，作者只见"0 字"不知是降级。裁决焦点条据此显示警告 + 引导重写/跳过。
  const readyBeatDegraded = ref<{
    beat_id?: string
    segment_index?: number
    reason?: string
    attempts?: number
  } | null>(null)
  // ===== 主编辑器直改（裁决窗口期当前段可编辑） =====
  // 就绪段的服务器原文快照：dirty 判定基准 +「放弃改动」还原用。
  // watch readyBeatId 统一快照，覆盖 SSE onBeatReady / 轮询恢复 / resync 三条路径。
  const readySegmentOriginal = ref('')
  // 作者是否在主编辑器改过当前就绪段（dirty → 接受时走 lock_with_text 而非 pass）
  const readySegmentDirty = ref(false)
  watch(readyBeatId, (newId) => {
    readySegmentDirty.value = false
    readySegmentOriginal.value = newId ? (segmentTexts.value[newId] || '') : ''
  })

  /** 主编辑器直改回写：裁决期作者在当前段的每次输入同步到 segmentTexts
   *  （预览随之 rebuild；与原文不一致才标 dirty，改回去 = 恢复干净态）。 */
  function setReadySegmentText(text: string) {
    const id = readyBeatId.value
    if (!id) return
    segmentTexts.value = { ...segmentTexts.value, [id]: text }
    streamText.value = Object.values(segmentTexts.value).join('\n\n')
    readySegmentDirty.value = text.trim() !== readySegmentOriginal.value.trim()
  }

  /** 放弃作者改动：还原为 LLM 原文（预览 rebuild 后编辑器显示原文） */
  function revertReadySegment() {
    const id = readyBeatId.value
    if (!id || !readySegmentDirty.value) return
    segmentTexts.value = { ...segmentTexts.value, [id]: readySegmentOriginal.value }
    streamText.value = Object.values(segmentTexts.value).join('\n\n')
    readySegmentDirty.value = false
  }

  /** 裁决「接受」：作者改过正文则走 lock_with_text（作者文本定稿，跳过 LLM），
   *  否则 pass。Space 快捷键与焦点条①按钮共用本路由。
   *  特例：作者把正文删空（dirty 但 text 为空）=「不要这段」，路由到 skip——
   *  走 pass 会把 LLM 原文静默锁进终稿，与作者意图完全相反（真实事故）。
   *
   *  NLE-ADF 3.0：作者模式裁决态（代笔就绪）下，画布幽灵草稿是事实源——
   *  作者可能已改幽灵文本，segmentTexts 路由感知不到画布编辑，走 pass 会丢字。
   *  此态委托 lockAuthoringBeat（读画布文档 [base, docEnd]，统一锁拍路由），
   *  保证「画布即事实源」。非作者模式仍走 segmentTexts 路由（预览投影态）。 */
  function acceptReadySegment(chapterId: string) {
    const id = readyBeatId.value
    if (!id) return
    // 作者模式裁决态：画布即事实源，委托 lockAuthoringBeat
    if (authoringEnabled.value) {
      lockAuthoringBeat()
      return
    }
    const text = (segmentTexts.value[id] || '').trim()
    if (readySegmentDirty.value) {
      if (text) {
        advanceBeat(chapterId, 'lock_with_text', { beatId: id, authorText: segmentTexts.value[id] })
      } else {
        advanceBeat(chapterId, 'skip', { beatId: id })
      }
    } else {
      advanceBeat(chapterId, 'pass', { beatId: id })
    }
  }

  // lock_with_text 提交后，后端 lock_segment_with_author_text 会把作者文本以
  // BEAT_TEXT_CHUNK 全量推回，而作者文本经 setReadySegmentText 已在 segmentTexts 里，
  // onBeatChunk 的 append 会拼成两遍——置一次性替换标记，下一个 chunk 改为整段替换。
  const _chunkReplaceOnce = new Set<string>()

  /** BEAT_TEXT_CHUNK 统一入口：lock_with_text 全量推回做替换，其余 append（流式增量） */
  function _handleBeatChunk(data: { beat_id: string; delta: string }) {
    const prev = _chunkReplaceOnce.has(data.beat_id) ? '' : (segmentTexts.value[data.beat_id] || '')
    _chunkReplaceOnce.delete(data.beat_id)
    segmentTexts.value = { ...segmentTexts.value, [data.beat_id]: prev + data.delta }
    streamText.value = Object.values(segmentTexts.value).join('\n\n')
    _noteSteppingActivity()
  }

  /** 步进活动心跳：任何步进 SSE 事件到达都重置轮询超时计数——
   *  慢渲染（重试/慢模型数分钟）时 SSE 明明健康，90 次计数上限却把会话
   *  误砸成 error（真实事故）。渲染期每个 chunk/start 事件都证明后端活着。 */
  function _noteSteppingActivity() {
    _steppingPollCount = 0
  }

  /** back 回退统一回滚：后端弹栈语义是「目标段及之后全部作废重渲」
   *  （stepping_runtime 恢复 target_i 前的快照后从 target_i 依次重渲），
   *  前端必须同步清掉目标段及其后各段的正文/锁定/进度——只清目标段会让
   *  后段旧文本在重渲时被 chunk append 拼成翻倍、状态轨残留陈旧「已就绪」灯。 */
  function _rollbackFromBeat(beatId: string, segmentIndex?: number) {
    const targetIdx = segmentIndex
      ?? beatSlots.value.find(s => s.beat_id === beatId)?.segment_index
      ?? 0
    const affected = new Set<string>([beatId])
    for (const s of beatSlots.value) {
      if (typeof s.segment_index === 'number' && s.segment_index >= targetIdx) {
        affected.add(s.beat_id)
      }
    }
    const texts = { ...segmentTexts.value }
    for (const id of affected) delete texts[id]
    segmentTexts.value = texts
    streamText.value = Object.values(segmentTexts.value).join('\n\n')
    lockedBeatIds.value = new Set([...lockedBeatIds.value].filter(id => !affected.has(id)))
    renderProgress.value = renderProgress.value.filter(p => !affected.has(p.beat_id))
    // 作者模式：回滚拍的碎片计数一并作废（幽灵时间轴节点退回 ○）
    const counts = { ...fragmentCounts.value }
    for (const id of affected) delete counts[id]
    fragmentCounts.value = counts
  }

  /** 重渲/跳过前清段文本：BEAT_TEXT_CHUNK 在步进模式是整段全量推回
   *  （bsadf_workflow render_one），append 语义下旧文本必须先行清除，
   *  否则 edit/back 重渲后旧文+新文拼成两倍（真实正文翻倍事故）。 */
  function _clearSegmentText(beatId: string) {
    if (!(beatId in segmentTexts.value)) return
    const texts = { ...segmentTexts.value }
    delete texts[beatId]
    segmentTexts.value = texts
    streamText.value = Object.values(segmentTexts.value).join('\n\n')
  }

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

  // ===== 无感自沉淀（三重门 + 软切混合；常量即 UX 规划案的时机旋钮） =====
  const AUTO_LOCK_MIN_PAUSE_MS = 5000   // 停顿门：连续无输入时长
  const AUTO_LOCK_MIN_INTERVAL_MS = 30000  // 间隔门：距上次沉淀
  const AUTO_LOCK_READY_RATIO = 0.9     // 字数门：拍目标达成度
  const SOFT_CUT_RATIO = 1.2            // 软切阈值：一气呵成写过头时句界收束
  let _lastEditTs = 0
  let _lastLockTs = 0
  let _sedimentTimer: ReturnType<typeof setInterval> | null = null
  /** 软切淡提示（AutoCutHint 数据源） */
  const autoCutNotice = ref<{ beatId: string; message: string } | null>(null)
  let _autoCutTimer: ReturnType<typeof setTimeout> | null = null
  /** 软切后余文顺延：下次 AUTHORING_OPEN 的创作区基线 */
  let _pendingCarryBasePos: number | null = null
  /** 撤回合并后该拍目标临时翻倍（防立刻再切同一拍） */
  let _mergeBoostBeatId: string | null = null
  /** 撤回合并标记：下一次 back 回退保留文档文本（只回生成状态） */
  let _keepTextOnNextRollback = false

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

  /** BEAT_AUTHORING_OPEN 统一处理（SSE 事件 / 轮询自愈 / 失步 resync 三路共用）。
   *  与岔路门同理：挂起等作者期间必须停轮询（run 无限期等动作，90 次上限会误报超时）。 */
  function _onBeatAuthoringOpen(data: { beat_id: string; segment_index: number; target_word_count?: number; card_snapshot?: BeatSlot }) {
    _stopSteppingPoll()
    authoringBeatId.value = data.beat_id
    authoringBeatCard.value = data.card_snapshot
      || beatSlots.value.find(s => s.beat_id === data.beat_id)
      || null
    renderingBeatId.value = null
    readyBeatId.value = null
    readyBeatDegraded.value = null
    stage.value = 'beat_authoring'
    generating.value = false
    // 记录创作区基线。栈里已有本拍（back 重开 / resync 重建）→ 复用旧基线
    // （重开前的本拍碎片文本仍在文档里，新基线会把它漏出 authorText）；
    // 软切顺延 → 用句界切点作基线（余文归本拍）；
    // freshCanvas 首开 → 文档开头（开局自由文字归入拍 0）；
    // 否则以当前文档末尾为新基线压栈。
    const editor = chapterEditorHandle.value
    const existIdx = beatBaseStack.findIndex(e => e.beatId === data.beat_id)
    if (existIdx >= 0) {
      authoringBasePos = beatBaseStack[existIdx].basePos
      beatBaseStack.length = existIdx + 1
    } else {
      if (_pendingCarryBasePos != null) {
        const docEnd = editor ? editor.state.doc.content.size : _pendingCarryBasePos
        authoringBasePos = Math.min(_pendingCarryBasePos, docEnd)
        _pendingCarryBasePos = null
      } else if (_freshCanvas && beatBaseStack.length === 0) {
        authoringBasePos = 0
      } else {
        authoringBasePos = editor ? editor.state.doc.content.size : 0
      }
      beatBaseStack.push({ beatId: data.beat_id, basePos: authoringBasePos })
    }
    // 合并助推只对本拍有效（开新拍即失效）
    if (_mergeBoostBeatId && _mergeBoostBeatId !== data.beat_id) _mergeBoostBeatId = null
    fragmentAnchorPos = authoringBasePos
    // 拍基线快照（count=0）：本拍"全部撤销"的回拨终点（重开不重复记录）
    if (!fragmentSnapshots.value.some((s) => s.beatId === data.beat_id && s.count === 0)) {
      _snapshotFragment(data.beat_id, 0)
    }
    upsertRenderProgress(data.beat_id, 'ready', { segmentIndex: data.segment_index })
    stepProgress.value = {
      label: '等你创作',
      index: (data.segment_index ?? 0) + 1,
      total: beatSlots.value.length,
    }
  }

  /** 微缝合：取 [碎片锚点, 光标] 的作者碎片 + 点选零件，SSE 流式灌成幽灵草稿。
   *  自由缝合：无 run/拍（开局管线未就绪）也可调用——缝合不等卡。 */
  function requestStitch(pickedParts: string[]) {
    const editor = chapterEditorHandle.value
    if (!editor || stitching.value) return
    if (!currentChapterId) return
    const doc = editor.state.doc
    const selFrom = editor.state.selection.from
    // 碎片 = [碎片锚点, 光标] 区间文本（作者自上次锁碎片后写的全部内容）；
    // 截尾 200 字防既有长文档被整段当碎片（schema 上限 500）
    const fragment = doc.textBetween(Math.min(fragmentAnchorPos, selFrom), selFrom, '\n\n').trim().slice(-200)
    if (!fragment) return
    // 衔接上文 = [本拍基线, 碎片锚点]（本拍此前已锁的碎片）
    const rolling = doc.textBetween(
      Math.min(authoringBasePos, doc.content.size),
      Math.min(fragmentAnchorPos, doc.content.size),
      '\n\n',
    )
    stitching.value = true
    if (stitchAbort) stitchAbort.abort()
    stitchAbort = new AbortController()
    bsadfApi.stitch(currentChapterId, {
      run_id: steppingRunId.value || null,
      beat_id: authoringBeatId.value || null,
      fragment,
      picked_parts: pickedParts,
      rolling_prefix: rolling,
    }, {
      onStart: () => {
        beginGhost('stitch')
      },
      onChunk: (delta) => {
        appendGhost(delta)
      },
      onDone: () => {
        stitching.value = false
        stitchAbort = null
      },
      onError: (msg) => {
        stitching.value = false
        stitchAbort = null
        // 缝合失败零残留：半截幽灵一并蒸发（Esc 语义），作者碎片原样保留
        evaporateGhost()
        error.value = msg
        setTimeout(() => { if (error.value === msg) error.value = null }, 3000)
      },
    }, stitchAbort.signal)
  }

  /** Enter 锁死当前幽灵碎片：摘 mark 变正文，碎片锚点推进到定稿末尾。 */
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

  /** 时间轴回拨：恢复当前创作拍到第 count 个碎片锁死时的文档状态。
   *  v1 边界：仅当前创作拍内可划（跨已锁拍的回拨走 back 动作链）。 */
  function scrubToFragment(beatId: string, count: number): boolean {
    if (beatId !== authoringBeatId.value) return false
    const snap = fragmentSnapshots.value.find((s) => s.beatId === beatId && s.count === count)
    const editor = chapterEditorHandle.value
    if (!snap || !editor) return false
    if (ghostActive.value) evaporateGhost()
    // 全量恢复（快照含已锁拍前缀，恢复即全局一致）
    const html = snap.text
      .split(/\n\n+/)
      .map((p) => p.trim())
      .filter(Boolean)
      .map((p) => `<p>${p}</p>`)
      .join('')
    editor.commands.setContent(html || '<p></p>', true)
    // 光标落到文档末尾（回拨后继续写的位置），碎片锚点同步复位
    editor.commands.setTextSelection(editor.state.doc.content.size)
    fragmentAnchorPos = editor.state.doc.content.size
    fragmentCounts.value = { ...fragmentCounts.value, [beatId]: count }
    fragmentSnapshots.value = fragmentSnapshots.value.filter(
      (s) => !(s.beatId === beatId && s.count > count),
    )
    return true
  }

  /** 空行 Space = 召唤 AI 整段代笔（渲染路径全闸门原样：降级/字数/岔路）。 */
  function summonGhostRender() {
    if (!currentChapterId || !authoringBeatId.value) return
    if (stage.value !== 'beat_authoring') return
    advanceBeat(currentChapterId, 'render', { beatId: authoringBeatId.value })
  }

  /** Ctrl+Enter 锁死本拍（作者模式主出口）。
   *  创作区 [基线, 文档末尾] 全部文本 = 作者定稿（碎片 + 缝合稿 + 代笔稿 +
   *  一切手动修改），走 lock_with_text；空定稿 = 不要这拍 → skip。 */
  function lockAuthoringBeat() {
    if (!currentChapterId) return
    // 裁决态（代笔就绪）与创作态都可锁拍；其余阶段不响应
    const inAdjudication = stage.value === 'beat_stepping' && !!readyBeatId.value && authoringEnabled.value
    if (stage.value !== 'beat_authoring' && !inAdjudication) return
    const beatId = inAdjudication ? readyBeatId.value! : authoringBeatId.value
    const editor = chapterEditorHandle.value
    if (!beatId || !editor) return
    // 有未提交幽灵：先并入（Ctrl+Enter 的意图显然是连草稿一起定稿）
    if (ghostActive.value) commitGhostFragment()
    const doc = editor.state.doc
    const base = Math.min(authoringBasePos, doc.content.size)
    const text = doc.textBetween(base, doc.content.size, '\n\n').trim()
    _lastLockTs = Date.now()  // 手动沉淀也计入间隔门（防自动沉淀紧跟着连击）
    if (!text) {
      advanceBeat(currentChapterId, 'skip', { beatId })
      return
    }
    advanceBeat(currentChapterId, 'lock_with_text', { beatId, authorText: text })
  }

  /** 作者模式 back 回拨的画布侧回滚：删掉目标拍及之后的创作区文本
   *  （后端弹栈只回滚生成状态，文档里已锁拍的正文不删会混进重写的拍）。
   *  在 onBeatBacked 里调用；目标拍基线保留在栈顶供 AUTHORING_OPEN 复用。
   *  撤回合并模式（_keepTextOnNextRollback）：只回生成状态，文档一字不动。 */
  function _authoringRollbackDoc(beatId: string) {
    const editor = chapterEditorHandle.value
    const entryIdx = beatBaseStack.findIndex(e => e.beatId === beatId)
    if (_keepTextOnNextRollback) {
      _keepTextOnNextRollback = false
      // 保留目标拍基线条目（重开时区域 = 原基线→文档末尾的完整未切文本）
      if (entryIdx >= 0) beatBaseStack.length = entryIdx + 1
      if (ghostActive.value) evaporateGhost()
      return
    }
    if (editor && entryIdx >= 0) {
      const base = Math.min(beatBaseStack[entryIdx].basePos, editor.state.doc.content.size)
      if (base < editor.state.doc.content.size) {
        editor.chain().deleteRange({ from: base, to: editor.state.doc.content.size }).run()
      }
      beatBaseStack.length = entryIdx
    }
    if (ghostActive.value) evaporateGhost()
  }

  // ===== 无感自沉淀引擎 =====
  function _markEditActivity() {
    _lastEditTs = Date.now()
  }
  watch(chapterEditorHandle, (editor, prev) => {
    prev?.off('update', _markEditActivity)
    prev?.off('selectionUpdate', _markEditActivity)
    editor?.on('update', _markEditActivity)
    editor?.on('selectionUpdate', _markEditActivity)
  }, { immediate: true })

  function _startSedimentLoop() {
    if (_sedimentTimer) return
    _sedimentTimer = setInterval(_sedimentTick, 1000)
  }
  function _stopSedimentLoop() {
    if (_sedimentTimer) { clearInterval(_sedimentTimer); _sedimentTimer = null }
  }
  watch(stage, (s) => {
    if (s === 'beat_authoring') _startSedimentLoop()
    else _stopSedimentLoop()
  })

  /** 懒增强载荷应用（SSE 事件与 state 慢查两路共用）：增强卡/决策集/Loop1 刷新，
   *  当前创作拍卡快照同步（Dock 零件随之从种子升级到增强版）。幂等。 */
  function _applyEnhancedCards(data: { beat_slots?: BeatSlot[]; decision_set?: ChapterDecisionSet; loop1_result?: any }) {
    if (Array.isArray(data.beat_slots) && data.beat_slots.length) {
      beatSlots.value = data.beat_slots
    }
    if (data.decision_set) decisionSet.value = data.decision_set
    if (data.loop1_result) loop1Result.value = data.loop1_result
    if (authoringBeatId.value && Array.isArray(data.beat_slots)) {
      const cur = data.beat_slots.find((s) => s.beat_id === authoringBeatId.value)
      if (cur) authoringBeatCard.value = cur
    }
  }

  /** 创作期慢查增强就绪（10s 一次，sediment 循环驱动；SSE 事件的兜底通道） */
  let _enhanceSyncTicks = 0
  async function _syncEnhancedCards() {
    if (!steppingRunId.value) return
    try {
      const resp = await fetch(`/api/chapters/stepping-run/${steppingRunId.value}/state`)
      if (!resp.ok) return
      const st = await resp.json()
      if (st.cards_enhanced && Array.isArray(st.enhanced_beat_slots)) {
        _applyEnhancedCards({
          beat_slots: st.enhanced_beat_slots,
          decision_set: st.enhanced_decision_set,
          loop1_result: st.loop1_result,
        })
      }
    } catch {
      // 静默：增强同步是锦上添花，失败等下一轮
    }
  }

  /** 三重门检查：字数≥目标90% + 停顿≥5s + 距上次≥30s（令牌节度核心） */
  function _sedimentTick() {
    if (stage.value !== 'beat_authoring') return
    if (!authoringBeatId.value || !currentChapterId) return
    if (ghostActive.value || stitching.value || generating.value) return
    // 懒增强慢查（10s 一次）：卡增强就绪后刷新 Dock 零件与决策集
    _enhanceSyncTicks++
    if (_enhanceSyncTicks >= 10) {
      _enhanceSyncTicks = 0
      void _syncEnhancedCards()
    }
    const editor = chapterEditorHandle.value
    if (!editor) return
    const now = Date.now()
    if (now - _lastEditTs < AUTO_LOCK_MIN_PAUSE_MS) return
    if (now - _lastLockTs < AUTO_LOCK_MIN_INTERVAL_MS) return
    const doc = editor.state.doc
    const base = Math.min(authoringBasePos, doc.content.size)
    const region = doc.textBetween(base, doc.content.size, '\n\n')
    const target = authoringBeatCard.value?.target_word_count || 500
    // 撤回合并助推：本拍目标临时翻倍（防立刻再切同一拍）
    const effectiveTarget = _mergeBoostBeatId === authoringBeatId.value ? target * 2 : target
    if (region.trim().length < effectiveTarget * AUTO_LOCK_READY_RATIO) return
    _autoLockCurrentBeat(region.trim(), effectiveTarget)
  }

  /** 软切切点：在 [0.9×target, 1.2×target] 内找最后一个句末标点；找不到返回 -1 */
  function _findSentenceCutIndex(text: string, target: number): number {
    const lo = Math.floor(target * AUTO_LOCK_READY_RATIO)
    const hi = Math.min(text.length - 1, Math.floor(target * SOFT_CUT_RATIO))
    for (let i = hi; i >= lo; i--) {
      if ('。！？…'.includes(text[i])) return i
    }
    return -1
  }

  /** 文本偏移 → PM 位置探测（段落边界两侧计数口径不同，±4 窗口内穷举对齐） */
  function _pmPosForTextOffset(basePos: number, textOffset: number): number | null {
    const editor = chapterEditorHandle.value
    if (!editor) return null
    const doc = editor.state.doc
    const size = doc.content.size
    const guess = Math.min(size, Math.max(basePos, basePos + textOffset))
    for (let delta = 0; delta <= 4; delta++) {
      for (const cand of [guess + delta, guess - delta]) {
        if (cand < basePos || cand > size) continue
        if (doc.textBetween(basePos, cand, '\n\n').length === textOffset) return cand
      }
    }
    return null
  }

  function _showAutoCutNotice(beatId: string) {
    autoCutNotice.value = { beatId, message: '已替你在这里喘了口气（句界收束），余文顺延下一拍' }
    if (_autoCutTimer) clearTimeout(_autoCutTimer)
    _autoCutTimer = setTimeout(() => { autoCutNotice.value = null }, 8000)
  }

  /** 自动沉淀主出口：达标锁定；写过头（≥1.2×目标）时软切——句界前段沉淀，
   *  余文顺延下一拍并给淡提示（可撤回合并）。 */
  function _autoLockCurrentBeat(regionText: string, target: number) {
    const beatId = authoringBeatId.value
    if (!beatId || !currentChapterId) return
    _lastLockTs = Date.now()
    if (regionText.length >= target * SOFT_CUT_RATIO) {
      const cutIdx = _findSentenceCutIndex(regionText, target)
      if (cutIdx > 0) {
        const cutPos = _pmPosForTextOffset(
          Math.min(authoringBasePos, chapterEditorHandle.value?.state.doc.content.size ?? 0),
          cutIdx + 1,
        )
        if (cutPos != null) {
          _pendingCarryBasePos = cutPos
          _showAutoCutNotice(beatId)
          advanceBeat(currentChapterId, 'lock_with_text', {
            beatId,
            authorText: regionText.slice(0, cutIdx + 1),
          })
          return
        }
        // 位置换算失败：整段锁（宁可胖拍，不错切）
      }
    }
    advanceBeat(currentChapterId, 'lock_with_text', { beatId, authorText: regionText })
  }

  /** 软切撤回合并：back 回退本拍但保留全部文档文本；本拍目标临时翻倍。 */
  function mergeAutoCut() {
    const notice = autoCutNotice.value
    if (!notice || !currentChapterId) return
    if (stage.value !== 'beat_authoring' || !authoringBeatId.value) return
    autoCutNotice.value = null
    _mergeBoostBeatId = notice.beatId
    _keepTextOnNextRollback = true
    advanceBeat(currentChapterId, 'back', { beatId: authoringBeatId.value })
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
    // 防御：复位时幽灵草稿不该存在；存在即蒸发（AI 临时元素零残留）
    if (ghostActive.value) evaporateGhost()
    // 沉淀引擎态一并复位
    autoCutNotice.value = null
    if (_autoCutTimer) { clearTimeout(_autoCutTimer); _autoCutTimer = null }
    _pendingCarryBasePos = null
    _mergeBoostBeatId = null
    _keepTextOnNextRollback = false
    _lastLockTs = 0
  }

  let abortController: AbortController | null = null
  let currentChapterId: string | null = null  // 当前 session 绑定的章节（用于持久化 key）

  const isTerminal = computed(() => stage.value === 'done' || stage.value === 'error')

  // ============================================================
  // 派生：当前任务焦点（渲染阶段「当前任务」焦点条的唯一数据源）
  // 纯只读消费现有 ref，不引入新状态。把散落三处的引导收敛为单一焦点。
  // 设计：任何时刻焦点条只表达一件事，最多一个主按钮（或无）。
  // ============================================================
  const currentTask = computed<CurrentTask>(() => {
    const st = stage.value
    const total = beatSlots.value.length
    const segNo = (idx?: number) => (typeof idx === 'number' ? idx + 1 : undefined)

    // 渲染前：Track B 单次暂停，分镜卡就绪。
    // ⚠ 不给主按钮（曾传原始卡 + 空 branch_choices 提交，绕过 StoryboardPanel 的
    // 草稿与分支选择 → 作者编辑静默丢失；分镜卡草稿只存在于 StoryboardPanel 内部，
    // 焦点条无法取得）。开始渲染的唯一出口 = 下方分镜工作台底部 CTA。
    if (st === 'beat_pending') {
      return {
        kind: 'edit-beats',
        title: '分镜卡已就绪',
        hint: '检查下面每张分镜卡（核心转折 / 必现画面 / 台词）后，点击下方「开始渲染」。结构（段数、段序）一旦开始渲染即锁定。',
        segTotal: total,
      }
    }

    // 渲染中：某段正在渲染，纯进度无按钮
    if (st === 'beat_rendering') {
      const rId = renderingBeatId.value
      const slot = rId ? beatSlots.value.find(s => s.beat_id === rId) : null
      const idx = slot?.segment_index
      // 推进过渡态识别：advanceBeat 为即时反馈把 renderingBeatId 设成刚被接受的
      // 旧段，但该段此时已在 lockedBeatIds 里（pass/skip/lock_with_text 已锁），
      // 并非真在渲染——下一段的 BEAT_RENDER_START 要等后端跑完记忆倒灌才到达。
      // 此处据此区分，避免显示误导性的「正在渲染第 N 段」（N=已锁的旧段，
      // 看像在重渲染本段——推进重渲事故）。
      const advancingTransition = !!rId && lockedBeatIds.value.has(rId)
      return {
        kind: 'rendering',
        title: advancingTransition
          ? '正在准备下一段…'
          : (rId ? `正在渲染第 ${segNo(idx)}${total ? '/' + total : ''} 段` : '正在渲染'),
        hint: advancingTransition
          ? '上一段已定稿，正在为下一段整理记忆与状态。'
          : (slot ? `这段写「${slot.core_plot_event}」。完成后会自动停下等你。` : 'AI 正在写，完成后会自动停下等你。'),
        segIndex: advancingTransition ? undefined : segNo(idx),
        segTotal: total,
      }
    }

    // 裁决态：某段已就绪，等作者三选一
    if (st === 'beat_stepping' && readyBeatId.value) {
      const slot = readyBeatCard.value || beatSlots.value.find(s => s.beat_id === readyBeatId.value)
      const idx = slot?.segment_index
      const text = readyBeatId.value ? segmentTexts.value[readyBeatId.value] : ''
      const wc = text ? text.length : 0
      const degradedInfo = readyBeatDegraded.value
      // 是否末段：后端靠循环退出触发 COMPLETE，不传 is_last 标志，前端以
      // segment_index === total-1 自行判断（与 StoryboardPanel 高潮段标记同款）。
      const isLast = total > 0 && (idx ?? -1) + 1 >= total
      // 降级段：正文为空、终稿会消失。明示"接受=这段不进正文"，并把引导重心
      // 从"接受(Space)"转向"重写本段/直接在正文写"（CurrentTaskBar 据 degraded 重组按钮）。
      // 降级 reason 经 formatDegradedReason 翻译，避免裸露英文枚举。
      if (degradedInfo) {
        return {
          kind: 'advance',
          degraded: true,
          title: `⚠ 第 ${segNo(idx)}${total ? '/' + total : ''} 段渲染失败`,
          hint: `原因：${formatDegradedReason(degradedInfo.reason)}（已重试 ${degradedInfo.attempts ?? 2} 次）。这段没有正文。建议「重写本段」让 AI 重试，或直接在左侧正文里写一段（改动随接受定稿）。${isLast ? '这是最后一段。' : ''}若直接接受，这段将不出现在最终正文中。`,
          segIndex: segNo(idx),
          segTotal: total,
          isLast,
          primary: {
            label: isLast
              ? '接受并跳过（本段不进正文），完成本章生成'
              : `接受并跳过（本段不进正文），进入第 ${(segNo(idx) ?? 0) + 1} 段`,
            hint: '',
            action: 'accept',
          },
        }
      }
      return {
        kind: 'advance',
        title: `第 ${segNo(idx)}${total ? '/' + total : ''} 段已生成${wc ? ' · ' + wc + ' 字' : ''}`,
        hint: slot
          ? isLast
            ? `这段写「${slot.core_plot_event}」。可直接在左侧正文里改字（改动随接受定稿），或接受它完成本章、重写本段。`
            : `这段写「${slot.core_plot_event}」。可直接在左侧正文里改字（改动随接受定稿），或接受它进入下一段、重写本段。`
          : isLast
            ? '可直接在左侧正文里改字（改动随接受定稿），或接受本段完成本章、重写本段。'
            : '可直接在左侧正文里改字（改动随接受定稿），或接受本段进入下一段、重写本段。',
        segIndex: segNo(idx),
        segTotal: total,
        isLast,
        primary: {
          label: isLast ? '接受，完成本章生成' : `接受，进入第 ${(segNo(idx) ?? 0) + 1} 段`,
          hint: 'Space',
          action: 'accept',
        },
      }
    }

    // 岔路态（beat_branch_choosing）：决策交互在顶部 BranchDecisionPanel 完成，
    // 焦点条不渲染（落兜底 idle），两者互斥同槽。

    // 完成但有降级/救援段
    if (st === 'done' && (degradedBeats.value.length > 0 || rescueNeeded.value.length > 0)) {
      const n = degradedBeats.value.length + rescueNeeded.value.length
      return {
        kind: 'post-rescue',
        title: `全章已生成，但有 ${n} 段需复查`,
        hint: '这些段渲染失败或核心转折未落地。可以在下面分镜卡里对它们「重写本段」。',
        segTotal: total,
      }
    }

    // 全部完成
    if (st === 'done') {
      return {
        kind: 'done',
        title: '全章渲染完成',
        hint: '你随时可以对任意一段「重写本段」。',
        segTotal: total,
      }
    }

    // 兜底（非渲染阶段，焦点条通常不显示）
    return { kind: 'idle', title: '' }
  })

  // ---- 持久化：把当前产物序列化到 localStorage ----
  /**
   * 按 segment_index 顺序把 segmentTexts 拼成完整终稿（段间 \n\n 分隔）。
   *
   * 用于 rerender-beat 成功后重建 streamText：segmentTexts 按 beat_id 存（无序），
   * 需借 beatSlots 的 segment_index 排序，保证终稿段序正确。空段（降级/skip 残留）
   * 过滤，与后端 stepping_runtime.py 终稿拼接规则一致。
   */
  function _rebuildStreamTextFromSegments(): string {
    // beat_id → segment_index 映射（beatSlots 已含全部卡的 segment_index）
    const order = new Map<string, number>()
    for (const s of beatSlots.value) {
      if (typeof s.segment_index === 'number') order.set(s.beat_id, s.segment_index)
    }
    // skipped 段不进终稿（与后端 stepping_loop 终稿只拼 locked_segments 一致）——
    // onBeatSkipped 已清文本，这里是残留防御，防旧快照里的跳过段文本混入落库
    const skipped = new Set(
      renderProgress.value.filter(p => p.status === 'skipped').map(p => p.beat_id),
    )
    const entries = Object.entries(segmentTexts.value)
      .map(([beatId, text]) => ({ beatId, text, idx: order.has(beatId) ? order.get(beatId)! : 999 }))
      .filter(e => (e.text || '').trim() && !skipped.has(e.beatId)) // 过滤空段 + 跳过段
      .sort((a, b) => a.idx - b.idx)
    return entries.map(e => e.text).join('\n\n')
  }

  /** 收集当前 ref 值为快照（不含版本/章节/时间戳，由 _saveSnapshot 补） */
  function _collectSnapshot() {
    return {
      stage: stage.value,
      engine: engine.value,
      stepProgress: stepProgress.value,
      tierDecision: tierDecision.value,
      streamText: streamText.value,
      climaxScore: climaxScore.value,
      auditVerdict: auditVerdict.value,
      auditFindings: auditFindings.value,
      degraded: degraded.value,
      finalStats: finalStats.value,
      adfAnchor: adfAnchor.value,
      adfPreconditions: adfPreconditions.value,
      adfEmotionCurve: adfEmotionCurve.value,
      adfAudit: adfAudit.value,
      refineryIssues: refineryIssues.value,
      refinerySurgeries: refinerySurgeries.value,
      refineryHolisticVerdict: refineryHolisticVerdict.value,
      refineryStats: refineryStats.value,
      // BS-ADF：beatRunId 是临时会话凭证（同 refineryRunId），不持久化
      beatSlots: beatSlots.value,
      renderProgress: renderProgress.value,
      degradedBeats: degradedBeats.value,
      decisionSet: decisionSet.value,
      rescueNeeded: rescueNeeded.value,
      // 步进段态持久化（刷新恢复后 rerenderBeat 重建终稿依赖 segmentTexts）
      segmentTexts: segmentTexts.value,
      lockedBeatIds: [...lockedBeatIds.value],
      bsadfTrack: bsadfTrack.value,
      steppingEnabled: steppingEnabled.value,
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
    // 切换章节：先把当前章的状态存下来，再取消可能进行中的步进运行
    if (currentChapterId && currentChapterId !== chapterId) {
      persist()
      _cancelSteppingRun()
      _stopSteppingPoll()
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
    tierDecision.value = snap.tierDecision
    streamText.value = snap.streamText
    climaxScore.value = snap.climaxScore
    auditVerdict.value = snap.auditVerdict
    auditFindings.value = snap.auditFindings
    degraded.value = snap.degraded
    finalStats.value = snap.finalStats
    adfAnchor.value = snap.adfAnchor
    adfPreconditions.value = snap.adfPreconditions
    adfEmotionCurve.value = snap.adfEmotionCurve
    adfAudit.value = snap.adfAudit
    refineryIssues.value = snap.refineryIssues
    refinerySurgeries.value = snap.refinerySurgeries
    refineryHolisticVerdict.value = snap.refineryHolisticVerdict
    refineryStats.value = snap.refineryStats
    // 防御：旧 schema 快照（anchor_actions/conflict_trigger 时代）与新字段不兼容，
    // 逐卡校验 key_anchors 数组存在才恢复，否则丢弃（避免 UI 读 undefined 崩溃）
    beatSlots.value = (snap.beatSlots || []).filter(
      (s: any) => s && Array.isArray(s.key_anchors) && typeof s.core_plot_event === 'string',
    )
    renderProgress.value = snap.renderProgress || []
    degradedBeats.value = snap.degradedBeats || []
    decisionSet.value = snap.decisionSet || null
    rescueNeeded.value = (snap.rescueNeeded || []).filter(
      (r: any) => r && typeof r.segment_index === 'number',
    )
    // 步进段态恢复（done 态单段重渲重建终稿依赖 segmentTexts；缺省为旧版快照，给空）
    segmentTexts.value = snap.segmentTexts || {}
    lockedBeatIds.value = new Set(snap.lockedBeatIds || [])
    bsadfTrack.value = snap.bsadfTrack ?? null
    steppingEnabled.value = snap.steppingEnabled ?? false
    // 瞬时段态统一复位：步进运行态（就绪/渲染中/岔路门/降级提示）是会话凭证，
    // 刷新/切章后后端 run 已失效，不复位会残留到目标章——分镜卡级动作被
    // steppingActive 恒 true 锁死、A 章段文本串进 B 章终稿（真实事故）。
    readyBeatId.value = null
    readyBeatCard.value = null
    readyBeatDegraded.value = null
    renderingBeatId.value = null
    branchChoicePending.value = null
    steppingRunId.value = null
    emergentFacts.value = {}
    loop1Result.value = null
    pendingSaveText.value = null
    _chunkReplaceOnce.clear()
    _resetAuthoringTransient()
    // 中断态归正：刷新后无法续 LLM，强制为已完成的静态展示
    if (snap.stage === 'done' || snap.stage === 'error') {
      stage.value = snap.stage
    } else {
      // 上次处于生成中途（tier_classifying/zone_writing/beat_pending 等），刷新后已无法续上
      // → 若已有正文则记为 done，否则记为 idle（避免显示假的"生成中"进度）
      // 同时清掉 stepProgress（中断态的进度是旧的，恢复会误导用户以为还在生成）
      stepProgress.value = null
      stage.value = snap.streamText ? 'done' : 'idle'
    }
    generating.value = false
    error.value = null
    inflightEvents.value = []  // 飞行中事件不持久化（瞬时态）
    refineryRunId.value = null  // runId 是临时会话凭证，刷新后失效
    beatRunId.value = null  // beat runId 同样是临时凭证，刷新后失效
    rerenderRunId.value = null  // 同上：pending 在后端内存，刷新后前端不再引用
  }

  /** 内部 reset（不触碰 currentChapterId，不 persist） */
  function _resetInternal() {
    stage.value = 'idle'
    generating.value = false
    error.value = null
    stepProgress.value = null
    engine.value = 'v3.2'
    tierDecision.value = null
    streamText.value = ''
    climaxScore.value = null
    inflightEvents.value = []
    auditFindings.value = []
    auditVerdict.value = null
    degraded.value = []
    finalStats.value = null
    adfAnchor.value = null
    adfPreconditions.value = []
    adfEmotionCurve.value = []
    adfAudit.value = null
    refineryIssues.value = []
    refineryRunId.value = null
    refinerySurgeries.value = []
    refineryHolisticVerdict.value = null
    refineryStats.value = null
    beatSlots.value = []
    beatRunId.value = null
    rerenderRunId.value = null
    renderProgress.value = []
    degradedBeats.value = []
    bsadfTrack.value = null
    steppingEnabled.value = false
    rerenderingBeatId.value = null
    decisionSet.value = null
    rescueNeeded.value = []
    lastDoneMode.value = null
    // 风险3修复：清理步进轮询定时器 + 清空 steppingRunId（防止拆卸后永久轮询）
    _stopSteppingPoll()
    steppingRunId.value = null
    branchChoicePending.value = null
    segmentTexts.value = {}
    readyBeatId.value = null  // 触发 readyBeatId watch → 同步复位 readySegmentOriginal/Dirty
    readyBeatDegraded.value = null
    _chunkReplaceOnce.clear()
    lockedBeatIds.value = new Set()
    renderingBeatId.value = null
    authoringEnabled.value = false
    _resetAuthoringTransient()
  }

  /** 最近一次入口（供失败重试 retry 再次触发）；start / startRefinery 时记录 */
  let lastAction: (() => void) | null = null

  /** 定档事件填充（ADF 的 onTierDecided 与 BS-ADF 的 TIER_DECIDED 共用，载荷结构一致） */
  function applyTierDecision(decision: { tier: string; reason: string; climax_score?: number | null }) {
    tierDecision.value = {
      tier: decision.tier as any,
      reason: decision.reason,
      climax_score: decision.climax_score ?? null,
      forced_by_user: decision.tier !== 'auto',
      max_depth: 0,
      development_ratio: 0,
    }
    stage.value = 'tier_decided'
    stepProgress.value = { label: `篇幅：${tierLabel(decision.tier)}` }
  }

  /** 审计结论填充（ADF 的 onAudit 与 BS-ADF 的 ADF_AUDIT / BSADF_METADATA.audit 兜底共用）。
   *  BSADF_METADATA.audit 是后端 audit_to_dict 产物，比 ADF_AUDIT 事件多
   *  style_violations/style_score/missing_beats 字段，结构兼容可直接传入。 */
  function applyAdfAudit(audit: AdfAuditResult) {
    adfAudit.value = audit
    auditVerdict.value = audit.verdict
    if (audit.climax_score != null) climaxScore.value = audit.climax_score
    if (Array.isArray(audit.structure_issues)) {
      auditFindings.value = audit.structure_issues.map((v: string) => ({
        detail: v,
        severity: 'warning',
        category: 'structure',
      }))
    }
    if (Array.isArray(audit.emotion_mismatches)) {
      auditFindings.value.push(
        ...audit.emotion_mismatches.map((v: string) => ({
          detail: v,
          severity: 'info',
          category: 'emotion',
        })),
      )
    }
  }

  /** BS-ADF 兜底事件（onEvent 通道）：审计 / 降级 / 元数据 / 正文输出提示，
   *  对齐 ADF 路径的填充逻辑（此前这些事件被 _dispatchEvent 安全忽略，
   *  导致 BS-ADF 生成后降级详情 / 审计结论 / 铺垫要点恒空）。 */
  function handleBsadfEvent(event: string, data: any) {
    // NLE-ADF 2.0 懒增强完成：种子卡 → 增强卡（Dock 零件/DDE 决策集/Loop1 缺口刷新）
    if (event === 'BEAT_CARDS_ENRICHED') {
      _applyEnhancedCards(data)
      return
    }
    // ADF_ANCHOR_DESIGNED：存锚点设计（climax_description 供脉络条摘要展示）
    if (event === 'ADF_ANCHOR_DESIGNED') {
      adfAnchor.value = {
        climax_intensity: data.climax_intensity,
        climax_description: data.climax_description,
        setup_points: data.setup_points,
        emotion_flow_samples: data.emotion_flow_samples,
      }
      // ⚠ BS-ADF 情绪曲线恒空修复：此前 emotion_flow_samples 只存进 adfAnchor
      // 不喂 adfEmotionCurve（ADF 路径 start() 有喂），Canon tab 曲线对 BS-ADF
      // 章节永远空白——数据明明已到达前端
      adfEmotionCurve.value = data.emotion_flow_samples || []
      return
    }
    if (event === 'ADF_AUDIT') {
      applyAdfAudit({
        verdict: data.verdict,
        missing_setup_points: data.missing_setup_points || [],
        emotion_mismatches: data.emotion_mismatches || [],
        structure_issues: data.structure_issues || [],
        climax_score: data.climax_score,
        fix_targets: data.fix_targets || [],
      })
    } else if (event === 'DEGRADED') {
      degraded.value.push({
        reason: data.reason,
        phase: data.phase,
        detail: data.detail,
      })
    } else if (event === 'BSADF_METADATA') {
      // 完整元数据：填充铺垫要点（同 ADF_METADATA 的处理）
      if (Array.isArray(data.climax_design?.setup_points)) {
        adfPreconditions.value = data.climax_design.setup_points
      }
      // audit 兜底：ADF_AUDIT 事件正常会先到；未到（异常路径）时用
      // BSADF_METADATA.audit（audit_to_dict 产物）补，避免审计结论恒空
      if (!adfAudit.value && data.audit && data.audit.verdict) {
        applyAdfAudit(data.audit)
      }
    } else if (event === 'FINAL_TEXT_STREAM') {
      stepProgress.value = { label: '输出正文' }
      // 终稿重放前清掉渲染期原稿：渲染中 segmentTexts/streamText 装的是
      // 各段 BEAT_TEXT_CHUNK 原稿，随后 TEXT_CHUNK 会按 200 字切块重放
      // 后处理终稿，不清会原稿+终稿双份拼接；预览同时切到精修全文流式视图
      streamText.value = ''
      segmentTexts.value = {}
    }
    // UNIFIED_METRIC / GENERATION_RUN：audit 已通过 ADF_AUDIT 处理（同 ADF onMetric 语义）
  }

  /** 把 BS-ADF 的 BSADF_STAGE/ADF_STAGE 事件映射为写作语言步骤标签。
   *  sessionStage 为 null 时只换标签、不动 stage 状态机
   *  （AUTHOR_DIALOGUE 的 beat_pending 由 onSlots 负责；未知事件保持现状）。 */
  function mapBsadfStageToLabel(stageName: string): { label: string; sessionStage: SessionStage | null } {
    switch (stageName) {
      case 'CONTEXT_ASSEMBLING':
        return { label: '组装上下文', sessionStage: 'tier_classifying' }
      case 'SPINE_BUILDING':
        return { label: '构建脉络骨架', sessionStage: 'tier_classifying' }
      case 'ANCHOR_DESIGN':
        return { label: '设计远端锚点', sessionStage: 'tier_classifying' }
      case 'TIER_DECIDE':
        return { label: '章节定档', sessionStage: 'tier_classifying' }
      case 'SLOT_BUILD':
        return { label: '构建分镜卡', sessionStage: 'setup_growing' }
      case 'BRANCH_CHECK':
        return { label: '检查剧情岔路', sessionStage: 'setup_growing' }
      case 'RENDER':
      case 'RENDER_RESUMED':
        return { label: '逐段渲染', sessionStage: 'beat_rendering' }
      case 'AUTHOR_DIALOGUE':
        return { label: '等待你编辑分镜卡', sessionStage: null }
      case 'PRUNE':
        // 剪枝属后处理（全段已锁），映射 refining 而非 zone_writing——
        // 否则底栏误标「写作中」，作者以为还在逐段产出
        return { label: '重构剪枝', sessionStage: 'refining' }
      case 'ANCHOR_AUDIT':
        return { label: '锚点审计', sessionStage: 'auditing' }
      case 'REFINE':
        return { label: '条件补埋', sessionStage: 'refining' }
      case 'BEAT_PATCH':
        return { label: '补写遗漏节拍', sessionStage: 'refining' }
      case 'CONSISTENCY_GUARD':
        return { label: '一致性守卫', sessionStage: 'auditing' }
      default:
        return { label: stageName, sessionStage: null }
    }
  }

  function cancel() {
    _cancelSteppingRun()
    _stopSteppingPoll()
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
  // 旧路径（startBeat）保持 legacy 可切换。

  /** 激活自适应写作模式。
   *  作者进章节开始打字时调（取代旧冷启动 startBeat）。
   *  不跑定档/锚点/分镜管线——作者轴置 composing，辅助层据此挂载。 */
  function enterAdaptive(chapterId: string) {
    if (adaptiveMode.value && authorLane.value === 'composing') return  // 已激活
    // 若旧管线在跑，先取消（adaptive 与 step 互斥）
    if (generating.value && stage.value !== 'idle') {
      _cancelSteppingRun()
      _stopSteppingPoll()
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

  // adaptive 续写注入器：由 useAdaptiveAssist 注入（解耦 session 与 API 层）。
  // session 的键位状态机在 adaptive composing 态调它触发续写，不直接 import adaptiveApi。
  let _adaptiveContinueFn: ((mode: 'stitch' | 'continue', parts: Array<{ text: string; direction?: string }>) => void) | null = null
  function setAdaptiveContinue(fn: ((mode: 'stitch' | 'continue', parts: Array<{ text: string; direction?: string }>) => void) | null) {
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

  /** 失败重试：再次触发最近一次入口（startBeat / startRefinery 已记录 lastAction） */
  function retry() {
    if (generating.value) return
    error.value = null
    lastAction?.()
  }

  function reset() {
    _cancelSteppingRun()
    _stopSteppingPoll()
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

  // ============================================================
  // V4.1 Refinery 控制：startRefinery + confirmRefinery
  // ============================================================

  /** 启动精修第一阶段：诊断（产出问题清单后停在对话式介入点 2） */
  function startRefinery(
    chapterId: string,
    opts: { mode?: 'deep' | 'light'; enablePolish?: boolean; rawText?: string | null } = {},
  ) {
    // 防重入：若 generating 卡住（上次生成/精修未正确复位），点击会被吞。
    // 这里给出可见反馈而非静默 return，方便用户排查。
    if (generating.value) {
      console.warn('[startRefinery] 已有生成/精修任务进行中（generating=true），已忽略本次点击。若这是误判，请刷新页面后重试。')
      return
    }
    // 不 reset，保留已生成的正文（精修是在生成后做的）
    // 记录入口供失败后 retry（重试即重新诊断）
    lastAction = () => startRefinery(chapterId, opts)
    generating.value = true
    error.value = null
    stage.value = 'auditing' // 复用 auditing 阶段标识
    abortController = new AbortController()

    refineryApi.diagnose(
      chapterId,
      {
        mode: opts.mode || 'deep',
        enable_polish: opts.enablePolish !== false,
        raw_text: opts.rawText || null,
      },
      {
        onStage: (stageName) => {
          if (stageName === 'DIAGNOSTIC') {
            stepProgress.value = { label: '检查全文' }
          } else if (stageName === 'DIALOGUE') {
            stepProgress.value = { label: '等待你确认修改清单' }
          }
        },
        onIssues: (payload) => {
          refineryIssues.value = payload.issues
          refineryRunId.value = payload.run_id
          generating.value = false
          stage.value = 'refining' // 进入"等确认"状态
          stepProgress.value = { label: `${payload.issues.length} 个问题待确认` }
        },
        onError: (err) => {
          error.value = err
          generating.value = false
          stage.value = 'error'
          abortController = null
        },
      },
      abortController.signal,
    )
  }

  /** 精修第二阶段：作者确认后执行手术+回读+抛光 */
  function confirmRefinery(
    chapterId: string,
    decisions: IssueDecision[],
    customIssues: RefineryIssue[] = [],
  ) {
    const runId = refineryRunId.value
    if (!runId) {
      error.value = '缺少 refinery run_id'
      return
    }
    // 立即释放 runId 并清空问题清单：问题清单面板（要求 runId 非空）随之关闭，
    // 手术进度面板（RefineryProgress，要求 runId===null）接管展示。
    // 警示：此前整个手术阶段保留 runId，两面板条件互斥导致进度 UI 永不出现。
    refineryRunId.value = null
    refineryIssues.value = []
    generating.value = true
    stage.value = 'refining'
    abortController = new AbortController()
    startedAt = Date.now()  // 精修手术阶段重新计时（诊断等待不算）
    streamText.value = '' // 清空，准备接收抛光后的新正文
    refinerySurgeries.value = []
    refineryHolisticVerdict.value = null

    refineryApi.confirm(
      chapterId,
      {
        run_id: runId,
        decisions,
        custom_issues: customIssues,
        mode: 'deep',
      },
      {
        onStage: (stageName) => {
          if (stageName === 'SURGERY') stepProgress.value = { label: '逐处修改' }
          else if (stageName === 'REREAD') stepProgress.value = { label: '通读全文' }
          else if (stageName === 'POLISH') stepProgress.value = { label: '定稿润色' }
        },
        onOperation: (data) => {
          stepProgress.value = {
            label: `修改 ${data.operation_index}/${data.total_operations}`,
            index: data.operation_index,
            total: data.total_operations,
          }
        },
        onSurgery: (surgery) => {
          refinerySurgeries.value.push(surgery)
        },
        onReread: (verdict) => {
          refineryHolisticVerdict.value = verdict
        },
        onPolish: () => {
          stepProgress.value = { label: '抛光完成' }
        },
        onChunk: (chunk) => {
          streamText.value += chunk
        },
        onDone: (result) => {
          generating.value = false
          stage.value = 'done'
          refineryStats.value = result.stats
          finalStats.value = startedAt != null
            ? { ...(result.stats || {}), duration_ms: Date.now() - startedAt }
            : result.stats
          lastDoneMode.value = 'refinery'
          // runId 已在 confirm 开始时释放（进度面板接管），此处幂等确保为空，
          // 让"启动精修"按钮（要求 stage='done' 且 runId 为空）可以再次显示
          refineryRunId.value = null
          abortController = null
          persist()  // 精修完成：持久化精修产物
        },
        onError: (err) => {
          error.value = err
          generating.value = false
          stage.value = 'error'
          abortController = null
          persist()
        },
      },
      abortController.signal,
    )
  }

  // ============================================================
  // BS-ADF 控制：startBeat（Track A 全自动 / Track B 跑到槽位卡暂停）
  // + confirmBeats（Track B 恢复渲染）+ cancelBeat
  // ============================================================

  /** 步进事件 → renderProgress 同步（P3 修复）。
   *  步进路径（generate/advance-beat）后端不发 BEAT_RENDER_PROGRESS，
   *  不喂数据的话 BeatProgress 恒「准备中」、脉络条 currentIndex 恒 0
   *  （真实误导：步进到第 5 段仍高亮第 1 段）。
   *  segment_index / word_count 缺省时回查已有项与 beatSlots。幂等（按 beat_id upsert）。 */
  function upsertRenderProgress(
    beatId: string,
    status: 'rendering' | 'ready' | 'rendered' | 'skipped',
    opts: { segmentIndex?: number; wordCount?: number } = {},
  ) {
    const idx = renderProgress.value.findIndex(p => p.beat_id === beatId)
    const prev = idx >= 0 ? renderProgress.value[idx] : null
    const segIdx = opts.segmentIndex
      ?? prev?.segment_index
      ?? beatSlots.value.find(s => s.beat_id === beatId)?.segment_index
      ?? 0
    const item: RenderProgress = {
      beat_id: beatId,
      segment_index: segIdx,
      status,
      word_count: opts.wordCount ?? prev?.word_count ?? 0,
      reason: prev?.reason,
      coverage_missing: prev?.coverage_missing,
      word_overflow: prev?.word_overflow,
    }
    if (idx >= 0) renderProgress.value[idx] = item
    else renderProgress.value.push(item)
  }

  /** BS-ADF：启动生成（当前只使用步进模式 enable_stepping=true）。
   *  Track A/B 为历史兼容参数，活跃流程为 startBeat → 槽位卡就绪 → advance-beat 循环 → COMPLETE。 */
  function startBeat(
    chapterId: string,
    tier: string,
    opts: {
      track?: 'A' | 'B'
      targetWordCount?: number | null
      maxSegments?: number
      authorIntent?: string
      expectationActions?: Record<string, string>
      steppingEnabled?: boolean
      enableAuthoring?: boolean
      freshCanvas?: boolean
      enableOutlineSelfCheck?: boolean
      enableMemoryIngestion?: boolean
    } = {},
  ) {
    if (generating.value) {
      console.warn('[startBeat] 已有生成任务进行中，已忽略')
      return
    }
    // 重新生成前必须清理上一次步进运行（裁决态 generating=false，防重入不拦截）：
    // 不取消的话旧 stepping_loop 后端任务永久挂起等 action，直到 1 小时 TTL 才回收。
    _cancelSteppingRun()
    _stopSteppingPoll()
    lastAction = () => startBeat(chapterId, tier, opts)
    // 绑定章节 + 清旧快照（这是全新生成，旧产物作废；此前漏绑定，
    // persist 可能写到上一章的 key 下、旧快照残留到首个 persist 点）
    currentChapterId = chapterId
    _clearSnapshot(chapterId)
    generating.value = true
    error.value = null
    stage.value = 'tier_classifying'
    bsadfTrack.value = opts.track || 'A'
    steppingEnabled.value = opts.steppingEnabled ?? false
    authoringEnabled.value = opts.enableAuthoring ?? false
    _freshCanvas = opts.freshCanvas ?? false
    abortController = new AbortController()
    startedAt = Date.now()
    // 清空旧产物（含 stepProgress，避免上次进度残留误导）
    streamText.value = ''
    stepProgress.value = null
    beatSlots.value = []
    beatRunId.value = null
    rerenderRunId.value = null
    renderProgress.value = []
    degradedBeats.value = []
    decisionSet.value = null
    rescueNeeded.value = []
    // 兜底事件填充的产物一并清空（定档/审计/降级/铺垫要点），防上章残留
    tierDecision.value = null
    adfAudit.value = null
    adfPreconditions.value = []
    degraded.value = []
    // 步进态一并清空（steppingRunId 是临时凭证，新 run 的 run_id 由 STEPPING_INITIALIZED 重新给）
    steppingRunId.value = null
    segmentTexts.value = {}
    readyBeatId.value = null
    readyBeatCard.value = null
    lockedBeatIds.value = new Set()
    renderingBeatId.value = null
    branchChoicePending.value = null
    emergentFacts.value = {}
    loop1Result.value = null
    _resetAuthoringTransient()

    bsadfApi.start(
      chapterId,
      {
        tier,
        track: opts.track || 'A',
        target_word_count: opts.targetWordCount ?? null,
        max_segments: opts.maxSegments ?? 6,
        author_intent: opts.authorIntent,
        expectation_actions: opts.expectationActions,
        enable_stepping: opts.steppingEnabled ?? false,
        enable_authoring: opts.enableAuthoring ?? false,
        enable_outline_self_check: opts.enableOutlineSelfCheck ?? false,
        enable_memory_ingestion: opts.enableMemoryIngestion ?? false,
        // enable_dde 不再随 track 写死：后端默认 true，Track A 静默应用默认走向、
        // Track B 把 decision_set 内嵌进 BEAT_SLOTS_BUILT，由后端按轨处理
      },
      {
        onStage: (stageName, _data) => {
          // 映射后端 BSADF_STAGE/ADF_STAGE 到中文标签 + stage 状态机
          const { label, sessionStage } = mapBsadfStageToLabel(stageName)
          if (sessionStage) stage.value = sessionStage
          stepProgress.value = { label }
        },
        onSlotEnrichProgress: (current, total, _beatId) => {
          // 槽位扩写逐卡进度（SLOT_BUILD 阶段，避免 60s 沉默）
          stepProgress.value = {
            label: '分镜卡扩写',
            index: current,
            total,
          }
        },
        onDdeAutoApplied: (payload) => {
          // Track A 静默 DDE：有分支已按默认走向突变（卡片 branch_directive 已注入）；
          // 无分支时 decision_set.has_story_branch=false，面板据此展示"本章无岔路"
          decisionSet.value = payload.decision_set || null
        },
        onSlots: (payload) => {
          // 轨道/载荷守卫：仅 Track B 暂停的完整版（route 层带 run_id + 全量卡）
          // 才进 beat_pending 并解 generating；Track A 的 workflow 版（无 run_id，
          // 载荷带 beat_slots/decision_set）只提前填卡，不动 stage/generating
          // （否则 Track A 渲染中途被误判为"完成"，_editor 覆盖提前解锁）。
          if (payload.run_id && payload.slots?.length) {
            // Track B 暂停触发：槽位卡就绪（分支信息随卡内嵌，单次暂停）
            beatSlots.value = payload.slots
            beatRunId.value = payload.run_id
            decisionSet.value = payload.decision_set || null
            const branchCount = payload.decision_set?.decision_nodes?.length || 0
            // NLE-ADF 步进模式
            if (opts.steppingEnabled) {
              steppingRunId.value = payload.run_id
              // 清空步进态产物，等后端推第一段 BEAT_RENDER_READY
              segmentTexts.value = {}
              readyBeatId.value = null
              lockedBeatIds.value = new Set()
              generating.value = true
              stage.value = 'beat_rendering'
              // 底栏进度：带 index/total（GenerationOverlay 显示 N/M 段与进度条）；
              // 渲染推进由 onBeatRenderStart/onBeatReady 持续更新，不再一次性写死
              // （"N 处剧情走向待选"由分镜卡状态轨与岔路门面板表达，底栏不重复）
              stepProgress.value = {
                label: '逐段渲染',
                index: 0,
                total: payload.slots.length,
              }
              // 启动轮询：IAB 等短 SSE 环境下，generate 的 SSE 流可能在首段
              // 渲染完成前断开。轮询 state 端点作为备用通道，等 current_segment_ready
              // 后手动触发 onBeatReady 逻辑（切 beat_stepping + 设 readyBeatId）。
              _pollSteppingReady(payload.run_id, currentChapterId || '')
            } else {
              generating.value = false  // 解覆盖 editor
              stage.value = 'beat_pending'
              stepProgress.value = {
                label: branchCount > 0
                  ? `${payload.slots.length} 张分镜卡待编辑 · ${branchCount} 处剧情走向待选`
                  : `${payload.slots.length} 张分镜卡待编辑`,
              }
            }
          } else {
            // Track A（及 Track B 先于 route 完整版到达的 workflow 版）：
            // 仅填充 beatSlots / decisionSet，让渲染期卡片可见
            if (payload.slots?.length) beatSlots.value = payload.slots
            if (payload.decision_set) decisionSet.value = payload.decision_set
          }
        },
        onTierDecided: (decision) => {
          applyTierDecision(decision)
        },
        onEvent: (event, data) => {
          handleBsadfEvent(event, data)
        },
        onRenderProgress: (data) => {
          // 更新 renderProgress（替换或追加同 beat_id 的项）
          const idx = renderProgress.value.findIndex(p => p.beat_id === data.beat_id)
          if (idx >= 0) {
            renderProgress.value[idx] = data
          } else {
            renderProgress.value.push(data)
          }
          stepProgress.value = {
            label: `渲染 ${data.segment_index + 1}/${beatSlots.value.length}`,
            index: data.segment_index + 1,
            total: beatSlots.value.length,
          }
        },
        // NLE-ADF 步进事件（首段渲染由 generate-bsadf 的 SSE 桥接推来）。
        // 与 advanceBeat 的回调共享同一套逻辑。
        onBeatRenderStart: (data) => {
          renderingBeatId.value = data.beat_id
          readyBeatId.value = null
          readyBeatDegraded.value = null
          _noteSteppingActivity()
          // 全量 chunk 语义：渲染开始即作废旧文本（edit/back 重渲防翻倍）
          _clearSegmentText(data.beat_id)
          // 作者模式代笔：chunk 直接灌成画布幽灵草稿（不走路由预览投影）
          if (authoringEnabled.value) beginGhost('render')
          upsertRenderProgress(data.beat_id, 'rendering', { segmentIndex: data.segment_index })
          stepProgress.value = {
            label: '逐段渲染',
            index: (data.segment_index ?? 0) + 1,
            total: beatSlots.value.length,
          }
          if (data.card_snapshot) {
            const idx = beatSlots.value.findIndex(s => s.beat_id === data.beat_id)
            if (idx >= 0) beatSlots.value[idx] = data.card_snapshot
          }
        },
        // NLE-ADF 2.0 作者模式：拍打开，等作者创作（SSE 事件与轮询自愈共用处理）
        onBeatAuthoringOpen: (data) => {
          _onBeatAuthoringOpen(data)
        },
        onBeatChunk: (data) => {
          _handleBeatChunk(data)
          // 作者模式代笔：正文以幽灵草稿形态流进画布（作者可改词再锁）
          if (authoringEnabled.value && ghostSource.value === 'render') appendGhost(data.delta)
        },
        onBeatReady: (data) => {
          renderingBeatId.value = null
          readyBeatId.value = data.beat_id
          readyBeatCard.value = data.card_snapshot || null
          // 消费降级载荷：步进模式后端只把降级信息挂在 READY 上（不发
          // BEAT_DOWNGRADED 事件），不存则作者只见"0 字"误判为空段
          readyBeatDegraded.value = data.degraded || null
          stage.value = 'beat_stepping'
          generating.value = false  // 解锁，等作者按 Space
          upsertRenderProgress(data.beat_id, 'ready', { segmentIndex: data.segment_index, wordCount: data.word_count })
          stepProgress.value = {
            label: '待你裁决',
            index: (data.segment_index ?? 0) + 1,
            total: beatSlots.value.length,
          }
        },
        onBeatBranchChoice: (data) => {
          // 岔路门挂起期间必须停轮询：run 在等作者选走向，current_segment_ready
          // 恒为 False，不停的话 90 次轮询后误报"步进轮询超时"把会话砸成 error
          // （真实事故：每次生成挂在 beat0 岔路门，3 分钟后必报"生成失败"）
          _stopSteppingPoll()
          branchChoicePending.value = {
            beat_id: data.beat_id,
            segment_index: data.segment_index,
            node: data.node,
            card: data.card_snapshot || null,
          }
          readyBeatId.value = null
          readyBeatDegraded.value = null
          renderingBeatId.value = null
          stage.value = 'beat_branch_choosing'
          generating.value = false
        },
        onBeatLocked: (data) => {
          readyBeatDegraded.value = null
          lockedBeatIds.value = new Set([...lockedBeatIds.value, data.beat_id])
          if (data.extracted_facts) {
            emergentFacts.value = { ...emergentFacts.value, [data.beat_id]: data.extracted_facts }
          }
          upsertRenderProgress(data.beat_id, 'rendered')
        },
        onBeatSkipped: (data) => {
          // skipped 段不入 locked 集合，也不应视为已渲染；单独标记为 skipped
          readyBeatDegraded.value = null
          // 清掉残留正文：跳过段不进终稿（重建时另有 skipped 过滤兜底）
          _clearSegmentText(data.beat_id)
          upsertRenderProgress(data.beat_id, 'skipped')
        },
        onBeatBacked: (data) => {
          // 后端已弹栈回退到目标段：目标段及之后全部作废重渲（快照语义），
          // 前端统一回滚这些段的正文/锁定/进度（此前只清目标段 → 后段旧文本
          // 在重渲时被 chunk append 拼成翻倍、状态轨残留陈旧「已就绪」灯）。
          _rollbackFromBeat(data.beat_id, data.segment_index)
          // 作者模式：画布侧同步删掉回滚拍的创作区文本（后端只回滚生成状态）
          if (authoringEnabled.value) _authoringRollbackDoc(data.beat_id)
          readyBeatId.value = null
          readyBeatCard.value = null
          readyBeatDegraded.value = null
          renderingBeatId.value = data.beat_id
          stage.value = 'beat_rendering'
          generating.value = true
          upsertRenderProgress(data.beat_id, 'rendering', { segmentIndex: data.segment_index })
          if (data.rejected) {
            // 首段无可回退：仅提示，后端会重发 BEAT_RENDER_READY 恢复裁决态。
            // 仅当 error 仍是本条提示时才清除，避免覆盖同期真实错误
            error.value = '已经是第一段，无法继续回退'
            setTimeout(() => {
              if (error.value === '已经是第一段，无法继续回退') error.value = null
            }, 2000)
          }
        },
        onAllBeatsLocked: () => {
          renderingBeatId.value = null  // 末段无下一个 RENDER_START 清灯，在此复位
          stage.value = 'assembling'
        },
        onLoop1Checked: (data) => {
          loop1Result.value = data
        },
        onDowngraded: (data) => {
          degradedBeats.value.push(data)
        },
        onRescueNeeded: (items) => {
          // 审计判核心转折未落地的节拍（路线 C 内联救援卡）
          rescueNeeded.value = items
        },
        onChunk: (chunk) => {
          streamText.value += chunk
        },
        onDone: (result) => {
          generating.value = false
          // 后端 PRUNE/audit 阶段在 COMPLETE 之前；COMPLETE 在 onDone，直接转 done
          finalStats.value = startedAt != null
            ? { ...(result.stats || {}), duration_ms: Date.now() - startedAt }
            : result.stats
          lastDoneMode.value = 'bsadf'
          stage.value = 'done'
          // SSE 帧丢失安全网：COMPLETE 携带完整终稿，覆盖 streamText
          // （步进模式终稿由 advanceBeat 的 onDone 负责，此处不动）
          if (result.text && !opts.steppingEnabled) streamText.value = result.text
          // 完成后用后端下发的卡刷新（Track A 首次持卡；含渲染后 status 与
          // 分支突变后的 branch_directive，分镜工作台据此只读展示）
          if (result.beat_slots?.length) {
            beatSlots.value = result.beat_slots
          }
          if (result.rescue_needed?.length) {
            rescueNeeded.value = result.rescue_needed
          }
          // Track A：pending 以生成 run_id 为 key，存下来供完成后 rerender 取上下文
          rerenderRunId.value = result.generation_run_id || null
          beatRunId.value = null  // 幂等清空
          _resetAuthoringTransient()
          abortController = null
          persist()
        },
        onError: (err) => {
          error.value = err
          generating.value = false
          stage.value = 'error'
          abortController = null
          persist()
        },
      },
      abortController.signal,
    )
  }

  /** BS-ADF Track B：作者编辑分镜卡 + 选定剧情分支后恢复渲染。
   *  ⚠ 前端当前只使用步进模式，不再调用本入口；保留为历史兼容。 */
  function confirmBeats(
    chapterId: string,
    editedSlots: BeatSlot[],
    opts: { branchChoices?: Record<string, string>; skipped?: boolean } = {},
  ) {
    const runId = beatRunId.value
    if (!runId) {
      error.value = '缺少 beat run_id'
      return
    }
    // runId handoff（照搬 confirmRefinery 的技巧）：捕获 → 清空 → 调 API。
    // 注意：beatSlots 不再清空——分镜工作台在渲染态/完成态继续持卡展示，
    // 供事后「极速微调」与定点重渲染复用（渲染进度另由 renderProgress 展示）。
    // Track B：pending 以原始暂停 run_id 为 key（confirm 产生的是新 run_id），
    // 存下它供完成后 rerender 取上下文。
    rerenderRunId.value = runId
    beatRunId.value = null
    generating.value = true
    stage.value = 'beat_rendering'
    stepProgress.value = null
    abortController = new AbortController()
    streamText.value = ''
    renderProgress.value = []
    degradedBeats.value = []
    rescueNeeded.value = []

    bsadfApi.confirm(
      chapterId,
      {
        run_id: runId,
        edited_slots: editedSlots,
        branch_choices: opts.branchChoices || {},
        skipped: opts.skipped || false,
      },
      {
        onStage: (stageName) => {
          // confirm 流复用 BS-ADF 阶段映射（RENDER_RESUMED/PRUNE/ANCHOR_AUDIT 等）
          const { label, sessionStage } = mapBsadfStageToLabel(stageName)
          if (sessionStage) stage.value = sessionStage
          stepProgress.value = { label }
        },
        onRenderProgress: (data) => {
          const idx = renderProgress.value.findIndex(p => p.beat_id === data.beat_id)
          if (idx >= 0) renderProgress.value[idx] = data
          else renderProgress.value.push(data)
          stepProgress.value = {
            label: `渲染 ${data.segment_index + 1}/${editedSlots.length}`,
            index: data.segment_index + 1,
            total: editedSlots.length,
          }
        },
        onDowngraded: (data) => {
          degradedBeats.value.push(data)
        },
        onRescueNeeded: (items) => {
          rescueNeeded.value = items
        },
        onEvent: (event, data) => {
          handleBsadfEvent(event, data)
        },
        // Track B 恢复渲染：段定稿正文实时上屏（与 startBeat 的 onBeatChunk 一致；
        // 此前该路径未接此回调，渲染期编辑器恒空）
        onBeatChunk: (data) => {
          _handleBeatChunk(data)
          // 作者模式代笔：正文以幽灵草稿形态流进画布（作者可改词再锁）
          if (authoringEnabled.value && ghostSource.value === 'render') appendGhost(data.delta)
        },
        onChunk: (chunk) => {
          streamText.value += chunk
        },
        onDone: (result) => {
          generating.value = false
          stage.value = 'done'
          // 补耗时（对齐 startBeat 的 onDone 写法；startedAt 自 startBeat 起算，
          // 含作者在 beat_pending 的编辑等待——与 Track B 语义一致）
          finalStats.value = startedAt != null
            ? { ...(result.stats || {}), duration_ms: Date.now() - startedAt }
            : result.stats
          lastDoneMode.value = 'bsadf'
          // SSE 帧丢失安全网：COMPLETE 携带完整终稿，直接覆盖 streamText
          // （正常路径下 TEXT_CHUNK 重放已拼出同一份文本，覆盖无副作用）
          if (result.text) streamText.value = result.text
          // 完成后用后端下发的卡刷新（含渲染后 status 与分支突变后的 branch_directive）
          if (result.beat_slots?.length) {
            beatSlots.value = result.beat_slots
          }
          if (result.rescue_needed?.length) {
            rescueNeeded.value = result.rescue_needed
          }
          beatRunId.value = null
          abortController = null
          persist()
        },
        onError: (err) => {
          error.value = err
          generating.value = false
          stage.value = 'error'
          abortController = null
          persist()
        },
      },
      abortController.signal,
    )
  }

  /** BS-ADF Track B 取消（回滚到 idle） */
  function cancelBeat() {
    _cancelSteppingRun()
    _stopSteppingPoll()
    beatSlots.value = []
    beatRunId.value = null
    rerenderRunId.value = null
    renderProgress.value = []
    degradedBeats.value = []
    decisionSet.value = null
    rescueNeeded.value = []
    generating.value = false
    stage.value = 'idle'
  }

  /**
   * BS-ADF：降级/救援单卡重渲染（调 /rerender-beat，同步 JSON）。
   *
   * 降级或 rescue_needed 的某张 beat 由作者重新编辑后单卡重渲染（不重跑全章）。
   * editedSlot 是作者编辑后的整卡，后端用它替代暂存快照重渲染。
   * 后端返回 {segment:{text}, card, degraded}：
   * - 成功（degraded=null）：从 degradedBeats / rescueNeeded 移除该 beat，把渲染结果记入 renderProgress（status='rendered'）。
   * - 再次降级（degraded 非空）：把新的降级句柄替换 degradedBeats 中同 beat_id 的项（attempts 累加）。
   * 任意一种分支都持久化（刷新后能看到最新降级态）。
   */
  async function rerenderBeat(chapterId: string, beatId: string, editedSlot: BeatSlot) {
    // 进行中指示：分镜卡点亮「渲染中」灯 + 按钮禁用防连点（finally 确保复位）
    rerenderingBeatId.value = beatId
    try {
      const result = await bsadfApi.rerenderBeat(chapterId, {
        beat_id: beatId,
        edited_slot: editedSlot,
        // 带上生成 run_id（beatRunId 优先，完成态回退 rerenderRunId），后端据此
        // 从 _PENDING_BEAT_SLOTS 取完整渲染上下文（专名表/场景设定/锚点），
        // 不走空上下文兜底；两者都无时后端按 beat_id 扫描兜底
        run_id: beatRunId.value || rerenderRunId.value,
      })
      // 后端响应字段：result.segment.text（正文）/ result.degraded（再次降级句柄，可空）
      const text = result?.segment?.text ?? ''
      const reDegraded = result && result.degraded
      if (reDegraded) {
        // 再次降级：替换同 beat_id 的旧降级项（保留最新 attempts/reason）
        degradedBeats.value = degradedBeats.value.map(d =>
          d.beat_id === beatId ? {
            beat_id: reDegraded.beat_id,
            segment_index: reDegraded.segment_index,
            reason: reDegraded.reason,
            attempts: reDegraded.attempts ?? d.attempts,
          } : d,
        )
      } else {
        // 渲染成功：移出降级清单与救援清单，把结果记入 renderProgress（标记为 rendered）
        degradedBeats.value = degradedBeats.value.filter(d => d.beat_id !== beatId)
        rescueNeeded.value = rescueNeeded.value.filter(r => r.beat_id !== beatId)
        // 用后端返回的卡刷新分镜工作台（status → rendered，内容为最终渲染用卡）
        if (result?.card) {
          const cardIdx = beatSlots.value.findIndex(s => s.beat_id === beatId)
          if (cardIdx >= 0) beatSlots.value[cardIdx] = result.card
        }
        const segIndex = (editedSlot && typeof editedSlot.segment_index === 'number')
          ? editedSlot.segment_index
          : (result && result.segment && result.segment.index) ?? 0
        // 替换或追加同 beat_id 的进度项（与 onRenderProgress 的去重逻辑一致）
        const idx = renderProgress.value.findIndex(p => p.beat_id === beatId)
        const progressItem = {
          beat_id: beatId,
          segment_index: segIndex,
          status: 'rendered',
          word_count: (text || '').length,
        }
        if (idx >= 0) renderProgress.value[idx] = progressItem
        else renderProgress.value.push(progressItem)
        // 写回段正文 + 重建终稿 + 触发落库（修复 rerender-beat 不落库 stub）。
        // 此前重渲结果只进 renderProgress，既不写 segmentTexts/streamText，也不落库，
        // 导致作者在分镜卡「重写本段」得到的成品无法进入章节正文、刷新即丢。
        segmentTexts.value = { ...segmentTexts.value, [beatId]: text }
        // 仅 done 态重建终稿：非 done 态 streamText 由 BEAT_TEXT_CHUNK 流式驱动，
        // 此处重建会与流式覆盖冲突；done 态 streamText 是固化的终稿，需手动重建。
        if (stage.value === 'done') {
          streamText.value = _rebuildStreamTextFromSegments()
          // watch stage→done 不会重触发，置 pendingSaveText 让 WorkspaceView 落库
          pendingSaveText.value = streamText.value
        }
      }
      persist()  // 重渲染结果持久化（刷新后保留降级态/成功态）
      return result
    } catch (e: any) {
      error.value = e.message || '重渲染失败'
      return null
    } finally {
      rerenderingBeatId.value = null
    }
  }

  /** NLE-ADF：轮询 stepping-run state，等首段 ready 后切 beat_stepping。
   * IAB 等短 SSE 环境的备用通道——SSE 流断开后仍能拿到首段就绪状态。 */
  function _stopSteppingPoll() {
    if (_steppingPollTimer) { clearTimeout(_steppingPollTimer); _steppingPollTimer = null }
    _steppingPollCount = 0
  }
  function _pollSteppingReady(runId: string, chapterId: string) {
    _stopSteppingPoll()
    const poll = async () => {
      // 风险3修复：停止条件检查（含 idle/error/done/beat_stepping + session 变更）
      // beat_branch_choosing 也必须停：岔路门挂起期间 run 在等作者选走向，
      // current_segment_ready 恒为 False，继续轮询只会走到上限误报超时
      if (stage.value === 'beat_stepping' || stage.value === 'done' || stage.value === 'idle' || stage.value === 'error' || stage.value === 'beat_branch_choosing' || stage.value === 'beat_authoring') return
      if (steppingRunId.value !== runId) return
      // 风险7修复：轮询次数上限 + 退避
      _steppingPollCount++
      if (_steppingPollCount > _STEPPING_POLL_MAX) {
        error.value = '步进轮询超时（3 分钟无响应）'
        stage.value = 'error'
        generating.value = false
        return
      }
      try {
        const resp = await fetch(`/api/chapters/stepping-run/${runId}/state`)
        // run 已不存在（后端重启/会话过期，内存态即丢）：立即失败并明说原因，
        // 不再每 2s 空轮 3 分钟（既刷屏后端 404 日志，又让作者干等）
        if (resp.status === 404) {
          error.value = '步进会话已失效（后端重启或会话过期），请重新生成'
          stage.value = 'error'
          generating.value = false
          return
        }
        if (!resp.ok) { _steppingPollTimer = setTimeout(poll, 2000); return }
        const st = await resp.json()
        if (st.status === 'error') {
          // 后端步进循环异常兜底（stepping_loop 包装器置 error 态；SSE 断流时
          // 事件丢失，轮询是唯一通道——此前静默 return，界面永久卡在渲染中）
          error.value = '生成失败：后端步进循环异常'
          stage.value = 'error'
          generating.value = false
          return
        }
        // 后处理阶段（PRUNE/审计/守卫/残句，N 次 LLM 串行可达数分钟）：
        // 不算超时次数——此前 90 次上限（约 3 分钟）必然误报"步进轮询超时"
        // 把正常运行砸成 error（真实事故隐患：慢模型后处理常态超 3 分钟）
        if (st.status === 'post_processing') {
          _steppingPollCount = 0
          _steppingPollTimer = setTimeout(poll, 2000)
          return
        }
        if (st.status === 'done') {
          // COMPLETE 帧丢失兜底：SSE 断流（sse.ts 容忍结束不报错）时轮询发现
          // 后端已终态 → 用 final_result 补齐 done 落地（同 advanceBeat onDone
          // 逻辑），否则界面永久卡在后处理态、正文永不落库
          if (st.final_result) {
            _finalizeDoneFromPoll(st.final_result)
          } else {
            // status 先于 final_result 置位的瞬时窗口（stepping_runtime 先改
            // status 再赋 result），下一轮再取
            _steppingPollTimer = setTimeout(poll, 500)
          }
          return
        }
        // 岔路门自愈：BEAT_BRANCH_CHOICE 事件丢失（IAB 短 SSE 断流）时，
        // 轮询发现 run 挂在岔路门 → 本地重建待选状态切 beat_branch_choosing，
        // 否则前端停在 beat_rendering 空等，90 次后误报"轮询超时"
        if (st.awaiting_branch_choice && st.pending_branch?.node) {
          branchChoicePending.value = {
            beat_id: st.pending_branch.beat_id,
            segment_index: st.pending_branch.segment_index,
            node: st.pending_branch.node,
            card: st.pending_branch.card_snapshot || null,
          }
          readyBeatId.value = null
          readyBeatDegraded.value = null
          renderingBeatId.value = null
          stage.value = 'beat_branch_choosing'
          generating.value = false
          return
        }
        // 作者模式自愈：BEAT_AUTHORING_OPEN 事件丢失（IAB 短 SSE 断流）时，
        // 轮询发现 run 挂在作者模式门 → 本地重建创作态（画布基线随之记录），
        // 否则前端停在 beat_rendering 空等，90 次后误报"轮询超时"
        if (st.awaiting_authoring && st.pending_authoring) {
          _onBeatAuthoringOpen({
            beat_id: st.pending_authoring.beat_id,
            segment_index: st.pending_authoring.segment_index,
            target_word_count: st.pending_authoring.target_word_count,
            card_snapshot: st.pending_authoring.card_snapshot,
          })
          return
        }
        if (st.current_segment_ready && st.current_beat_id) {
          if (st.current_segment_text) {
            segmentTexts.value = {
              ...segmentTexts.value,
              [st.current_beat_id]: st.current_segment_text,
            }
            streamText.value = Object.values(segmentTexts.value).join('\n\n')
          }
          readyBeatId.value = st.current_beat_id
          // state 端点从卡快照重建降级提示（SSE 断流后 READY.degraded 已丢）
          readyBeatDegraded.value = st.current_segment_degraded || null
          const cardIdx = beatSlots.value.findIndex(s => s.beat_id === st.current_beat_id)
          readyBeatCard.value = cardIdx >= 0 ? beatSlots.value[cardIdx] : null
          renderingBeatId.value = null
          stage.value = 'beat_stepping'
          generating.value = false
          upsertRenderProgress(st.current_beat_id, 'ready', {
            wordCount: (st.current_segment_text || '').length,
          })
          return
        }
      } catch (e) {
        // 网络错误，继续轮询（有次数上限兜底）
      }
      _steppingPollTimer = setTimeout(poll, 2000)
    }
    _steppingPollTimer = setTimeout(poll, 3000)
  }

  /** 轮询兜底完成：SSE 断流丢失 COMPLETE 帧时，用 state 端点返回的
   *  final_result 补齐 done 落地（与 advanceBeat onDone 同逻辑；兼容无
   *  final_result 的旧后端版本，退化为本地拼接文本）。 */
  function _finalizeDoneFromPoll(result: any) {
    _stopSteppingPoll()
    stage.value = 'done'
    lastDoneMode.value = 'bsadf'
    streamText.value = result?.text || Object.values(segmentTexts.value).join('\n\n')
    finalStats.value = result?.stats || null
    generating.value = false
    // 终态统一复位瞬时段态（与 advanceBeat onDone 一致；renderingBeatId 残留
    // 会让分镜卡「重写本段」被 steppingActive 恒 true 锁死）
    renderingBeatId.value = null
    readyBeatId.value = null
    readyBeatCard.value = null
    readyBeatDegraded.value = null
    branchChoicePending.value = null
    abortController = null
    steppingRunId.value = null
    beatRunId.value = null
    if (result?.beat_slots?.length) beatSlots.value = result.beat_slots
    if (result?.rescue_needed?.length) rescueNeeded.value = result.rescue_needed
    // 降级清单（步进不发 BEAT_DOWNGRADED，done 态降级段复查入口的唯一来源）
    if (result?.degraded_beats?.length) {
      degradedBeats.value = result.degraded_beats.map((d: any) => ({
        beat_id: d.beat_id,
        segment_index: d.segment_index,
        reason: d.reason,
        attempts: d.attempts ?? 2,
      }))
    }
    // 审校结论兜底（ADF_AUDIT 事件丢帧时仍可落地）
    if (result?.audit?.verdict && !adfAudit.value) {
      applyAdfAudit({
        verdict: result.audit.verdict,
        missing_setup_points: result.audit.missing_setup_points || [],
        emotion_mismatches: [],
        structure_issues: [],
        climax_score: result.audit.climax_score ?? result.climax_score,
        fix_targets: [],
      })
    }
    if (result?.generation_run_id) rerenderRunId.value = result.generation_run_id
    _resetAuthoringTransient()
    persist()
  }

  /** NLE-ADF 失步自愈：advanceBeat 收到 409/404 时，用 state 端点把本地
   *  步进态重新对齐到后端真实进度（本地 readyBeatId 陈旧/后端已前进的场景）。
   *  对齐成功回 beat_stepping 继续裁决；run 已终态/丢失才落到 error。 */
  async function _resyncStepping(runId: string, origMsg: string) {
    try {
      const resp = await fetch(`/api/chapters/stepping-run/${runId}/state`)
      if (!resp.ok) throw new Error(`state ${resp.status}`)
      const st = await resp.json()
      // 作者模式挂起（409 的另一种典型场景：作者动作与后端开门时序交错）：
      // 对齐回创作态继续写，不落「失步无法恢复」误报
      if (st.status === 'stepping' && st.awaiting_authoring && st.pending_authoring) {
        error.value = null
        _onBeatAuthoringOpen({
          beat_id: st.pending_authoring.beat_id,
          segment_index: st.pending_authoring.segment_index,
          target_word_count: st.pending_authoring.target_word_count,
          card_snapshot: st.pending_authoring.card_snapshot,
        })
        return
      }
      // 渲染中/后处理中（409 SEGMENT_NOT_READY 的典型场景：段还在渲染，
      // 本地重复提交或旧流超时触发 resync）：后端健康，对齐到渲染态继续等，
      // 不能落「失步无法恢复」误报（真实误报事故）
      if (st.status === 'stepping' && !st.current_segment_ready) {
        renderingBeatId.value = st.current_beat_id || null
        readyBeatId.value = null
        stage.value = 'beat_rendering'
        generating.value = true
        error.value = null
        _pollSteppingReady(runId, currentChapterId || '')
        return
      }
      if (st.status === 'post_processing') {
        renderingBeatId.value = null
        stage.value = 'assembling'
        generating.value = true
        error.value = null
        _pollSteppingReady(runId, currentChapterId || '')
        return
      }
      if (st.status === 'stepping' && st.current_segment_ready && st.current_beat_id) {
        const idx = typeof st.current_beat_index === 'number' ? st.current_beat_index : 0
        const ids: string[] = Array.isArray(st.cards) ? st.cards : []
        lockedBeatIds.value = new Set(ids.slice(0, Math.max(idx, 0)))
        if (st.current_segment_text) {
          segmentTexts.value = {
            ...segmentTexts.value,
            [st.current_beat_id]: st.current_segment_text,
          }
          streamText.value = Object.values(segmentTexts.value).join('\n\n')
        }
        readyBeatId.value = st.current_beat_id
        readyBeatDegraded.value = st.current_segment_degraded || null  // 恢复降级态
        const cardIdx = beatSlots.value.findIndex(s => s.beat_id === st.current_beat_id)
        readyBeatCard.value = cardIdx >= 0 ? beatSlots.value[cardIdx] : null
        renderingBeatId.value = null
        stage.value = 'beat_stepping'
        generating.value = false
        error.value = null
        upsertRenderProgress(st.current_beat_id, 'ready', {
          wordCount: (st.current_segment_text || '').length,
        })
        persist()
        return
      }
      if (st.status === 'done') {
        if (st.final_result) {
          // 优先用 final_result 补齐终稿/统计（resync 场景同样可能丢 COMPLETE 帧）
          _finalizeDoneFromPoll(st.final_result)
        } else {
          stage.value = 'done'
          generating.value = false
          persist()
        }
        return
      }
    } catch {
      // 对齐失败（run 丢失/网络错误），落到下面的 error 分支
    }
    // 404 = run 在后端内存中已不存在（uvicorn --reload 重启 / 超 TTL 被回收），
    // 与网络抖动区分开，文案直接说清原因，避免作者以为是临时故障反复重试。
    error.value = /404/.test(origMsg)
      ? '步进会话已失效（后端已重启或等待超时），点「重试」从头重新生成本章'
      : `步进会话失步且无法恢复（${origMsg}），请重新生成`
    stage.value = 'error'
    generating.value = false
    persist()
  }

  /** 取消/清理 BS-ADF 后台运行（步进/Track A/Track B），避免后端僵尸 task。
   *  完成态正常结束不调用；取消/重置/切章/卸载时调用。 */
  function _cancelSteppingRun() {
    const runId = steppingRunId.value || beatRunId.value || rerenderRunId.value
    if (!runId || !currentChapterId) return
    void bsadfApi.cancelRun(currentChapterId, runId).catch(() => {
      // 取消调用失败不阻塞 UI（run 可能已过期或已完成）
    })
  }

  /** NLE-ADF：步进锁死推进（每段就绪后作者按 Space 推进下一段）。
   *  P2/P3 新增 action：lock_with_text（作者文本定稿，跳过 LLM）/ back（回退上一段） */
  function advanceBeat(
    chapterId: string,
    action: 'pass' | 'edit' | 'branch' | 'skip' | 'lock_with_text' | 'back' | 'render',
    opts: {
      beatId: string
      editedSlot?: BeatSlot
      branchChoice?: { option_id: string; label: string; plot_impact: string }
      authorText?: string  // P2：lock_with_text 时携带作者定稿的段正文
    },
  ) {
    if (!steppingRunId.value || !opts.beatId) return
    // 风险4修复：防止重复提交——正在渲染时不接受新 advanceBeat
    if (generating.value && stage.value === 'beat_rendering') return
    // 风险4修复：中止旧的 AbortController（防止旧 SSE 流持续 mutate 状态）
    if (abortController) abortController.abort()
    abortController = new AbortController()
    currentChapterId = chapterId
    generating.value = true
    stage.value = 'beat_rendering'
    // 即时反馈：点亮当前段「渲染中」让作者看到点击生效。pass 之后后端要先跑
    // 记忆倒灌（一次 LLM）再发下一段的 BEAT_RENDER_START，期间若无任何视觉
    // 反馈，作者会以为没点上。
    // ⚠ 但这个 renderingBeatId 指向的是【刚被接受的旧段】，不是真在渲染的段——
    // currentTask 据此判断「推进过渡期」（已锁段却在 rendering 态 = 必为过渡），
    // 显示段号无关的「正在准备下一段」而非误导性的「正在渲染第 N 段」（推进重渲事故）。
    // 待下一段 BEAT_RENDER_START 携真实 beat_id 到达，renderingBeatId 更新为
    // 未锁的新段，currentTask 即切换回带段号的「正在渲染第 N+1 段」。
    readyBeatId.value = null
    readyBeatCard.value = null
    renderingBeatId.value = opts.beatId
    // P2：lock_with_text 的作者文本不在此预写 segmentTexts——后端
    // lock_segment_with_author_text 会以 BEAT_TEXT_CHUNK 全量推回作者文本，
    // 预写会被 onBeatChunk 的 append 拼成两遍（真实事故：采纳后正文翻倍）。
    // 主编辑器直改场景：作者文本已经 setReadySegmentText 同步进 segmentTexts，
    // 置一次性替换标记，全量推回时整段替换而非 append（同一防翻倍机制）。
    if (action === 'lock_with_text') _chunkReplaceOnce.add(opts.beatId)
    // 即时反馈靠上面的 renderingBeatId 点亮「渲染中」即可。
    // 轮询兜底：advanceBeat 的 SSE 流可能在下一段就绪前断开
    // （IAB 等短 SSE 环境），轮询作为备用通道接管。
    _pollSteppingReady(steppingRunId.value, chapterId)

    bsadfApi.advanceBeat(
      chapterId,
      {
        run_id: steppingRunId.value,
        beat_id: opts.beatId,
        action,
        edited_slot: opts.editedSlot,
        branch_choice: opts.branchChoice,
        author_text: opts.authorText,  // P2：透传给后端 lock_with_text
      },
      {
        onBeatRenderStart: (data) => {
          renderingBeatId.value = data.beat_id
          readyBeatId.value = null
          readyBeatDegraded.value = null
          _noteSteppingActivity()
          // 全量 chunk 语义：渲染开始即作废旧文本（edit/back 重渲防翻倍）
          _clearSegmentText(data.beat_id)
          // 作者模式代笔：chunk 直接灌成画布幽灵草稿（不走路由预览投影）
          if (authoringEnabled.value) beginGhost('render')
          upsertRenderProgress(data.beat_id, 'rendering', { segmentIndex: data.segment_index })
          stepProgress.value = {
            label: '逐段渲染',
            index: (data.segment_index ?? 0) + 1,
            total: beatSlots.value.length,
          }
          if (data.card_snapshot) {
            const idx = beatSlots.value.findIndex(s => s.beat_id === data.beat_id)
            if (idx >= 0) beatSlots.value[idx] = data.card_snapshot
          }
        },
        // NLE-ADF 2.0 作者模式：拍打开，等作者创作（SSE 事件与轮询自愈共用处理）
        onBeatAuthoringOpen: (data) => {
          _onBeatAuthoringOpen(data)
        },
        onBeatChunk: (data) => {
          _handleBeatChunk(data)
          // 作者模式代笔：正文以幽灵草稿形态流进画布（作者可改词再锁）
          if (authoringEnabled.value && ghostSource.value === 'render') appendGhost(data.delta)
        },
        onBeatReady: (data) => {
          renderingBeatId.value = null
          readyBeatId.value = data.beat_id
          readyBeatCard.value = data.card_snapshot || null
          // 消费降级载荷：步进模式后端只把降级信息挂在 READY 上（不发
          // BEAT_DOWNGRADED 事件），不存则作者只见"0 字"误判为空段
          readyBeatDegraded.value = data.degraded || null
          stage.value = 'beat_stepping'
          generating.value = false
          upsertRenderProgress(data.beat_id, 'ready', { segmentIndex: data.segment_index, wordCount: data.word_count })
          stepProgress.value = {
            label: '待你裁决',
            index: (data.segment_index ?? 0) + 1,
            total: beatSlots.value.length,
          }
        },
        onBeatBranchChoice: (data) => {
          // 岔路门挂起期间必须停轮询：run 在等作者选走向，current_segment_ready
          // 恒为 False，不停的话 90 次轮询后误报"步进轮询超时"把会话砸成 error
          // （真实事故：每次生成挂在 beat0 岔路门，3 分钟后必报"生成失败"）
          _stopSteppingPoll()
          branchChoicePending.value = {
            beat_id: data.beat_id,
            segment_index: data.segment_index,
            node: data.node,
            card: data.card_snapshot || null,
          }
          readyBeatId.value = null
          readyBeatDegraded.value = null
          renderingBeatId.value = null
          stage.value = 'beat_branch_choosing'
          generating.value = false
        },
        onBeatLocked: (data) => {
          readyBeatDegraded.value = null
          lockedBeatIds.value = new Set([...lockedBeatIds.value, data.beat_id])
          if (data.extracted_facts) {
            emergentFacts.value = { ...emergentFacts.value, [data.beat_id]: data.extracted_facts }
          }
          upsertRenderProgress(data.beat_id, 'rendered')
        },
        onBeatSkipped: (data) => {
          // skipped 段不入 locked 集合，也不应视为已渲染；单独标记为 skipped
          readyBeatDegraded.value = null
          // 清掉残留正文：跳过段不进终稿（重建时另有 skipped 过滤兜底）
          _clearSegmentText(data.beat_id)
          upsertRenderProgress(data.beat_id, 'skipped')
        },
        onBeatBacked: (data) => {
          // 后端已弹栈回退到目标段：目标段及之后全部作废重渲（快照语义），
          // 前端统一回滚这些段的正文/锁定/进度（此前只清目标段 → 后段旧文本
          // 在重渲时被 chunk append 拼成翻倍、状态轨残留陈旧「已就绪」灯）。
          _rollbackFromBeat(data.beat_id, data.segment_index)
          // 作者模式：画布侧同步删掉回滚拍的创作区文本（后端只回滚生成状态）
          if (authoringEnabled.value) _authoringRollbackDoc(data.beat_id)
          readyBeatId.value = null
          readyBeatCard.value = null
          readyBeatDegraded.value = null
          renderingBeatId.value = data.beat_id
          stage.value = 'beat_rendering'
          generating.value = true
          upsertRenderProgress(data.beat_id, 'rendering', { segmentIndex: data.segment_index })
          if (data.rejected) {
            // 首段无可回退：仅提示，后端会重发 BEAT_RENDER_READY 恢复裁决态。
            // 仅当 error 仍是本条提示时才清除，避免覆盖同期真实错误
            error.value = '已经是第一段，无法继续回退'
            setTimeout(() => {
              if (error.value === '已经是第一段，无法继续回退') error.value = null
            }, 2000)
          }
        },
        onAllBeatsLocked: () => {
          renderingBeatId.value = null  // 末段无下一个 RENDER_START 清灯，在此复位
          stage.value = 'assembling'
        },
        onLoop1Checked: (data) => {
          loop1Result.value = data
        },
        onStage: (stageName, _data) => {
          // 步进循环内后处理阶段透传：PRUNE/ANCHOR_AUDIT/REFINE/BEAT_PATCH/
          // CONSISTENCY_GUARD 是数分钟长耗时，此前空实现让步骤条永久停在
          // 上一段「渲染 N/M 段」，用户面对冻结黑盒（后处理黑盒事故）
          _noteSteppingActivity()
          const { label, sessionStage } = mapBsadfStageToLabel(stageName)
          if (sessionStage) stage.value = sessionStage
          stepProgress.value = { label }
        },
        // 后处理期事件（ADF_AUDIT/ADF_CONSISTENCY 等）只随 advance 流到达，
        // 必须接 handleBsadfEvent——空实现曾让审校结论对步进章节恒空
        onEvent: (event, data) => {
          handleBsadfEvent(event, data)
        },
        onDone: (result) => {
          stage.value = 'done'
          lastDoneMode.value = 'bsadf'
          streamText.value = result.text || Object.values(segmentTexts.value).join('\n\n')
          finalStats.value = startedAt != null
            ? { ...(result.stats || {}), duration_ms: Date.now() - startedAt }
            : result.stats
          generating.value = false
          // 终态统一复位瞬时段态（renderingBeatId 残留会让分镜卡「重写本段」
          // 被 steppingActive 恒 true 锁死——真实交互死路，每次完成必现）
          _stopSteppingPoll()
          renderingBeatId.value = null
          readyBeatId.value = null
          readyBeatCard.value = null
          readyBeatDegraded.value = null
          branchChoicePending.value = null
          abortController = null
          // 运行凭证随 COMPLETE 失效（防 done 后 cancel 误打到已完结 run）
          steppingRunId.value = null
          beatRunId.value = null
          // 完成后用后端下发的卡刷新（渲染后 status + branch_directive；
          // 此前未消费，分镜卡停留在渲染前快照）
          if (result.beat_slots?.length) {
            beatSlots.value = result.beat_slots
          }
          // ⚠ 步进模式 rescue 信息只随 COMPLETE 载荷下发（后端不发
          // RESCUE_NEEDED SSE 事件）——此前未消费导致救援卡在步进完成后
          // 永不显示，路线 C 救援流程断链
          if (result.rescue_needed?.length) {
            rescueNeeded.value = result.rescue_needed
          }
          // COMPLETE 载荷的降级清单：步进不发 BEAT_DOWNGRADED，这是降级段
          // 唯一来源——不消费则 done 态降级段彻底隐形（post-rescue 永不触发）
          if (result.degraded_beats?.length) {
            degradedBeats.value = result.degraded_beats.map((d: any) => ({
              beat_id: d.beat_id,
              segment_index: d.segment_index,
              reason: d.reason,
              attempts: d.attempts ?? 2,
            }))
          }
          // COMPLETE.audit 兜底：ADF_AUDIT 事件若丢帧，审校结论仍可落地
          if (result.audit?.verdict && !adfAudit.value) {
            applyAdfAudit({
              verdict: result.audit.verdict as AdfAuditResult['verdict'],
              missing_setup_points: result.audit.missing_setup_points || [],
              emotion_mismatches: [],
              structure_issues: [],
              climax_score: result.audit.climax_score ?? result.climax_score,
              fix_targets: [],
            })
          }
          // 供完成后 rerender 取完整渲染上下文（pending 以该 run_id 为 key）
          rerenderRunId.value = result.generation_run_id || null
          _resetAuthoringTransient()
          persist()
        },
        onError: (msg) => {
          // 步进失步自愈：本地待裁决段与后端当前段不一致（409 BEAT_NOT_CURRENT）
          // 或 run 过期（404）时，先拉 state 端点重新对齐，对齐失败才真报错
          if (/409|404/.test(msg) && steppingRunId.value) {
            void _resyncStepping(steppingRunId.value, msg)
            return
          }
          error.value = msg
          stage.value = 'error'
          generating.value = false
          persist()
        },
      },
      abortController.signal,
    )
  }

  /** NLE-ADF：提交步进岔路选择（optionId=null 表示接受默认走向/跳过补充，等价 Space；
   *  'custom:' 前缀 = Loop1 缺口节点的作者补充文本，label 即走向注入） */
  function submitBranchChoice(optionId: string | null) {
    if (!branchChoicePending.value || !currentChapterId) return
    const beatId = branchChoicePending.value.beat_id
    if (optionId === null) {
      advanceBeat(currentChapterId, 'pass', { beatId })
    } else if (optionId.startsWith('custom:')) {
      // Loop1 缺口补充：作者自定义文本作为本段走向（plot_impact 留空，
      // 后端 directive = plot_impact or label = 文本本身）
      const text = optionId.slice('custom:'.length).trim()
      advanceBeat(currentChapterId, 'branch', {
        beatId,
        branchChoice: text ? { option_id: optionId, label: text, plot_impact: '' } : undefined,
      })
    } else {
      const node = branchChoicePending.value.node
      const opt = node.options.find(o => o.option_id === optionId)
      advanceBeat(currentChapterId, 'branch', {
        beatId,
        branchChoice: opt ? { option_id: opt.option_id, label: opt.label, plot_impact: opt.plot_impact } : undefined,
      })
    }
    branchChoicePending.value = null
    stage.value = 'beat_rendering'
    generating.value = true
    // 岔路门提交后重启轮询兜底：advanceBeat 的 SSE 流可能在下一段
    // 就绪前断开（IAB 短 SSE），轮询是备用通道。
    if (steppingRunId.value && currentChapterId) {
      _pollSteppingReady(steppingRunId.value, currentChapterId)
    }
  }

  // ===== NLE-ADF：Space 键步进锁死推进 =====
  function _spaceKeyHandler(e: KeyboardEvent) {
    if (e.code !== 'Space') return
    if (e.isComposing) return  // IME 候选期的 Space 是选词键
    const target = e.target as HTMLElement | null
    const tag = target?.tagName
    if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT') return
    // adaptive composing 态作者就在正文编辑器里写，Space 必须能触发缝合/续写；
    // 旧路径（stage 机器态）保留原守卫——contenteditable 内 Space 一律放行不拦截。
    const _adaptiveComposing = adaptiveMode.value && authorLane.value === 'composing'
    if (target?.isContentEditable && !_adaptiveComposing) return
    if (stage.value === 'beat_branch_choosing' && currentChapterId) {
      e.preventDefault()
      submitBranchChoice(null)
      return
    }
    if (stage.value === 'beat_stepping' && readyBeatId.value && currentChapterId) {
      // 降级段禁用 Space 推进：降级段正文为空、终稿会消失，按 Space(=pass)
      // 会默默丢段且无强警告（降级引导事故）。降级态焦点条已隐藏 Space 提示，
      // 这里同步禁用快捷键，引导作者走「重写本段/直接在正文写」。
      if (readyBeatDegraded.value) return
      e.preventDefault()
      if (authoringEnabled.value) {
        // 作者模式代笔裁决：画布幽灵即事实源，统一走锁拍路由
        // （作者可能已改幽灵文本；segmentTexts 路由感知不到画布编辑）
        lockAuthoringBeat()
        return
      }
      // 作者在主编辑器改过正文时自动改走 lock_with_text（改动随本段定稿）
      acceptReadySegment(currentChapterId)
    }
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
      const result: any = await chapterApi.defatSelection({ text: original })
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

  // 幽灵/缝合/锁拍快捷键在编辑器内生效——必须捕获阶段拦截（bubble 阶段
  // ProMirror 已先消费按键把 Space/Enter 插进文档，拦截失效）。
  function _authoringKeyHandler(e: KeyboardEvent) {
    // 中文输入法组合态全放行：IME 候选期的 Space/Enter/数字是选词键，拦截=灾难
    if (e.isComposing) return
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
    const inAuthoringContext = stage.value === 'beat_authoring'
      || (stage.value === 'beat_stepping' && authoringEnabled.value)
      || ghostActive.value
      // NLE-ADF 3.0：adaptive composing 态——作者在正文编辑器里写，
      // Space（缝合/续写）/ Enter（Ctrl+沉淀）/ 数字（吸附）必须在捕获阶段拦截，
      // 否则 ProMirror 在 bubble 阶段先把 Space/Enter 插进文档，拦截失效。
      || (adaptiveMode.value && authorLane.value === 'composing')
    if (!inAuthoringContext) return
    const target = e.target as HTMLElement | null
    // 编辑器外的表单控件不拦（岔路面板自定义走向文本框等）
    if (target && !target.isContentEditable && (target.tagName === 'INPUT' || target.tagName === 'TEXTAREA')) return

    // Esc：蒸发幽灵 > 关 Dock > 清空吸附（逐层退出 AI 临时元素）
    if (e.key === 'Escape') {
      if (ghostActive.value) {
        e.preventDefault()
        e.stopPropagation()
        evaporateGhost()
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
    // Tab：手动唤起 Spark Dock（parts 态——递设定物料做缝合锚点）。
    // 旧路径 beat_authoring + 新路径 adaptive composing 均生效。
    if (e.key === 'Tab' && !ghostActive.value && (
      stage.value === 'beat_authoring'
      || (adaptiveMode.value && authorLane.value === 'composing')
    )) {
      e.preventDefault()
      e.stopPropagation()
      showSparkDock()
      return
    }
    // 数字键 1~4：Dock 打开时吸附对应挂件（拦默认防数字进正文）
    if (sparkDockVisible.value && /^Digit[1-4]$/.test(e.code)) {
      e.preventDefault()
      e.stopPropagation()
      attachSparkPart(Number(e.code.slice(5)) - 1)
      return
    }
    // Enter：幽灵在屏 = 锁死碎片（摘 mark 变正文；拦默认防多插一个换行）
    if (e.key === 'Enter' && !e.ctrlKey && !e.metaKey && ghostActive.value) {
      e.preventDefault()
      e.stopPropagation()
      commitGhostFragment()
      return
    }
    // Ctrl+Enter：锁死本拍（创作态/代笔裁决态）或沉淀当前段（adaptive composing 态）
    if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) {
      // adaptive composing 态：触发沉淀（走 useAdaptiveAssist.settleCurrent）
      if (adaptiveMode.value && authorLane.value === 'composing') {
        e.preventDefault()
        e.stopPropagation()
        _adaptiveSettleFn?.()
        return
      }
      e.preventDefault()
      e.stopPropagation()
      lockAuthoringBeat()
      return
    }
    // Ctrl+Backspace：回退上一拍（P3 快照栈；抽屉收起时画布内唯一回退入口）
    if ((e.ctrlKey || e.metaKey) && e.code === 'Backspace'
      && stage.value === 'beat_authoring' && authoringBeatId.value && currentChapterId) {
      e.preventDefault()
      e.stopPropagation()
      advanceBeat(currentChapterId, 'back', { beatId: authoringBeatId.value })
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
      || (adaptiveMode.value && authorLane.value === 'composing')
    )
    if (e.code === 'Space' && spaceActive) {
      const editor = chapterEditorHandle.value
      if (!editor) return
      // adaptive 模式分支：零件吸附 → 缝合续写；否则顺句续写
      if (adaptiveMode.value && authorLane.value === 'composing') {
        if (attachedParts.value.length) {
          e.preventDefault()
          e.stopPropagation()
          _adaptiveContinueFn?.('stitch', attachedParts.value.map((p) => ({ text: p.text, direction: p.direction })))
          // 缝合触发：清吸附意图 + 隐藏卡片舱（让位给脉冲点/幽灵草稿，避免视觉混乱）
          // 下次停顿心跳会重新弹出卡片舱（如果段落变了）
          clearAttachedParts()
          hideSparkDock()
          return
        }
        const $fromAd = editor.state.selection.$from
        if ($fromAd.parent.textContent.trim() !== '') {
          e.preventDefault()
          e.stopPropagation()
          _adaptiveContinueFn?.('continue', [])
          return
        }
        return  // 空行 + 无零件：不拦截（adaptive 模式不召唤代笔，由作者主动）
      }
      // 旧路径分支
      if (attachedParts.value.length) {
        e.preventDefault()
        e.stopPropagation()
        requestStitch(attachedParts.value.map((p) => p.text))
        // 缝合触发即消费吸附意图（下一次缝合重新点选）
        clearAttachedParts()
        hideSparkDock()
        return
      }
      const $from = editor.state.selection.$from
      if (stage.value === 'beat_authoring' && $from.parent.textContent.trim() === '') {
        // 空行 = 召唤 AI 整段代笔
        e.preventDefault()
        e.stopPropagation()
        summonGhostRender()
        return
      }
      if ($from.parent.textContent.trim() !== '') {
        // 无零件裸补全：AI 顺写当前句（管线期也可——自由缝合不等卡）
        e.preventDefault()
        e.stopPropagation()
        requestStitch([])
        return
      }
    }
  }
  onMounted(() => window.addEventListener('keydown', _spaceKeyHandler))
  onMounted(() => window.addEventListener('keydown', _authoringKeyHandler, true))
  onUnmounted(() => {
    _cancelSteppingRun()
    _stopSteppingPoll()
    // 卸载即中止在途 SSE：否则流继续跑到终态事件，期间 mutate 已卸载 session
    // 的 ref（有界泄漏）；主动 abort 在 sse.ts 按非错误静默结束
    if (abortController) {
      abortController.abort()
      abortController = null
    }
    window.removeEventListener('keydown', _spaceKeyHandler)
    window.removeEventListener('keydown', _authoringKeyHandler, true)
  })

  return {
    stage,
    generating,
    error,
    stepProgress,
    engine,
    tierDecision,
    streamText,
    climaxScore,
    inflightEvents,
    auditFindings,
    auditVerdict,
    degraded,
    finalStats,
    lastDoneMode,
    // V3.2 ADF
    adfAnchor,
    adfPreconditions,
    adfEmotionCurve,
    adfAudit,
    // V4.1 Refinery
    refineryIssues,
    refineryRunId,
    refinerySurgeries,
    refineryHolisticVerdict,
    refineryStats,
    // BS-ADF
    beatSlots,
    beatRunId,
    renderProgress,
    degradedBeats,
    bsadfTrack,
    steppingEnabled,
    rerenderingBeatId,
    decisionSet,
    rescueNeeded,
    // NLE-ADF 步进
    segmentTexts, readyBeatId, readyBeatCard, lockedBeatIds,
    renderingBeatId, loop1Result, steppingRunId, emergentFacts,
    branchChoicePending, readyBeatDegraded,
    // rerender-beat 成功后的待落库正文信号（WorkspaceView watch → 落库）
    pendingSaveText,
    advanceBeat,
    submitBranchChoice,
    // NLE-ADF 2.0 作者模式
    authoringEnabled, authoringBeatId, authoringBeatCard, stitching, fragmentCounts,
    requestStitch, lockAuthoringBeat, commitGhostFragment, summonGhostRender,
    scrubToFragment,
    autoCutNotice, mergeAutoCut,
    // 主编辑器直改（裁决期）：dirty 标记 + 回写/还原/接受路由
    readySegmentDirty,
    setReadySegmentText,
    revertReadySegment,
    acceptReadySegment,
    isTerminal,
    currentTask,
    cancel,
    reset,
    retry,
    startRefinery,
    confirmRefinery,
    startBeat,
    confirmBeats,
    cancelBeat,
    rerenderBeat,
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
  }
}

function tierLabel(tier: string): string {
  switch (tier) {
    case 'climax':
      return '高潮章'
    case 'turn':
      return '转折章'
    case 'progress':
      return '推进章'
    case 'transition':
      return '过渡章'
    default:
      return tier
  }
}
