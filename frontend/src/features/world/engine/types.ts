/**
 * World 设定层核心类型（与后端 schemas/world.py 对应）。
 *
 * 设计原则（照搬世界绘卷）：
 * - 时变状态（位置/疆域/生死/归属）一律不存表，由 computeWorldState 推演
 * - 实体表只存"固有属性"（身份证），事件表是唯一事实源
 * - Timestamp = 连续日计数，与架空历法解耦（换历法只改 timeFormat.ts）
 */

/** 数值时间戳：以创世为元年的连续日计数（与历法解耦） */
export type Timestamp = number

/** 地图内部坐标 [x, y]（CRS.Simple 浮点，非像素非经纬度） */
export type Point = [number, number]

export type EntityType = 'character' | 'faction' | 'asset'
export type LocationKind = 'point' | 'region' | 'route'

/** 地图绘制模式：territory=疆域圈绘（≥3 顶点）/ move-path=move 途经点（≥0 个）/ null=未在画 */
export type DrawMode = 'territory' | 'move-path' | null

export type EventType =
  | 'birth'
  | 'death'
  | 'move'
  | 'battle'
  | 'territory_change'
  | 'found'
  | 'destroy'
  | 'alliance'
  | 'war_declare'
  | 'coronation'
  | 'custom'

export interface WorldEntity {
  id: string
  book_id: string
  entity_type: EntityType
  name: string
  /** M2 档案扩展（旧数据可能缺省，消费方用 ?? 兜底） */
  aliases?: string[]
  importance?: number
  visibility?: string // public=读者已知 / private=作者已知
  /** 画布锚位（单一画布）：无推演位置时的作者摆位 */
  canvas_x?: number | null
  canvas_y?: number | null
  intro: string
  tags: string[]
  props: Record<string, unknown>
}

/**
 * 伏笔（PlotLedger 的世界页投影）。
 * 弧线带只关心时间锚与内容；M5 侧栏账本/详情抽屉另需章锚与 meta（证据/来源徽标）。
 */
export interface Foreshadow {
  id: string
  ledger_key: string
  entry_type: string
  content: string
  status: 'open' | 'closed' | 'dropped'
  world_time_planted: number | null
  world_time_resolved: number | null
  /** 埋设章号（章节锚，与 world_time 双轨并存） */
  created_at_chapter?: number | null
  hook_id?: string | null
  /** 原样携带：meta.source（AI 登记徽标）/ meta.planted_in_text（埋设证据） */
  meta?: Record<string, any> | null
}

export interface WorldLocation {
  id: string
  book_id: string
  name: string
  kind: LocationKind
  parent_id: string | null
  coord_x: number | null
  coord_y: number | null
  /** region: polygon 点[]；route: polyline 点[] */
  geometry: Record<string, unknown>
  intro: string
  tags: string[]
}

export interface WorldEvent {
  id: string
  book_id: string
  sequence_num: number
  event_type: EventType
  time_start: Timestamp
  time_end: Timestamp
  location_id: string | null
  participant_ids: string[]
  faction_ids: string[]
  /** 类型相关：birth.parent_ids / move.path / territory_change.polygon 等 */
  payload: Record<string, unknown>
  /** 因果链事件 id[] */
  causes: string[]
  /** 关联章节 id（只读，按章过滤用） */
  chapter_ref: string | null
  tags: string[]
  note: string
}

// ===== WorldState（computeWorldState 派生，不持久化）=====

export interface CharacterState {
  entity_id: string
  location_id: string | null
  position: Point | null
  alive: boolean
  label: string
  last_event_id: string | null
}

export interface TerritoryState {
  faction_id: string
  polygon: Point[]
  last_event_id: string | null
}

export interface RelationState {
  relation_id: string
  source_entity_id: string
  target_entity_id: string
  relation_type: string
  label: string
  active: boolean
}

export interface LocationState {
  location_id: string
  exists: boolean
  last_event_id: string | null
}

export interface WorldState {
  at_time: Timestamp
  character_states: CharacterState[]
  territory_states: TerritoryState[]
  location_states: LocationState[]
  relation_states: RelationState[]
}

/** 章节叙事时间锚（世界页轻量投影，仅取时间轴所需字段） */
export interface ChapterAnchor {
  id: string
  chapter_number: number
  chapter_name: string | null
  narrative_time: number | null
}

/** 实体关系边（脑图透镜的边）。static=false 时由 event_ref 锚事件回放推演激活 */
export interface WorldRelation {
  id: string
  book_id: string
  source_entity_id: string
  target_entity_id: string
  relation_type: string
  label: string
  affinity: number | null
  note: string
  static: boolean
  event_ref: string | null
}

// ===== 底图（图片拼贴 + 手绘笔迹）=====

export interface WorldMapLayer {
  id: string
  book_id: string
  /** /world-images/{book_id}/{uuid}{ext} */
  image_url: string
  /** 中心点（内部坐标） */
  x: number
  y: number
  /** 尺寸（内部坐标单位） */
  w: number
  h: number
  /** 层序（小者在下） */
  z_index: number
  opacity: number
}

export type MapLayerPatch = Partial<
  Pick<WorldMapLayer, 'x' | 'y' | 'w' | 'h' | 'z_index' | 'opacity'>
>

export interface WorldMapStroke {
  id: string
  book_id: string
  color: string
  width: number
  /** [[x, y], ...] 内部坐标 */
  points: Point[]
}
