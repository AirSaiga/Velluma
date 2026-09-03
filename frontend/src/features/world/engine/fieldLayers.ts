/**
 * 实体档案字段级真相分层（2026-09-03）——前端共享判据（纯函数，供抽屉控件与
 * CanonSection 派生区共用；后端对应 services/world/field_layers.py，语义同构）。
 *
 * 存储契约：WorldEntity.field_layers = { [field_key]: { level, public_text?, reveal_chapter? } }
 * 缺键 = 公开（零存储）。字段内容本身即「里」，作者不两边维护；半露只需补「表」。
 */
import type { WorldEntity } from './types'

export type FieldLayerLevel = 'private' | 'partial'

export interface FieldLayerSpec {
  level: FieldLayerLevel
  /** 表（读者目前看到的版本）；仅 partial 有意义，可空（空=按秘密处理，后端同口径） */
  public_text?: string
  /** 第几章揭（可空） */
  reveal_chapter?: number | null
}

export type FieldLayers = Record<string, FieldLayerSpec>

/** 三态用户词（与 CanonSection/VIS_LABELS 口径一致；公开=无徽标缺省态） */
export const FIELD_LAYER_LABELS: Record<'public' | FieldLayerLevel, string> = {
  public: '公开',
  partial: '半露',
  private: '秘密',
}

/** chip 释义（title 悬浮） */
export const FIELD_LAYER_TITLES: Record<'public' | FieldLayerLevel, string> = {
  public: '公开：读者可以看到，AI 可直接写出（点击切为半露）',
  partial: '半露：读者只知「表」版本，其余 AI 死守（点击切为秘密）',
  private: '秘密：只有 AI 知道——可用于铺垫暗示，绝不直接写出（点击改回公开）',
}

function readLayers(entity: Pick<WorldEntity, 'field_layers'> | null | undefined): FieldLayers {
  const raw = entity?.field_layers
  return raw && typeof raw === 'object' ? (raw as FieldLayers) : {}
}

/** 单字段分层读取（防御：坏行/缺键 = 公开） */
export function getFieldLayer(
  entity: Pick<WorldEntity, 'field_layers'> | null | undefined,
  fieldKey: string,
): FieldLayerSpec | null {
  const spec = readLayers(entity)[fieldKey]
  if (!spec || typeof spec !== 'object') return null
  return spec.level === 'private' || spec.level === 'partial' ? spec : null
}

export function fieldLayerLevel(
  entity: Pick<WorldEntity, 'field_layers'> | null | undefined,
  fieldKey: string,
): 'public' | FieldLayerLevel {
  return getFieldLayer(entity, fieldKey)?.level ?? 'public'
}

/**
 * 点击循环 公开 → 半露 → 秘密 → 公开，返回合并后的全量 field_layers
 *（后端 update 是键级整体覆盖，调用方照 props 同款模式整体提交）。
 * 半露 ⇄ 秘密 切换保留已填的表/揭示章；只有回到公开才删键。
 */
export function cycleFieldLayer(
  entity: Pick<WorldEntity, 'field_layers'> | null | undefined,
  fieldKey: string,
): FieldLayers {
  const layers = { ...readLayers(entity) }
  const cur = getFieldLayer(entity, fieldKey)
  if (!cur) {
    layers[fieldKey] = { level: 'partial' }
  } else if (cur.level === 'partial') {
    layers[fieldKey] = { ...cur, level: 'private' }
  } else {
    delete layers[fieldKey]
  }
  return layers
}

/** 半露内联编辑（表 / 揭示章）合并；仅在已是半露时生效 */
export function mergeFieldLayer(
  entity: Pick<WorldEntity, 'field_layers'> | null | undefined,
  fieldKey: string,
  patch: Partial<FieldLayerSpec>,
): FieldLayers {
  const layers = { ...readLayers(entity) }
  const cur = getFieldLayer(entity, fieldKey)
  if (!cur) return layers
  layers[fieldKey] = { ...cur, ...patch }
  return layers
}

/** CanonSection 派生行（「来自角色档案」分组） */
export interface FieldLayerRow {
  entityId: string
  entityName: string
  fieldKey: string
  /** 字段用户词标签（来自 entitySchema） */
  fieldLabel: string
  level: FieldLayerLevel
  fullText: string
  publicText: string
  revealChapter: number | null
}

/**
 * 从实体全集派生分层字段行（与后端 iter_field_layers 同口径）：
 * 整人 private 实体跳过（全档案已在秘密通道）；缺内容/坏行不入列。
 */
export function deriveFieldLayerRows(
  entities: ReadonlyArray<Pick<WorldEntity, 'id' | 'name' | 'visibility' | 'props' | 'field_layers'>>,
  labelOf: (fieldKey: string, entityType?: string) => string,
): FieldLayerRow[] {
  const rows: FieldLayerRow[] = []
  for (const ent of entities || []) {
    if ((ent.visibility || 'public') === 'private') continue
    const layers = readLayers(ent)
    const props = ent.props && typeof ent.props === 'object' ? ent.props : {}
    for (const [fieldKey, spec] of Object.entries(layers)) {
      if (!spec || (spec.level !== 'private' && spec.level !== 'partial')) continue
      const fullText = String((props as Record<string, unknown>)[fieldKey] ?? '').trim()
      if (!fullText) continue
      const ch = Number(spec.reveal_chapter)
      rows.push({
        entityId: ent.id,
        entityName: ent.name || '',
        fieldKey,
        fieldLabel: labelOf(fieldKey, (ent as WorldEntity).entity_type),
        level: spec.level,
        fullText,
        publicText: String(spec.public_text ?? '').trim(),
        revealChapter: Number.isFinite(ch) && ch > 0 ? Math.trunc(ch) : null,
      })
    }
  }
  return rows
}
