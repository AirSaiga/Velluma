import { describe, expect, it } from 'vitest'
import { interpolateOnPath } from '../interpolate'

describe('interpolateOnPath（move 事件弧长插值）', () => {
  const path: [number, number][] = [
    [0, 0],
    [10, 0],
    [10, 10],
  ]

  it('空 path → null 位置', () => {
    expect(interpolateOnPath([], 0, 10, 5).position).toBeNull()
  })

  it('单点 path → 恒返回该点', () => {
    const r = interpolateOnPath([[3, 4]], 0, 10, 5)
    expect(r.position).toEqual([3, 4])
  })

  it('t ≤ tStart → 起点', () => {
    expect(interpolateOnPath(path, 0, 10, 0).position).toEqual([0, 0])
    expect(interpolateOnPath(path, 0, 10, -5).position).toEqual([0, 0])
  })

  it('t ≥ tEnd → 终点', () => {
    expect(interpolateOnPath(path, 0, 10, 10).position).toEqual([10, 10])
    expect(interpolateOnPath(path, 0, 10, 99).position).toEqual([10, 10])
  })

  it('弧长中点落在拐角上（不是顶点比例：前两段等长，半程=拐角）', () => {
    // 总弧长 20（10+10），p=0.5 → 目标弧长 10 = 第一段末 = 拐角 (10,0)
    const r = interpolateOnPath(path, 0, 10, 5)
    expect(r.position).toEqual([10, 0])
    expect(r.label).toContain('50%')
  })

  it('弧长插值：四分之一程在第一段中点（顶点比例法会给错答案）', () => {
    // 顶点比例法 p=0.25*2=0.5 顶点 → (10,0)；弧长法 0.25*20=5 → (5,0)
    const r = interpolateOnPath(path, 0, 10, 2.5)
    expect(r.position).toEqual([5, 0])
  })

  it('第二段内的进度线性插值', () => {
    // 目标弧长 15 → 第二段过半 (10,5)
    const r = interpolateOnPath(path, 0, 10, 7.5)
    expect(r.position).toEqual([10, 5])
  })

  it('在途标签带进度百分比', () => {
    expect(interpolateOnPath(path, 0, 10, 1).label).toBe('在途（进度 10%）')
  })

  it('区间内端点附近/零长度 path 防御', () => {
    // 全零点 path（总弧长 0）→ 首点兜底
    const zero = interpolateOnPath(
      [
        [1, 1],
        [1, 1],
      ],
      0,
      10,
      5,
    )
    expect(zero.position).toEqual([1, 1])
  })
})
