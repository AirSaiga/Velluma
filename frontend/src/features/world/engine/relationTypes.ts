/**
 * 关系类型表（脑图透镜的边配色与标签，表驱动）。
 *
 * 扩展：追加一项即可（边色 / 选择器 / 图例共用此表）。
 */
export interface RelationTypeMeta {
  value: string
  label: string
  color: string
}

export const RELATION_TYPES: RelationTypeMeta[] = [
  { value: 'ally', label: '同盟', color: '#22c55e' },
  { value: 'enemy', label: '敌对', color: '#ef4444' },
  { value: 'kin', label: '亲属', color: '#f59e0b' },
  { value: 'master', label: '师徒', color: '#60a5fa' },
  { value: 'follower', label: '从属', color: '#8b5cf6' },
  { value: 'lover', label: '恋人', color: '#ec4899' },
  { value: 'rival', label: '宿敌', color: '#dc2626' },
  { value: 'custom', label: '自定义', color: '#94a3b8' },
]

export function relationTypeMeta(type: string): RelationTypeMeta {
  return RELATION_TYPES.find((t) => t.value === type) || RELATION_TYPES[RELATION_TYPES.length - 1]
}
