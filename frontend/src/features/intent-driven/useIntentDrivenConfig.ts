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
  RecommendResponse
} from '@/types/intentDriven'
import type { GenerateChapterAgenticPayload, ReasoningConfig } from '@/types'
import { intentDrivenApi } from '../../services/api/domain'
import { CREATIVE_INTENT_TEMPLATES, CHAPTER_GOAL_TEMPLATES } from './intentTemplates'

// 默认状态
const defaultState: IntentDrivenState = {
  selectedIntents: [],
  selectedGoals: [],
  selectedPlanType: 'balanced',
  recommendedPlans: [],
  userOverrides: {},
  isExpertModeExpanded: false,
  wordCount: 3000,
  authorIntent: ''
}

const state = ref<IntentDrivenState>({ ...defaultState })
const intentTemplatesSource = ref<CreativeIntentTemplate[]>([...CREATIVE_INTENT_TEMPLATES])
const goalTemplatesSource = ref<ChapterGoalTemplate[]>([...CHAPTER_GOAL_TEMPLATES])
let templatesLoaded = false

async function ensureTemplatesLoaded() {
  if (templatesLoaded) {
    return
  }
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

export function useIntentDrivenConfig() {
  void ensureTemplatesLoaded()

  // 计算属性
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
  
  const canSelectMoreIntents = computed(() => {
    return state.value.selectedIntents.length < 2
  })
  
  const hasSelection = computed(() => {
    return state.value.selectedIntents.length > 0 || state.value.selectedGoals.length > 0
  })
  
  const recommendedPlan = computed(() => {
    return state.value.recommendedPlans.find(
      p => p.plan_type === state.value.selectedPlanType
    )
  })
  
  const recommendedPlans = computed(() => state.value.recommendedPlans)
  
  const selectedPlanType = computed(() => state.value.selectedPlanType)
  
  const isExpertModeExpanded = computed(() => state.value.isExpertModeExpanded)
  
  const hasOverrides = computed(() => {
    return Object.keys(state.value.userOverrides).length > 0
  })
  
  const overrideCount = computed(() => {
    return Object.keys(state.value.userOverrides).length
  })
  
  const userOverrides = computed(() => state.value.userOverrides)

  // 篇幅与创作意图（从组件本地 ref 提升到单例状态）
  const wordCount = computed(() => state.value.wordCount)
  const authorIntent = computed(() => state.value.authorIntent)

  function setWordCount(value: number) {
    state.value.wordCount = Math.max(500, Math.min(10000, value))
  }

  function setAuthorIntent(value: string) {
    state.value.authorIntent = value
  }

  // 方法
  function toggleIntent(intentId: CreativeIntentType) {
    const index = state.value.selectedIntents.indexOf(intentId)
    
    if (index > -1) {
      state.value.selectedIntents.splice(index, 1)
    } else if (canSelectMoreIntents.value) {
      state.value.selectedIntents.push(intentId)
    }
    
    refreshRecommendations()
  }
  
  function toggleGoal(goalId: ChapterGoalType) {
    const index = state.value.selectedGoals.indexOf(goalId)
    
    if (index > -1) {
      state.value.selectedGoals.splice(index, 1)
    } else {
      state.value.selectedGoals.push(goalId)
    }
    
    refreshRecommendations()
  }
  
  function selectPlanType(planType: PlanType) {
    state.value.selectedPlanType = planType
  }
  
  function toggleExpertMode() {
    state.value.isExpertModeExpanded = !state.value.isExpertModeExpanded
  }
  
  function setOverride(field: string, value: any, originalValue: any) {
    state.value.userOverrides[field] = {
      original: originalValue,
      current: value
    }
  }
  
  function clearOverride(field: string) {
    delete state.value.userOverrides[field]
  }
  
  function clearAllOverrides() {
    state.value.userOverrides = {}
  }
  
  function reset() {
    state.value = { ...defaultState }
  }
  
  async function refreshRecommendations() {
    if (!hasSelection.value) {
      state.value.recommendedPlans = []
      return
    }
    
    try {
      const data: RecommendResponse = await intentDrivenApi.recommend({
        creative_intents: state.value.selectedIntents,
        chapter_goals: state.value.selectedGoals.length > 0 ? state.value.selectedGoals : null
      })
      state.value.recommendedPlans = data.plans
    } catch (error) {
      console.error('获取推荐方案失败:', error)
      state.value.recommendedPlans = generateLocalRecommendations()
    }
  }
  
  function generateLocalRecommendations(): RecommendedPlan[] {
    const plans: RecommendedPlan[] = []
    
    plans.push({
      plan_id: 'balanced_default',
      plan_name: '均衡方案',
      plan_type: 'balanced',
      description: '在速度与质量之间取得平衡',
      reasoning: '基于您选择的意图，系统推荐此均衡配置',
      estimated_time: '约 2-3 分钟',
      risk_hints: [],
      derivation_log: [],
      policy: {
        tension_level: 3,
        pacing_style: 'balanced',
        memory_span: 'balanced_reference',
        creativity_level: 'balanced_creation',
        refinement_depth: 'standard',
        progression_preference: 'focus_scene_action',
        workflow_tier: 'TIER_2_STANDARD',
        enable_dual_track: true,
        enable_fail_fast: true,
        rag_top_k: 5,
        rag_alpha: 0.6,
        rag_beta: 0.2,
        rag_gamma: 0.2,
        rag_lambda: 0.1
      }
    })
    
    plans.push({
      plan_id: 'fast_track',
      plan_name: '快速方案',
      plan_type: 'fast',
      description: '快速生成，适合预览',
      reasoning: '如果您希望快速看到结果',
      estimated_time: '约 1-2 分钟',
      risk_hints: ['质量可能略低'],
      derivation_log: [],
      policy: {
        tension_level: 2,
        pacing_style: 'balanced',
        memory_span: 'recent_only',
        creativity_level: 'balanced_creation',
        refinement_depth: 'light',
        progression_preference: 'focus_scene_action',
        workflow_tier: 'TIER_1_FAST',
        enable_dual_track: false,
        enable_fail_fast: false,
        rag_top_k: 3,
        rag_alpha: 0.4,
        rag_beta: 0.5,
        rag_gamma: 0.1,
        rag_lambda: 0.3
      }
    })
    
    plans.push({
      plan_id: 'quality_first',
      plan_name: '精雕细琢',
      plan_type: 'quality',
      description: '最高质量输出',
      reasoning: '如果这是关键章节',
      estimated_time: '约 4-6 分钟',
      risk_hints: ['耗时较长'],
      derivation_log: [],
      policy: {
        tension_level: 4,
        pacing_style: 'balanced',
        memory_span: 'deep_dive',
        creativity_level: 'balanced_creation',
        refinement_depth: 'deep',
        progression_preference: 'focus_scene_action',
        workflow_tier: 'TIER_3_FORTRESS',
        enable_dual_track: true,
        enable_fail_fast: true,
        rag_top_k: 10,
        rag_alpha: 0.5,
        rag_beta: 0.15,
        rag_gamma: 0.35,
        rag_lambda: 0.05
      }
    })
    
    return plans
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
    const overrides = Object.fromEntries(
      Object.entries(state.value.userOverrides).map(([k, v]) => [k, v.current])
    )
    
    return {
      chapter_id: baseParams.chapterId,
      api_key: baseParams.apiConfig.api_key,
      base_url: baseParams.apiConfig.base_url,
      model: baseParams.apiConfig.model,
      
      creative_intents: state.value.selectedIntents.length > 0 
        ? state.value.selectedIntents 
        : undefined,
      chapter_goals: state.value.selectedGoals.length > 0 
        ? state.value.selectedGoals 
        : undefined,
      selected_plan_type: state.value.selectedPlanType,
      
      user_overrides: Object.keys(overrides).length > 0 ? overrides : undefined,
      
      word_count: baseParams.wordCount,
      author_intent: baseParams.authorIntent
    }
  }
  
  function getIntentDisplayName(intentType: CreativeIntentType): string {
    const template = intentTemplates.value.find(t => t.id === intentType)
    return template?.display_name || intentType
  }
  
  return {
    // 状态
    state,
    
    // 计算属性
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

    // 篇幅与创作意图
    wordCount,
    authorIntent,
    setWordCount,
    setAuthorIntent,

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
// 意图驱动 → 双轨生成载荷桥接函数
// 将 GenerationPolicy 映射为 GenerateChapterAgenticPayload，供生成按钮调用
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
   * 如果提供，将优先使用章节中保存的配置而非全局状态
   */
  chapterData?: {
    creative_intents?: string[]
    chapter_goals?: string[]
    selected_plan_type?: string
    user_overrides?: Record<string, any>
    word_count?: number
    author_intent?: string
  }
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

  // 优先使用传入的章节数据，否则使用全局状态
  const chapterData = params.chapterData
  const currentState = state.value

  // 从章节数据或全局状态获取配置
  const selectedIntents = chapterData?.creative_intents ?? currentState.selectedIntents
  const selectedGoals = chapterData?.chapter_goals ?? currentState.selectedGoals
  const selectedPlanType = (chapterData?.selected_plan_type as PlanType) ?? currentState.selectedPlanType
  const userOverrides = chapterData?.user_overrides ?? currentState.userOverrides
  const wordCount = chapterData?.word_count ?? currentState.wordCount
  const authorIntent = chapterData?.author_intent ?? currentState.authorIntent

  if (selectedIntents.length === 0) {
    errors.push('请先在智能设置中选择创作意图')
  }

  // 根据 plan_type 获取对应的 policy
  // 如果没有推荐方案，使用默认配置
  let policy = currentState.recommendedPlans.find(p => p.plan_type === selectedPlanType)?.policy
  if (!policy) {
    // 使用默认配置
    policy = {
      tension_level: 3,
      pacing_style: 'balanced',
      memory_span: 'balanced_reference',
      creativity_level: 'balanced_creation',
      refinement_depth: 'standard',
      progression_preference: 'focus_scene_action',
      workflow_tier: 'TIER_2_STANDARD',
      enable_dual_track: true,
      enable_fail_fast: true,
      rag_top_k: 5,
      rag_alpha: 0.6,
      rag_beta: 0.2,
      rag_gamma: 0.2,
      rag_lambda: 0.1
    } as any
  }

  if (errors.length > 0) {
    return { payload: null, errors }
  }

  // 处理 user_overrides 的两种可能格式：
  // 1. 来自全局状态: { [field]: { original, current } }
  // 2. 来自数据库: { [field]: value }
  const overrides = Object.fromEntries(
    Object.entries(userOverrides).map(([k, v]) => {
      // 如果是 { original, current } 格式，取 current
      if (v && typeof v === 'object' && 'current' in v) {
        return [k, v.current]
      }
      // 否则直接取值（来自数据库的格式）
      return [k, v]
    })
  )

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
    if (depth === 'deep') return 4
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

    word_count: overrides.word_count ?? wordCount,
    tension_level: overrides.tension_level ?? policy.tension_level,
    pacing_style: (overrides.pacing_style ?? policy.pacing_style) as any,
    author_intent: authorIntent || undefined,

    max_iterations: refinementToIterations(policy.refinement_depth),
    rag_top_k: overrides.rag_top_k ?? policy.rag_top_k,
    rag_alpha: overrides.rag_alpha ?? policy.rag_alpha,
    rag_beta: overrides.rag_beta ?? policy.rag_beta,
    rag_gamma: overrides.rag_gamma ?? policy.rag_gamma,
    rag_lambda: overrides.rag_lambda ?? policy.rag_lambda,

    fast_mode: policy.workflow_tier === 'TIER_1_FAST',
    skip_minor_refine: true,
    force_parallel_prose: false,

    reasoning_config: reasoningConfig,
    reasoning_model_reasoning_config: reasoningModelReasoningConfig,
    creative_model_reasoning_config: creativeModelReasoningConfig
  }

  return { payload, errors: [] }
}
