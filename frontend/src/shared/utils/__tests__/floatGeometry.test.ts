import { describe, it, expect } from 'vitest'
import { placeFloating } from '../floatGeometry'

/**
 * placeFloating 对拍（00 期 §4.1A）：确定序 clamp→flip→maxHeight。
 * 视口统一 1000×800，margin 默认 8，gap 默认 8。
 */

const VP = { width: 1000, height: 800 }

describe('placeFloating 水平夹紧', () => {
  it('align=start 贴锚左缘', () => {
    const r = placeFloating({ top: 100, left: 200, bottom: 120, right: 300 }, { width: 160, height: 100 }, VP)
    expect(r.left).toBe(200)
  })

  it('右溢出夹回视口右缘内', () => {
    const r = placeFloating({ top: 100, left: 900, bottom: 120, right: 990 }, { width: 160, height: 100 }, VP)
    expect(r.left).toBe(1000 - 160 - 8)
  })

  it('左溢出夹回视口左缘内', () => {
    const r = placeFloating({ top: 100, left: 2, bottom: 120, right: 100 }, { width: 160, height: 100 }, VP)
    expect(r.left).toBe(8)
  })

  it('align=center 以锚中心对齐', () => {
    const r = placeFloating({ top: 100, left: 400, bottom: 120, right: 500 }, { width: 100, height: 50 }, VP)
    expect(r.left).toBe(450 - 50)
  })

  it('align=end 以锚右缘对齐', () => {
    const r = placeFloating({ top: 100, left: 400, bottom: 120, right: 500 }, { width: 100, height: 50 }, VP)
    expect(r.left).toBe(500 - 100)
  })
})

describe('placeFloating 垂直方向与翻转', () => {
  it('prefer=below 放锚下方', () => {
    const r = placeFloating({ top: 100, left: 200, bottom: 120, right: 300 }, { width: 100, height: 80 }, VP)
    expect(r.top).toBe(128)
    expect(r.flipped).toBe(false)
    expect(r.maxHeight).toBeNull()
  })

  it('下方不足翻转到上方，flipped=true', () => {
    const r = placeFloating({ top: 740, left: 200, bottom: 760, right: 300 }, { width: 100, height: 80 }, VP)
    expect(r.flipped).toBe(true)
    expect(r.top).toBe(740 - 8 - 80)
  })

  it('prefer=above 放锚上方，上方不足翻到下方', () => {
    const above = placeFloating({ top: 60, left: 200, bottom: 80, right: 300 }, { width: 100, height: 80, prefer: 'above' }, VP)
    expect(above.flipped).toBe(true)
    expect(above.top).toBe(88)

    const normal = placeFloating({ top: 400, left: 200, bottom: 420, right: 300 }, { width: 100, height: 80, prefer: 'above' }, VP)
    expect(normal.flipped).toBe(false)
    expect(normal.top).toBe(400 - 8 - 80)
  })

  it('两侧都放不下（锚居中+浮层过高）→ 夹紧并给 maxHeight', () => {
    const r = placeFloating({ top: 395, left: 200, bottom: 405, right: 300 }, { width: 100, height: 900 }, VP)
    expect(r.top).toBe(8)
    expect(r.maxHeight).toBe(800 - 16)
  })

  it('翻转到上方仍越界（锚贴顶）→ 夹紧回视口内', () => {
    const r = placeFloating({ top: 5, left: 200, bottom: 25, right: 300 }, { width: 100, height: 300 }, VP)
    // 下方放不下（25+8+300=333 < 792 放得下！）→ 不翻转，直接 below
    expect(r.top).toBe(33)
  })

  it('flip=false 时下方不足不翻转，直接夹紧给 maxHeight', () => {
    const r = placeFloating({ top: 740, left: 200, bottom: 760, right: 300 }, { width: 100, height: 200, flip: false }, VP)
    expect(r.flipped).toBe(false)
    expect(r.top).toBe(800 - 8 - 200)
    expect(r.maxHeight).toBe(800 - 16)
  })
})

describe('placeFloating 点锚', () => {
  it('点锚按零宽高矩形处理', () => {
    const r = placeFloating({ x: 500, y: 400 }, { width: 120, height: 60 }, VP)
    expect(r.left).toBe(500)
    expect(r.top).toBe(408)
  })

  it('点锚贴右缘时浮层左移不溢出', () => {
    const r = placeFloating({ x: 960, y: 400 }, { width: 300, height: 60 }, VP)
    expect(r.left).toBe(1000 - 300 - 8)
  })
})
