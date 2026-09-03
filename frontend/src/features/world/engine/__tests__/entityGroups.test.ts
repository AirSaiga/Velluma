import { describe, expect, it } from 'vitest'
import { groupEntities, groupKeyOf, listGroupNames } from '../entityGroups'

const ent = (name: string, group_name?: string | null) => ({ name, group_name })

describe('groupKeyOf', () => {
  it('null / 缺省 / 空串 / 纯空白 一律未分组', () => {
    expect(groupKeyOf(ent('a', null))).toBeNull()
    expect(groupKeyOf(ent('a'))).toBeNull()
    expect(groupKeyOf(ent('a', ''))).toBeNull()
    expect(groupKeyOf(ent('a', '   '))).toBeNull()
  })

  it('trim 后保留中间空白', () => {
    expect(groupKeyOf(ent('a', '  机甲 '))).toBe('机甲')
    expect(groupKeyOf(ent('a', 'S 级机甲'))).toBe('S 级机甲')
  })
})

describe('groupEntities', () => {
  it('全部未分组 → 单个 null 组（调用方退化平铺，存量零变化）', () => {
    const groups = groupEntities([ent('红月'), ent('流光', null)])
    expect(groups).toEqual([{ name: null, entities: [ent('红月'), ent('流光', null)] }])
  })

  it('空列表 → 单个空 null 组', () => {
    expect(groupEntities([])).toEqual([{ name: null, entities: [] }])
  })

  it('未分组恒居首位，有名组按字典序', () => {
    const groups = groupEntities([
      ent('血噬', '机甲'),
      ent('杂件'),
      ent('玄铁剑', '武器'),
      ent('红月', '机甲'),
    ])
    expect(groups.map((g) => g.name)).toEqual([null, '机甲', '武器'])
    expect(groups[0].entities).toEqual([ent('杂件')])
    expect(groups[1].entities.map((e) => e.name)).toEqual(['血噬', '红月'])
  })

  it('组内保持传入顺序（不重排）', () => {
    const groups = groupEntities([ent('c', 'g'), ent('a', 'g'), ent('b', 'g')])
    expect(groups[0].entities.map((e) => e.name)).toEqual(['c', 'a', 'b'])
  })

  it('空白差异归并为同组（「 机甲 」与「机甲」同组）', () => {
    const groups = groupEntities([ent('a', ' 机甲 '), ent('b', '机甲')])
    expect(groups).toHaveLength(1)
    expect(groups[0].name).toBe('机甲')
  })
})

describe('listGroupNames', () => {
  it('去重 + 字典序 + 跳过未分组', () => {
    const names = listGroupNames([ent('a', '武器'), ent('b', '机甲'), ent('c'), ent('d', '武器'), ent('e', ' 机甲 ')])
    expect(names).toEqual(['机甲', '武器'])
  })
})
