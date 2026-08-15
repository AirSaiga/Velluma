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

// ============================================================
// 人话层（UX 重构）：火候 / 时机 / 类型归类
// 底层存储不变（数字张力、状态枚举），这里只负责语言映射
// ============================================================

/** 火候四档：录入时替代裸数字张力，tension 为落库映射值 */
export const HEAT_LEVELS = [
  { key: 'simmering', label: '刚埋下', tension: 2 },
  { key: 'brewing', label: '在发酵', tension: 5 },
  { key: 'urgent', label: '读者急了', tension: 8 },
  { key: 'overdue', label: '快凉了', tension: 10 },
] as const

/** 数字张力 → 火候词（列表卡片展示用） */
export function tensionToHeat(tension: number): string {
  if (tension <= 3) return '刚埋下'
  if (tension <= 6) return '在发酵'
  if (tension <= 8) return '读者急了'
  return '快凉了'
}

/**
 * 释放时机五档：作者的时间感是模糊的，不强制具体章号。
 * override 写入 author_override（作者处理意图），expected_payoff_chapter 一律存 null。
 */
export const TIMING_OPTIONS = [
  { key: 'unknown', label: '没想好', override: null },
  { key: 'soon', label: '尽快', override: '打算：尽快收' },
  { key: 'few', label: '几章后', override: '打算：几章后收' },
  { key: 'volume_end', label: '卷末', override: '打算：卷末收' },
  { key: 'long', label: '长线捂着', override: '打算：长线捂着' },
] as const

/**
 * 按描述关键词确定性归类（无 AI）：为类型 select 提供预填默认值，用户可改。
 * 具体词（打脸/相认等）优先，泛化词（为什么/到底）殿后，默认悬念。
 */
export function guessTypeFromDescription(description: string): ExpectationType {
  const d = description || ''
  const rules: Array<[ExpectationType, string[]]> = [
    ['revenge', ['打脸', '复仇', '报仇', '雪耻', '教训', '收拾']],
    ['romance', ['感情', '相认', '告白', '在一起', '心动', '表白']],
    ['power_reveal', ['展露', '实力', '底牌', '能力', '出手', '爆发']],
    ['growth', ['升级', '成长', '突破', '变强', '觉醒', '蜕变']],
    ['mystery', ['来历', '是谁', '真相', '身份', '秘密', '目的', '为什么', '到底']],
  ]
  for (const [type, keywords] of rules) {
    if (keywords.some(k => d.includes(k))) return type
  }
  return 'mystery'
}
