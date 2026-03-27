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
    tension_level: 10,
    rag_lambda: -3
  })

  assert.equal(normalized.word_count, 1)
  assert.equal(normalized.tension_level, 5)
  assert.equal(normalized.rag_lambda, 0)
})

test('validateAgenticForm 会规范化输入并返回合法配置', () => {
  // 注意：validateAgenticForm 内部会先调用 normalizeAgenticForm 规范化输入
  // 所有非法值都会被自动修正，因此通常不会返回错误
  const result = validateAgenticForm({
    ...AGENTIC_DEFAULTS,
    word_count: -100,
    rag_lambda: -1
  })

  // 非法值被规范化后不会触发错误
  assert.equal(result.errors.length, 0)
  // 验证规范化后的值
  assert.equal(result.normalized.word_count, 1)
  assert.equal(result.normalized.rag_lambda, 0)
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
  assert.equal(payload?.fast_mode, false)
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
    tension_level: 10,
    pacing_style: 'invalid_style' as any,
    memory_span: 'invalid_span' as any,
    creativity_level: 'invalid_creativity' as any,
    progression_preference: 'invalid_progression' as any,
    refinement_depth: 'invalid_refinement' as any,
    rag_lambda: -1
  })

  assert.equal(feedback.word_count, '本章篇幅需在 500~10000 之间')
  assert.equal(feedback.tension_level, '剧情张力等级 (V3.0)需在 1~5 之间')
  assert.equal(feedback.pacing_style, '叙事节奏偏好选项无效')
  assert.equal(feedback.memory_span, 'AI 记忆回溯跨度选项无效')
  assert.equal(feedback.creativity_level, '自由发挥程度选项无效')
  assert.equal(feedback.progression_preference, '剧情推进偏好选项无效')
  assert.equal(feedback.refinement_depth, '精雕细琢深度选项无效')
  assert.equal(feedback.rag_lambda, '旧内容淡出强度需大于等于 0')
})
