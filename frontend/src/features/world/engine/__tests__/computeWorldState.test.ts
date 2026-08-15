import { describe, it, expect, beforeEach } from 'vitest'
import { computeWorldState } from '../computeWorldState'
import type { WorldEvent, WorldLocation, WorldRelation } from '../types'

let seq = 0
function mkEvent(partial: Partial<WorldEvent>): WorldEvent {
  seq += 1
  return {
    id: `ev-${seq}`,
    book_id: 'b1',
    sequence_num: seq,
    event_type: 'custom',
    time_start: 0,
    time_end: 0,
    location_id: null,
    participant_ids: [],
    faction_ids: [],
    payload: {},
    causes: [],
    chapter_ref: null,
    tags: [],
    note: '',
    ...partial,
  }
}

const loc = (id: string, x: number, y: number): WorldLocation => ({
  id,
  book_id: 'b1',
  name: id,
  kind: 'point',
  parent_id: null,
  coord_x: x,
  coord_y: y,
  geometry: {},
  intro: '',
  tags: [],
})

beforeEach(() => {
  seq = 0
})

describe('computeWorldState — 决策① 出生/死亡', () => {
  it('出生事件让角色在 t 后存在并定位到出生地', () => {
    const events = [
      mkEvent({
        event_type: 'birth',
        time_start: 100,
        payload: { character_id: 'c1', location_id: 'l1' },
      }),
    ]
    const state = computeWorldState(events, { l1: loc('l1', 10, 20) }, 100)
    expect(state.character_states).toHaveLength(1)
    expect(state.character_states[0].alive).toBe(true)
    expect(state.character_states[0].position).toEqual([10, 20])
  })

  it('出生前角色不存在', () => {
    const events = [
      mkEvent({ event_type: 'birth', time_start: 100, payload: { character_id: 'c1' } }),
    ]
    expect(computeWorldState(events, {}, 50).character_states).toHaveLength(0)
  })

  it('死亡时间之后角色非存活，之前存活', () => {
    const events = [
      mkEvent({ event_type: 'birth', time_start: 0, payload: { character_id: 'c1' } }),
      mkEvent({ event_type: 'death', time_start: 200, payload: { character_id: 'c1' } }),
    ]
    expect(computeWorldState(events, {}, 150).character_states[0].alive).toBe(true)
    expect(computeWorldState(events, {}, 250).character_states[0].alive).toBe(false)
  })
})

describe('computeWorldState — 决策② move 沿 path 插值', () => {
  it('move 中点按弧长插值（直线中点）', () => {
    const events = [
      mkEvent({
        event_type: 'move',
        time_start: 100,
        time_end: 200,
        payload: { character_ids: ['c1'], path: [[0, 0], [100, 0]] },
      }),
    ]
    const state = computeWorldState(events, {}, 150)
    expect(state.character_states[0].position).toEqual([50, 0])
    expect(state.character_states[0].label).toContain('在途')
  })

  it('move 结束后驻留终点', () => {
    const events = [
      mkEvent({
        event_type: 'move',
        time_start: 100,
        time_end: 200,
        payload: { character_ids: ['c1'], path: [[0, 0], [100, 0]] },
      }),
    ]
    const state = computeWorldState(events, {}, 300)
    expect(state.character_states[0].position).toEqual([100, 0])
    expect(state.character_states[0].label).toBe('驻留')
  })

  it('多段 path 按弧长比例（非顶点比例）', () => {
    // 两段不等长：[0,0]→[100,0]（长100）→[100,100]（长100），总 200
    // t 中点（进度 0.5）应落在第一段末尾 [100,0]
    const events = [
      mkEvent({
        event_type: 'move',
        time_start: 0,
        time_end: 100,
        payload: { character_ids: ['c1'], path: [[0, 0], [100, 0], [100, 100]] },
      }),
    ]
    const state = computeWorldState(events, {}, 50)
    expect(state.character_states[0].position).toEqual([100, 0])
  })
})

describe('computeWorldState — 决策③ 疆域事件溯源', () => {
  it('疆域 = 最近一次 time_start≤t 的 territory_change', () => {
    const events = [
      mkEvent({
        event_type: 'territory_change',
        time_start: 50,
        payload: { faction_id: 'f1', polygon: [[0, 0], [10, 0], [10, 10]], action: 'gain' },
      }),
      mkEvent({
        event_type: 'territory_change',
        time_start: 150,
        payload: { faction_id: 'f1', polygon: [[0, 0], [20, 0], [20, 20]], action: 'gain' },
      }),
    ]
    expect(computeWorldState(events, {}, 100).territory_states[0].polygon[1]).toEqual([10, 0])
    expect(computeWorldState(events, {}, 200).territory_states[0].polygon[1]).toEqual([20, 0])
  })

  it('疆域 lose 且空 polygon = 失去全部', () => {
    const events = [
      mkEvent({
        event_type: 'territory_change',
        time_start: 50,
        payload: { faction_id: 'f1', polygon: [[0, 0], [10, 0]], action: 'gain' },
      }),
      mkEvent({
        event_type: 'territory_change',
        time_start: 150,
        payload: { faction_id: 'f1', polygon: [], action: 'lose' },
      }),
    ]
    expect(computeWorldState(events, {}, 100).territory_states).toHaveLength(1)
    expect(computeWorldState(events, {}, 200).territory_states).toHaveLength(0)
  })
})

describe('computeWorldState — 乱序稳定', () => {
  it('按 sequence_num 排序回放（seq 大的后设覆盖，与输入数组顺序无关）', () => {
    // move1 seq=1，move2 seq=2；输入数组故意倒序 [move2, move1]
    const move1 = mkEvent({
      event_type: 'move',
      time_start: 0,
      time_end: 10,
      payload: { character_ids: ['c1'], path: [[0, 0], [100, 0]] },
    }) // seq=1
    const move2 = mkEvent({
      event_type: 'move',
      time_start: 0,
      time_end: 10,
      payload: { character_ids: ['c1'], path: [[0, 0], [200, 0]] },
    }) // seq=2
    // 回放按 seq 升序：move1(seq1) 先设中点 [50,0]，move2(seq2) 覆盖中点 [100,0]
    const state = computeWorldState([move2, move1], {}, 5)
    expect(state.character_states).toHaveLength(1)
    expect(state.character_states[0].position).toEqual([100, 0])
  })
})

describe('computeWorldState — found/destroy', () => {
  it('destroy 后地点不存在', () => {
    const events = [
      mkEvent({ event_type: 'found', time_start: 0, payload: { target_id: 'l1' } }),
      mkEvent({ event_type: 'destroy', time_start: 100, payload: { target_id: 'l1' } }),
    ]
    expect(computeWorldState(events, {}, 50).location_states[0].exists).toBe(true)
    expect(computeWorldState(events, {}, 150).location_states[0].exists).toBe(false)
  })
})

const mkRelation = (partial: Partial<WorldRelation>): WorldRelation => ({
  id: 'rel-1',
  book_id: 'b1',
  source_entity_id: 'c1',
  target_entity_id: 'c2',
  relation_type: 'ally',
  label: '',
  affinity: null,
  note: '',
  static: true,
  event_ref: null,
  ...partial,
})

describe('computeWorldState — 决策④ 关系边激活', () => {
  it('static 边恒活跃', () => {
    const rel = mkRelation({ static: true })
    expect(computeWorldState([], {}, 0, [rel]).relation_states[0].active).toBe(true)
    expect(computeWorldState([], {}, 99999, [rel]).relation_states[0].active).toBe(true)
  })

  it('事件锚定边：锚事件回放前失活，回放后激活', () => {
    const anchor = mkEvent({ event_type: 'alliance', time_start: 300 })
    const rel = mkRelation({ static: false, event_ref: anchor.id })
    expect(computeWorldState([anchor], {}, 299, [rel]).relation_states[0].active).toBe(false)
    expect(computeWorldState([anchor], {}, 300, [rel]).relation_states[0].active).toBe(true)
  })

  it('锚事件不存在于回放集合时失活（引用悬空守卫）', () => {
    const rel = mkRelation({ static: false, event_ref: 'ev-missing' })
    expect(computeWorldState([], {}, 999, [rel]).relation_states[0].active).toBe(false)
  })

  it('static=false 且无锚事件按恒活跃处理（后端同构规则）', () => {
    const rel = mkRelation({ static: false, event_ref: null })
    expect(computeWorldState([], {}, 0, [rel]).relation_states[0].active).toBe(true)
  })

  it('不传 relations 时 relation_states 为空数组（向后兼容）', () => {
    expect(computeWorldState([], {}, 0).relation_states).toEqual([])
  })
})
