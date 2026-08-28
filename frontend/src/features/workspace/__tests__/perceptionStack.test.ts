/**
 * 感知带锚定卡碰撞避让（stackAnchoredTops）纯函数测试。
 *
 * 背景（2026-08-28 实测）：锚定卡各自按「正文对应词的 Y」绝对定位，
 * 相邻行/同 label 多条提醒 → 卡片直接叠在一起。修复 = 按 Y 排序逐张下推。
 */
import { describe, it, expect } from 'vitest'
import { stackAnchoredTops } from '../../workspace/composables/usePerceptionAlignment'

describe('stackAnchoredTops', () => {
  it('同 Y 多卡按数组序稳定下推，互不重叠', () => {
    const tops = [100, 100, 100]
    const out = stackAnchoredTops(tops, [44, 44, 44])
    expect(out).toEqual([100, 144, 188])
  })

  it('相邻行（间距小于卡高）只推后卡，前卡不动', () => {
    const out = stackAnchoredTops([100, 120], [44, 44])
    expect(out[0]).toBe(100)
    expect(out[1]).toBe(144) // 120 < 100+44 → 推到 144
  })

  it('间距足够的卡保持原位', () => {
    const out = stackAnchoredTops([100, 300, 600], [44, 60, 44])
    expect(out).toEqual([100, 300, 600])
  })

  it('乱序输入按 Y 排序下推，输出保持输入序', () => {
    // 输入序 [低, 高, 中]：中卡虽 Y 更小但排在后——按 Y 排序后 高卡可能被推
    const out = stackAnchoredTops([200, 100, 110], [44, 44, 44])
    expect(out[0]).toBe(200)
    expect(out[1]).toBe(100)
    expect(out[2]).toBe(144) // 110 < 100+44 → 推
  })

  it('null（找不到正文位置）原样保留不参与下推', () => {
    const out = stackAnchoredTops([100, null, 100], [44, 44, 44])
    expect(out[1]).toBeNull()
    expect(out[0]).toBe(100)
    expect(out[2]).toBe(144)
  })

  it('detail 卡（更高）把后面的卡推得更远', () => {
    const out = stackAnchoredTops([100, 120], [90, 44])
    expect(out[1]).toBe(190)
  })
})
