import type { EventType } from './types'

/**
 * 事件模板（表驱动，照搬世界绘卷）。
 *
 * 分两组：
 * - 结构化组（birth/move/death）：requiredPayloadFields 列必填 payload，表单据此动态渲染 + 校验
 * - 共用组（battle/territory_change/found/destroy/custom）：M1 只填 type+note，结构化字段后续补
 *
 * 扩展不改主框架：加 alliance/war_declare 等，只需往 EVENT_TEMPLATES 追加一项。
 */
export interface EventTemplate {
  type: EventType
  label: string
  description: string
  defaultNote: string
  defaultTags: string[]
  /** 必填 payload 字段（表单据此动态渲染 + 提交校验） */
  requiredPayloadFields: string[]
}

export const EVENT_TEMPLATES: EventTemplate[] = [
  {
    type: 'birth',
    label: '出生',
    description: '角色出生（生死的唯一来源）',
    defaultNote: '',
    defaultTags: [],
    requiredPayloadFields: ['character_id', 'location_id'],
  },
  {
    type: 'move',
    label: '移动',
    description: '角色从 A 地到 B 地（沿 path 弧长插值在途位置）',
    defaultNote: '',
    defaultTags: [],
    requiredPayloadFields: ['character_ids', 'from_location_id', 'to_location_id', 'path'],
  },
  {
    type: 'death',
    label: '死亡',
    description: '角色死亡',
    defaultNote: '',
    defaultTags: [],
    requiredPayloadFields: ['character_id'],
  },
  {
    type: 'battle',
    label: '战役',
    description: '战斗事件',
    defaultNote: '',
    defaultTags: ['战役'],
    requiredPayloadFields: [],
  },
  {
    type: 'territory_change',
    label: '疆域变更',
    description: '势力疆域变化（payload 含完整 polygon）',
    defaultNote: '',
    defaultTags: [],
    requiredPayloadFields: ['faction_id', 'polygon', 'action'],
  },
  {
    type: 'found',
    label: '建立',
    description: '建立地点/势力',
    defaultNote: '',
    defaultTags: [],
    requiredPayloadFields: ['target_id'],
  },
  {
    type: 'destroy',
    label: '毁灭',
    description: '毁灭地点/势力',
    defaultNote: '',
    defaultTags: [],
    requiredPayloadFields: ['target_id'],
  },
  {
    type: 'alliance',
    label: '结盟',
    description: '两个势力结盟',
    defaultNote: '',
    defaultTags: [],
    requiredPayloadFields: [],
  },
  {
    type: 'war_declare',
    label: '宣战',
    description: '两个势力宣战',
    defaultNote: '',
    defaultTags: [],
    requiredPayloadFields: [],
  },
  {
    type: 'coronation',
    label: '即位',
    description: '角色身份变更/即位',
    defaultNote: '',
    defaultTags: [],
    requiredPayloadFields: [],
  },
  {
    type: 'custom',
    label: '自定义',
    description: '其他事件（payload 自由结构）',
    defaultNote: '',
    defaultTags: [],
    requiredPayloadFields: [],
  },
]

/** 事件类型 → 显示色（地图 marker / 模板选择器小圆点用） */
export const EVENT_TYPE_COLOR: Record<string, string> = {
  birth: '#34d399',
  death: '#6b7280',
  move: '#60a5fa',
  battle: '#ef4444',
  territory_change: '#a855f7',
  found: '#10b981',
  destroy: '#9ca3af',
  alliance: '#22c55e',
  war_declare: '#dc2626',
  coronation: '#f59e0b',
  custom: '#94a3b8',
}

export function getTemplate(type: EventType): EventTemplate | undefined {
  return EVENT_TEMPLATES.find((t) => t.type === type)
}
