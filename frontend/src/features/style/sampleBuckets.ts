/**
 * 样本库分区纯函数（我的笔迹库批，2026-09）。
 *
 * GET /books/{id}/samples 已合并返回本书段 + 笔迹库段（每条带 scope 字段），
 * 前端按 scope 分桶渲染两个分区；本模块只做纯数据整形，供展示层与测试共用。
 *
 * 红线（与后端 422 闸同口径）：source=adopted_ghost 的样本禁入笔迹库
 * （AI 学 AI 不跨库扩散）——展示层置灰转移入口，兜底仍由后端拦截。
 */
import type { AuthorSample } from '../../types'

export interface SampleBuckets {
  /** 本书样本（scope=book 或缺省——缺省视为本书，容错老响应体） */
  book: AuthorSample[]
  /** 我的笔迹库（scope=global，含本书挂入的条目） */
  library: AuthorSample[]
}

/** 按 scope 字段分桶；接口各段内已新→旧，保持原序不重排。 */
export function bucketSamples(samples: AuthorSample[]): SampleBuckets {
  const book: AuthorSample[] = []
  const library: AuthorSample[] = []
  for (const s of samples) {
    if (s.scope === 'global') library.push(s)
    else book.push(s)
  }
  return { book, library }
}

/** 是否可转入笔迹库：采纳幽灵样本（AI 写的）禁入——后端 422，前端先置灰。 */
export function canEnterLibrary(sample: AuthorSample): boolean {
  return sample.source !== 'adopted_ghost'
}

/**
 * 提炼弹窗预填候选：只取本书自己的样本按字数降序取前 count 条内容。
 * 外来 global 行是别书的字，不该顶着「你写的文字」进本书指纹提炼的预填框；
 * 本书零样本时返回空数组（弹窗走手贴路径）。
 */
export function extractPrefillCandidates(
  samples: AuthorSample[],
  currentBookId: string | null | undefined,
  count = 3,
): string[] {
  return samples
    .filter(s => !isForeignSample(s, currentBookId))
    .sort((a, b) => b.word_count - a.word_count)
    .slice(0, count)
    .map(s => s.content)
}

/**
 * 是否外来样本（2026-09 用户拍板）：book_id 存在且不等于当前书 → 在「我的笔迹库」分区只读。
 * 容错：缺 book_id 或缺当前书 ID 时视为本书（宁可放行 editable，不误伤本书样本）。
 */
export function isForeignSample(
  sample: AuthorSample,
  currentBookId: string | null | undefined,
): boolean {
  if (!sample.book_id || !currentBookId) return false
  return sample.book_id !== currentBookId
}

/** 外来样本只读的悬停解释（作者语言；知道书名就点名，不知道就指路）。 */
export function foreignSampleHint(
  sample: AuthorSample,
  bookTitleById?: Record<string, string>,
): string {
  const title = bookTitleById?.[sample.book_id]
  return title
    ? `来自《${title}》的样本——去那本书的文风页里改`
    : '来自其他书的样本——去那本书的文风页里改'
}

/** 笔迹库分区头部待命文案：让跨书补位机制对作者可见（作者语言，零术语）。 */
export function libraryStandbyLabel(count: number): string {
  return count > 0
    ? `笔迹库 · ${count} 条待命——新书与缺场景时自动补位`
    : '笔迹库还空着——把最像你的字转入，新书缺范例时自动补位'
}
