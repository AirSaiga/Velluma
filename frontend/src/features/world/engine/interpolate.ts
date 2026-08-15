import type { Point } from './types'

/**
 * 决策②：沿 path 折线按时间进度做**弧长插值**（不是顶点比例）。
 *
 * move 事件在 [tStart, tEnd] 区间内，按时间进度 p=(t-tStart)/(tEnd-tStart)，
 * 在 path 的累计弧长上定位 p*总弧长 落在哪一段，再在该段内线性插值。
 *
 * 返回 { position, label }；t 超出区间返回端点；path 不足返回 null/首点。
 */
export function interpolateOnPath(
  path: Point[],
  tStart: number,
  tEnd: number,
  t: number,
): { position: Point | null; label: string } {
  if (!path || path.length === 0) return { position: null, label: '' }
  if (path.length === 1) return { position: [path[0][0], path[0][1]], label: '' }
  if (t <= tStart) return { position: [path[0][0], path[0][1]], label: '' }
  if (t >= tEnd) return { position: [path[path.length - 1][0], path[path.length - 1][1]], label: '' }

  const span = Math.max(1, tEnd - tStart)
  const p = (t - tStart) / span // 0..1 时间进度

  // 计算每段长度 + 累计总长
  const segs: number[] = []
  let total = 0
  for (let i = 0; i < path.length - 1; i++) {
    const dx = path[i + 1][0] - path[i][0]
    const dy = path[i + 1][1] - path[i][1]
    const len = Math.sqrt(dx * dx + dy * dy)
    segs.push(len)
    total += len
  }
  if (total <= 0) return { position: [path[0][0], path[0][1]], label: '' }

  const target = p * total
  let acc = 0
  for (let i = 0; i < segs.length; i++) {
    const segLen = segs[i]
    if (acc + segLen >= target || i === segs.length - 1) {
      const segP = Math.max(0, Math.min(1, (target - acc) / Math.max(1e-9, segLen)))
      const x = path[i][0] + (path[i + 1][0] - path[i][0]) * segP
      const y = path[i][1] + (path[i + 1][1] - path[i][1]) * segP
      return { position: [x, y] as Point, label: `在途（进度 ${Math.floor(p * 100)}%）` }
    }
    acc += segLen
  }
  return { position: [path[path.length - 1][0], path[path.length - 1][1]], label: '' }
}
