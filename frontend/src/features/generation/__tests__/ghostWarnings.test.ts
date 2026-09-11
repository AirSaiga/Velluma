/**
 * C1 上屏前快检（P5 §5.1）——疑点汇总话术纯函数测试。
 *
 * 只测 summarizeGhostWarnings（纯函数，无 DOM/window 依赖——vitest node 环境
 * 直接 import useGhostDraft 模块安全：其 window 访问全部在函数体内调用时才发生）。
 * 红线口径：话术必须含「只是提醒」类语义（只提醒不拦截，采纳已完成）。
 */
import { describe, it, expect } from 'vitest'
import { summarizeGhostWarnings } from '../composables/useGhostDraft'
import type { GhostWarning } from '../../../services/api/domain/adaptive.api'

function w(kind: GhostWarning['kind'], span = '触发词', message = '说明'): GhostWarning {
  return { kind, span_text: span, message }
}

describe('summarizeGhostWarnings', () => {
  it('空列表返回空串（调用方据此静默，不打扰）', () => {
    expect(summarizeGhostWarnings([])).toBe('')
  })

  it('单条：计数 + kind 短标签 + 只是提醒口径', () => {
    const s = summarizeGhostWarnings([w('dead_speak', '老烟')])
    expect(s).toBe('已采纳，含 1 处疑点：死者开口（只是提醒，可不管）')
  })

  it('同 kind 多条去重为 ×N（按类汇总不逐条刷屏）', () => {
    const s = summarizeGhostWarnings([w('dead_speak', '老烟'), w('dead_speak', '烟叔')])
    expect(s).toBe('已采纳，含 2 处疑点：死者开口×2（只是提醒，可不管）')
  })

  it('三类齐发：按出现序拼接、总数为条数和', () => {
    const s = summarizeGhostWarnings([
      w('dead_speak', '老烟'),
      w('canon_leak', '叶姑娘'),
      w('secret_leak', '皇室遗孤'),
    ])
    expect(s).toBe(
      '已采纳，含 3 处疑点：死者开口、秘密穿帮、秘密外泄（只是提醒，可不管）',
    )
  })

  it('未知 kind 回退原词（后端新增枚举不炸前端）', () => {
    const s = summarizeGhostWarnings([w('future_kind' as GhostWarning['kind'])])
    expect(s).toContain('future_kind')
    expect(s).toContain('1 处疑点')
  })
})
