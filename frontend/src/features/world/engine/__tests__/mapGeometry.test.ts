import { describe, expect, it } from 'vitest'
import {
  arcControlPoint,
  countSyntheticTail,
  distToSeg,
  pickNearest,
  pickScaleBarDays,
  resampleRing,
} from '../mapGeometry'

describe('pickScaleBarDays', () => {
  it('60~160px 内取档位天数值', () => {
    // pxLen = days*ppd/unitsPerScreenPx：ppd=100、units=1 时 days=1 → 100px ∈ [60,160]
    expect(pickScaleBarDays(100, 1)).toBe(1)
  })

  it('从小到大第一个命中即返回（半日档优先）', () => {
    // ppd=80：0.5 天=40px 不够、1 天=80px 命中
    expect(pickScaleBarDays(80, 1)).toBe(1)
    // ppd=50：0.5 天=25px、1=50px、2=100px 命中
    expect(pickScaleBarDays(50, 1)).toBe(2)
  })

  it('半日档命中返回 0.5（调用方渲染「半日」）', () => {
    expect(pickScaleBarDays(240, 1)).toBe(0.5) // 0.5*240=120px
  })

  it('无档位返回 null（回落「已标定」文案）', () => {
    expect(pickScaleBarDays(1000, 1)).toBeNull() // 最小档 0.5 天=500px，全部出带
    expect(pickScaleBarDays(1, 1)).toBeNull() // 最大档 50 天=50px，全部不够
  })

  it('缩放换算经 unitsPerScreenPx（units 越小同天数像素越长）', () => {
    // ppd=400、units=1：0.5 天=200px、1 天=400px 全部出带 → null
    expect(pickScaleBarDays(400, 1)).toBeNull()
    // ppd=100、units=4：0.5→12.5 / 1→25 / 2→50 全不够，5 天→125px 命中
    expect(pickScaleBarDays(100, 4)).toBe(5)
  })
})

describe('distToSeg', () => {
  it('垂足在线段内：点到直线的垂直距离', () => {
    expect(distToSeg({ x: 0, y: 3 }, { x: 0, y: 0 }, { x: 10, y: 0 })).toBeCloseTo(3)
  })

  it('垂足在线段外：钳到端点（t∈[0,1]）', () => {
    expect(distToSeg({ x: 12, y: 0 }, { x: 0, y: 0 }, { x: 10, y: 0 })).toBeCloseTo(2)
    expect(distToSeg({ x: -5, y: 1 }, { x: 0, y: 0 }, { x: 10, y: 0 })).toBeCloseTo(
      Math.hypot(5, 1),
    )
  })

  it('零长线段退化：到 a 的距离', () => {
    expect(distToSeg({ x: 3, y: 4 }, { x: 0, y: 0 }, { x: 0, y: 0 })).toBeCloseTo(5)
  })
})

describe('resampleRing', () => {
  it('空环与单点环', () => {
    expect(resampleRing([], 4)).toEqual([])
    expect(resampleRing([[1, 2]], 3)).toEqual([
      [1, 2],
      [1, 2],
      [1, 2],
    ])
  })

  it('正方形环重采样到 4 点 ≈ 原四角（弧长均匀）', () => {
    const sq: [number, number][] = [
      [0, 0],
      [10, 0],
      [10, 10],
      [0, 10],
    ]
    const out = resampleRing(sq, 4)
    // 周长 40，四等分点恰为四角（起点对齐第一个顶点）
    expect(out[0]).toEqual([0, 0])
    expect(out[1][0]).toBeCloseTo(10)
    expect(out[1][1]).toBeCloseTo(0)
    expect(out[2][0]).toBeCloseTo(10)
    expect(out[2][1]).toBeCloseTo(10)
    expect(out[3][0]).toBeCloseTo(0)
    expect(out[3][1]).toBeCloseTo(10)
  })

  it('输出点数恰为 n 且落在环上（顶点数对齐的 morph 前提）', () => {
    const tri: [number, number][] = [
      [0, 0],
      [6, 0],
      [0, 8],
    ]
    const out = resampleRing(tri, 7)
    expect(out).toHaveLength(7)
    for (const [x, y] of out) {
      expect(x).toBeGreaterThanOrEqual(0)
      expect(y).toBeGreaterThanOrEqual(0)
      // 直角三角形边上：x/6 + y/8 <= 1（斜边约束）+ 两条直角边约束
      expect(x / 6 + y / 8).toBeLessThanOrEqual(1.000001)
    }
  })
})

describe('arcControlPoint', () => {
  it('水平线段的控制点在垂直方向偏移', () => {
    const c = arcControlPoint({ x: 0, y: 0 }, { x: 100, y: 0 })
    expect(c.x).toBeCloseTo(50)
    expect(c.y).toBeCloseTo(12) // len=100 → off=min(60, 12)=12，垂直向上
  })

  it('长线段偏移封顶 60（不随长度无限增长）', () => {
    const c = arcControlPoint({ x: 0, y: 0 }, { x: 1000, y: 0 })
    expect(c.y).toBeCloseTo(60)
  })

  it('重合端点 len 退化不 NaN', () => {
    const c = arcControlPoint({ x: 5, y: 5 }, { x: 5, y: 5 })
    expect(Number.isFinite(c.x)).toBe(true)
    expect(Number.isFinite(c.y)).toBe(true)
  })
})

describe('pickNearest', () => {
  const pts: Array<[string, { x: number; y: number }]> = [
    ['a', { x: 0, y: 0 }],
    ['b', { x: 10, y: 0 }],
    ['c', { x: 100, y: 100 }],
  ]

  it('取严格更近者且排除自身', () => {
    expect(pickNearest(1, 0, pts, 26, 'b')).toBe('a')
    expect(pickNearest(11, 0, pts, 26, 'a')).toBe('b')
  })

  it('半径外不命中（严格小于）', () => {
    expect(pickNearest(100, 100, pts, 26)).toBe('c') // 距离 0 命中自身
    expect(pickNearest(90, 90, pts, 14)).toBeNull() // 距 c = √200 ≈14.14 > 14
  })

  it('恰在半径边界不命中（d < r² 严格）', () => {
    const solo: Array<[string, { x: number; y: number }]> = [['a', { x: 0, y: 0 }]]
    expect(pickNearest(26, 0, solo, 26)).toBeNull()
    expect(pickNearest(25.9, 0, solo, 26)).toBe('a')
  })
})

describe('countSyntheticTail', () => {
  const now = 1_000_000
  /** 顶点工厂：钉住 [x, y] 元组类型（裸字面量会被推断成 number[]） */
  const V = (x: number, y: number, t: number) => ({ p: [x, y] as [number, number], t })

  it('同位且 600ms 内的尾部顶点全部剥除（上限 2）', () => {
    const pts = [V(5, 5, now - 5000), V(9, 9, now - 300), V(9, 9, now - 100)]
    expect(countSyntheticTail(pts, 9, 9, now)).toBe(2)
  })

  it('位置不同（真实顶点）或时间过窗不剥', () => {
    const pts = [V(5, 5, now - 100), V(9.5, 9, now - 100)] // 距双击点 x 差 0.5 > 0.01
    expect(countSyntheticTail(pts, 9, 9, now)).toBe(0)
    const old = [V(9, 9, now - 700)] // 超 600ms 窗
    expect(countSyntheticTail(old, 9, 9, now)).toBe(0)
  })

  it('只剥连续尾部：隔着真实顶点的旧合成顶点不动', () => {
    const pts = [
      V(9, 9, now - 200), // 更早的同位（会被隔断）
      V(5, 5, now - 150), // 真实顶点（位置不同）
      V(9, 9, now - 50), // 尾部合成
    ]
    expect(countSyntheticTail(pts, 9, 9, now)).toBe(1)
  })

  it('空数组与 max 上限', () => {
    expect(countSyntheticTail([], 0, 0, now)).toBe(0)
    const three = [V(1, 1, now - 300), V(1, 1, now - 200), V(1, 1, now - 100)]
    expect(countSyntheticTail(three, 1, 1, now)).toBe(2) // max=2 封顶
  })
})
