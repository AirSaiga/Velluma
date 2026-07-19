// 创作意图驱动层类型定义

// 创作意图类型
export type CreativeIntentType = 
  | 'advance_mainline'
  | 'character_development'
  | 'atmosphere_building'
  | 'build_conflict'
  | 'close_hooks'
  | 'worldbuilding'
  | 'emotional_warming'
  | 'dialogue_scene'
  | 'big_scene'
  | 'transition_chapter'
  | 'suspense_ending'

// 章节目标类型
export type ChapterGoalType =
  | 'introduce_character'
  | 'resolve_conflict'
  | 'reveal_secret'
  | 'change_relationship'
  | 'set_scene'

// 方案类型（旧版保留，兼容已有数据）
export type PlanType = 'balanced' | 'fast' | 'quality' | 'creative'

// =============================================================================
// V4.1 简化配置类型
// =============================================================================

/** 本章类型 — 决定基础生成路径 */
export type ChapterType =
  | 'emotional'      // 情感内心戏 → Fast Path（自由创作，灵气优先）
  | 'action'         // 动作冲突戏 → Fortress（物理一致性优先）
  | 'daily'          // 日常过渡章 → Fast Path（轻松过渡）
  | 'suspense'       // 悬疑推理戏 → Standard（逻辑严密）
  | 'worldbuilding'  // 世界观展开 → Standard（设定准确）

/** 节奏偏好 */
export type PacingPreference = 'tight' | 'natural' | 'relaxed'

/** 质量偏好 — 在基础路径上微调 */
export type QualityPreference = 'fast' | 'balanced' | 'quality'

/** V4.1 简化生成配置 — 用户只需选 3 个参数 */
export interface SimpleGenerationConfig {
  chapterType: ChapterType
  pacing: PacingPreference
  quality: QualityPreference
  wordCount: number
  authorIntent: string
}

/** 本章类型的 UI 展示信息 */
export interface ChapterTypeInfo {
  id: ChapterType
  label: string
  icon: string
  description: string
  defaultTier: 'TIER_1_FAST' | 'TIER_2_STANDARD' | 'TIER_3_FORTRESS'
}

// 创作意图模板
export interface CreativeIntentTemplate {
  id: CreativeIntentType
  display_name: string
  short_desc: string
  detailed_desc: string
  applicable_scenarios: string[]
  style_recommendation: string
  icon: string
  combo_suggestions?: CreativeIntentType[]
}

// 章节目标模板
export interface ChapterGoalTemplate {
  id: ChapterGoalType
  display_name: string
  description: string
  required_elements: string[]
  success_criteria: string[]
}

// 推荐方案
export interface RecommendedPlan {
  plan_id: string
  plan_name: string
  plan_type: PlanType
  description: string
  reasoning: string
  estimated_time: string
  risk_hints: string[]
  derivation_log: Array<{ rule: string; result: string }>
  policy: GenerationPolicy
}

// 生成策略
export interface GenerationPolicy {
  tension_level: number
  pacing_style: 'slow_burn' | 'balanced' | 'fast_paced'
  memory_span: 'recent_only' | 'balanced_reference' | 'deep_dive'
  creativity_level: 'strict_prompt' | 'balanced_creation' | 'wild_imagination'
  refinement_depth: 'light' | 'standard' | 'deep'
  progression_preference: 'focus_scene_action' | 'push_mainline'
  workflow_tier: 'TIER_1_FAST' | 'TIER_2_STANDARD' | 'TIER_3_FORTRESS'
  enable_dual_track: boolean
  enable_fail_fast: boolean
  rag_top_k: number
  rag_alpha: number
  rag_beta: number
  rag_gamma: number
  rag_lambda: number
}

// 意图驱动请求
export interface IntentDrivenGeneratePayload {
  chapter_id: string

  // API 配置（前端向后端传递）
  api_key?: string
  base_url?: string
  model?: string

  // 意图参数（旧版兼容）
  creative_intents?: CreativeIntentType[]
  intent_priorities?: number[]
  custom_intent_description?: string

  // 章节目标（旧版兼容）
  chapter_goals?: ChapterGoalType[]
  target_entity_ids?: string[]

  // 方案选择（旧版兼容）
  selected_plan_type?: PlanType

  // 用户覆盖（旧版兼容）
  user_overrides?: Record<string, any>

  // 基础参数
  word_count: number
  author_intent?: string
}

// 意图状态
export interface IntentDrivenState {
  // V4.1 简化参数（新增）
  chapterType: ChapterType
  pacing: PacingPreference
  quality: QualityPreference

  // 基础调整
  wordCount: number
  authorIntent: string

  // 旧版兼容字段
  selectedIntents: CreativeIntentType[]
  selectedGoals: ChapterGoalType[]
  selectedPlanType: PlanType
  recommendedPlans: RecommendedPlan[]
  userOverrides: Record<string, { original: any; current: any }>
  isExpertModeExpanded: boolean
}

// 推荐方案响应
export interface RecommendResponse {
  plans: RecommendedPlan[]
  intent_analysis: {
    selected_intents: string[]
    merged_strategy: Record<string, any>
  }
  derivation_explanation: Array<{ rule: string; result: string }>
}

// =============================================================================
// V4.1 推导配置映射表
// =============================================================================

export const CHAPTER_TYPE_CONFIG: Record<ChapterType, {
  label: string
  /** 章节默认路径（fallback），实际生成时 per-beat 自动分配 */
  baseTier: 'TIER_1_FAST' | 'TIER_2_STANDARD' | 'TIER_3_FORTRESS'
  narrativeWeight: string
  baseTension: number
  memorySpan: 'recent_only' | 'balanced_reference' | 'deep_dive'
  description: string
}> = {
  emotional: {
    label: '情感内心戏',
    baseTier: 'TIER_1_FAST',
    narrativeWeight: 'focus_character_emotion',
    baseTension: 4,
    memorySpan: 'balanced_reference',
    description: '心理描写、情感流动、角色内心转变。优先灵气与自由创作。'
  },
  action: {
    label: '动作冲突戏',
    baseTier: 'TIER_3_FORTRESS',
    narrativeWeight: 'focus_plot_conflict',
    baseTension: 5,
    memorySpan: 'deep_dive',
    description: '打斗、追逐、对抗。需要物理一致性与动作连贯性。'
  },
  daily: {
    label: '日常过渡章',
    baseTier: 'TIER_1_FAST',
    narrativeWeight: 'focus_scene_description',
    baseTension: 1,
    memorySpan: 'recent_only',
    description: '轻松日常、过渡衔接。轻快自然即可。'
  },
  suspense: {
    label: '悬疑推理戏',
    baseTier: 'TIER_2_STANDARD',
    narrativeWeight: 'focus_plot_conflict',
    baseTension: 4,
    memorySpan: 'deep_dive',
    description: '线索铺设、逻辑推演。需要严密的伏笔回收。'
  },
  worldbuilding: {
    label: '世界观展开',
    baseTier: 'TIER_2_STANDARD',
    narrativeWeight: 'focus_world_lore',
    baseTension: 2,
    memorySpan: 'deep_dive',
    description: '设定揭示、规则展开。需要准确的设定一致性。'
  }
}

export const PACING_CONFIG: Record<PacingPreference, {
  label: string
  pacingStyle: 'slow_burn' | 'balanced' | 'fast_paced'
  tensionDelta: number
}> = {
  tight:   { label: '紧凑推进', pacingStyle: 'fast_paced', tensionDelta: +1 },
  natural: { label: '顺其自然', pacingStyle: 'balanced',   tensionDelta: 0 },
  relaxed: { label: '舒缓铺陈', pacingStyle: 'slow_burn',  tensionDelta: -1 }
}

export const QUALITY_CONFIG: Record<QualityPreference, {
  label: string
  tierDelta: number
  iterations: number
  refinementDepth: 'light' | 'standard' | 'deep'
}> = {
  fast:     { label: '快速出稿', tierDelta: -1, iterations: 1, refinementDepth: 'light' },
  balanced: { label: '均衡质量', tierDelta: 0,  iterations: 2, refinementDepth: 'standard' },
  quality:  { label: '精细打磨', tierDelta: +1, iterations: 3, refinementDepth: 'deep' }
}

// =============================================================================
// V4.1 策略推导函数
// =============================================================================

export function derivePolicyFromSimpleConfig(config: {
  chapterType: ChapterType
  pacing: PacingPreference
  quality: QualityPreference
  wordCount: number
}): GenerationPolicy & { derivation_log: Array<{ rule: string; result: string }> } {
  const log: Array<{ rule: string; result: string }> = []

  // 1. 本章类型决定基础路径
  const typeCfg = CHAPTER_TYPE_CONFIG[config.chapterType]
  let tier = typeCfg.baseTier
  let tension = typeCfg.baseTension
  log.push({ rule: `本章类型：${typeCfg.label}`, result: `基础路径 ${tier}，叙事权重 ${typeCfg.narrativeWeight}` })

  // 2. 节奏偏好调整张力和节奏风格
  const paceCfg = PACING_CONFIG[config.pacing]
  tension = Math.max(1, Math.min(5, tension + paceCfg.tensionDelta))
  log.push({ rule: `节奏偏好：${paceCfg.label}`, result: `${paceCfg.pacingStyle}，张力 ${tension}` })

  // 3. 质量偏好调整路径等级
  const qualCfg = QUALITY_CONFIG[config.quality]
  const tiers: Array<'TIER_1_FAST' | 'TIER_2_STANDARD' | 'TIER_3_FORTRESS'> =
    ['TIER_1_FAST', 'TIER_2_STANDARD', 'TIER_3_FORTRESS']
  const currentIdx = tiers.indexOf(tier)
  const newIdx = Math.max(0, Math.min(2, currentIdx + qualCfg.tierDelta))
  if (newIdx !== currentIdx) {
    tier = tiers[newIdx]
    log.push({ rule: `质量偏好：${qualCfg.label}`, result: `路径调整为 ${tier}` })
  } else {
    log.push({ rule: `质量偏好：${qualCfg.label}`, result: `路径保持 ${tier}` })
  }

  // 4. 自动推导 RAG 和记忆参数
  const ragTopK = config.quality === 'quality' ? 8 : config.quality === 'balanced' ? 5 : 3
  const ragAlpha = config.chapterType === 'suspense' ? 0.5 : 0.6

  // 5. 双轨：前端不决定，后端根据字数和节拍数自动判断
  log.push({ rule: '双轨生成', result: `字数 ${config.wordCount}，由后端自动判断` })

  // 6. Per-Beat 路径分配（V4.1）
  log.push({ rule: 'Per-Beat 路径分配', result: `章节默认路径 ${tier}，实际生成时根据每个节拍的 pacing_type 和 weight 自动分配（Fast/Standard/Fortress）` })

  const policy: GenerationPolicy = {
    tension_level: tension,
    pacing_style: paceCfg.pacingStyle,
    memory_span: typeCfg.memorySpan,
    creativity_level: 'balanced_creation', // 已全局废弃，保留兼容
    refinement_depth: qualCfg.refinementDepth,
    progression_preference: typeCfg.narrativeWeight as any,
    workflow_tier: tier,
    enable_dual_track: false, // 后端自动
    enable_fail_fast: tier === 'TIER_1_FAST',
    rag_top_k: ragTopK,
    rag_alpha: ragAlpha,
    rag_beta: 0.2,
    rag_gamma: 0.2,
    rag_lambda: 0.1
  }

  return { ...policy, derivation_log: log }
}

// 模板响应
export interface TemplatesResponse {
  creative_intents: CreativeIntentTemplate[]
  chapter_goals: ChapterGoalTemplate[]
}
