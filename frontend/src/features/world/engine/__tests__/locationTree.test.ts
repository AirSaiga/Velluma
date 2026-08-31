/**
 * 地点树（内部构造）对拍单测——与后端 test_location_tree.py 同构口径。
 */
import { describe, expect, it } from 'vitest'
import type { WorldLocation } from '../types'
import {
  childrenIndex,
  collectSubtree,
  locationPath,
  locationsById,
  topLevelLocations,
} from '../locationTree'

function loc(id: string, name: string, parent_id: string | null = null): WorldLocation {
  return {
    id,
    book_id: 'b1',
    name,
    kind: 'point',
    parent_id,
    coord_x: null,
    coord_y: null,
    geometry: {},
    intro: '',
    tags: [],
  }
}

/** 统一书架：基地 → B2层 → 拘留室；另一基地也有同名「拘留室」 */
function shelf(): WorldLocation[] {
  return [
    loc('base', '统合局基地'),
    loc('b2', 'B2 拘留层', 'base'),
    loc('cell', '拘留室', 'b2'),
    loc('rebel', '反抗军营地'),
    loc('cell2', '拘留室', 'rebel'),
  ]
}

describe('childrenIndex / topLevel / byId', () => {
  it('父子分组与顶层过滤', () => {
    const kids = childrenIndex(shelf())
    expect(kids.get('base')!.map((l) => l.id)).toEqual(['b2'])
    expect(kids.get('b2')!.map((l) => l.id)).toEqual(['cell'])
    expect(topLevelLocations(shelf()).map((l) => l.id)).toEqual(['base', 'rebel'])
    expect(locationsById(shelf()).size).toBe(5)
  })
})

describe('collectSubtree', () => {
  it('三层子树父前子后', () => {
    expect(collectSubtree(shelf(), 'base').map((l) => l.id)).toEqual(['base', 'b2', 'cell'])
  })

  it('删反抗军营地不误收统合局的拘留室', () => {
    const ids = collectSubtree(shelf(), 'rebel').map((l) => l.id)
    expect(ids).toEqual(['rebel', 'cell2'])
  })

  it('根缺失返回空', () => {
    expect(collectSubtree(shelf(), 'nope')).toEqual([])
    expect(collectSubtree([], 'base')).toEqual([])
  })
})

describe('locationPath', () => {
  it('顶层裸名 / 子 / 孙全路径', () => {
    const byId = locationsById(shelf())
    const get = (id: string) => byId.get(id)!
    expect(locationPath(get('base'), byId)).toBe('统合局基地')
    expect(locationPath(get('b2'), byId)).toBe('统合局基地·B2 拘留层')
    expect(locationPath(get('cell'), byId)).toBe('统合局基地·B2 拘留层·拘留室')
  })

  it('环防护截断不死循环', () => {
    const a = loc('a', '甲', 'b')
    const b = loc('b', '乙', 'a')
    const byId = locationsById([a, b])
    expect(locationPath(a, byId)).toBe('乙·甲')
  })
})
