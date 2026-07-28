/**
 * 统一生成会话（V3.1 F3 新建，规格 §11.2）。
 *
 * 职责：封装 V3.2 ADF（/generate-adf）生成链路，
 * 外加 V4.1 Refinery 精修（/refinery/diagnose + /refinery/confirm）的两阶段 SSE，
 * 把原始事件流解析为会话状态机供 UI 订阅。
 *
 * 引擎：固定 V3.2 ADF（adfApi.streamGenerate，消费 ADF_STAGE/ADF_ANCHOR_DESIGNED/... 事件）。
 * V3.1 Unified 引擎后端已剥离（/generate 端点不存在），相关死代码（startUnified 等）已删除。
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
import { ref, computed, onMounted, onUnmounted, type Ref, type ComputedRef } from 'vue'
import { adfApi, refineryApi, bsadfApi, type AdfEngine, type AdfAuditResult, type RefineryIssue, type RefinerySurgery, type RefineryHolisticVerdict, type IssueDecision, type BeatSlot, type RenderProgress, type DegradedBeat, type ChapterDecisionSet, type RescueNeededItem } from '../../../services/api/domain'

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
  | 'setup_ready' // 铺垫结构就绪，等确认
  | 'climax_writing' // 高潮段写作中
  | 'climax_ready' // 高潮段就绪，等确认
  | 'zone_writing' // 分区写作（蓄势段 + 铺陈段）
  | 'assembling' // 组装
  | 'auditing' // 审校
  | 'refining' // 精修
  | 'beat_pending' // 槽位卡已生成，等作者编辑（Track B 单次暂停态，分支选择内嵌其中）
  | 'beat_rendering' // 作者确认后，后台顺序渲染各段
  | 'beat_stepping' // NLE-ADF：正在逐段步进（某段就绪等空格推进）
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
  // 派生
  isTerminal: ComputedRef<boolean>
  // 控制
  start: (chapterId: string, tier: string, opts?: { targetWordCount?: number | null; maxSegments?: number; authorIntent?: string; expectationActions?: Record<string, string> }) => void
  cancel: () => void
  reset: () => void
  /** 失败重试：再次触发最近一次入口（生成 start / 精修诊断 startRefinery / BS-ADF startBeat） */
  retry: () => void
  // V4.1 Refinery 控制
  startRefinery: (chapterId: string, opts?: { mode?: 'deep' | 'light'; enablePolish?: boolean; rawText?: string | null }) => void
  confirmRefinery: (chapterId: string, decisions: IssueDecision[], customIssues?: RefineryIssue[]) => void
  // BS-ADF 控制
  startBeat: (chapterId: string, tier: string, opts?: { track?: 'A' | 'B'; targetWordCount?: number | null; maxSegments?: number; authorIntent?: string; expectationActions?: Record<string, string>; steppingEnabled?: boolean; enableOutlineSelfCheck?: boolean; enableMemoryIngestion?: boolean }) => void
  confirmBeats: (chapterId: string, editedSlots: BeatSlot[], opts?: { branchChoices?: Record<string, string>; skipped?: boolean }) => void
  cancelBeat: () => void
  /** BS-ADF：降级/救援单卡重渲染（调 /rerender-beat，同步 JSON；editedSlot 携带作者编辑后的整卡） */
  rerenderBeat: (chapterId: string, beatId: string, editedSlot: BeatSlot) => Promise<any>
  /** NLE-ADF：步进锁死推进（每段就绪后作者按 Space 推进下一段） */
  advanceBeat: (
    chapterId: string,
    action: 'pass' | 'edit' | 'branch' | 'skip',
    opts: {
      beatId: string
      editedSlot?: BeatSlot
      branchChoice?: { option_id: string; label: string; plot_impact: string }
    },
  ) => void
  // 持久化：进入章节时恢复上次会话产物（localStorage）
  loadForChapter: (chapterId: string) => void
  persist: () => void
}

export function useGenerationSession(): GenerationSession {
  const stage = ref<SessionStage>('idle')
  const generating = ref(false)
  const error = ref<string | null>(null)
  const stepProgress = ref<StepProgress | null>(null)
  const engine = ref<AdfEngine>('v3.2')

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
  const rerenderingBeatId = ref<string | null>(null)
  // DDE 章节级剧情分叉（Track A：DDE_AUTO_APPLIED；Track B：BEAT_SLOTS_BUILT 内嵌）
  const decisionSet = ref<ChapterDecisionSet | null>(null)
  // 救援标记：核心转折未落地的节拍（路线 C 内联救援卡数据源）
  const rescueNeeded = ref<RescueNeededItem[]>([])

  // ===== NLE-ADF 步进状态 =====
  const segmentTexts = ref<Record<string, string>>({})
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
  const emergentFacts = ref<Record<string, any>>({})

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
    // 切换章节：先把当前章的状态存下来
    if (currentChapterId && currentChapterId !== chapterId) {
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
    rerenderingBeatId.value = null
    decisionSet.value = null
    rescueNeeded.value = []
    lastDoneMode.value = null
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
    // ADF_ANCHOR_DESIGNED：存锚点设计（climax_description 供脉络条摘要展示）
    if (event === 'ADF_ANCHOR_DESIGNED') {
      adfAnchor.value = {
        climax_intensity: data.climax_intensity,
        climax_description: data.climax_description,
        setup_points: data.setup_points,
        emotion_flow_samples: data.emotion_flow_samples,
      }
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
    }
    // UNIFIED_METRIC / GENERATION_RUN：audit 已通过 ADF_AUDIT 处理（同 ADF onMetric 语义）
  }

  function start(
    chapterId: string,
    tier: string,
    opts: { targetWordCount?: number | null; maxSegments?: number; authorIntent?: string; expectationActions?: Record<string, string> } = {},
  ) {
    if (generating.value) return
    // 记录入口供失败后 retry（重试即再次触发同入口）
    lastAction = () => start(chapterId, tier, opts)
    // 绑定章节 + 清旧快照（这是全新生成，旧产物作废）
    currentChapterId = chapterId
    _clearSnapshot(chapterId)
    _resetInternal()
    generating.value = true
    stage.value = 'tier_classifying'
    abortController = new AbortController()
    startedAt = Date.now()  // 记录开始时间供 onDone 计算耗时

    // 固定使用 V3.2 ADF 引擎（锚点驱动流）
    engine.value = 'v3.2'
    startAdf(
      chapterId, tier,
      opts.targetWordCount ?? null, opts.maxSegments ?? 6,
      opts.authorIntent, opts.expectationActions,
    )
  }

  /** V3.2 ADF 引擎：调 adfApi.streamGenerate */
  function startAdf(
    chapterId: string,
    tier: string,
    targetWordCount: number | null,
    maxSegments: number,
    authorIntent?: string,
    expectationActions?: Record<string, string>,
  ) {
    adfApi.streamGenerate(
      chapterId,
      {
        tier: tier as any,
        target_word_count: targetWordCount,
        max_segments: maxSegments,
        author_intent: authorIntent || null,
        expectation_actions: expectationActions || null,
      },
      {
        onStage: (adfStage) => {
          const { label, sessionStage } = mapAdfStageToLabel(adfStage)
          stage.value = sessionStage
          stepProgress.value = { label }
        },
        onSpineBuilt: (data) => {
          stepProgress.value = { label: '前文脉络已梳理' }
        },
        onAnchorDesigned: (anchor) => {
          adfAnchor.value = anchor
          adfEmotionCurve.value = anchor.emotion_flow_samples || []
          stepProgress.value = {
            label: `高潮设计完成（强度 ${anchor.climax_intensity}/10）`,
          }
        },
        onTierDecided: (decision) => {
          applyTierDecision(decision)
        },
        onProgress: (index, total, data) => {
          stage.value = 'zone_writing'
          const register = data.register ? `（${data.register}）` : ''
          stepProgress.value = {
            label: `写正文${register}`,
            index,
            total,
            zone: 'forward_flow',
          }
        },
        // ADF_PRECONDITION_LANDED 事件不再推入 inflightEvents（用户不需要该提示卡片）
        onAudit: (audit) => {
          applyAdfAudit(audit)
        },
        onMetric: (metrics) => {
          // UNIFIED_METRIC 在 ADF 中复用，metrics.audit 已通过 onAudit 处理
        },
        onEvent: (event, data) => {
          if (event === 'ADF_METADATA' && data.climax_design) {
            // 完整元数据：填充 ADF 专用字段
            if (Array.isArray(data.climax_design.setup_points)) {
              adfPreconditions.value = data.climax_design.setup_points
            }
          } else if (event === 'DEGRADED') {
            degraded.value.push({
              reason: data.reason,
              phase: data.phase,
              detail: data.detail,
            })
          } else if (event === 'FINAL_TEXT_STREAM') {
            stepProgress.value = { label: '输出正文' }
          }
        },
        onChunk: (chunk) => {
          streamText.value += chunk
        },
        onDone: (result) => {
          generating.value = false
          stage.value = 'done'
          finalStats.value = result.stats || null
          if (startedAt != null) {
            // 把耗时塞进 stats 供弹窗读取（后端 stats 无此字段，纯前端计时）
            finalStats.value = { ...(result.stats || {}), duration_ms: Date.now() - startedAt }
          }
          if (result.climax_score != null) climaxScore.value = result.climax_score
          lastDoneMode.value = 'adf'
          abortController = null
          persist()  // 生成完成：持久化全部产物
        },
        onError: (err) => {
          error.value = err
          generating.value = false
          stage.value = 'error'
          abortController = null
          persist()  // 出错也存（保留已产出的部分产物供查看）
        },
      },
      abortController?.signal,
    )
  }

  /** 把 ADF_STAGE 事件映射为写作语言的步骤标签（V3.2） */
  function mapAdfStageToLabel(adfStage: string): { label: string; sessionStage: SessionStage } {
    switch (adfStage) {
      case 'CONTEXT_ASSEMBLING':
        return { label: '准备素材', sessionStage: 'tier_classifying' }
      case 'SPINE_BUILDING':
        return { label: '梳理前文脉络', sessionStage: 'tier_classifying' }
      case 'ANCHOR_DESIGN':
        return { label: '设计本章高潮', sessionStage: 'tier_classifying' }
      case 'TIER_DECIDE':
        return { label: '确定篇幅', sessionStage: 'tier_classifying' }
      case 'FORWARD_FLOW':
        return { label: '正文写作', sessionStage: 'zone_writing' }
      case 'PRUNE':
        return { label: '去 AI 味剪枝', sessionStage: 'zone_writing' }
      case 'ANCHOR_AUDIT':
        return { label: '结构检查', sessionStage: 'auditing' }
      case 'REFINE':
        return { label: '补充铺垫', sessionStage: 'refining' }
      case 'BEAT_PATCH':
        return { label: '补写遗漏节拍', sessionStage: 'refining' }
      case 'CONSISTENCY_GUARD':
        return { label: '一致性守卫', sessionStage: 'auditing' }
      default:
        return { label: adfStage, sessionStage: stage.value }
    }
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
        return { label: '重构剪枝', sessionStage: 'zone_writing' }
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
    if (abortController) {
      abortController.abort()
      abortController = null
    }
    generating.value = false
    stage.value = 'idle'
    error.value = null // 清空残留错误（取消/关闭即用户主动放弃）
  }

  /** 失败重试：再次触发最近一次入口（start / startRefinery 已记录 lastAction） */
  function retry() {
    if (generating.value) return
    error.value = null
    lastAction?.()
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

  /** BS-ADF：启动生成（Track A 全自动 / Track B 跑到槽位卡单次暂停） */
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
      enableOutlineSelfCheck?: boolean
      enableMemoryIngestion?: boolean
    } = {},
  ) {
    if (generating.value) {
      console.warn('[startBeat] 已有生成任务进行中，已忽略')
      return
    }
    lastAction = () => startBeat(chapterId, tier, opts)
    generating.value = true
    error.value = null
    stage.value = 'tier_classifying'
    bsadfTrack.value = opts.track || 'A'
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
              stepProgress.value = {
                label: branchCount > 0
                  ? `${payload.slots.length} 段逐段渲染中 · ${branchCount} 处剧情走向待选`
                  : `${payload.slots.length} 段逐段渲染中`,
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
          if (data.card_snapshot) {
            const idx = beatSlots.value.findIndex(s => s.beat_id === data.beat_id)
            if (idx >= 0) beatSlots.value[idx] = data.card_snapshot
          }
        },
        onBeatChunk: (data) => {
          const prev = segmentTexts.value[data.beat_id] || ''
          segmentTexts.value = { ...segmentTexts.value, [data.beat_id]: prev + data.delta }
          streamText.value = Object.values(segmentTexts.value).join('\n\n')
        },
        onBeatReady: (data) => {
          renderingBeatId.value = null
          readyBeatId.value = data.beat_id
          readyBeatCard.value = data.card_snapshot || null
          stage.value = 'beat_stepping'
          generating.value = false  // 解锁，等作者按 Space
        },
        onBeatLocked: (data) => {
          lockedBeatIds.value = new Set([...lockedBeatIds.value, data.beat_id])
          if (data.extracted_facts) {
            emergentFacts.value = { ...emergentFacts.value, [data.beat_id]: data.extracted_facts }
          }
        },
        onBeatSkipped: (data) => {
          lockedBeatIds.value = new Set([...lockedBeatIds.value, data.beat_id])
        },
        onAllBeatsLocked: () => {
          stage.value = 'assembling'
        },
        onBeatRerendered: (data) => {
          segmentTexts.value = { ...segmentTexts.value, [data.beat_id]: '' }
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

  /** BS-ADF Track B：作者编辑分镜卡 + 选定剧情分支后恢复渲染 */
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
  let _steppingPollTimer: ReturnType<typeof setTimeout> | null = null
  function _pollSteppingReady(runId: string, chapterId: string) {
    if (_steppingPollTimer) clearTimeout(_steppingPollTimer)
    const poll = async () => {
      // 已切到 beat_stepping/done 则停止轮询
      // 注意：不因 stage='error' 停止——SSE 断开会触发 onError 设 error，
      // 但后端 stepping_loop 可能仍在正常跑，轮询能恢复正确状态。
      if (stage.value === 'beat_stepping' || stage.value === 'done') return
      if (steppingRunId.value !== runId) return  // session 已变
      try {
        const resp = await fetch(`/api/chapters/stepping-run/${runId}/state`)
        if (!resp.ok) { _steppingPollTimer = setTimeout(poll, 2000); return }
        const st = await resp.json()
        if (st.status === 'error' || st.status === 'done') {
          // 生成结束/出错，停止轮询
          return
        }
        if (st.current_segment_ready && st.current_beat_id) {
          // 首段就绪：手动触发 onBeatReady 逻辑
          if (st.current_segment_text) {
            segmentTexts.value = {
              ...segmentTexts.value,
              [st.current_beat_id]: st.current_segment_text,
            }
            streamText.value = Object.values(segmentTexts.value).join('\n\n')
          }
          readyBeatId.value = st.current_beat_id
          const cardIdx = beatSlots.value.findIndex(s => s.beat_id === st.current_beat_id)
          readyBeatCard.value = cardIdx >= 0 ? beatSlots.value[cardIdx] : null
          renderingBeatId.value = null
          stage.value = 'beat_stepping'
          generating.value = false  // 解锁，等作者按 Space
          return  // 切态后停止轮询
        }
      } catch (e) {
        // 网络错误，继续轮询
      }
      _steppingPollTimer = setTimeout(poll, 2000)
    }
    _steppingPollTimer = setTimeout(poll, 3000)  // 首次延迟 3 秒（给后端渲染时间）
  }

  /** NLE-ADF：步进锁死推进（每段就绪后作者按 Space 推进下一段） */
  function advanceBeat(
    chapterId: string,
    action: 'pass' | 'edit' | 'branch' | 'skip',
    opts: {
      beatId: string
      editedSlot?: BeatSlot
      branchChoice?: { option_id: string; label: string; plot_impact: string }
    },
  ) {
    if (!steppingRunId.value || !opts.beatId) return
    abortController = new AbortController()
    currentChapterId = chapterId
    generating.value = true
    stage.value = 'beat_rendering'

    bsadfApi.advanceBeat(
      chapterId,
      {
        run_id: steppingRunId.value,
        beat_id: opts.beatId,
        action,
        edited_slot: opts.editedSlot,
        branch_choice: opts.branchChoice,
      },
      {
        onBeatRenderStart: (data) => {
          renderingBeatId.value = data.beat_id
          readyBeatId.value = null
          if (data.card_snapshot) {
            const idx = beatSlots.value.findIndex(s => s.beat_id === data.beat_id)
            if (idx >= 0) beatSlots.value[idx] = data.card_snapshot
          }
        },
        onBeatChunk: (data) => {
          const prev = segmentTexts.value[data.beat_id] || ''
          segmentTexts.value = { ...segmentTexts.value, [data.beat_id]: prev + data.delta }
          streamText.value = Object.values(segmentTexts.value).join('\n\n')
        },
        onBeatReady: (data) => {
          renderingBeatId.value = null
          readyBeatId.value = data.beat_id
          readyBeatCard.value = data.card_snapshot || null
          stage.value = 'beat_stepping'
          generating.value = false
        },
        onBeatLocked: (data) => {
          lockedBeatIds.value = new Set([...lockedBeatIds.value, data.beat_id])
          if (data.extracted_facts) {
            emergentFacts.value = { ...emergentFacts.value, [data.beat_id]: data.extracted_facts }
          }
        },
        onBeatSkipped: (data) => {
          lockedBeatIds.value = new Set([...lockedBeatIds.value, data.beat_id])
        },
        onAllBeatsLocked: () => {
          stage.value = 'assembling'
        },
        onBeatRerendered: (data) => {
          segmentTexts.value = { ...segmentTexts.value, [data.beat_id]: '' }
        },
        onLoop1Checked: (data) => {
          loop1Result.value = data
        },
        onStage: () => { /* 兼容 */ },
        onEvent: () => { /* 兜底 */ },
        onDone: (result) => {
          stage.value = 'done'
          lastDoneMode.value = 'bsadf'
          streamText.value = result.text || Object.values(segmentTexts.value).join('\n\n')
          finalStats.value = result.stats || null
          generating.value = false
          persist()
        },
        onError: (msg) => {
          error.value = msg
          stage.value = 'error'
          generating.value = false
          persist()
        },
      },
      abortController.signal,
    )
  }

  // ===== NLE-ADF：Space 键步进锁死推进 =====
  function _spaceKeyHandler(e: KeyboardEvent) {
    if (e.code !== 'Space') return
    const target = e.target as HTMLElement | null
    const tag = target?.tagName
    if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT') return
    if (target?.isContentEditable) return
    if (stage.value === 'beat_stepping' && readyBeatId.value && currentChapterId) {
      e.preventDefault()
      advanceBeat(currentChapterId, 'pass', { beatId: readyBeatId.value })
    }
  }
  onMounted(() => window.addEventListener('keydown', _spaceKeyHandler))
  onUnmounted(() => window.removeEventListener('keydown', _spaceKeyHandler))

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
    rerenderingBeatId,
    decisionSet,
    rescueNeeded,
    // NLE-ADF 步进
    segmentTexts, readyBeatId, readyBeatCard, lockedBeatIds,
    renderingBeatId, loop1Result, steppingRunId, emergentFacts,
    advanceBeat,
    isTerminal,
    start,
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
