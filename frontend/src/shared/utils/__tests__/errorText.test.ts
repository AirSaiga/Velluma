import { describe, expect, it } from 'vitest'
import { formatGenerationError } from '../errorText'

describe('formatGenerationError', () => {
  it('空文案 → 通用兜底', () => {
    expect(formatGenerationError('')).toBe('生成失败，请重试')
    expect(formatGenerationError('   ')).toBe('生成失败，请重试')
  })

  it('429/限流/配额 → 额度文案', () => {
    expect(formatGenerationError('生成失败: RateLimitError: Error code: 429')).toContain('额度')
    expect(formatGenerationError('quota exceeded for this key')).toContain('额度')
  })

  it('401/403/API Key → 配置文案', () => {
    expect(formatGenerationError('Error code: 401 - invalid api key')).toContain('API Key')
  })

  it('timeout → 超时文案', () => {
    expect(formatGenerationError('Request timed out after 30s')).toContain('超时')
    expect(formatGenerationError('请求超时')).toContain('超时')
  })

  it('网络类 → 连接文案', () => {
    expect(formatGenerationError('TypeError: failed to fetch')).toContain('后端')
    expect(formatGenerationError('ECONNREFUSED 127.0.0.1:8002')).toContain('后端')
  })

  it('内容审查 → 拦截文案', () => {
    expect(formatGenerationError('content_filter: 数据检测不通过')).toContain('拦截')
  })

  it('未知错误 → 原文透传（原文仍可达用户，console 另有记录）', () => {
    expect(formatGenerationError('生成失败: SomeUnknownError')).toBe('生成失败: SomeUnknownError')
  })

  it('优先级：429 命中先于 401（按检查顺序）', () => {
    // 同时含 429 与 key 字样 → 走第一分支
    expect(formatGenerationError('429 rate limit, check api key')).toContain('额度')
  })
})
