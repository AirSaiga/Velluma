/**
 * B3 · 用量可见 API（P5 地基加固期批次 1，docs/foundation-hardening.md §2.5）。
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
}

/** 按组件（stage）拆账条目；label 为作者可读名（后端映射，未登记 stage 原样返回） */
export interface UsageStageEntry extends UsageTotals {
  stage: string
  label: string
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
}

/** 本书 adaptive 消耗：按日趋势 + 按 stage 汇总（GET /books/{id}/adaptive/usage） */
export interface BookUsage {
  book_id: string
  totals: UsageTotals
  by_stage: UsageStageEntry[]
  by_date: DailyUsage[]
}

export const usageApi = {
  /** 本章 adaptive 写作消耗（心跳组件/续写/沉淀/完稿拆账）。空数据返回零值结构。 */
  getChapterUsage: async (chapterId: string): Promise<ChapterUsage> => {
    return requestJson(`/chapters/${chapterId}/adaptive/usage`)
  },

  /** 本书 adaptive 消耗：totals + by_stage（降序）+ by_date（升序）。 */
  getBookUsage: async (bookId: string): Promise<BookUsage> => {
    return requestJson(`/books/${bookId}/adaptive/usage`)
  },
}
