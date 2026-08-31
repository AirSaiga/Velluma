/**
 * 地点树工具（前端侧，docs/location-interior.md）。
 *
 * 与后端 services/world/location_tree.py 同构——改口径两侧同步（各配单测对拍）。
 * 渲染契约不变量：上图权 = parent_id IS NULL——有父级的地点一律不上地图，
 * 只在父地点详情抽屉与地点列表缩进子树中呈现。
 */
import type { WorldLocation } from './types'

const PATH_SEP = '·'

export function locationsById(locations: WorldLocation[]): Map<string, WorldLocation> {
  const m = new Map<string, WorldLocation>()
  for (const l of locations) m.set(l.id, l)
  return m
}

/** parent_id → 直接子级列表（保持传入顺序；无父级不入表） */
export function childrenIndex(locations: WorldLocation[]): Map<string, WorldLocation[]> {
  const out = new Map<string, WorldLocation[]>()
  for (const l of locations) {
    if (!l.parent_id) continue
    const list = out.get(l.parent_id)
    if (list) list.push(l)
    else out.set(l.parent_id, [l])
  }
  return out
}

/** 顶层地点（上图/计数口径：地点列表徽标只数顶层，防「12 地点」虚高含房间） */
export function topLevelLocations(locations: WorldLocation[]): WorldLocation[] {
  return locations.filter((l) => !l.parent_id)
}

/**
 * 以 rootId 为根的整棵子树（含根，BFS 父前子后）。
 * 删除前取快照用——父前子后保证 undo 重建时父已存在。
 */
export function collectSubtree(locations: WorldLocation[], rootId: string): WorldLocation[] {
  const byId = locationsById(locations)
  const root = byId.get(rootId)
  if (!root) return []
  const kids = childrenIndex(locations)
  const out: WorldLocation[] = []
  const queue = [root]
  while (queue.length) {
    const cur = queue.shift()!
    out.push(cur)
    for (const c of kids.get(cur.id) || []) queue.push(c)
  }
  return out
}

/** 地点全路径「统合局基地·B2 拘留层」（顶层 = 裸名；防环截断）。 */
export function locationPath(loc: WorldLocation, byId: Map<string, WorldLocation>): string {
  const parts: string[] = [loc.name]
  const seen = new Set<string>([loc.id])
  let cur = loc
  while (cur.parent_id && !seen.has(cur.parent_id)) {
    const parent = byId.get(cur.parent_id)
    if (!parent) break
    parts.push(parent.name)
    seen.add(parent.id)
    cur = parent
  }
  return parts.reverse().join(PATH_SEP)
}
