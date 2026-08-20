/**
 * 时间轴 UI 状态（游标时刻 + 手动视野窗口）的类型与校验——前后端同构。
 *
 * 按书持久化在服务端 books.timeline_view（GET/PATCH /books/{id}/timeline-view，
 * 键级合并、显式 null 删键）。历史上的 localStorage 方案（velluma:tl-time /
 * velluma:tl-range）因启动脚本端口扫描导致 origin 漂移、状态看似「重置」，已弃用；
 * 旧键仅在加载时作一次性迁移来源读取，不再作为主存储。
 */

/** 手动视野窗口（起止年份，1 <= start < end） */
export interface TimelineRange {
  start: number
  end: number
}

/** books.timeline_view 的 JSON 形状；缺键=未设置（游标回创世 / 视野自动跟随事件） */
export interface TimelineViewState {
  cursor?: number
  range?: TimelineRange | null
}

/** 游标时刻校验：非负有限数 → 取整；非法返回 null（调用方按「未设置」处理） */
export function normalizeTimelineCursor(v: unknown): number | null {
  if (typeof v !== 'number' || !Number.isFinite(v) || v < 0) return null
  return Math.floor(v)
}

/** 视野窗口校验：整数年份且 1 <= start < end；非法返回 null */
export function normalizeTimelineRange(v: unknown): TimelineRange | null {
  if (!v || typeof v !== 'object') return null
  const { start, end } = v as Record<string, unknown>
  if (
    typeof start !== 'number' ||
    typeof end !== 'number' ||
    !Number.isInteger(start) ||
    !Number.isInteger(end) ||
    start < 1 ||
    end <= start
  ) {
    return null
  }
  return { start, end }
}
