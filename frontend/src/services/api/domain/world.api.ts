/**
 * World 设定层 API 客户端（独立于 canonApi）。
 * 端点 /books/{bookId}/world/...，经 transport 自动加 /api 前缀。
 *
 * 类型复用 engine/types（前后端同构）。
 */
import { requestJson } from '../transport'
import type {
  WorldEntity,
  WorldEvent,
  WorldLocation,
  WorldState,
  WorldMapLayer,
  WorldMapStroke,
  WorldRelation,
  ChapterAnchor,
  Point,
} from '../../../features/world/engine/types'

export interface WorldLocationCreate {
  id?: string // 幂等重建（undo/redo 恢复路径）
  name: string
  kind?: string
  coord_x?: number | null
  coord_y?: number | null
  intro?: string
  tags?: string[]
}

export interface WorldEntityCreate {
  id?: string // 幂等重建（undo/redo 恢复路径）
  entity_type: 'character' | 'faction' | 'asset'
  name: string
  intro?: string
  tags?: string[]
  props?: Record<string, unknown>
}

export interface WorldRelationCreate {
  id?: string // 幂等重建（undo/redo 恢复路径）
  source_entity_id: string
  target_entity_id: string
  relation_type?: string
  label?: string
  affinity?: number | null
  note?: string
  static?: boolean
  event_ref?: string | null
}

export interface WorldEventCreate {
  id?: string // 幂等重建（undo/redo 恢复路径）
  event_type: string
  time_start: number
  time_end: number
  location_id?: string | null
  participant_ids?: string[]
  faction_ids?: string[]
  payload?: Record<string, unknown>
  causes?: string[]
  chapter_ref?: string | null
  tags?: string[]
  note?: string
}

const JSON_HEADERS = { 'Content-Type': 'application/json' }

export const worldApi = {
  // ===== 地点 =====
  listLocations: (bookId: string) =>
    requestJson<WorldLocation[]>(`/books/${bookId}/world/locations`),

  createLocation: (bookId: string, data: WorldLocationCreate) =>
    requestJson<WorldLocation>(`/books/${bookId}/world/locations`, {
      method: 'POST',
      headers: JSON_HEADERS,
      body: JSON.stringify({ ...data, book_id: bookId }),
    }),

  updateLocation: (bookId: string, locationId: string, data: Partial<WorldLocationCreate>) =>
    requestJson<WorldLocation>(`/books/${bookId}/world/locations/${locationId}`, {
      method: 'PUT',
      headers: JSON_HEADERS,
      body: JSON.stringify(data),
    }),

  deleteLocation: (bookId: string, locationId: string) =>
    requestJson<{ deleted: boolean }>(`/books/${bookId}/world/locations/${locationId}`, {
      method: 'DELETE',
    }),

  // ===== 事件 =====
  listEvents: (bookId: string) => requestJson<WorldEvent[]>(`/books/${bookId}/world/events`),

  createEvent: (bookId: string, data: WorldEventCreate) =>
    requestJson<WorldEvent>(`/books/${bookId}/world/events`, {
      method: 'POST',
      headers: JSON_HEADERS,
      body: JSON.stringify({ ...data, book_id: bookId }),
    }),

  updateEvent: (bookId: string, eventId: string, data: Partial<WorldEventCreate>) =>
    requestJson<WorldEvent>(`/books/${bookId}/world/events/${eventId}`, {
      method: 'PUT',
      headers: JSON_HEADERS,
      body: JSON.stringify(data),
    }),

  deleteEvent: (bookId: string, eventId: string) =>
    requestJson<{ deleted: boolean }>(`/books/${bookId}/world/events/${eventId}`, {
      method: 'DELETE',
    }),

  // ===== 实体 =====
  listEntities: (bookId: string, entityType?: 'character' | 'faction' | 'asset') => {
    const qs = entityType ? `?entity_type=${entityType}` : ''
    return requestJson<WorldEntity[]>(`/books/${bookId}/world/entities${qs}`)
  },

  createEntity: (bookId: string, data: WorldEntityCreate) =>
    requestJson<WorldEntity>(`/books/${bookId}/world/entities`, {
      method: 'POST',
      headers: JSON_HEADERS,
      body: JSON.stringify({ ...data, book_id: bookId }),
    }),

  updateEntity: (bookId: string, entityId: string, data: Partial<WorldEntityCreate>) =>
    requestJson<WorldEntity>(`/books/${bookId}/world/entities/${entityId}`, {
      method: 'PUT',
      headers: JSON_HEADERS,
      body: JSON.stringify(data),
    }),

  deleteEntity: (bookId: string, entityId: string) =>
    requestJson<{ deleted: boolean }>(`/books/${bookId}/world/entities/${entityId}`, {
      method: 'DELETE',
    }),

  // ===== 关系（脑图透镜的边）=====
  listRelations: (bookId: string) =>
    requestJson<WorldRelation[]>(`/books/${bookId}/world/relations`),

  createRelation: (bookId: string, data: WorldRelationCreate) =>
    requestJson<WorldRelation>(`/books/${bookId}/world/relations`, {
      method: 'POST',
      headers: JSON_HEADERS,
      body: JSON.stringify({ ...data, book_id: bookId }),
    }),

  updateRelation: (
    bookId: string,
    relationId: string,
    data: Partial<Omit<WorldRelationCreate, 'id' | 'source_entity_id' | 'target_entity_id'>>,
  ) =>
    requestJson<WorldRelation>(`/books/${bookId}/world/relations/${relationId}`, {
      method: 'PUT',
      headers: JSON_HEADERS,
      body: JSON.stringify(data),
    }),

  deleteRelation: (bookId: string, relationId: string) =>
    requestJson<{ deleted: boolean }>(`/books/${bookId}/world/relations/${relationId}`, {
      method: 'DELETE',
    }),

  // ===== 章节叙事时间锚（章节轴↔世界轴的桥）=====
  /** 只取世界页所需字段的轻量投影（后端返回完整 ChapterResponse，多余字段忽略） */
  listChapterAnchors: async (bookId: string): Promise<ChapterAnchor[]> => {
    const raw = await requestJson<
      Array<{
        id: string
        chapter_number: number
        chapter_name?: string | null
        narrative_time?: number | null
      }>
    >(`/books/${bookId}/chapters`)
    return raw.map((c) => ({
      id: c.id,
      chapter_number: c.chapter_number,
      chapter_name: c.chapter_name ?? null,
      narrative_time: c.narrative_time ?? null,
    }))
  },

  setChapterAnchor: (chapterId: string, narrativeTime: number) =>
    requestJson<unknown>(`/chapters/${chapterId}`, {
      method: 'PUT',
      headers: JSON_HEADERS,
      body: JSON.stringify({ narrative_time: narrativeTime }),
    }),

  // ===== 旧设定中心一次性迁移（幂等）=====
  migrateLegacy: (bookId: string) =>
    requestJson<{
      characters: { migrated: number; skipped_existing: number }
      assets: { migrated: number; skipped_existing: number }
      locations: { migrated: number; skipped_existing: number }
      relations: { migrated: number; skipped_missing_endpoint: number; skipped_existing: number }
      foreshadows_anchored: number
      dynamic_states_skipped: number
    }>(`/books/${bookId}/world/migrate-legacy`, { method: 'POST' }),

  // ===== 推演 =====
  getState: (bookId: string, t: number) =>
    requestJson<WorldState>(`/books/${bookId}/world/state?t=${t}`),

  // ===== 底图：图片拼贴层 =====
  listMapLayers: (bookId: string) =>
    requestJson<WorldMapLayer[]>(`/books/${bookId}/world/map/layers`),

  createMapLayer: (
    bookId: string,
    data: { image_url: string; x: number; y: number; w: number; h: number },
  ) =>
    requestJson<WorldMapLayer>(`/books/${bookId}/world/map/layers`, {
      method: 'POST',
      headers: JSON_HEADERS,
      body: JSON.stringify({ ...data, book_id: bookId }),
    }),

  updateMapLayer: (
    bookId: string,
    layerId: string,
    patch: Partial<Pick<WorldMapLayer, 'x' | 'y' | 'w' | 'h' | 'z_index' | 'opacity'>>,
  ) =>
    requestJson<WorldMapLayer>(`/books/${bookId}/world/map/layers/${layerId}`, {
      method: 'PUT',
      headers: JSON_HEADERS,
      body: JSON.stringify(patch),
    }),

  deleteMapLayer: (bookId: string, layerId: string) =>
    requestJson<{ deleted: boolean }>(`/books/${bookId}/world/map/layers/${layerId}`, {
      method: 'DELETE',
    }),

  // ===== 底图：手绘笔迹 =====
  listMapStrokes: (bookId: string) =>
    requestJson<WorldMapStroke[]>(`/books/${bookId}/world/map/strokes`),

  createMapStroke: (
    bookId: string,
    data: { color: string; width: number; points: Point[] },
  ) =>
    requestJson<WorldMapStroke>(`/books/${bookId}/world/map/strokes`, {
      method: 'POST',
      headers: JSON_HEADERS,
      body: JSON.stringify({ ...data, book_id: bookId }),
    }),

  deleteMapStroke: (bookId: string, strokeId: string) =>
    requestJson<{ deleted: boolean }>(`/books/${bookId}/world/map/strokes/${strokeId}`, {
      method: 'DELETE',
    }),

  // ===== 底图：图片上传（multipart，不设 Content-Type 让浏览器带 boundary）=====
  uploadMapImage: (bookId: string, file: File) => {
    const form = new FormData()
    form.append('file', file)
    return requestJson<{ url: string }>(`/books/${bookId}/world/map/upload`, {
      method: 'POST',
      body: form,
    })
  },
}
