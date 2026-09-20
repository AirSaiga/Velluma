/**
 * 实体档案字段 schema（表驱动，docs/reports/world-unified-settings.md §2.1）。
 *
 * 档案字段存 WorldEntity.props（JSONB），字段集会随反馈演化——加字段只改这里的数组，
 * 抽屉据此动态渲染行 +「添加字段」菜单过滤已加过的。设计原则：字段按需出现（生长式），
 * 绝不做一次性大表单。
 */
import type { EntityType } from './types'

export interface ArchiveField {
  key: string
  label: string
  hint: string
  /** 多行文本（背景/经历）用 textarea，其余单行 */
  multiline?: boolean
}

export const ARCHIVE_FIELDS: Record<EntityType, ArchiveField[]> = {
  character: [
    { key: 'appearance', label: '外貌', hint: '一句话，写到再补' },
    { key: 'personality', label: '性格', hint: '核心特质 2-3 个' },
    { key: 'background', label: '背景', hint: '出身 / 经历', multiline: true },
    { key: 'goal', label: '目标', hint: '他想要什么' },
    { key: 'motive', label: '动机', hint: '为什么想要' },
    { key: 'speech_style', label: '说话风格', hint: '语气 / 口头禅 / 称谓习惯' },
    { key: 'habits', label: '习惯', hint: '小动作 / 癖好' },
    { key: 'skills', label: '能力', hint: '武功 / 法术 / 技术' },
  ],
  faction: [
    { key: 'ideology', label: '理念', hint: '信条 / 目标' },
    { key: 'structure', label: '组织结构', hint: '层级 / 制度' },
    { key: 'territory_note', label: '领地说明', hint: '疆域的补充描述（几何在地图圈绘）' },
  ],
  asset: [
    { key: 'description', label: '描述', hint: '外观 / 功能', multiline: true },
    { key: 'origin', label: '来历', hint: '出处 / 历史' },
  ],
}

export function archiveFields(type: EntityType): ArchiveField[] {
  return ARCHIVE_FIELDS[type] || []
}
