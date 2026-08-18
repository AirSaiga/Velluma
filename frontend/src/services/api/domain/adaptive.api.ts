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
  /** 来源标记：'expectation' = 期待账本衍生件 */
  origin?: string
}

/** Canon 感知提示（canon_watch 组件产，写中停顿心跳返回） */
export interface CanonHint {
  /** 感知类型：appearance 角色出场 / callback 伏笔回收时机 / leak private 泄露 / style_drift 文风漂移（S4 补全） */
  kind: 'appearance' | 'callback' | 'leak' | 'contradiction' | 'style_drift'
  /** 实体名（角色名 / 伏笔标签 / Canon 节点 label） */
  node_label: string
  /** 实体类型：character / hook / canon */
  node_type: string
  /** 一句话说明（感知带卡片正文） */
  detail: string
  /** 严重度：error > warning > info（影响排序/着色） */
  severity: string
}

export interface HeartbeatResult {
  dock_parts: DockPart[]
  direction_cards: DirectionCard[]
  intent_source: string
  intent_arc: string
  intent_confidence: number
  fact_count: number
  total_words: number
  activated: string[]
  signals: string[]
  /** Canon 感知提示（canon_watch 产；写中右缘感知带数据源） */
  canon_hints?: CanonHint[]
  /** 世界数据版本（路由层附带；写作页切片保鲜比对，查询失败无此字段） */
  world_version?: { events: number; updated_at: string | null } | null
  /** 章级谋篇进度（P1.4 M2；无脉络/无锚点无此字段——进度行静默缺席） */
  spine_progress?: SpineProgress | null
}

/** 章级谋篇进度（纯算法判定：pending→hit 只前进；dropped 作者手点） */
export interface SpineProgress {
  intent: string
  anchors: { id: string; text: string; status: 'pending' | 'hit' | 'dropped' }[]
  pending_count: number
  hint: string
}

/** 走向卡（层 3 推测首 beat）：Ctrl+Space 走向卡舱的数据源 */
export interface DirectionCard {
  event: string
  anchors: string[]
  /** 服务于的谋篇锚点 id（P1.4 M2 走向卡挂脉络；命中本章非 dropped 锚点才透传） */
  serves_anchor?: string
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
    /** 记忆倒灌：完稿时本章写入向量记忆的块数 */
    memory_indexed?: number
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

// ===== 章级谋篇·软脉络（P1.4，docs/chapter-planning-spine.md）=====
export interface SpineAnchor {
  id: string
  text: string
  source: 'author' | 'ai'
  status: 'pending' | 'hit' | 'dropped'
}
export interface ChapterSpine {
  intent?: { text: string; source: 'author' | 'ai' }
  anchors?: SpineAnchor[]
}
export interface SpineSuggestion {
  intent: string
  anchors: string[]
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

  /** 协作交互埋点（P0-3 本地 jsonl 零上报；词表见后端端点 6 注释） */
  logCollabEvent: async (
    chapterId: string,
    kind: string,
    detail?: Record<string, unknown>,
  ): Promise<void> => {
    await requestJson(`/chapters/${chapterId}/adaptive/event`, {
      method: 'POST',
      body: JSON.stringify({ kind, detail: detail || {} }),
    })
  },

  /** 残句定点修复（P1.2 作者裁决式：只产修复句，正文不动；每轮审计上限 5 处） */
  fixSentence: async (
    chapterId: string,
    payload: { sentence: string; defect_type?: string; description?: string },
  ): Promise<{ fixed: string | null; reason: string }> => {
    return requestJson(`/chapters/${chapterId}/adaptive/fix-sentence`, {
      method: 'POST',
      body: JSON.stringify(payload),
    })
  },

  /** 软脉络读取（null = 本章无脉络，一切 UI 静默缺席） */
  getSpine: async (chapterId: string): Promise<{ spine: ChapterSpine | null }> => {
    return requestJson(`/chapters/${chapterId}/adaptive/spine`)
  },

  /** 软脉络部分合并保存（只改传了的字段；锚点硬上限 5） */
  patchSpine: async (
    chapterId: string,
    patch: { intent?: { text: string; source: 'author' | 'ai' } | null; anchors?: SpineAnchor[] | null },
  ): Promise<{ spine: ChapterSpine | null }> => {
    return requestJson(`/chapters/${chapterId}/adaptive/spine`, {
      method: 'PATCH',
      body: JSON.stringify(patch),
    })
  },

  /** AI 谋篇建议（不落库——建议只在作者收下/编辑后才入库） */
  spineSuggest: async (chapterId: string): Promise<SpineSuggestion> => {
    return requestJson(`/chapters/${chapterId}/adaptive/spine-suggest`, { method: 'POST' })
  },

  /** 协作交互汇总（个人镜子：走向卡/幽灵稿/胶囊采纳率） */
  collabEventsSummary: async (chapterId: string): Promise<{
    total: number
    by_kind: Record<string, number>
    card_burst_rate: number | null
    ghost_adopt_rate: number | null
    capsule_expand_count: number
    quick_note_commit: number
  }> => {
    return requestJson(`/chapters/${chapterId}/adaptive/events/summary`)
  },

  /** 微缝合幽灵草稿（SSE 打字机推流）；mode='burst' 为段落级连写、'outline' 为细纲扩写 */
  stitchGhost: async (
    chapterId: string,
    params: {
      fragment: string
      rolling_prefix?: string
      mode?: 'stitch' | 'continue' | 'burst' | 'open' | 'outline'
      picked_parts?: string[]
      target_chars?: number
      chapter_intent?: string
      adopted_direction?: string
      beat_guidance?: string
      /** outline 模式：细纲之后的已写正文开头（双端缝合用） */
      after_text?: string
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
