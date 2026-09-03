/**
 * 实体单分组（2026-09-03，资产抽屉分组）。
 *
 * group_name 是组织元数据（不进 prompt 档案装配），一个实体至多归一组。
 * 本模块是分组渲染与分组建议的唯一判据——纯函数，对拍 __tests__/entityGroups.test.ts。
 */
import type { WorldEntity } from './types'

export interface EntityGroup<T> {
  /** null = 未分组 */
  name: string | null
  entities: T[]
}

type Groupable = Pick<WorldEntity, 'group_name'>

/** 归一分组键：trim 后为空（含 null/缺省）按未分组 */
export function groupKeyOf(ent: Groupable): string | null {
  const g = (ent.group_name ?? '').trim()
  return g || null
}

/**
 * 把已按展示序排好的实体聚成分组段：
 * - 组内顺序原样保留（不重排——重要度序由调用方决定）
 * - 未分组恒居首位：连续创建的新资产落在未分组，不能被折叠组淹没
 * - 有名组按 localeCompare(zh) 字典序
 * - 全部未分组 → 返回单个 name=null 组（调用方据此退化为平铺渲染，存量书零视觉变化）
 */
export function groupEntities<T extends Groupable>(entities: readonly T[]): EntityGroup<T>[] {
  const buckets = new Map<string, T[]>()
  const ungrouped: T[] = []
  for (const ent of entities) {
    const key = groupKeyOf(ent)
    if (key === null) {
      ungrouped.push(ent)
    } else {
      const list = buckets.get(key)
      if (list) list.push(ent)
      else buckets.set(key, [ent])
    }
  }
  const groups: EntityGroup<T>[] = []
  if (ungrouped.length || buckets.size === 0) groups.push({ name: null, entities: ungrouped })
  for (const name of [...buckets.keys()].sort((a, b) => a.localeCompare(b, 'zh'))) {
    groups.push({ name, entities: buckets.get(name)! })
  }
  return groups
}

/** 既有分组名清单（详情抽屉分组输入的候选建议），去重 + 字典序 */
export function listGroupNames(entities: readonly Groupable[]): string[] {
  const names = new Set<string>()
  for (const ent of entities) {
    const key = groupKeyOf(ent)
    if (key !== null) names.add(key)
  }
  return [...names].sort((a, b) => a.localeCompare(b, 'zh'))
}
