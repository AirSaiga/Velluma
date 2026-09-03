/**
 * 字段级真相分层（2026-09-03）纯函数对拍。
 *
 * 锁定：三态循环（半露⇄秘密保留表/揭示章，回公开才删键）、merge 守卫、
 * 派生行口径（整人私有跳过/空内容不入列/坏数据防御）——与后端
 * services/world/field_layers.py 语义同构。
 */
import { describe, expect, it } from 'vitest'
import {
  cycleFieldLayer,
  deriveFieldLayerRows,
  fieldLayerLevel,
  getFieldLayer,
  mergeFieldLayer,
} from '../fieldLayers'

const LABELS: Record<string, string> = { background: '背景', skills: '能力' }
const labelOf = (k: string) => LABELS[k] || k

describe('fieldLayerLevel / getFieldLayer 防御', () => {
  it('缺键/坏行/非法 level 一律按公开', () => {
    expect(fieldLayerLevel(undefined, 'background')).toBe('public')
    expect(fieldLayerLevel({ field_layers: undefined }, 'background')).toBe('public')
    expect(fieldLayerLevel({ field_layers: { background: null as any } }, 'background')).toBe('public')
    expect(fieldLayerLevel({ field_layers: { background: { level: 'nonsense' } } }, 'background')).toBe('public')
    expect(getFieldLayer({ field_layers: { background: { level: 'private' } } }, 'background')?.level).toBe('private')
  })
})

describe('cycleFieldLayer 三态循环', () => {
  it('公开 → 半露 → 秘密 → 公开（删键）', () => {
    const e0 = { field_layers: undefined as any }
    const l1 = cycleFieldLayer(e0, 'background')
    expect(l1.background).toEqual({ level: 'partial' })
    const l2 = cycleFieldLayer({ field_layers: l1 }, 'background')
    expect(l2.background.level).toBe('private')
    const l3 = cycleFieldLayer({ field_layers: l2 }, 'background')
    expect('background' in l3).toBe(false)
  })

  it('半露 ⇄ 秘密切换保留已填的表与揭示章', () => {
    const e = {
      field_layers: {
        background: { level: 'partial' as const, public_text: '普通电工', reveal_chapter: 8 },
      },
    }
    const l = cycleFieldLayer(e, 'background')
    expect(l.background).toEqual({ level: 'private', public_text: '普通电工', reveal_chapter: 8 })
    const l2 = cycleFieldLayer({ field_layers: l }, 'background')
    expect('background' in l2).toBe(false) // 回公开才清数据
  })

  it('不动其他字段的分层', () => {
    const e = { field_layers: { skills: { level: 'private' as const } } }
    const l = cycleFieldLayer(e, 'background')
    expect(l.skills).toEqual({ level: 'private' })
    expect(l.background).toEqual({ level: 'partial' })
  })
})

describe('mergeFieldLayer', () => {
  it('仅对已分层字段生效；合并 public_text / reveal_chapter', () => {
    const e = { field_layers: { background: { level: 'partial' as const } } }
    const l = mergeFieldLayer(e, 'background', { public_text: '普通电工', reveal_chapter: 8 })
    expect(l.background).toEqual({ level: 'partial', public_text: '普通电工', reveal_chapter: 8 })
    // 未分层字段 merge 是空操作（不制造意外条目）
    const l2 = mergeFieldLayer(e, 'skills', { public_text: 'x' })
    expect('skills' in l2).toBe(false)
  })
})

describe('deriveFieldLayerRows（CanonSection 派生区口径）', () => {
  const ents = [
    {
      id: 'e1',
      name: '林尘',
      visibility: 'public',
      props: { background: '表面是电工，实际是卧底', skills: '会修老式电台' },
      field_layers: {
        background: { level: 'partial', public_text: '普通电工', reveal_chapter: 8 },
        skills: { level: 'private' },
      },
    },
    {
      id: 'e2',
      name: '黑手',
      visibility: 'private', // 整人私有 → 整实体跳过
      props: { background: '秘密' },
      field_layers: { background: { level: 'private' } },
    },
    {
      id: 'e3',
      name: '空字段',
      visibility: 'public',
      props: {},
      field_layers: { background: { level: 'private' } }, // 无内容 → 不入列
    },
  ]

  it('派生行：公开实体的分层字段入列，整人私有/空内容跳过', () => {
    const rows = deriveFieldLayerRows(ents as any, labelOf)
    expect(rows.map((r) => `${r.entityName}·${r.fieldLabel}`)).toEqual(['林尘·背景', '林尘·能力'])
    const bg = rows[0]
    expect(bg.level).toBe('partial')
    expect(bg.publicText).toBe('普通电工')
    expect(bg.revealChapter).toBe(8)
    expect(rows[1].revealChapter).toBeNull()
  })

  it('空集/坏数据安全', () => {
    expect(deriveFieldLayerRows([], labelOf)).toEqual([])
    expect(deriveFieldLayerRows([{ id: 'x', name: 'x' } as any], labelOf)).toEqual([])
  })
})
