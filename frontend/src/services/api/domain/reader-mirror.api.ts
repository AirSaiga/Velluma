/**
 * Reader Mirror API（V4.2 路径 B）。
 *
 * 端点（前缀 /api/books/{book_id}/reader-mirror）：
 * - GET  /                       获取全书 mirror
 * - GET  /plan/{chapter_number}  本章规划建议（介入点 1）
 * - POST /expectations           添加期待
 * - PUT  /expectations/{id}      更新期待
 * - DELETE /expectations/{id}    删除期待
 * - POST /tension/{chapter}      记录张力
 * - POST /infer/{chapter_id}     章节后推断
 */

import { requestJson } from '../transport'

export type ExpectationType = 'power_reveal' | 'revenge' | 'romance' | 'mystery' | 'growth'
export type ExpectationStatus = 'setup' | 'accumulating' | 'payoff' | 'subverted' | 'dropped'

export interface Expectation {
  id: string
  book_id: string
  type: ExpectationType
  description: string
  source: 'author_declared' | 'auto_inferred'
  status: ExpectationStatus
  current_tension: number
  expected_payoff_chapter: number | null
  tension_history: Array<{ chapter: number; tension: number; event: string }>
  related_hook_ids: string[]
  related_character_ids: string[]
  author_override: string | null
}

export interface ChapterTensionSample {
  chapter_number: number
  overall_tension: number
  active_expectations: number
  is_payoff_chapter: boolean
  note: string
}

export interface ChapterPlanSuggestion {
  chapter_number: number
  expectations_to_setup: string[]
  expectations_to_accumulate: string[]
  expectations_to_payoff: string[]
  suggested_tension: number
  is_payoff_chapter_recommended: boolean
  rationale: string
  author_override: string | null
}

export interface ReaderMirror {
  expectations: Expectation[]
  tension_curve: ChapterTensionSample[]
  information_asymmetries: any[]
}

export const readerMirrorApi = {
  get: (bookId: string) =>
    requestJson<ReaderMirror>(`/books/${bookId}/reader-mirror`),

  getPlan: (bookId: string, chapterNumber: number) =>
    requestJson<ChapterPlanSuggestion>(`/books/${bookId}/reader-mirror/plan/${chapterNumber}`),

  createExpectation: (bookId: string, data: Partial<Expectation> & { id: string; type: ExpectationType; description: string }) =>
    requestJson<Expectation>(`/books/${bookId}/reader-mirror/expectations`, {
      method: 'POST',
      body: JSON.stringify(data),
    }),

  updateExpectation: (bookId: string, expectationId: string, data: { tension_delta?: number; new_status?: ExpectationStatus; tension_event?: string; chapter_number: number }) =>
    requestJson<Expectation>(`/books/${bookId}/reader-mirror/expectations/${expectationId}`, {
      method: 'PUT',
      body: JSON.stringify(data),
    }),

  deleteExpectation: (bookId: string, expectationId: string) =>
    requestJson<{ deleted: boolean }>(`/books/${bookId}/reader-mirror/expectations/${expectationId}`, {
      method: 'DELETE',
    }),

  recordTension: (bookId: string, chapterNumber: number, data: { overall_tension: number; is_payoff?: boolean; note?: string }) =>
    requestJson<{ recorded: boolean }>(`/books/${bookId}/reader-mirror/tension/${chapterNumber}`, {
      method: 'POST',
      body: JSON.stringify(data),
    }),

  infer: (bookId: string, chapterId: string) =>
    requestJson<{ updated: boolean; expectations_count: number }>(`/books/${bookId}/reader-mirror/infer/${chapterId}`, {
      method: 'POST',
      body: JSON.stringify({}),
    }),
}

export const EXPECTATION_TYPE_LABELS: Record<ExpectationType, string> = {
  power_reveal: '实力揭示',
  revenge: '复仇打脸',
  romance: '感情',
  mystery: '悬念',
  growth: '成长',
}

export const EXPECTATION_STATUS_LABELS: Record<ExpectationStatus, string> = {
  setup: '埋设',
  accumulating: '累积中',
  payoff: '已释放',
  subverted: '已反转',
  dropped: '已放弃',
}

export const EXPECTATION_STATUS_COLORS: Record<ExpectationStatus, string> = {
  setup: '#94a3b8',
  accumulating: '#f59e0b',
  payoff: '#10b981',
  subverted: '#8b5cf6',
  dropped: '#6b7280',
}
