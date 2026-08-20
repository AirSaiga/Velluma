import type { Point, WorldEvent, WorldLocation } from './types'

/**
 * 事件 → 地图坐标协议（照搬世界绘卷）：
 * - move → path 起点（无 path 则 from_location 坐标）
 * - territory_change → polygon 质心
 * - 其他 → payload.point（地图点选录入的结构化点）→ 旧数据 note 里的 @x,y 标记 → location_id 的坐标
 */
export function eventPoint(
  e: WorldEvent,
  locationsById: Record<string, WorldLocation>,
): Point | null {
  if (e.event_type === 'move') {
    const path = (e.payload.path as Point[] | undefined) || []
    if (path.length > 0) return [path[0][0], path[0][1]]
    const fromId = (e.payload.from_location_id as string | undefined) || null
    return locCoord(fromId, locationsById)
  }
  if (e.event_type === 'territory_change') {
    const polygon = (e.payload.polygon as Point[] | undefined) || []
    if (polygon.length > 0) return centroid(polygon)
  }
  // 地图点选录入的结构化点（新契约，note 保持干净）
  const p = e.payload.point as Point | undefined
  if (Array.isArray(p) && p.length >= 2) return [p[0], p[1]]
  // 旧数据回退：note 里的 @x,y 标记
  const legacy = parsePointFromNote(e.note || '')
  if (legacy) return legacy
  return locCoord(e.location_id, locationsById)
}

function locCoord(
  locId: string | null,
  locationsById: Record<string, WorldLocation>,
): Point | null {
  if (!locId) return null
  const loc = locationsById[locId]
  if (loc && loc.coord_x != null && loc.coord_y != null) {
    return [loc.coord_x, loc.coord_y]
  }
  return null
}

export function centroid(points: Point[]): Point | null {
  if (points.length === 0) return null
  let sx = 0
  let sy = 0
  for (const [x, y] of points) {
    sx += x
    sy += y
  }
  return [sx / points.length, sy / points.length]
}

/** 从 note 里解析 @x,y 标记（旧契约，新数据走 payload.point） */
export function parsePointFromNote(note: string): Point | null {
  const m = (note || '').match(/@(-?\d+\.?\d*),\s*(-?\d+\.?\d*)/)
  return m ? [parseFloat(m[1]), parseFloat(m[2])] : null
}

/** 从 note 里剥离 @x,y 标记，返回干净 note（UI 显示用） */
export function stripPointFromNote(note: string): string {
  return (note || '').replace(/@-?\d+\.?\d*,\s*-?\d+\.?\d*/g, '').trim()
}
