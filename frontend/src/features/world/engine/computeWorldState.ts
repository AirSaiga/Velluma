import type { WorldEvent, WorldLocation, WorldState, WorldRelation, Point } from './types'
import { interpolateOnPath } from './interpolate'

/**
 * 事件溯源推演引擎（纯函数）：从事件流 fold 成时刻 t 的 WorldState。
 *
 * 与后端 repositories/world_repository.compute_world_state_from_events 同构
 * （前后端共用算法逻辑，可独立单测）。
 *
 * 四条决策（照搬世界绘卷）：
 * ① 生死：alive = born≤t 且 (无 death 或 death>t)
 * ② move 沿 payload.path 弧长插值在途位置
 * ③ 疆域 = 最近一次 time_start≤t 的 territory_change 的 polygon
 *    （action='lose' 且空 polygon → 失去全部疆域）
 * ④ 关系边：static 恒活跃；event_ref 锚事件已回放（time_start≤t）才活跃
 *
 * 算法：过滤 time_start≤t → 按 sequence_num 升序（乱序输入结果稳定）→
 * 按 event_type 分发回放，累加 character/territory/location 状态。
 */
export function computeWorldState(
  events: WorldEvent[],
  locationsById: Record<string, WorldLocation>,
  t: number,
  relations?: WorldRelation[],
): WorldState {
  const applicable = events
    .filter((e) => e.time_start <= t)
    .slice()
    .sort((a, b) => a.sequence_num - b.sequence_num)

  const characterStates = new Map<
    string,
    {
      entity_id: string
      location_id: string | null
      position: Point | null
      alive: boolean
      label: string
      last_event_id: string | null
    }
  >()
  const born = new Set<string>()
  const dead = new Map<string, number>()
  const territoryStates = new Map<
    string,
    { faction_id: string; polygon: Point[]; last_event_id: string | null }
  >()
  const locationExists = new Map<string, boolean>()

  const locCoord = (locId: string | null): Point | null => {
    if (!locId) return null
    const loc = locationsById[locId]
    if (loc && loc.coord_x != null && loc.coord_y != null) {
      return [loc.coord_x, loc.coord_y]
    }
    return null
  }

  for (const e of applicable) {
    const eid = e.id
    switch (e.event_type) {
      case 'birth': {
        const cid = (e.payload.character_id as string | undefined) || null
        if (cid) {
          born.add(cid)
          const birthLoc = (e.payload.location_id as string | undefined) || e.location_id || null
          characterStates.set(cid, {
            entity_id: cid,
            location_id: birthLoc,
            position: locCoord(birthLoc),
            alive: true,
            label: '出生',
            last_event_id: eid,
          })
        }
        break
      }
      case 'death': {
        const cid = (e.payload.character_id as string | undefined) || null
        if (cid) {
          dead.set(cid, e.time_start)
          const s = characterStates.get(cid)
          if (s) {
            s.alive = false
            s.last_event_id = eid
            s.label = '已死亡'
          }
        }
        break
      }
      case 'move': {
        const cids = (e.payload.character_ids as string[] | undefined) || []
        const path = (e.payload.path as Point[] | undefined) || []
        const toLoc = (e.payload.to_location_id as string | undefined) || null
        for (const cid of cids) {
          const { position, label } = interpolateOnPath(path, e.time_start, e.time_end, t)
          characterStates.set(cid, {
            entity_id: cid,
            location_id: toLoc,
            position: position || locCoord(toLoc),
            alive: !dead.has(cid),
            label: label || (t >= e.time_end ? '驻留' : ''),
            last_event_id: eid,
          })
        }
        break
      }
      case 'territory_change': {
        const fid = (e.payload.faction_id as string | undefined) || null
        if (fid) {
          const polygon = (e.payload.polygon as Point[] | undefined) || []
          const action = (e.payload.action as string | undefined) || 'gain'
          if (action === 'lose' && polygon.length === 0) {
            territoryStates.delete(fid)
          } else {
            territoryStates.set(fid, { faction_id: fid, polygon, last_event_id: eid })
          }
        }
        break
      }
      case 'found': {
        const tid = (e.payload.target_id as string | undefined) || null
        if (tid) locationExists.set(tid, true)
        break
      }
      case 'destroy': {
        const tid = (e.payload.target_id as string | undefined) || null
        if (tid) locationExists.set(tid, false)
        break
      }
      default:
        // battle/alliance/war_declare/coronation/custom：不改世界状态
        break
    }
  }

  // 生死最终判定（决策①）：born≤t 且 (无 death 或 death>t)
  for (const [cid, s] of characterStates) {
    s.alive = born.has(cid) && (!dead.has(cid) || (dead.get(cid) as number) > t)
  }

  // 决策④：关系边激活状态（static 恒活跃；锚事件已回放才活跃）
  const relationStates = (relations || []).map((r) => ({
    relation_id: r.id,
    source_entity_id: r.source_entity_id,
    target_entity_id: r.target_entity_id,
    relation_type: r.relation_type,
    label: r.label || '',
    active: r.static || !r.event_ref
      ? true
      : applicable.some((e) => e.id === r.event_ref),
  }))

  return {
    at_time: t,
    character_states: Array.from(characterStates.values()),
    territory_states: Array.from(territoryStates.values()),
    location_states: Array.from(locationExists.entries()).map(([location_id, exists]) => ({
      location_id,
      exists,
      last_event_id: null,
    })),
    relation_states: relationStates,
  }
}
