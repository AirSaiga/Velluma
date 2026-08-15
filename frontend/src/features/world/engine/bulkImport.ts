import type { EventType, Timestamp, Point } from './types'
import { fromYMD } from './timeFormat'

/**
 * TSV 批量导入解析（照搬世界绘卷，纯函数）。
 *
 * 第一行中文表头，Tab 分隔，一行一事件。错误收集不抛异常（部分成功）。
 * 表头字段：类型/开始年/开始月/开始日/结束年/结束月/结束日/备注/标签/地点ID/人物ID/X坐标/Y坐标
 */
export interface ParsedEventInput {
  event_type: EventType
  time_start: Timestamp
  time_end: Timestamp
  note: string
  tags: string[]
  location_id?: string
  participant_ids: string[]
  coord?: Point
}

export interface ParseResult {
  rows: ParsedEventInput[]
  errors: { line: number; message: string }[]
}

const VALID_TYPES: EventType[] = [
  'birth', 'death', 'move', 'battle', 'territory_change',
  'found', 'destroy', 'alliance', 'war_declare', 'coronation', 'custom',
]

const HEADER_MAP: Record<string, string> = {
  类型: 'event_type',
  开始年: 'sy', 开始月: 'smo', 开始日: 'sd',
  结束年: 'ey', 结束月: 'emo', 结束日: 'ed',
  备注: 'note', 标签: 'tags',
  地点ID: 'location_id', 人物ID: 'participant_ids',
  X坐标: 'cx', Y坐标: 'cy',
}

export function parseTsv(text: string): ParseResult {
  const lines = text.split(/\r?\n/).filter((l) => l.trim() !== '')
  const result: ParseResult = { rows: [], errors: [] }
  if (lines.length === 0) return result

  const headers = lines[0].split('\t').map((h) => h.trim())
  const colIdx: Record<string, number> = {}
  headers.forEach((h, i) => {
    const key = HEADER_MAP[h]
    if (key) colIdx[key] = i
  })

  for (let i = 1; i < lines.length; i++) {
    const cells = lines[i].split('\t')
    const get = (key: string): string =>
      colIdx[key] != null ? (cells[colIdx[key]] || '').trim() : ''

    const typeStr = get('event_type') as EventType
    if (!VALID_TYPES.includes(typeStr)) {
      result.errors.push({ line: i + 1, message: `未知事件类型：${typeStr || '(空)'}` })
      continue
    }

    const sy = parseInt(get('sy'), 10)
    const smo = parseInt(get('smo'), 10) || 1
    const sd = parseInt(get('sd'), 10) || 1
    if (!sy) {
      result.errors.push({ line: i + 1, message: '缺开始年' })
      continue
    }
    const timeStart = fromYMD(sy, smo, sd)

    const ey = parseInt(get('ey'), 10)
    const emo = parseInt(get('emo'), 10) || smo
    const ed = parseInt(get('ed'), 10) || sd
    const timeEnd = ey ? fromYMD(ey, emo, ed) : timeStart

    const tags = get('tags')
      ? get('tags').split(/[，,]/).map((t) => t.trim()).filter(Boolean)
      : []
    const participantIds = get('participant_ids')
      ? get('participant_ids').split(/[，,]/).map((t) => t.trim()).filter(Boolean)
      : []

    let note = get('note')
    const cx = parseFloat(get('cx'))
    const cy = parseFloat(get('cy'))
    let coord: Point | undefined
    if (!isNaN(cx) && !isNaN(cy)) {
      coord = [cx, cy]
      note = `${note} @${cx},${cy}`.trim()
    }

    result.rows.push({
      event_type: typeStr,
      time_start: timeStart,
      time_end: timeEnd,
      note: note.trim(),
      tags,
      location_id: get('location_id') || undefined,
      participant_ids: participantIds,
      coord,
    })
  }
  return result
}

export const SAMPLE_TSV = [
  '类型\t开始年\t开始月\t开始日\t结束年\t备注\t标签\tX坐标\tY坐标',
  'birth\t1\t1\t1\t\t主角出生\t主角,身世\t100\t200',
  'move\t5\t3\t1\t5\t3\t15\t主角远行\t\t300\t400',
  'battle\t10\t\t\t\t决战\t决战\t500\t600',
].join('\n')
