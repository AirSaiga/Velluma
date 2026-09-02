/**
 * 时间轴 UI 状态（游标时刻 + 手动视野窗口）的类型与校验——前后端同构。
 *
 * 按书持久化在服务端 books.timeline_view（GET/PATCH /books/{id}/timeline-view，
 * 键级合并、显式 null 删键）。历史上的 localStorage 方案（velluma:tl-time /
 * velluma:tl-range）因启动脚本端口扫描导致 origin 漂移、状态看似「重置」，已弃用；
 * 旧键仅在加载时作一次性迁移来源读取，不再作为主存储。
 */

/**
 * 手动视野窗口（起止年份）。
 *
 * 2026-09-02 起允许浮点年——浮点精确到「日」：窗口日计数 = [round((start-1)*365), round(end*365))。
 * 坐标约定：start=1+起日/365（1 基年坐标），end=止日/365（0 基「已完成年数」坐标）——两坐标系
 * 相差整 1 年，整数年与旧语义逐日等价（start=首年，end=末年的下一年），存量整数数据零迁移。
 * ⚠ 浮点窗口落在单年内时 start 可大于 end（近 1 年）——合法性只看日空间：start >= 1 且
 * end > start-1 且名义跨度 >= 1 天。浮点由滚轮缩放产生（日级视野）；「框定视野」表单仍只产整数年。
 */
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

/** 视野窗口校验：有限数值、start >= 1、日空间窗口非空（坐标约定见 TimelineRange——浮点同窗单年内 start 可大于 end，勿改回 start < end）；非法返回 null */
export function normalizeTimelineRange(v: unknown): TimelineRange | null {
  if (!v || typeof v !== 'object') return null
  const { start, end } = v as Record<string, unknown>
  if (
    typeof start !== 'number' ||
    typeof end !== 'number' ||
    !Number.isFinite(start) ||
    !Number.isFinite(end) ||
    start < 1 ||
    end <= start - 1 ||
    (end - (start - 1)) * 365 < 1
  ) {
    return null
  }
  return { start, end }
}
