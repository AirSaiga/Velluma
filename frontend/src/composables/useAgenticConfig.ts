import type { AgenticFormState, GenerateChapterAgenticPayload, ReasoningConfig } from '../types'

const FLOAT_PRECISION = 1000
const MEMORY_SPAN_TOP_K = {
  recent_only: 2,
  balanced_reference: 3,
  deep_dive: 6
} as const
const CREATIVITY_ALPHA = {
  strict_prompt: 0.75,
  balanced_creation: 0.6,
  wild_imagination: 0.45
} as const
const PROGRESSION_BETA_RATIO = {
  focus_scene_action: 0.75,
  push_mainline: 0.35
} as const
const REFINEMENT_ITERATIONS = {
  light: 1,
  standard: 2,
  deep: 4
} as const

export interface AgenticLegacyFields {
  max_iterations: number
  rag_top_k: number
  rag_alpha: number
  rag_beta: number
  rag_gamma: number
}

export const AGENTIC_GROUPS = {
  steering: {
    title: '创作意图',
    description: '指导 AI 的写作方向。'
  },
  style: {
    title: '风格基调',
    description: '调节剧情张力与叙事节奏。'
  },
  generation: {
    title: '生成控制',
    description: '控制本章篇幅与生成稳定性。'
  },
  memory: {
    title: '前文回顾策略',
    description: '按语义挡位配置记忆检索与推进偏好。'
  },
  workflow: {
    title: '生成流程设置',
    description: '调节改写深度，平衡耗时与质量。'
  }
} as const

export const AGENTIC_DEFAULTS: AgenticFormState = {
  word_count: 2000,
  tension_level: 3,  // V3.0: 默认改为 3 (均衡流)
  pacing_style: 'balanced',
  memory_span: 'balanced_reference',
  creativity_level: 'balanced_creation',
  progression_preference: 'focus_scene_action',
  refinement_depth: 'standard',
  rag_lambda: 0.1,
  author_intent: '',
  force_parallel_prose: false
}

export interface AgenticFieldOption {
  label: string
  value: string | number
}

export const AGENTIC_FIELD_CONFIG: Record<keyof AgenticFormState, {
  label: string
  description: string
  rangeHint: string
  recommended: string
  group: keyof typeof AGENTIC_GROUPS
}> = {
  word_count: {
    label: '本章篇幅',
    description: '期望生成的字数规模。',
    rangeHint: '范围 500~10000',
    recommended: '推荐 2000',
    group: 'generation'
  },
  tension_level: {
    label: '剧情张力等级 (V3.0)',
    description: '控制冲突的激烈程度，同时决定智能路由层级：Level 1-2 疾速流(低算力) / Level 3 均衡流 / Level 4-5 堡垒流(全功能)',
    rangeHint: '范围 1~5',
    recommended: '默认：3 (均衡流)',
    group: 'style'
  },
  pacing_style: {
    label: '叙事节奏偏好',
    description: '决定情节推进的速度与细节描写的比重。',
    rangeHint: '可选：慢热 / 平衡 / 快节奏',
    recommended: '默认：平衡',
    group: 'style'
  },
  memory_span: {
    label: 'AI 记忆回溯跨度',
    description: '控制系统回看前文的范围深度。',
    rangeHint: '可选：仅看近期 / 正常参考 / 深挖伏笔',
    recommended: '默认：正常参考',
    group: 'memory'
  },
  creativity_level: {
    label: '自由发挥程度',
    description: '控制生成内容相对提示词的约束强度。',
    rangeHint: '可选：紧扣提示词 / 均衡发展 / 天马行空',
    recommended: '默认：均衡发展',
    group: 'memory'
  },
  progression_preference: {
    label: '剧情推进偏好',
    description: '决定更偏向当前场景动作或主线推进。',
    rangeHint: '可选：聚焦当前场景动作 / 强推主线大纲进度',
    recommended: '默认：聚焦当前场景动作',
    group: 'memory'
  },
  refinement_depth: {
    label: '精雕细琢深度',
    description: '深度越高耗时越长，但细节质量通常更高。',
    rangeHint: '可选：轻度 / 标准 / 深度',
    recommended: '默认：标准',
    group: 'workflow'
  },
  rag_lambda: {
    label: '旧内容淡出强度',
    description: '决定系统减少早期内容引用的速度。',
    rangeHint: '可选：关闭 / 轻度 / 中度 / 强',
    recommended: '默认：轻度',
    group: 'memory'
  },
  author_intent: {
    label: '创作意图',
    description: '在此输入具体的指导说明，如“增加悬疑感”、“重点描写环境”等。',
    rangeHint: '自由文本',
    recommended: '可选',
    group: 'steering'
  },
  force_parallel_prose: {
    label: '极速模式（正文并行生成）',
    description: '开启后所有正文段落将同时生成，极大提升速度但可能损失段落间连贯性。适合对连贯性要求不高的场景。',
    rangeHint: '可选：开启/关闭',
    recommended: '默认：关闭',
    group: 'workflow'
  }
}

export const AGENTIC_FIELD_OPTIONS: Partial<Record<keyof AgenticFormState, AgenticFieldOption[]>> = {
  pacing_style: [
    { label: '慢热', value: 'slow_burn' },
    { label: '平衡', value: 'balanced' },
    { label: '快节奏', value: 'fast_paced' }
  ],
  memory_span: [
    { label: '仅看近期', value: 'recent_only' },
    { label: '正常参考', value: 'balanced_reference' },
    { label: '深挖伏笔', value: 'deep_dive' }
  ],
  creativity_level: [
    { label: '紧扣提示词', value: 'strict_prompt' },
    { label: '均衡发展', value: 'balanced_creation' },
    { label: '天马行空', value: 'wild_imagination' }
  ],
  progression_preference: [
    { label: '聚焦当前场景动作', value: 'focus_scene_action' },
    { label: '强推主线大纲进度', value: 'push_mainline' }
  ],
  refinement_depth: [
    { label: '轻度', value: 'light' },
    { label: '标准', value: 'standard' },
    { label: '深度', value: 'deep' }
  ],
  rag_lambda: [
    { label: '关闭', value: 0 },
    { label: '轻度', value: 0.1 },
    { label: '中度', value: 0.3 },
    { label: '强', value: 0.6 }
  ]
}

function toNumber(value: unknown, fallback: number) {
  const num = Number(value)
  return Number.isFinite(num) ? num : fallback
}

function clamp(value: number, min: number, max?: number) {
  const lowerBounded = Math.max(min, value)
  if (typeof max === 'number') return Math.min(lowerBounded, max)
  return lowerBounded
}

function roundFloat(value: number) {
  return Math.round(value * FLOAT_PRECISION) / FLOAT_PRECISION
}

function pickNearestByValue<T extends string>(value: number, mapping: Record<T, number>, fallback: T) {
  let selected = fallback
  let minDistance = Number.POSITIVE_INFINITY
  for (const key of Object.keys(mapping) as T[]) {
    const distance = Math.abs(mapping[key] - value)
    if (distance < minDistance) {
      minDistance = distance
      selected = key
    }
  }
  return selected
}

function normalizeSelect<T extends string>(value: unknown, allowed: readonly T[], fallback: T): T {
  if (typeof value === 'string' && (allowed as readonly string[]).includes(value)) {
    return value as T
  }
  return fallback
}

function normalizeProgressionFromLegacy(input: Partial<AgenticLegacyFields>) {
  const rawBeta = toNumber(input.rag_beta, NaN)
  const rawGamma = toNumber(input.rag_gamma, NaN)
  if (!Number.isFinite(rawBeta) || !Number.isFinite(rawGamma)) {
    return AGENTIC_DEFAULTS.progression_preference
  }
  const total = rawBeta + rawGamma
  if (total <= 0) {
    return AGENTIC_DEFAULTS.progression_preference
  }
  const ratio = rawBeta / total
  return pickNearestByValue(ratio, PROGRESSION_BETA_RATIO, AGENTIC_DEFAULTS.progression_preference)
}

function normalizeMemorySpanFromLegacy(input: Partial<AgenticLegacyFields>) {
  const topK = Math.round(clamp(toNumber(input.rag_top_k, MEMORY_SPAN_TOP_K[AGENTIC_DEFAULTS.memory_span]), 1, 20))
  return pickNearestByValue(topK, MEMORY_SPAN_TOP_K, AGENTIC_DEFAULTS.memory_span)
}

function normalizeCreativityFromLegacy(input: Partial<AgenticLegacyFields>) {
  const alpha = roundFloat(clamp(toNumber(input.rag_alpha, CREATIVITY_ALPHA[AGENTIC_DEFAULTS.creativity_level]), 0, 1))
  return pickNearestByValue(alpha, CREATIVITY_ALPHA, AGENTIC_DEFAULTS.creativity_level)
}

function normalizeRefinementFromLegacy(input: Partial<AgenticLegacyFields>) {
  const iterations = Math.round(clamp(toNumber(input.max_iterations, 2), 1, 5))
  return pickNearestByValue(iterations, REFINEMENT_ITERATIONS, AGENTIC_DEFAULTS.refinement_depth)
}

export function normalizeAgenticForm(input: Partial<AgenticFormState & AgenticLegacyFields>) {
  const normalizedMemorySpan = normalizeSelect(
    input.memory_span,
    Object.keys(MEMORY_SPAN_TOP_K) as Array<AgenticFormState['memory_span']>,
    normalizeMemorySpanFromLegacy(input)
  )
  const normalizedCreativity = normalizeSelect(
    input.creativity_level,
    Object.keys(CREATIVITY_ALPHA) as Array<AgenticFormState['creativity_level']>,
    normalizeCreativityFromLegacy(input)
  )
  const normalizedProgression = normalizeSelect(
    input.progression_preference,
    Object.keys(PROGRESSION_BETA_RATIO) as Array<AgenticFormState['progression_preference']>,
    normalizeProgressionFromLegacy(input)
  )
  const normalizedRefinement = normalizeSelect(
    input.refinement_depth,
    Object.keys(REFINEMENT_ITERATIONS) as Array<AgenticFormState['refinement_depth']>,
    normalizeRefinementFromLegacy(input)
  )
  const normalizedPacing = normalizeSelect(
    input.pacing_style,
    ['slow_burn', 'balanced', 'fast_paced'] as Array<AgenticFormState['pacing_style']>,
    AGENTIC_DEFAULTS.pacing_style
  )

  return {
    word_count: Math.round(clamp(toNumber(input.word_count, AGENTIC_DEFAULTS.word_count), 1)),
    tension_level: Math.round(clamp(toNumber(input.tension_level, AGENTIC_DEFAULTS.tension_level), 1, 5)),
    pacing_style: normalizedPacing,
    memory_span: normalizedMemorySpan,
    creativity_level: normalizedCreativity,
    progression_preference: normalizedProgression,
    refinement_depth: normalizedRefinement,
    rag_lambda: roundFloat(clamp(toNumber(input.rag_lambda, AGENTIC_DEFAULTS.rag_lambda), 0)),
    author_intent: (input.author_intent || '').trim(),
    force_parallel_prose: Boolean(input.force_parallel_prose)
  }
}

export function buildLegacyAgenticFields(form: Partial<AgenticFormState>): AgenticLegacyFields {
  const normalized = normalizeAgenticForm(form)
  const ragTopK = MEMORY_SPAN_TOP_K[normalized.memory_span]
  const ragAlpha = CREATIVITY_ALPHA[normalized.creativity_level]
  const betaRatio = PROGRESSION_BETA_RATIO[normalized.progression_preference]
  const residual = roundFloat(1 - ragAlpha)
  const ragBeta = roundFloat(residual * betaRatio)
  const ragGamma = roundFloat(Math.max(0, 1 - ragAlpha - ragBeta))
  const maxIterations = REFINEMENT_ITERATIONS[normalized.refinement_depth]

  return {
    max_iterations: maxIterations,
    rag_top_k: ragTopK,
    rag_alpha: ragAlpha,
    rag_beta: ragBeta,
    rag_gamma: ragGamma
  }
}

export function serializeAgenticForm(form: Partial<AgenticFormState>) {
  const normalized = normalizeAgenticForm(form)
  const legacy = buildLegacyAgenticFields(normalized)
  return {
    ...normalized,
    ...legacy
  }
}

export function deserializeAgenticForm(input: unknown) {
  if (!input || typeof input !== 'object') {
    return { ...AGENTIC_DEFAULTS }
  }
  return normalizeAgenticForm(input as Partial<AgenticFormState & AgenticLegacyFields>)
}

export function validateAgenticForm(input: Partial<AgenticFormState & AgenticLegacyFields>) {
  const normalized = normalizeAgenticForm(input)
  const errors: string[] = []

  if (normalized.word_count < 1) errors.push('字数目标必须大于 0')
  if (normalized.rag_lambda < 0) errors.push('旧内容淡出速度必须大于等于 0')

  return {
    normalized,
    errors
  }
}

export function buildAgenticPayload(params: {
  chapterId: string
  apiConfig: { 
    api_key: string
    base_url?: string
    model?: string
    reasoning_model?: string
    creative_model?: string
    // 默认模型的推理模式配置
    reasoning_enabled?: boolean
    reasoning_effort?: ReasoningConfig['effort']
    reasoning_exclude?: boolean
    // 逻辑推理模型的推理模式配置
    reasoning_model_reasoning_enabled?: boolean
    reasoning_model_reasoning_effort?: ReasoningConfig['effort']
    reasoning_model_reasoning_exclude?: boolean
    // 创意生成模型的推理模式配置
    creative_model_reasoning_enabled?: boolean
    creative_model_reasoning_effort?: ReasoningConfig['effort']
    creative_model_reasoning_exclude?: boolean
  }
  form: Partial<AgenticFormState & AgenticLegacyFields>
}): { payload: GenerateChapterAgenticPayload | null; errors: string[] } {
  const { normalized, errors } = validateAgenticForm(params.form)
  const legacyFields = buildLegacyAgenticFields(normalized)
  const apiKey = (params.apiConfig.api_key || '').trim()
  if (!apiKey) {
    errors.push('请先配置 API Key')
  }

  if (errors.length > 0) {
    return { payload: null, errors }
  }

  // 双模型配置处理
  const hasDualModel = !!(params.apiConfig.reasoning_model || params.apiConfig.creative_model)
  const baseModel = params.apiConfig.model || 'gpt-4o-mini'
  
  // 单模型模式的推理模式配置处理
  let reasoningConfig: ReasoningConfig | undefined = undefined
  if (!hasDualModel && params.apiConfig.reasoning_enabled) {
    reasoningConfig = {
      enabled: true,
      effort: params.apiConfig.reasoning_effort || 'medium',
      exclude: params.apiConfig.reasoning_exclude || false
    }
  }
  
  // 双模型模式的推理模式配置处理
  let reasoningModelReasoningConfig: ReasoningConfig | undefined = undefined
  let creativeModelReasoningConfig: ReasoningConfig | undefined = undefined
  
  if (hasDualModel) {
    // 逻辑推理模型的推理配置
    if (params.apiConfig.reasoning_model_reasoning_enabled) {
      reasoningModelReasoningConfig = {
        enabled: true,
        effort: params.apiConfig.reasoning_model_reasoning_effort || 'high',
        exclude: params.apiConfig.reasoning_model_reasoning_exclude || false
      }
    }
    
    // 创意生成模型的推理配置
    if (params.apiConfig.creative_model_reasoning_enabled) {
      creativeModelReasoningConfig = {
        enabled: true,
        effort: params.apiConfig.creative_model_reasoning_effort || 'low',
        exclude: params.apiConfig.creative_model_reasoning_exclude || false
      }
    }
  }
  
  return {
    payload: {
      chapter_id: params.chapterId,
      api_key: apiKey,
      base_url: params.apiConfig.base_url || undefined,
      // 向后兼容：保留 model 字段
      model: baseModel,
      // 双模型配置
      reasoning_model: hasDualModel ? (params.apiConfig.reasoning_model || baseModel) : undefined,
      creative_model: hasDualModel ? (params.apiConfig.creative_model || baseModel) : undefined,
      word_count: normalized.word_count,
      tension_level: normalized.tension_level,
      pacing_style: normalized.pacing_style,
      max_iterations: legacyFields.max_iterations,
      rag_top_k: legacyFields.rag_top_k,
      rag_alpha: legacyFields.rag_alpha,
      rag_beta: legacyFields.rag_beta,
      rag_gamma: legacyFields.rag_gamma,
      rag_lambda: normalized.rag_lambda,
      author_intent: normalized.author_intent,
      fast_mode: false,
      skip_minor_refine: true,
      force_parallel_prose: normalized.force_parallel_prose,
      // 单模型模式的推理模式配置
      reasoning_config: reasoningConfig,
      // 双模型模式的推理模式配置
      reasoning_model_reasoning_config: reasoningModelReasoningConfig,
      creative_model_reasoning_config: creativeModelReasoningConfig
    },
    errors: []
  }
}

export function getAgenticFieldFeedback(input: Partial<AgenticFormState>) {
  const feedback: Partial<Record<keyof AgenticFormState, string>> = {}
  const checkNumber = (key: keyof AgenticFormState) => {
    const value = Number(input[key])
    if (!Number.isFinite(value)) {
      feedback[key] = `${AGENTIC_FIELD_CONFIG[key].label}必须填写数字`
      return null
    }
    return value
  }
  const checkSelect = (key: keyof AgenticFormState, allowed: string[]) => {
    const value = input[key]
    if (typeof value !== 'string' || !allowed.includes(value)) {
      feedback[key] = `${AGENTIC_FIELD_CONFIG[key].label}选项无效`
    }
  }

  const wordCount = checkNumber('word_count')
  if (wordCount !== null && (wordCount < 500 || wordCount > 10000)) {
    feedback.word_count = `${AGENTIC_FIELD_CONFIG.word_count.label}需在 500~10000 之间`
  }

  const tension = checkNumber('tension_level')
  if (tension !== null && (tension < 1 || tension > 5)) {
    feedback.tension_level = `${AGENTIC_FIELD_CONFIG.tension_level.label}需在 1~5 之间`
  }
  checkSelect('pacing_style', ['slow_burn', 'balanced', 'fast_paced'])

  checkSelect('memory_span', Object.keys(MEMORY_SPAN_TOP_K))
  checkSelect('creativity_level', Object.keys(CREATIVITY_ALPHA))
  checkSelect('progression_preference', Object.keys(PROGRESSION_BETA_RATIO))
  checkSelect('refinement_depth', Object.keys(REFINEMENT_ITERATIONS))

  const lambdaValue = checkNumber('rag_lambda')
  if (lambdaValue !== null && lambdaValue < 0) {
    feedback.rag_lambda = `${AGENTIC_FIELD_CONFIG.rag_lambda.label}需大于等于 0`
  }

  return feedback
}
