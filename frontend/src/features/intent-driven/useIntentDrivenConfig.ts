import { ref, computed } from 'vue'
import type {
  CreativeIntentType,
  ChapterGoalType,
  PlanType,
  CreativeIntentTemplate,
  ChapterGoalTemplate,
  RecommendedPlan,
  IntentDrivenState,
  IntentDrivenGeneratePayload,
  ChapterType,
  PacingPreference,
  QualityPreference,
  SimpleGenerationConfig
} from '@/types/intentDriven'
import {
  derivePolicyFromSimpleConfig,
  CHAPTER_TYPE_CONFIG
} from '@/types/intentDriven'
import type { GenerateChapterAgenticPayload, ReasoningConfig } from '@/types'
import { intentDrivenApi } from '../../services/api/domain'
import { CREATIVE_INTENT_TEMPLATES, CHAPTER_GOAL_TEMPLATES } from './intentTemplates'

// =============================================================================
// 默认状态
// =============================================================================

const defaultState: IntentDrivenState = {
  // V4.1 简化参数（仅保留 chapterType，pacing/quality 内部固定）
  chapterType: 'emotional',
  pacing: 'natural',
  quality: 'balanced',

  // 基础调整
  wordCount: 3000,
  authorIntent: '',

  // 旧版兼容字段
  selectedIntents: [],
  selectedGoals: [],
  selectedPlanType: 'balanced',
  recommendedPlans: [],
  userOverrides: {},
  isExpertModeExpanded: false
}

const state = ref<IntentDrivenState>({ ...defaultState })
const intentTemplatesSource = ref<CreativeIntentTemplate[]>([...CREATIVE_INTENT_TEMPLATES])
const goalTemplatesSource = ref<ChapterGoalTemplate[]>([...CHAPTER_GOAL_TEMPLATES])
let templatesLoaded = false

async function ensureTemplatesLoaded() {
  if (templatesLoaded) return
  templatesLoaded = true
  try {
    const data = await intentDrivenApi.getTemplates()
    if (Array.isArray(data?.creative_intents) && data.creative_intents.length > 0) {
      intentTemplatesSource.value = data.creative_intents
    }
    if (Array.isArray(data?.chapter_goals) && data.chapter_goals.length > 0) {
      goalTemplatesSource.value = data.chapter_goals
    }
  } catch {
    intentTemplatesSource.value = [...CREATIVE_INTENT_TEMPLATES]
    goalTemplatesSource.value = [...CHAPTER_GOAL_TEMPLATES]
  }
}

// =============================================================================
// 策略推导
// =============================================================================

function buildCurrentSimpleConfig(): SimpleGenerationConfig {
  return {
    chapterType: state.value.chapterType,
    // pacing/quality 已从前端面板移除，内部固定为均衡值
    pacing: 'natural',
    quality: 'balanced',
    wordCount: state.value.wordCount,
    authorIntent: state.value.authorIntent
  }
}

function buildRecommendedPlan(): RecommendedPlan {
  const config = buildCurrentSimpleConfig()
  const derived = derivePolicyFromSimpleConfig(config)
  const { derivation_log, ...policy } = derived

  const typeLabel = CHAPTER_TYPE_CONFIG[config.chapterType].label

  const tierNames: Record<string, string> = {
    TIER_1_FAST: '自由创作',
    TIER_2_STANDARD: '标准编排',
    TIER_3_FORTRESS: '严选打磨'
  }

  return {
    plan_id: `derived_${config.chapterType}`,
    plan_name: typeLabel,
    plan_type: 'balanced',
    description: `基于「${typeLabel}」类型生成。系统将根据每个节拍的内容特征自动匹配最佳生成策略。`,
    reasoning: `章节默认路径为「${tierNames[policy.workflow_tier] || policy.workflow_tier}」，实际生成时每个节拍会根据 pacing_type 和 weight 自动分配 Fast / Standard / Fortress 路径`,
    estimated_time: policy.workflow_tier === 'TIER_1_FAST'
      ? '约 1-2 分钟'
      : policy.workflow_tier === 'TIER_3_FORTRESS'
        ? '约 4-6 分钟'
        : '约 2-3 分钟',
    risk_hints: [],
    derivation_log,
    policy
  }
}

// =============================================================================
// 主 composable
// =============================================================================

export function useIntentDrivenConfig() {
  void ensureTemplatesLoaded()

  // ---- V4.1 简化参数 ----
  const chapterType = computed(() => state.value.chapterType)

  function setChapterType(value: ChapterType) {
    state.value.chapterType = value
    state.value.recommendedPlans = [buildRecommendedPlan()]
  }

  const simpleConfig = computed(() => buildCurrentSimpleConfig())

  // ---- 基础调整 ----
  const wordCount = computed(() => state.value.wordCount)
  const authorIntent = computed(() => state.value.authorIntent)

  function setWordCount(value: number) {
    state.value.wordCount = Math.max(500, Math.min(10000, value))
  }

  function setAuthorIntent(value: string) {
    state.value.authorIntent = value
  }

  // ---- 旧版兼容计算属性 ----
  const selectedIntents = computed(() => state.value.selectedIntents)
  const selectedGoals = computed(() => state.value.selectedGoals)
  const intentTemplates = computed(() => intentTemplatesSource.value)
  const goalTemplates = computed(() => goalTemplatesSource.value)

  const selectedIntentTemplates = computed(() => {
    return state.value.selectedIntents
      .map(id => intentTemplates.value.find(t => t.id === id))
      .filter(Boolean)
  })

  const selectedGoalTemplates = computed(() => {
    return state.value.selectedGoals
      .map(id => goalTemplates.value.find(t => t.id === id))
      .filter(Boolean)
  })

  const canSelectMoreIntents = computed(() => false)

  const hasSelection = computed(() => {
    // V4.1: 只要三个简化参数有效即可（它们永远有值）
    return true
  })

  const recommendedPlan = computed(() => buildRecommendedPlan())
  const recommendedPlans = computed(() => [recommendedPlan.value])
  const selectedPlanType = computed(() => 'balanced' as PlanType)
  const isExpertModeExpanded = computed(() => state.value.isExpertModeExpanded)
  const hasOverrides = computed(() => false)
  const overrideCount = computed(() => 0)
  const userOverrides = computed(() => state.value.userOverrides)

  // ---- 旧版兼容方法（空操作） ----
  function toggleIntent(_intentId: CreativeIntentType) { /* 已废弃 */ }
  function toggleGoal(_goalId: ChapterGoalType) { /* 已废弃 */ }
  function selectPlanType(_planType: PlanType) { /* 已废弃 */ }
  function toggleExpertMode() {
    state.value.isExpertModeExpanded = !state.value.isExpertModeExpanded
  }
  function setOverride(_field: string, _value: any, _originalValue: any) { /* 已废弃 */ }
  function clearOverride(_field: string) { /* 已废弃 */ }
  function clearAllOverrides() { state.value.userOverrides = {} }

  function reset() {
    state.value = { ...defaultState }
  }

  async function refreshRecommendations() {
    state.value.recommendedPlans = [buildRecommendedPlan()]
  }

  function buildPayload(baseParams: {
    chapterId: string
    apiConfig: {
      api_key: string
      base_url?: string
      model?: string
    }
    wordCount: number
    authorIntent?: string
    generate?: boolean
  }): IntentDrivenGeneratePayload {
    return {
      chapter_id: baseParams.chapterId,
      api_key: baseParams.apiConfig.api_key,
      base_url: baseParams.apiConfig.base_url,
      model: baseParams.apiConfig.model,
      selected_plan_type: 'balanced',
      word_count: baseParams.wordCount,
      author_intent: baseParams.authorIntent
    }
  }

  function getIntentDisplayName(_intentType: CreativeIntentType): string {
    return ''
  }

  return {
    // 状态
    state,

    // V4.1 简化参数
    chapterType,
    setChapterType,
    simpleConfig,

    // 基础调整
    wordCount,
    authorIntent,
    setWordCount,
    setAuthorIntent,

    // 旧版兼容计算属性
    selectedIntents,
    selectedGoals,
    userOverrides,
    selectedIntentTemplates,
    selectedGoalTemplates,
    canSelectMoreIntents,
    hasSelection,
    recommendedPlans,
    recommendedPlan,
    selectedPlanType,
    isExpertModeExpanded,
    hasOverrides,
    overrideCount,

    // 模板数据
    intentTemplates,
    goalTemplates,

    // 方法
    toggleIntent,
    toggleGoal,
    selectPlanType,
    toggleExpertMode,
    setOverride,
    clearOverride,
    clearAllOverrides,
    reset,
    refreshRecommendations,
    buildPayload,
    getIntentDisplayName
  }
}

// =============================================================================
// 意图驱动 → Agentic 生成载荷桥接函数
// =============================================================================

export interface BuildAgenticPayloadParams {
  chapterId: string
  apiConfig: {
    api_key: string
    base_url?: string
    model?: string
    reasoning_model?: string
    creative_model?: string
    reasoning_enabled?: boolean
    reasoning_effort?: ReasoningConfig['effort']
    reasoning_exclude?: boolean
    reasoning_model_reasoning_enabled?: boolean
    reasoning_model_reasoning_effort?: ReasoningConfig['effort']
    reasoning_model_reasoning_exclude?: boolean
    creative_model_reasoning_enabled?: boolean
    creative_model_reasoning_effort?: ReasoningConfig['effort']
    creative_model_reasoning_exclude?: boolean
  }
  /**
   * 可选的章节数据，用于从中读取已保存的智能生成配置
   */
  chapterData?: {
    chapterType?: ChapterType
    pacing?: PacingPreference
    quality?: QualityPreference
    word_count?: number
    author_intent?: string
    // 旧版兼容
    creative_intents?: string[]
    chapter_goals?: string[]
    selected_plan_type?: string
    user_overrides?: Record<string, any>
  }
}

// =============================================================================
// 旧版配置 → V4.1 简化配置兼容推断
// =============================================================================

function inferChapterTypeFromLegacy(chapterData: any): ChapterType | undefined {
  const intents: string[] = chapterData?.creative_intents || []
  if (intents.includes('emotional_warming') || intents.includes('character_development')) {
    return 'emotional'
  }
  if (intents.includes('big_scene') || intents.includes('build_conflict')) {
    return 'action'
  }
  if (intents.includes('transition_chapter')) {
    return 'daily'
  }
  if (intents.includes('suspense_ending')) {
    return 'suspense'
  }
  if (intents.includes('worldbuilding')) {
    return 'worldbuilding'
  }
  return undefined
}

export function buildAgenticPayloadFromIntent(params: BuildAgenticPayloadParams): {
  payload: GenerateChapterAgenticPayload | null
  errors: string[]
} {
  const errors: string[] = []
  const apiKey = (params.apiConfig.api_key || '').trim()
  if (!apiKey) {
    errors.push('请先配置 API Key')
  }

  const chapterData = params.chapterData
  const currentState = state.value

  // 优先使用章节数据中的 V4.1 简化参数
  // 兼容旧数据：如果旧字段存在但新字段不存在，尝试推断
  const inferredType = inferChapterTypeFromLegacy(chapterData)

  const chapterType = chapterData?.chapterType ?? inferredType ?? currentState.chapterType
  const wordCount = chapterData?.word_count ?? currentState.wordCount
  const authorIntent = chapterData?.author_intent ?? currentState.authorIntent

  // pacing/quality 已从前端移除，内部固定为均衡值
  const derived = derivePolicyFromSimpleConfig({
    chapterType,
    pacing: 'natural',
    quality: 'balanced',
    wordCount
  })
  const { derivation_log: _log, ...policy } = derived

  const baseModel = params.apiConfig.model || 'gpt-4o-mini'
  const hasDualModel = !!(
    params.apiConfig.reasoning_model || params.apiConfig.creative_model
  )

  let reasoningConfig: ReasoningConfig | undefined
  let reasoningModelReasoningConfig: ReasoningConfig | undefined
  let creativeModelReasoningConfig: ReasoningConfig | undefined

  if (!hasDualModel && params.apiConfig.reasoning_enabled) {
    reasoningConfig = {
      enabled: true,
      effort: params.apiConfig.reasoning_effort || 'medium',
      exclude: params.apiConfig.reasoning_exclude || false
    }
  }

  if (hasDualModel) {
    if (params.apiConfig.reasoning_model_reasoning_enabled) {
      reasoningModelReasoningConfig = {
        enabled: true,
        effort: params.apiConfig.reasoning_model_reasoning_effort || 'high',
        exclude: params.apiConfig.reasoning_model_reasoning_exclude || false
      }
    }
    if (params.apiConfig.creative_model_reasoning_enabled) {
      creativeModelReasoningConfig = {
        enabled: true,
        effort: params.apiConfig.creative_model_reasoning_effort || 'low',
        exclude: params.apiConfig.creative_model_reasoning_exclude || false
      }
    }
  }

  const refinementToIterations = (depth: string) => {
    if (depth === 'light') return 1
    if (depth === 'deep') return 3
    return 2
  }

  const payload: GenerateChapterAgenticPayload = {
    chapter_id: params.chapterId,
    api_key: apiKey,
    base_url: params.apiConfig.base_url || undefined,
    model: baseModel,
    reasoning_model: hasDualModel
      ? params.apiConfig.reasoning_model || baseModel
      : undefined,
    creative_model: hasDualModel
      ? params.apiConfig.creative_model || baseModel
      : undefined,

    editor_mode: 'intent',
    memory_strategy: policy.memory_span,
    creativity_level: policy.creativity_level,
    refinement_depth: policy.refinement_depth,

    word_count: wordCount,
    tension_level: policy.tension_level,
    pacing_style: policy.pacing_style as any,
    author_intent: authorIntent || undefined,

    max_iterations: refinementToIterations(policy.refinement_depth),
    rag_top_k: policy.rag_top_k,
    rag_alpha: policy.rag_alpha,
    rag_beta: policy.rag_beta,
    rag_gamma: policy.rag_gamma,
    rag_lambda: policy.rag_lambda,

    fast_mode: policy.workflow_tier === 'TIER_1_FAST',
    skip_minor_refine: true,
    force_parallel_prose: false,

    reasoning_config: reasoningConfig,
    reasoning_model_reasoning_config: reasoningModelReasoningConfig,
    creative_model_reasoning_config: creativeModelReasoningConfig
  }

  return { payload, errors: errors.length > 0 ? errors : [] }
}
