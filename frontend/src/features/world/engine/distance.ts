/**
 * D4 空间换算（前端侧，docs/reports/map-scale-spatial.md §4）。
 *
 * 与后端 services/world/spatial.py 同构——改口径两侧同步（各配单测对拍）。
 * 未标定（map_scale 无 refs）一切函数静默降级：距离功能缺席不影响任何既有行为。
 */

export interface ScaleRef {
  ax: number; ay: number; bx: number; by: number
  days_foot: number
  label?: string
}
export interface MapScale {
  refs?: ScaleRef[]
  detour_factor?: number
  modes?: Record<string, number>
}

const MODE_SPEED_DEFAULTS: Record<string, number> = { walk: 1.0, horse: 2.5, boat: 2.0, caravan: 0.7 }

export function pxPerDay(scale: MapScale | null | undefined): number | null {
  const vals = (scale?.refs || [])
    .map((r) => {
      const days = Number(r.days_foot)
      if (!(days > 0)) return null
      const len = Math.hypot(r.bx - r.ax, r.by - r.ay)
      return len > 0 ? len / days : null
    })
    .filter((v): v is number => v != null && v > 0)
  if (!vals.length) return null
  return vals.reduce((s, v) => s + v, 0) / vals.length
}

export function distanceDays(
  a: [number, number],
  b: [number, number],
  scale: MapScale | null | undefined,
): number | null {
  const ppd = pxPerDay(scale)
  if (ppd == null) return null
  const detour = Math.min(3, Math.max(1, Number(scale?.detour_factor) || 1.2))
  return (Math.hypot(b[0] - a[0], b[1] - a[1]) / ppd) * detour
}

export function formatDistance(
  days: number | null | undefined,
  mode: string = 'walk',
  scale?: MapScale | null,
): string {
  if (days == null || days < 0) return ''
  const speed = Number(scale?.modes?.[mode]) > 0 ? Number(scale!.modes![mode]) : (MODE_SPEED_DEFAULTS[mode] ?? 1.0)
  const v = days / speed
  const unit = mode === 'walk' ? '步程' : '行程'
  if (v < 0.25) return '近在咫尺'
  if (v < 1.0) return `约半日${unit}`
  if (v < 10.0) return `约 ${v.toFixed(1).replace(/\.0$/, '')} 天${unit}`
  return `约 ${Math.round(v)} 天${unit}`
}

export function formatDistanceWithScale(
  a: [number, number], b: [number, number],
  scale: MapScale | null | undefined, mode = 'walk',
): string {
  return formatDistance(distanceDays(a, b, scale), mode, scale)
}

/** 相遇距离分档（D4-2）：null=同地（沿用 W5-lite）或未标定 */
export function encounterBand(days: number | null | undefined): string | null {
  if (days == null) return null
  if (days <= 0.05) return null
  if (days < 0.5) return '半日内可达'
  if (days <= 3.0) return '1-3 天路程'
  return '更远'
}

// ---- 空白舆图隐含地球尺度（docs/reports/map-scale-spatial.md §2.2，与后端 blank_atlas_suggested_scale 同构）----
const KM_PER_DAY_FOOT = 30
const EARTH_CIRCUMFERENCE_KM = 40075

/** 空白舆图上画的一段线按地球尺度折算的步行日（atlasWidth=内部单位图宽） */
export function blankAtlasSuggestedDays(lineLen: number, atlasWidth: number = 900): number {
  if (atlasWidth <= 0 || lineLen <= 0) return 0
  const fullWidthDays = EARTH_CIRCUMFERENCE_KM / KM_PER_DAY_FOOT // ≈1335.8
  return (lineLen / atlasWidth) * fullWidthDays
}
