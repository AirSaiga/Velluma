/**
 * 地图几何纯函数（WorldMap 的数学部分，抽出来便于 vitest 对拍）。
 *
 * - pickScaleBarDays：比例尺角标选档（60~160px 内的整数天值档位）
 * - distToSeg：屏幕空间点到线段距离（手绘橡皮擦的命中判定）
 * - resampleRing：闭合环按弧长重采样到 N 点（疆域 morph 前的顶点数对齐）
 * - arcControlPoint：关系线三点轻弧的控制点（中点沿垂直方向偏移）
 * - pickNearest：容器坐标最近节点命中（⇧拖线建关系的松手判定）
 * - countSyntheticTail：双击闭合前应剥除的合成顶点数（伴随 click 产生的同位顶点）
 *
 * 零 Leaflet 依赖：坐标全部裸 number / {x,y}——L.Point 结构兼容可直接传入。
 */

export interface Pt {
  x: number
  y: number
}

/**
 * 比例尺选档：找 60~160px 档位的天数值（0.5=半日）。
 * CRS.Simple 覆写 scale(zoom)=2^zoom，unitsPerScreenPx=1/2^zoom 由调用方算好传入。
 * 无合适档位返回 null（调用方回落「已标定」文案）。
 */
export function pickScaleBarDays(
  ppd: number,
  unitsPerScreenPx: number,
  candidates: number[] = [0.5, 1, 2, 5, 10, 20, 50],
): number | null {
  for (const days of candidates) {
    const pxLen = (days * ppd) / unitsPerScreenPx
    if (pxLen >= 60 && pxLen <= 160) return days
  }
  return null
}

/** 点到线段距离；线段退化（零长）时为到 a 的距离。 */
export function distToSeg(p: Pt, a: Pt, b: Pt): number {
  const dx = b.x - a.x
  const dy = b.y - a.y
  const len2 = dx * dx + dy * dy
  if (len2 === 0) return Math.hypot(p.x - a.x, p.y - a.y)
  let t = ((p.x - a.x) * dx + (p.y - a.y) * dy) / len2
  t = Math.max(0, Math.min(1, t))
  return Math.hypot(p.x - (a.x + t * dx), p.y - (a.y + t * dy))
}

/** 闭合环按弧长均匀重采样到 n 点（疆域 morph：顶点数不同的两个环先对齐再插值）。 */
export function resampleRing(pts: [number, number][], n: number): [number, number][] {
  if (pts.length === 0) return []
  if (pts.length === 1) return Array.from({ length: n }, () => [...pts[0]] as [number, number])
  const segs: number[] = []
  let total = 0
  for (let i = 0; i < pts.length; i++) {
    const a = pts[i]
    const b = pts[(i + 1) % pts.length] // 闭合环采样
    const len = Math.hypot(b[0] - a[0], b[1] - a[1])
    segs.push(len)
    total += len
  }
  const out: [number, number][] = []
  for (let k = 0; k < n && total > 0; k++) {
    let target = (k / n) * total
    for (let i = 0; i < segs.length; i++) {
      if (target <= segs[i] || i === segs.length - 1) {
        const t = segs[i] === 0 ? 0 : Math.min(1, target / segs[i])
        const a = pts[i]
        const b = pts[(i + 1) % pts.length]
        out.push([a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t])
        break
      }
      target -= segs[i]
    }
  }
  return out
}

/** 关系线轻弧控制点：中点沿垂直方向偏移 min(maxOff, len×ratio)——随端点移动伸缩。 */
export function arcControlPoint(a: Pt, b: Pt, maxOff = 60, ratio = 0.12): Pt {
  const mx = (a.x + b.x) / 2
  const my = (a.y + b.y) / 2
  const dx = b.x - a.x
  const dy = b.y - a.y
  const len = Math.hypot(dx, dy) || 1
  const off = Math.min(maxOff, len * ratio)
  return { x: mx - (dy / len) * off, y: my + (dx / len) * off }
}

/** 容器坐标最近节点命中（平方距离比较，严格小于 radius 才命中；excludeId 跳过自身）。 */
export function pickNearest(
  px: number,
  py: number,
  points: Array<[string, Pt]>,
  radius = 26,
  excludeId?: string,
): string | null {
  let bestId: string | null = null
  let bestD = radius * radius
  for (const [id, p] of points) {
    if (id === excludeId) continue
    const d = (p.x - px) ** 2 + (p.y - py) ** 2
    if (d < bestD) {
      bestD = d
      bestId = id
    }
  }
  return bestId
}

/**
 * 双击闭合前应剥除的尾部合成顶点数：双击伴随 1~2 次 click（数量随事件源不定），
 * 与双击同位置（<eps）且 windowMs 内的尾部顶点是合成物；用户真实顶点时间更早
 * 或位置不同，不会被误删。最多剥 max 个。
 */
export function countSyntheticTail(
  points: { p: [number, number]; t: number }[],
  lng: number,
  lat: number,
  now: number,
  max = 2,
  windowMs = 600,
  eps = 0.01,
): number {
  let removed = 0
  while (removed < max) {
    const last = points[points.length - 1 - removed]
    if (!last) break
    const sameSpot = Math.abs(last.p[0] - lng) < eps && Math.abs(last.p[1] - lat) < eps
    if (now - last.t < windowMs && sameSpot) removed++
    else break
  }
  return removed
}
