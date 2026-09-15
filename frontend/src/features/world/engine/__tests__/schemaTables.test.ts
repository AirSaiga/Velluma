import { describe, expect, it } from 'vitest'
import { ARCHIVE_FIELDS, archiveFields } from '../entitySchema'
import { EVENT_TEMPLATES } from '../eventTemplates'
import { RELATION_TYPES, relationTypeMeta } from '../relationTypes'

/**
 * 表驱动模块的表完整性对拍：加字段/加类型只改数组，但表本身不能烂——
 * key 重复会让「添加字段」菜单过滤失效，type 重复会让表单渲染错模板。
 */

describe('entitySchema 档案字段表', () => {
  it('三类实体都有字段', () => {
    for (const type of ['character', 'faction', 'asset'] as const) {
      expect(ARCHIVE_FIELDS[type].length).toBeGreaterThan(0)
    }
  })

  it('同类实体字段 key 不重复', () => {
    for (const fields of Object.values(ARCHIVE_FIELDS)) {
      const keys = fields.map((f) => f.key)
      expect(new Set(keys).size).toBe(keys.length)
    }
  })

  it('字段都有 label 与非空 hint（表单渲染契约）', () => {
    for (const fields of Object.values(ARCHIVE_FIELDS)) {
      for (const f of fields) {
        expect(f.label.trim()).toBeTruthy()
        expect(f.hint.trim()).toBeTruthy()
      }
    }
  })

  it('背景/描述类字段标记 multiline', () => {
    const character = ARCHIVE_FIELDS.character
    expect(character.find((f) => f.key === 'background')?.multiline).toBe(true)
    expect(ARCHIVE_FIELDS.asset.find((f) => f.key === 'description')?.multiline).toBe(true)
    expect(character.find((f) => f.key === 'appearance')?.multiline).toBeFalsy()
  })

  it('未知类型 → 空数组（动态渲染不炸）', () => {
    expect(archiveFields('unknown' as never)).toEqual([])
  })
})

describe('eventTemplates 事件模板表', () => {
  it('type 不重复（表单按 type 选模板）', () => {
    const types = EVENT_TEMPLATES.map((t) => t.type)
    expect(new Set(types).size).toBe(types.length)
  })

  it('模板四要素齐全', () => {
    for (const t of EVENT_TEMPLATES) {
      expect(t.label.trim()).toBeTruthy()
      expect(t.description.trim()).toBeTruthy()
      expect(Array.isArray(t.defaultTags)).toBe(true)
      expect(Array.isArray(t.requiredPayloadFields)).toBe(true)
    }
  })

  it('结构化组必填字段契约（表单校验依赖）', () => {
    const byType = new Map(EVENT_TEMPLATES.map((t) => [t.type, t]))
    expect(byType.get('birth')!.requiredPayloadFields).toContain('character_id')
    expect(byType.get('move')!.requiredPayloadFields).toEqual(
      expect.arrayContaining(['character_ids', 'from_location_id', 'to_location_id', 'path']),
    )
    expect(byType.get('death')!.requiredPayloadFields).toContain('character_id')
  })

  it('共用组不强制 payload（M1 只填 type+note）', () => {
    const byType = new Map(EVENT_TEMPLATES.map((t) => [t.type, t]))
    expect(byType.get('battle')!.requiredPayloadFields).toEqual([])
    expect(byType.get('custom')!.requiredPayloadFields).toEqual([])
  })
})

describe('relationTypes 关系类型表', () => {
  it('value 不重复（选择器/图例共用）', () => {
    const values = RELATION_TYPES.map((t) => t.value)
    expect(new Set(values).size).toBe(values.length)
  })

  it('每项都有合法 hex 边色', () => {
    for (const t of RELATION_TYPES) {
      expect(t.color).toMatch(/^#[0-9a-f]{6}$/i)
    }
  })

  it('已知类型查得到', () => {
    expect(relationTypeMeta('ally').label).toBe('同盟')
  })

  it('未知类型兜底 custom（末项契约）', () => {
    expect(relationTypeMeta('不存在的关系').value).toBe('custom')
  })
})
