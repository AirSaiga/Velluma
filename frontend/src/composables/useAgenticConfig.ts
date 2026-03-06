import type { AgenticFormState, GenerateChapterAgenticPayload } from '../types'

const FLOAT_PRECISION = 1000

export const AGENTIC_GROUPS = {
  generation: {
    title: '生成控制',
    description: '控制本章篇幅与生成稳定性。'
  },
  memory: {
    title: '前文回顾策略',
    description: '调整系统参考历史内容时的侧重点。'
  },
  workflow: {
    title: '生成流程设置',
    description: '设置自动检查与改写的次数。'
  }
} as const

export const AGENTIC_DEFAULTS: AgenticFormState = {
  word_count: 2000,
  max_iterations: 2,
  rag_top_k: 3,
  rag_alpha: 0.6,
  rag_beta: 0.2,
  rag_gamma: 0.2,
  rag_lambda: 0.1
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
  max_iterations: {
    label: '自动改写次数',
    description: '内容不理想时，系统最多再尝试几次。',
    rangeHint: '范围 1~5',
    recommended: '推荐 2',
    group: 'workflow'
  },
  rag_top_k: {
    label: '参考前文条目数',
    description: '每次生成参考的历史片段数量。',
    rangeHint: '范围 1~20',
    recommended: '推荐 3',
    group: 'memory'
  },
  rag_alpha: {
    label: '情节相关程度',
    description: '提高后会更优先参考和当前情节最贴近的前文。',
    rangeHint: '范围 0~1',
    recommended: '推荐 0.6',
    group: 'memory'
  },
  rag_beta: {
    label: '最近章节优先',
    description: '提高后会更优先参考最近发生的内容。',
    rangeHint: '范围 0~1',
    recommended: '推荐 0.2',
    group: 'memory'
  },
  rag_gamma: {
    label: '主线线索优先',
    description: '提高后会更优先参考关键剧情线索。',
    rangeHint: '范围 0~1',
    recommended: '推荐 0.2',
    group: 'memory'
  },
  rag_lambda: {
    label: '旧内容淡出速度',
    description: '数值越大，系统越少引用较早内容。',
    rangeHint: '范围 ≥ 0',
    recommended: '推荐 0.1',
    group: 'memory'
  }
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

export function normalizeAgenticForm(input: Partial<AgenticFormState>) {
  const normalized: AgenticFormState = {
    word_count: Math.round(clamp(toNumber(input.word_count, AGENTIC_DEFAULTS.word_count), 1)),
    max_iterations: Math.round(clamp(toNumber(input.max_iterations, AGENTIC_DEFAULTS.max_iterations), 1, 5)),
    rag_top_k: Math.round(clamp(toNumber(input.rag_top_k, AGENTIC_DEFAULTS.rag_top_k), 1, 20)),
    rag_alpha: roundFloat(clamp(toNumber(input.rag_alpha, AGENTIC_DEFAULTS.rag_alpha), 0, 1)),
    rag_beta: roundFloat(clamp(toNumber(input.rag_beta, AGENTIC_DEFAULTS.rag_beta), 0, 1)),
    rag_gamma: roundFloat(clamp(toNumber(input.rag_gamma, AGENTIC_DEFAULTS.rag_gamma), 0, 1)),
    rag_lambda: roundFloat(clamp(toNumber(input.rag_lambda, AGENTIC_DEFAULTS.rag_lambda), 0))
  }
  return normalized
}

export function validateAgenticForm(input: Partial<AgenticFormState>) {
  const normalized = normalizeAgenticForm(input)
  const errors: string[] = []
  const weightSum = roundFloat(normalized.rag_alpha + normalized.rag_beta + normalized.rag_gamma)

  if (normalized.word_count < 1) errors.push('字数目标必须大于 0')
  if (normalized.max_iterations < 1 || normalized.max_iterations > 5) errors.push('自动改写次数必须在 1~5 之间')
  if (normalized.rag_top_k < 1 || normalized.rag_top_k > 20) errors.push('前文参考条目数必须在 1~20 之间')
  if (Math.abs(weightSum - 1) > 0.001) errors.push('三项回顾偏好总和必须为 1')
  if (normalized.rag_lambda < 0) errors.push('旧内容淡出速度必须大于等于 0')

  return {
    normalized,
    errors
  }
}

export function buildAgenticPayload(params: {
  chapterId: string
  apiConfig: { api_key: string; base_url?: string; model?: string }
  form: Partial<AgenticFormState>
}): { payload: GenerateChapterAgenticPayload | null; errors: string[] } {
  const { normalized, errors } = validateAgenticForm(params.form)
  const apiKey = (params.apiConfig.api_key || '').trim()
  if (!apiKey) {
    errors.push('请先配置 API Key')
  }

  if (errors.length > 0) {
    return { payload: null, errors }
  }

  return {
    payload: {
      chapter_id: params.chapterId,
      api_key: apiKey,
      base_url: params.apiConfig.base_url || undefined,
      model: params.apiConfig.model || 'gpt-4o-mini',
      word_count: normalized.word_count,
      max_iterations: normalized.max_iterations,
      rag_top_k: normalized.rag_top_k,
      rag_alpha: normalized.rag_alpha,
      rag_beta: normalized.rag_beta,
      rag_gamma: normalized.rag_gamma,
      rag_lambda: normalized.rag_lambda,
      fast_mode: true,
      skip_minor_refine: true
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

  const wordCount = checkNumber('word_count')
  if (wordCount !== null && (wordCount < 500 || wordCount > 10000)) {
    feedback.word_count = `${AGENTIC_FIELD_CONFIG.word_count.label}需在 500~10000 之间`
  }

  const maxIterations = checkNumber('max_iterations')
  if (maxIterations !== null && (maxIterations < 1 || maxIterations > 5)) {
    feedback.max_iterations = `${AGENTIC_FIELD_CONFIG.max_iterations.label}需在 1~5 之间`
  }

  const topK = checkNumber('rag_top_k')
  if (topK !== null && (topK < 1 || topK > 20)) {
    feedback.rag_top_k = `${AGENTIC_FIELD_CONFIG.rag_top_k.label}需在 1~20 之间`
  }

  const alpha = checkNumber('rag_alpha')
  if (alpha !== null && (alpha < 0 || alpha > 1)) {
    feedback.rag_alpha = `${AGENTIC_FIELD_CONFIG.rag_alpha.label}需在 0~1 之间`
  }

  const beta = checkNumber('rag_beta')
  if (beta !== null && (beta < 0 || beta > 1)) {
    feedback.rag_beta = `${AGENTIC_FIELD_CONFIG.rag_beta.label}需在 0~1 之间`
  }

  const gamma = checkNumber('rag_gamma')
  if (gamma !== null && (gamma < 0 || gamma > 1)) {
    feedback.rag_gamma = `${AGENTIC_FIELD_CONFIG.rag_gamma.label}需在 0~1 之间`
  }

  const lambdaValue = checkNumber('rag_lambda')
  if (lambdaValue !== null && lambdaValue < 0) {
    feedback.rag_lambda = `${AGENTIC_FIELD_CONFIG.rag_lambda.label}需大于等于 0`
  }

  if (alpha !== null && beta !== null && gamma !== null) {
    const sum = roundFloat(alpha + beta + gamma)
    if (Math.abs(sum - 1) > 0.001) {
      feedback.rag_alpha = '三项回顾权重总和必须为 1'
      feedback.rag_beta = '三项回顾权重总和必须为 1'
      feedback.rag_gamma = '三项回顾权重总和必须为 1'
    }
  }

  return feedback
}
