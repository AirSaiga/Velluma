/**
 * A5b 批量裁决纯逻辑 + A5d 收件箱直达旗标（P5 docs/foundation-hardening.md §3.2）。
 *
 * 网络/端点链路（runBatchAccept/undoBatchAccept 的 accept/delete/reopen 串序）
 * 走 GUI 手动验证（与既有 W4 候选回流测试口径一致——世界域此前无 api mock harness，
 * 纯函数层锁行为：勾选/剔除/全选/汇总/撤销名单/旗标消费）。
 */
import { describe, it, expect } from 'vitest'
import {
  initBatchSelection,
  toggleBatchSelection,
  setAllBatchSelection,
  selectedBatchIds,
  summarizeBatch,
  undoableOutcomes,
  inboxAutoOpen,
  requestOpenInbox,
  OPEN_INBOX_EVENT,
  type BatchSelection,
  type BatchAcceptOutcome,
} from '../batchAccept'

// node 测试环境无 window（与 useGenerationSession.test 的 localStorage 桩同款思路：
// 被测模块调用时才解析全局，挂内存桩即可；CustomEvent/EventTarget 是 node 22 原生类）
;(globalThis as Record<string, unknown>).window = new EventTarget()

const items = [{ id: 'a' }, { id: 'b' }, { id: 'c' }]

describe('A5b 批量勾选（默认全选 + 逐条剔除）', () => {
  it('打开预览默认全选', () => {
    const sel = initBatchSelection(items)
    expect(sel).toEqual({ a: true, b: true, c: true })
    expect(selectedBatchIds(items, sel)).toEqual(['a', 'b', 'c'])
  })

  it('剔除单条后名单只剩其余（顺序保持候选列表序）', () => {
    let sel: BatchSelection = initBatchSelection(items)
    sel = toggleBatchSelection(sel, 'b')
    expect(sel.b).toBe(false)
    expect(selectedBatchIds(items, sel)).toEqual(['a', 'c'])
  })

  it('toggle 不可变（新对象引用，Vue 响应式可追踪）', () => {
    const sel = initBatchSelection(items)
    const next = toggleBatchSelection(sel, 'a')
    expect(next).not.toBe(sel)
    expect(sel.a).toBe(true) // 原对象不被原地改
    expect(next.a).toBe(false)
  })

  it('再点一次恢复勾选（剔除可反悔）', () => {
    let sel = toggleBatchSelection(initBatchSelection(items), 'a')
    sel = toggleBatchSelection(sel, 'a')
    expect(selectedBatchIds(items, sel)).toEqual(['a', 'b', 'c'])
  })

  it('全不选 → 名单空；全选 → 全回来（全不选产出全 false 映射，名单口径仍为空）', () => {
    const none = setAllBatchSelection(items, false)
    expect(selectedBatchIds(items, none)).toEqual([])
    const all = setAllBatchSelection(items, true)
    expect(selectedBatchIds(items, all)).toEqual(['a', 'b', 'c'])
  })

  it('选中名单忽略不在选择表里的 id（防脏数据）', () => {
    const sel = { a: true } as BatchSelection
    expect(selectedBatchIds(items, sel)).toEqual(['a'])
  })
})

describe('A5b 批次汇总与撤销名单', () => {
  const ok = (id: string, extra?: Partial<BatchAcceptOutcome>): BatchAcceptOutcome => ({
    candidateId: id, ok: true, chapterId: 'ch1', eventId: null, canonNodeId: null, ...extra,
  })
  const fail = (id: string): BatchAcceptOutcome => ({
    candidateId: id, ok: false, chapterId: 'ch1', eventId: null, canonNodeId: null,
  })

  it('summarizeBatch：成功/失败分账', () => {
    const outcomes = [ok('a'), fail('b'), ok('c', { eventId: 'e1' })]
    expect(summarizeBatch(outcomes)).toEqual({ ok: 2, failed: 1 })
  })

  it('空批次零值', () => {
    expect(summarizeBatch([])).toEqual({ ok: 0, failed: 0 })
  })

  it('undoableOutcomes 只含成功项（失败项无转正产物，无需 reopen）', () => {
    const outcomes = [ok('a', { eventId: 'e1' }), fail('b'), ok('c', { canonNodeId: 'n1' })]
    expect(undoableOutcomes(outcomes).map((o) => o.candidateId)).toEqual(['a', 'c'])
  })

  it('事件候选与 canon 候选的撤销产物分型（eventId / canonNodeId 各自携带）', () => {
    const outcomes = [
      ok('a', { eventId: 'e1' }),
      ok('b', { canonNodeId: 'n1' }),
    ]
    const undoable = undoableOutcomes(outcomes)
    expect(undoable[0].eventId).toBe('e1')
    expect(undoable[0].canonNodeId).toBeNull()
    expect(undoable[1].canonNodeId).toBe('n1')
    expect(undoable[1].eventId).toBeNull()
  })
})

describe('A5d 收件箱直达（旗标 + 事件）', () => {
  it('requestOpenInbox：置旗标并派发事件', () => {
    const fired: CustomEvent[] = []
    const listener = (e: Event) => fired.push(e as CustomEvent)
    window.addEventListener(OPEN_INBOX_EVENT, listener)
    try {
      requestOpenInbox()
      expect(inboxAutoOpen.value).toBe(true)
      expect(fired).toHaveLength(1)
    } finally {
      window.removeEventListener(OPEN_INBOX_EVENT, listener)
      inboxAutoOpen.value = false // 复位（模块级单例状态，勿泄漏给后续用例）
    }
  })
})