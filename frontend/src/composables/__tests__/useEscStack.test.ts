import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

/**
 * node 环境无 window——stub 出 addEventListener/removeEventListener 捕获
 * capture 监听的挂摘协议（栈空即摘，不常驻）。
 * 栈是模块级单例：每个用例 resetModules + 动态 import 取全新实例。
 */

function stubWindow() {
  const listeners: Array<(e: KeyboardEvent) => void> = []
  const isCapture = (opts: unknown) => opts === true || !!(opts as any)?.capture
  const win = {
    addEventListener: vi.fn((kind: string, fn: any, opts: any) => {
      if (kind === 'keydown' && isCapture(opts)) listeners.push(fn)
    }),
    removeEventListener: vi.fn((kind: string, fn: any, opts: any) => {
      const i = listeners.indexOf(fn)
      if (kind === 'keydown' && isCapture(opts) && i !== -1) listeners.splice(i, 1)
    }),
    dispatch: (e: Partial<KeyboardEvent>) => {
      const full = {
        defaultPrevented: false,
        preventDefault: vi.fn(),
        ...e,
      }
      for (const fn of [...listeners]) fn(full as KeyboardEvent)
      return full
    },
  }
  vi.stubGlobal('window', win)
  return win
}

let win: ReturnType<typeof stubWindow>

beforeEach(() => {
  vi.resetModules()
  win = stubWindow()
})

afterEach(() => {
  vi.unstubAllGlobals()
})

async function makeEsc() {
  const { useEscStack } = await import('../useEscStack')
  return useEscStack()
}

describe('useEscStack 全局 Esc 栈', () => {
  it('push 挂 window capture 监听', async () => {
    const esc = await makeEsc()
    esc.push(() => {})
    expect(win.addEventListener).toHaveBeenCalledWith('keydown', expect.any(Function), true)
    expect(esc.depth.value).toBe(1)
  })

  it('一次 Esc 只关栈顶一层（叠层不同关）', async () => {
    const esc = await makeEsc()
    const closes: string[] = []
    esc.push(() => closes.push('A'), 'A')
    esc.push(() => closes.push('B'), 'B')
    win.dispatch({ key: 'Escape' })
    expect(closes).toEqual(['B'])
  })

  it('defaultPrevented 让位（会话键处理器已消费 Esc）', async () => {
    const esc = await makeEsc()
    const close = vi.fn()
    esc.push(close)
    win.dispatch({ key: 'Escape', defaultPrevented: true })
    expect(close).not.toHaveBeenCalled()
  })

  it('非 Esc 键不触发', async () => {
    const esc = await makeEsc()
    const close = vi.fn()
    esc.push(close)
    win.dispatch({ key: 'Enter' })
    expect(close).not.toHaveBeenCalled()
  })

  it('Esc 事件被 preventDefault（不再冒泡关第二层）', async () => {
    const esc = await makeEsc()
    esc.push(() => {})
    const preventDefault = vi.fn()
    win.dispatch({ key: 'Escape', preventDefault })
    expect(preventDefault).toHaveBeenCalled()
  })

  it('remove 幂等：迟到的 remove 是无害 no-op', async () => {
    const esc = await makeEsc()
    const id1 = esc.push(() => {})
    esc.remove(id1)
    expect(esc.depth.value).toBe(0)
    expect(win.removeEventListener).toHaveBeenCalled()
    esc.remove(id1) // 再删一次不炸
    expect(esc.depth.value).toBe(0)
  })

  it('栈空即摘监听（不常驻全局）', async () => {
    const esc = await makeEsc()
    const id = esc.push(() => {})
    esc.remove(id)
    expect(win.removeEventListener).toHaveBeenCalledWith('keydown', expect.any(Function), true)
  })

  it('isTop 只有栈顶层为真', async () => {
    const esc = await makeEsc()
    const idA = esc.push(() => {}, 'A')
    const idB = esc.push(() => {}, 'B')
    expect(esc.isTop(idA)).toBe(false)
    expect(esc.isTop(idB)).toBe(true)
    esc.remove(idB)
    expect(esc.isTop(idA)).toBe(true)
  })

  it('close() 不自动弹栈——由调用方状态流转触发 remove', async () => {
    const esc = await makeEsc()
    let removed = false
    const id: { v?: symbol } = {}
    id.v = esc.push(() => {
      removed = true
      esc.remove(id.v!)
    })
    win.dispatch({ key: 'Escape' })
    expect(removed).toBe(true)
    expect(esc.depth.value).toBe(0)
  })
})
