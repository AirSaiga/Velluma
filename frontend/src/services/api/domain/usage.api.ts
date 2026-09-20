/**
 * B3 · 用量可见 API（P5 地基加固期批次 1，docs/reports/foundation-hardening.md §2.5）。
 *
 * adaptive 流的 token 消耗聚合（generation_runs 表，run_id=adaptive_{chapter_id}，
 * 后端 routes/chapter_generation/usage.py 只读聚合）。独立成模块而非并入
 * adaptive.api.ts——usage 是 insights 数据页消费的聚合视图，与写作台会话
 * API 关注点不同，也避免与 adaptive 层的并行施工互相牵扯。
 */
import { requestJson } from '../transport'

/** 用量汇总（口径与既有 /cost-report 一致：total = prompt + completion + thinking） */
export interface UsageTotals {
  calls: number
  prompt_tokens: number
  completion_tokens: number
  thinking_tokens: number
  total_tokens: number
  /** 已计价部分成本（元，6 位小数；价目表见 systemApi.getModelPrices） */
  cost: number
  /** 未计价 token 量（模型未配价——如实呈现，不冒充零成本） */
  unpriced_tokens: number
}

/** 按组件（stage）拆账条目；label 为作者可读名（后端映射，未登记 stage 原样返回） */
export interface UsageStageEntry extends UsageTotals {
  stage: string
  label: string
  /** 链路分组键（后端权威：perceive|ghost|settle|auto_read|other） */
  lane: string
  /** 链路作者可读名（写作中感知/续写/沉淀与完稿/系统自己去读/其他） */
  lane_label: string
}

/** 按链路（lane）汇总条目（2026-09-10 真实调用流程对齐：面板按链路分组呈现） */
export interface UsageLaneEntry {
  lane: string
  label: string
  calls: number
  total_tokens: number
  /** 占总量的百分比（0-100，一位小数；总账为 0 时 0） */
  share: number
  cost: number
  unpriced_tokens: number
}

/** 按模型汇总条目（价目表编辑入口的数据面：哪些模型在用、配没配价） */
export interface ModelUsageEntry {
  model: string
  calls: number
  total_tokens: number
  cost: number
  unpriced_tokens: number
  priced: boolean
}

/** 按日聚合条目（UTC 日期，'YYYY-MM-DD'） */
export interface DailyUsage extends UsageTotals {
  date: string
}

/** 本章 adaptive 消耗（GET /chapters/{id}/adaptive/usage） */
export interface ChapterUsage {
  chapter_id: string
  totals: UsageTotals
  by_stage: UsageStageEntry[]
  by_lane: UsageLaneEntry[]
  by_model: ModelUsageEntry[]
}

/** 本书 adaptive 消耗：按日趋势 + 按 stage/链路/模型汇总（GET /books/{id}/adaptive/usage） */
export interface BookUsage {
  book_id: string
  totals: UsageTotals
  by_stage: UsageStageEntry[]
  by_lane: UsageLaneEntry[]
  by_model: ModelUsageEntry[]
  by_date: DailyUsage[]
}

export const usageApi = {
  /** 本章 adaptive 写作消耗（心跳组件/续写/沉淀/完稿拆账）。空数据返回零值结构。 */
  getChapterUsage: async (chapterId: string): Promise<ChapterUsage> => {
    return requestJson(`/chapters/${chapterId}/adaptive/usage`)
  },

  /** 本书 adaptive 消耗：totals + by_stage（降序）+ by_lane（流程序）+ by_date（升序）。 */
  getBookUsage: async (bookId: string): Promise<BookUsage> => {
    return requestJson(`/books/${bookId}/adaptive/usage`)
  },

  /**
   * 清空本章 adaptive 用量台账（测试用；无 UI 入口，控制台/脚本调用）。
   * 只删本章 generation_runs 行，不碰正文与世界数据。
   */
  resetChapterUsage: async (chapterId: string): Promise<{ chapter_id: string; deleted: number }> => {
    return requestJson(`/chapters/${chapterId}/adaptive/usage`, { method: 'DELETE' })
  },
}
