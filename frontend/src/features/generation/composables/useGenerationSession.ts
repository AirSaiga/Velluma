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
import { ref, computed, type Ref, type ComputedRef } from 'vue'
import { adfApi, refineryApi, bsadfApi, type AdfEngine, type RefineryIssue, type RefinerySurgery, type RefineryHolisticVerdict, type IssueDecision, type BeatSlot, type RenderProgress, type DegradedBeat } from '../../../services/api/domain'

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
  | 'beat_pending' // 槽位卡已生成，等作者编辑（Track B 暂停态）
  | 'beat_rendering' // 作者确认后，后台顺序渲染各段
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
  bsadfTrack: Ref<'A' | 'B'>
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
  startBeat: (chapterId: string, tier: string, opts?: { track?: 'A' | 'B'; targetWordCount?: number | null; maxSegments?: number; authorIntent?: string; expectationActions?: Record<string, string> }) => void
  confirmBeats: (chapterId: string, editedSlots: BeatSlot[]) => void
  cancelBeat: () => void
  /** BS-ADF：降级单卡重渲染（调 /rerender-beat，同步 JSON） */
  rerenderBeat: (chapterId: string, beatId: string, editedSlot: BeatSlot) => Promise<any>
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
  const renderProgress = ref<RenderProgress[]>([])
  const degradedBeats = ref<DegradedBeat[]>([])
  const bsadfTrack = ref<'A' | 'B'>('A')

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
    beatSlots.value = snap.beatSlots || []
    renderProgress.value = snap.renderProgress || []
    degradedBeats.value = snap.degradedBeats || []
    // 中断态归正：刷新后无法续 LLM，强制为已完成的静态展示
    if (snap.stage === 'done' || snap.stage === 'error') {
      stage.value = snap.stage
    } else {
      // 上次处于生成中途（tier_classifying/zone_writing 等），刷新后已无法续上
      // → 若已有正文则记为 done，否则记为 error
      stage.value = snap.streamText ? 'done' : 'idle'
    }
    generating.value = false
    error.value = null
    inflightEvents.value = []  // 飞行中事件不持久化（瞬时态）
    refineryRunId.value = null  // runId 是临时会话凭证，刷新后失效
    beatRunId.value = null  // beat runId 同样是临时凭证，刷新后失效
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
    renderProgress.value = []
    degradedBeats.value = []
    bsadfTrack.value = 'A'
    lastDoneMode.value = null
  }

  /** 最近一次入口（供失败重试 retry 再次触发）；start / startRefinery 时记录 */
  let lastAction: (() => void) | null = null

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
      default:
        return { label: adfStage, sessionStage: stage.value }
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

  /** BS-ADF：启动生成（Track A 全自动 / Track B 跑到槽位卡暂停） */
  function startBeat(
    chapterId: string,
    tier: string,
    opts: {
      track?: 'A' | 'B'
      targetWordCount?: number | null
      maxSegments?: number
      authorIntent?: string
      expectationActions?: Record<string, string>
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
    // 清空旧产物
    streamText.value = ''
    beatSlots.value = []
    beatRunId.value = null
    renderProgress.value = []
    degradedBeats.value = []

    bsadfApi.start(
      chapterId,
      {
        tier,
        track: opts.track || 'A',
        target_word_count: opts.targetWordCount ?? null,
        max_segments: opts.maxSegments ?? 6,
        author_intent: opts.authorIntent,
        expectation_actions: opts.expectationActions,
      },
      {
        onStage: (stageName, _data) => {
          // 映射后端 BSADF_STAGE/ADF_STAGE 到前端 stage
          if (stageName === 'AUTHOR_DIALOGUE') {
            // Track B 暂停点（不应在这里触发，onSlots 会先触发）
            stepProgress.value = { label: '等待你编辑槽位卡' }
          } else if (stageName === 'RENDER' || stageName === 'RENDER_RESUMED') {
            stage.value = 'beat_rendering'
            stepProgress.value = { label: '逐段渲染' }
          } else {
            stepProgress.value = { label: stageName }
          }
        },
        onSlots: (payload) => {
          // Track B 暂停触发：槽位卡就绪
          beatSlots.value = payload.slots || []
          beatRunId.value = payload.run_id
          generating.value = false  // 解覆盖 editor
          stage.value = 'beat_pending'
          stepProgress.value = { label: `${(payload.slots || []).length} 张槽位卡待编辑` }
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
        onDowngraded: (data) => {
          degradedBeats.value.push(data)
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

  /** BS-ADF Track B：作者编辑槽位卡后恢复渲染 */
  function confirmBeats(chapterId: string, editedSlots: BeatSlot[]) {
    const runId = beatRunId.value
    if (!runId) {
      error.value = '缺少 beat run_id'
      return
    }
    // runId handoff（照搬 confirmRefinery 的技巧）：捕获 → 清空 → 调 API。
    // 清空 beatSlots 让槽位卡面板消失，进度面板接管展示。
    beatRunId.value = null
    beatSlots.value = []
    generating.value = true
    stage.value = 'beat_rendering'
    abortController = new AbortController()
    streamText.value = ''
    renderProgress.value = []
    degradedBeats.value = []

    bsadfApi.confirm(
      chapterId,
      { run_id: runId, edited_slots: editedSlots },
      {
        onStage: (stageName) => {
          if (stageName === 'RENDER_RESUMED') stepProgress.value = { label: '逐段渲染' }
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
        onChunk: (chunk) => {
          streamText.value += chunk
        },
        onDone: (result) => {
          generating.value = false
          stage.value = 'done'
          finalStats.value = result.stats
          lastDoneMode.value = 'bsadf'
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
    renderProgress.value = []
    degradedBeats.value = []
    generating.value = false
    stage.value = 'idle'
  }

  /**
   * BS-ADF：降级单卡重渲染（调 /rerender-beat，同步 JSON）。
   *
   * Phase 4d 降级的某张 beat 由作者重新编辑后单卡重渲染（不重跑全章）。
   * 后端返回 {segment:{text}, card, degraded}：
   * - 成功（degraded=null）：从 degradedBeats 移除该 beat，把渲染结果记入 renderProgress（status='rendered'）。
   * - 再次降级（degraded 非空）：把新的降级句柄替换 degradedBeats 中同 beat_id 的项（attempts 累加）。
   * 任意一种分支都持久化（刷新后能看到最新降级态）。
   */
  async function rerenderBeat(chapterId: string, beatId: string, editedSlot: BeatSlot) {
    try {
      const result = await bsadfApi.rerenderBeat(chapterId, { beat_id: beatId, edited_slot: editedSlot })
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
        // 渲染成功：移出降级清单，把结果记入 renderProgress（标记为 rendered）
        degradedBeats.value = degradedBeats.value.filter(d => d.beat_id !== beatId)
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
    }
  }

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
