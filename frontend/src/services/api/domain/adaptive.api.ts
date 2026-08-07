/**
 * NLE-ADF 3.0 自适应辅助 API（心跳模式）。
 *
 * 核心协议：前端防抖发 heartbeat（作者状态），后端调度器决定激活哪些组件，
 * 异步跑、写回世界模型。前端下次心跳拿到组件产出（挂件/建议）。
 *
 * 端点：
 * - heartbeat：作者状态心跳 → 返回快照 + 挂件
 * - settle：段落锁死 → 层1追加 + 沉淀
 * - finish：完稿 → 后处理
 * - model：拉取世界模型快照（恢复用）
 * - stitchGhost：微缝合（SSE，按需）
 */
import { streamSse } from '../stream'
import { requestJson } from '../transport'

// ============================================================
// 类型定义
// ============================================================

export interface DockPart {
  key: string
  kind: string
  icon: string
  text: string
  direction?: string
}

export interface HeartbeatResult {
  dock_parts: DockPart[]
  intent_source: string
  intent_arc: string
  intent_confidence: number
  fact_count: number
  total_words: number
  activated: string[]
  signals: string[]
}

export interface SettleResult {
  settled: boolean
  fact_count: number
  emergent_facts?: any
  conflicts?: any[]
}

/** 完稿后处理审计报告 */
export interface FinishReport {
  finished: boolean
  reason?: string
  report?: {
    chapter_id?: string
    word_count?: number
    sentence_defects?: any[]
    coverage?: {
      checked: boolean
      hit_count?: number
      miss_count?: number
      misses?: string[]
      reason?: string
    }
    canon_check?: {
      private_breaches?: string[]
      public_fact_count?: number
    }
    critique?: {
      issues?: Array<{ severity: string; category: string; detail: string }>
      verdict?: string
    }
  }
}

export interface WorldModelSnapshot {
  facts: any[]
  intent: any
  projections: any[]
  intent_version: number
  fact_count: number
  total_words: number
}

// ============================================================
// adaptiveApi
// ============================================================

export const adaptiveApi = {
  /** 作者状态心跳 → 触发调度器 → 返回快照 + 挂件 */
  heartbeat: async (
    chapterId: string,
    data: {
      word_count: number
      segment_count: number
      paused_ms: number
      cursor_at_paragraph_end: boolean
      has_outline: boolean
      outline_text: string
      recent_text: string
    },
  ): Promise<HeartbeatResult> => {
    return requestJson(`/chapters/${chapterId}/adaptive/heartbeat`, {
      method: 'POST',
      body: JSON.stringify(data),
    })
  },

  /** 段落锁死 → 层1追加 + 沉淀倒灌 */
  settle: async (
    chapterId: string,
    data: { text: string; entities?: any[]; commit?: boolean },
  ): Promise<SettleResult> => {
    return requestJson(`/chapters/${chapterId}/adaptive/settle`, {
      method: 'POST',
      body: JSON.stringify(data),
    })
  },

  /** 完稿 → 后处理审计（同步等待返回报告） */
  finish: async (chapterId: string): Promise<FinishReport> => {
    return requestJson(`/chapters/${chapterId}/adaptive/finish`, {
      method: 'POST',
    })
  },

  /** 拉取世界模型快照（恢复/调试用） */
  model: async (chapterId: string): Promise<WorldModelSnapshot> => {
    return requestJson(`/chapters/${chapterId}/adaptive/model`)
  },

  /** 微缝合幽灵草稿（SSE 打字机推流） */
  stitchGhost: async (
    chapterId: string,
    params: {
      fragment: string
      rolling_prefix?: string
      mode?: 'stitch' | 'continue'
      picked_parts?: string[]
      target_chars?: number
      chapter_intent?: string
      adopted_direction?: string
    },
    callbacks: {
      onStart?: (mode: string) => void
      onChunk?: (delta: string) => void
      onDone?: (result: { text: string; word_count: number }) => void
      onError?: (error: string) => void
    },
    signal?: AbortSignal,
  ) => {
    streamSse(`/chapters/${chapterId}/adaptive/stitch-ghost`, params, {
      onPayload: payload => {
        if (!payload || !payload.event) return
        if (payload.event === 'GHOST_START') {
          callbacks.onStart?.(payload.mode || 'stitch')
        } else if (payload.event === 'GHOST_CHUNK') {
          callbacks.onChunk?.(payload.delta || '')
        } else if (payload.event === 'GHOST_DONE') {
          callbacks.onDone?.({ text: payload.text || '', word_count: payload.word_count || 0 })
          return true
        } else if (payload.event === 'ERROR' || payload.event === 'GHOST_ERROR') {
          callbacks.onError?.(payload.error || '续写失败')
          return true
        }
      },
      onError: message => callbacks.onError?.(message),
    }, signal).catch(err => { if (!signal?.aborted) callbacks.onError?.(err.message) })
  },
}
