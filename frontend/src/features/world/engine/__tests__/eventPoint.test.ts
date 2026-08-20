/**
 * 事件 → 地图坐标协议单测（eventPoint.ts）。
 * 锁定优先级：move/territory 专属几何 > payload.point（点选结构化契约）
 * > note @x,y（旧契约兼容读取）> location_id > null。
 */
import { describe, expect, it } from 'vitest'
import { eventPoint, parsePointFromNote, stripPointFromNote } from '../eventPoint'
import type { WorldEvent, WorldLocation } from '../types'

function ev(over: Partial<WorldEvent>): WorldEvent {
  return {
    id: 'e1',
    book_id: 'b1',
    sequence_num: 1,
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
    ...over,
  }
}

const LOCS: Record<string, WorldLocation> = {
  l1: {
    id: 'l1',
    book_id: 'b1',
    name: '北岸要塞',
    kind: 'point',
    parent_id: null,
    coord_x: 10,
    coord_y: 20,
    geometry: {},
    intro: '',
    tags: [],
  },
}

describe('eventPoint 优先级', () => {
  it('move：path 起点优先，无 path 回落 from_location 坐标', () => {
    expect(
      eventPoint(ev({ event_type: 'move', payload: { path: [[1, 2], [3, 4]] } }), LOCS),
    ).toEqual([1, 2])
    expect(
      eventPoint(
        ev({ event_type: 'move', payload: { path: [], from_location_id: 'l1' } }),
        LOCS,
      ),
    ).toEqual([10, 20])
    expect(eventPoint(ev({ event_type: 'move', payload: {} }), LOCS)).toBeNull()
  })

  it('territory_change：polygon 质心', () => {
    expect(
      eventPoint(
        ev({ event_type: 'territory_change', payload: { polygon: [[0, 0], [10, 0], [10, 10], [0, 10]] } }),
        LOCS,
      ),
    ).toEqual([5, 5])
  })

  it('payload.point 优先于 note @x,y 与 location_id', () => {
    expect(
      eventPoint(
        ev({ payload: { point: [500, 300] }, note: '旧事 @1,1', location_id: 'l1' }),
        LOCS,
      ),
    ).toEqual([500, 300])
  })

  it('旧契约：note @x,y 兼容读取，优先于 location_id', () => {
    expect(eventPoint(ev({ note: '遭伏 @123.5,-45 惨败', location_id: 'l1' }), LOCS)).toEqual([
      123.5, -45,
    ])
  })

  it('location_id 坐标兜底；全无线索返回 null', () => {
    expect(eventPoint(ev({ location_id: 'l1' }), LOCS)).toEqual([10, 20])
    expect(eventPoint(ev({}), LOCS)).toBeNull()
    expect(eventPoint(ev({ location_id: 'missing' }), LOCS)).toBeNull()
  })
})

describe('note 标记工具（旧契约）', () => {
  it('parsePointFromNote：正负数/小数/逗号空格容忍，无标记返回 null', () => {
    expect(parsePointFromNote('@500,300')).toEqual([500, 300])
    expect(parsePointFromNote('x @-12.5, 7.25 y')).toEqual([-12.5, 7.25])
    expect(parsePointFromNote('没有标记')).toBeNull()
    expect(parsePointFromNote('')).toBeNull()
  })

  it('stripPointFromNote：剥离标记并收紧首尾空白（不合并内层空格）', () => {
    expect(stripPointFromNote('遭伏 @123,-45 惨败')).toBe('遭伏  惨败')
    expect(stripPointFromNote('@1,2')).toBe('')
    expect(stripPointFromNote('无标记')).toBe('无标记')
  })
})
