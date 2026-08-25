/**
 * A5b 批量裁决 + A5d 收件箱直达（P5 docs/foundation-hardening.md §3.2）。
 *
 * 批量裁决 = 「全部采纳」逐条预览（可勾选剔除）→ 确认后逐条走既有 accept 端点
 * （/world/candidates/{id}/accept，不改后端语义）→ toast 6 秒可撤销。
 * 撤销 = 逐条复合操作：删转正产物（事件 / canon 真相节点）+ reopen 候选回 pending
 * （与 useWorldSlice.undoAccept 单条撤销同一契约，批量化）。
 *
 * 勾选/剔除/汇总为纯函数（__tests__/batchAccept.test.ts 锁行为）；
 * 串行执行沿用批量删除的防竞态约定（不并行打后端）。
 */
import { ref } from 'vue'
import { worldApi } from '../../../services/api/domain/world.api'
import type { WorldEventCandidate } from '../../../services/api/domain/world.api'
import { canonApi } from '../../../services/api/domain/canon.api'
import { adaptiveApi } from '../../../services/api/domain/adaptive.api'

// ============================================================
// A5d 收件箱直达：toast action → 副驾抽屉滑出 + 切「此刻」tab + 收件箱展开
// ============================================================
// 与 velluma:world-refresh 同款事件解耦。抽屉/tab/收件箱分属三个组件
// （WorkspaceView / InspectorPanel / WorldSceneSlice），各自监听各自改状态。
// 挂载时序坑：抽屉关闭时 InspectorPanel 是 v-if 卸载态，事件发出时监听器
// 还不存在——inboxAutoOpen 旗标补位（挂载后消费），保证「打开抽屉→tab 就位」
// 两步都兑现。
export const OPEN_INBOX_EVENT = 'velluma:open-inbox'

/** 一次性旗标：请求打开收件箱时置 true，WorldSceneSlice 挂载时消费（复位 false） */
export const inboxAutoOpen = ref(false)

/** 请求直达收件箱（A5d toast action / A5c 报告区「去处理」共用入口） */
export function requestOpenInbox(): void {
  inboxAutoOpen.value = true
  window.dispatchEvent(new CustomEvent(OPEN_INBOX_EVENT))
}

// ============================================================
// 勾选状态（纯函数）
// ============================================================

export type BatchSelection = Record<string, boolean>

/** 打开预览默认全选（「全部采纳」语义；作者逐条剔除） */
export function initBatchSelection(items: Array<{ id: string }>): BatchSelection {
  const sel: BatchSelection = {}
  for (const it of items) sel[it.id] = true
  return sel
}

/** 不可变切换（Vue 响应式依赖新对象引用） */
export function toggleBatchSelection(sel: BatchSelection, id: string): BatchSelection {
  return { ...sel, [id]: !sel[id] }
}

/** 全选/清空（三态全选条：全选↔全不选） */
export function setAllBatchSelection(items: Array<{ id: string }>, value: boolean): BatchSelection {
  const sel: BatchSelection = {}
  for (const it of items) sel[it.id] = value
  return sel
}

/** 剔除后的采纳名单（保持候选列表顺序） */
export function selectedBatchIds(items: Array<{ id: string }>, sel: BatchSelection): string[] {
  return items.filter((it) => sel[it.id]).map((it) => it.id)
}

// ============================================================
// 批量采纳（串行走既有 accept 端点）
// ============================================================

export interface BatchAcceptOutcome {
  candidateId: string
  /** 采纳成功（转正或建节点） */
  ok: boolean
  /** 命中重复转正闸（账本已有同义事件）——未建事件、候选已留痕，不算失败也不进撤销名单 */
  duplicated: boolean
  /** 候选归属章（埋点归账用；跨章批量时逐章计数） */
  chapterId: string | null
  /** event_scout/settle 候选转正创建的事件 id（撤销时删；canon 候选为 null） */
  eventId: string | null
  /** canon_extract 候选转正建的真相节点 id（撤销时删；事件候选为 null） */
  canonNodeId: string | null
}

export interface BatchSummary {
  ok: number
  failed: number
  /** 重复跳过条数（重复转正闸；从 failed 里拆出——它不是作者的失败） */
  dup: number
}

export function summarizeBatch(outcomes: BatchAcceptOutcome[]): BatchSummary {
  let ok = 0
  let dup = 0
  for (const o of outcomes) {
    if (o.ok) ok++
    else if (o.duplicated) dup++
  }
  return { ok, failed: outcomes.length - ok - dup, dup }
}

/** 撤销名单 = 成功项（失败项无转正产物，无需 reopen）——纯函数供测试 */
export function undoableOutcomes(outcomes: BatchAcceptOutcome[]): BatchAcceptOutcome[] {
  return outcomes.filter((o) => o.ok)
}

/**
 * 逐条采纳（串行防后端竞态）。onProgress 驱动确认按钮进度文案。
 * 埋点：按候选归属章逐章记 batch_accept（世界页跨章批量也能归账）。
 */
export async function runBatchAccept(
  bookId: string,
  candidates: WorldEventCandidate[],
  onProgress?: (done: number, total: number) => void,
): Promise<BatchAcceptOutcome[]> {
  const outcomes: BatchAcceptOutcome[] = []
  let done = 0
  for (const c of candidates) {
    const item: BatchAcceptOutcome = {
      candidateId: c.id, ok: false, duplicated: false, chapterId: c.chapter_id || null,
      eventId: null, canonNodeId: null,
    }
    try {
      const r = await worldApi.acceptCandidate(bookId, c.id)
      if (r?.duplicated) {
        item.duplicated = true  // 重复转正闸：不建事件不失败，留痕跳过
      } else {
        item.ok = true
        item.eventId = r?.event?.id || null
        item.canonNodeId = r?.canon_node_id || null
      }
    } catch {
      item.ok = false  // 单条失败不阻断批次（如 409 已处理），尾部汇总提示
    }
    outcomes.push(item)
    done++
    onProgress?.(done, candidates.length)
  }
  _logBatchAccept(outcomes.filter((o) => o.ok), false)
  return outcomes
}

/**
 * 复合撤销：逐条「删转正产物 + reopen 回 pending」。
 * 单条撤销失败不阻断其余（链断降级为仅逐条），返回实际撤销条数。
 */
export async function undoBatchAccept(
  bookId: string,
  outcomes: BatchAcceptOutcome[],
): Promise<number> {
  const undoneItems: BatchAcceptOutcome[] = []
  for (const o of undoableOutcomes(outcomes)) {
    try {
      if (o.eventId) await worldApi.deleteEvent(bookId, o.eventId)
      if (o.canonNodeId) await canonApi.deleteNode(bookId, o.canonNodeId)
      await worldApi.reopenCandidate(bookId, o.candidateId)
      undoneItems.push(o)
    } catch {
      // 链断降级：该条保持已采纳（候选可在收件箱重开流程里人工处理）
    }
  }
  _logBatchAccept(undoneItems, true)
  return undoneItems.length
}

/** 埋点：按候选归属章逐章归账（undone=1 不计入 batch_accept_count 采纳条数）；失败静默 */
function _logBatchAccept(items: BatchAcceptOutcome[], undone: boolean): void {
  try {
    const byChapter = new Map<string, number>()
    for (const o of items) {
      if (!o.chapterId) continue
      byChapter.set(o.chapterId, (byChapter.get(o.chapterId) || 0) + 1)
    }
    for (const [chId, count] of byChapter) {
      void adaptiveApi.logCollabEvent(chId, 'batch_accept', { count, undone: undone ? 1 : 0 })
    }
  } catch {
    // 埋点绝不阻塞业务
  }
}
