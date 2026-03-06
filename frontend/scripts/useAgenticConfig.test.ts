import test from 'node:test'
import assert from 'node:assert/strict'
import {
  AGENTIC_DEFAULTS,
  buildAgenticPayload,
  getAgenticFieldFeedback,
  normalizeAgenticForm,
  validateAgenticForm
} from '../src/composables/useAgenticConfig.js'

test('normalizeAgenticForm 会把非法输入回退到允许范围', () => {
  const normalized = normalizeAgenticForm({
    word_count: -10,
    max_iterations: 99,
    rag_top_k: 0,
    rag_alpha: 5,
    rag_beta: -2,
    rag_gamma: 0.2,
    rag_lambda: -3
  })

  assert.equal(normalized.word_count, 1)
  assert.equal(normalized.max_iterations, 5)
  assert.equal(normalized.rag_top_k, 1)
  assert.equal(normalized.rag_alpha, 1)
  assert.equal(normalized.rag_beta, 0)
  assert.equal(normalized.rag_gamma, 0.2)
  assert.equal(normalized.rag_lambda, 0)
})

test('validateAgenticForm 会检出权重和不为 1 的失败场景', () => {
  const result = validateAgenticForm({
    ...AGENTIC_DEFAULTS,
    rag_alpha: 0.4,
    rag_beta: 0.4,
    rag_gamma: 0.4
  })

  assert.equal(result.errors.includes('三项回顾偏好总和必须为 1'), true)
})

test('buildAgenticPayload 在配置合法时输出完整 payload', () => {
  const { payload, errors } = buildAgenticPayload({
    chapterId: 'chapter-1',
    apiConfig: { api_key: '  key-123  ', base_url: 'https://api.example.com', model: 'gpt-test' },
    form: AGENTIC_DEFAULTS
  })

  assert.deepEqual(errors, [])
  assert.ok(payload)
  assert.equal(payload?.chapter_id, 'chapter-1')
  assert.equal(payload?.api_key, 'key-123')
  assert.equal(payload?.base_url, 'https://api.example.com')
  assert.equal(payload?.model, 'gpt-test')
  assert.equal(payload?.fast_mode, true)
  assert.equal(payload?.skip_minor_refine, true)
})

test('buildAgenticPayload 在缺少 API Key 时返回失败', () => {
  const { payload, errors } = buildAgenticPayload({
    chapterId: 'chapter-2',
    apiConfig: { api_key: '   ' },
    form: AGENTIC_DEFAULTS
  })

  assert.equal(payload, null)
  assert.equal(errors.includes('请先配置 API Key'), true)
})

test('getAgenticFieldFeedback 会为越界字段返回逐项提示', () => {
  const feedback = getAgenticFieldFeedback({
    word_count: 12000,
    max_iterations: 0,
    rag_top_k: 30,
    rag_alpha: 0.6,
    rag_beta: 0.3,
    rag_gamma: 0.3,
    rag_lambda: -1
  })

  assert.equal(feedback.word_count, '本章篇幅需在 500~10000 之间')
  assert.equal(feedback.max_iterations, '自动改写次数需在 1~5 之间')
  assert.equal(feedback.rag_top_k, '参考前文条目数需在 1~20 之间')
  assert.equal(feedback.rag_lambda, '旧内容淡出速度需大于等于 0')
  assert.equal(feedback.rag_alpha, '三项回顾权重总和必须为 1')
  assert.equal(feedback.rag_beta, '三项回顾权重总和必须为 1')
  assert.equal(feedback.rag_gamma, '三项回顾权重总和必须为 1')
})
