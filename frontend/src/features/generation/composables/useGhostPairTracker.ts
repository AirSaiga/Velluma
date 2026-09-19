/**
 * 幽灵改稿自动捕获（03 下一阶段 M1：书签位置映射 → 自动成对）。
 *
 * 原理：不找文字，跟住位置——采纳瞬间暂存幽灵原文 + 记下首尾两个 ProseMirror
 * position；GhostTrack 扩展的插件随每次事务把位置 map 过去（中间插字→尾后移；
 * 删句→靠拢；整段删除→塌缩为零宽守原地，「删了重打」重新张开照样成对）。
 * 自动保存时「对比并更新」（同一幽灵只留最新版：POST 新对 + DELETE 旧对）；
 * 切章定稿：读出两书签间现文与原文对比——相同=干净采纳静默跳过，不同=自动
 * 成对（bad=幽灵原文 / good=现文）提交 POST /api/deai/pairs（source=auto_ghost）。
 *
 * 数据纪律（不变）：bad 必须是 AI 原样产出（由构造保证）；收集侧三条硬校验
 * （bad 非空且 ≤100 字、good ≤600 字）；六闸与人工过目在入库侧（管线不动）。
 * 纯内存（一期接受应用重开丢失）；书签寿命=整个章节会话。
 */
import { deaiApi } from '../../../services/api/domain'

/** 契约窗口（deai/docs/contract.md C1）：一期只收 ≤100 字短稿 */
export const PAIR_BAD_MAX = 100
export const PAIR_GOOD_MAX = 600

export interface TrackedGhost {
  /** 本地幽灵序号（一章内递增） */
  id: string
  /** AI 原样产出（采纳时的幽灵原文） */
  bad: string
  from: number
  to: number
  /** 上次已提交的 good（干净=现文与 bad 或上次提交一致 → 跳过） */
  lastSubmittedGood: string
  /** 上次提交的服务端对 id（覆盖语义：POST 新对后 DELETE 旧对） */
  pairId: string | null
  /** 采集源（auto_ghost=五模式幽灵 / capsule=细纲扩写采纳；入账走 meta.source） */
  source: 'auto_ghost' | 'capsule'
}

/** chapterId → 该章正在跟踪的书签（切章 finalize 后清空） */
const tracked = new Map<string, TrackedGhost>()

let _seq = 0

// ============================================================
// 纯决策函数（单测锚点）
// ============================================================

export type PairAction = { op: 'skip' } | { op: 'submit'; good: string } | { op: 'reject' }

/** 对比决策：干净采纳跳过 / 有改动提交 / 越窗或塌缩拒绝。 */
export function decidePairAction(bad: string, lastGood: string, currentText: string): PairAction {
  const good = (currentText || '').trim()
  if (!bad.trim() || bad.length > PAIR_BAD_MAX) return { op: 'reject' }
  if (good.length > PAIR_GOOD_MAX) return { op: 'reject' }
  if (!good) return { op: 'skip' } // 塌缩为零宽（完全否决信号，不成对）
  if (good === bad.trim() || good === lastGood) return { op: 'skip' } // 干净采纳 / 无新改动
  return { op: 'submit', good }
}

// ============================================================
// 跟踪与位置映射
// ============================================================

/** 采纳瞬间调用（commitGhost 内）：暂存原文 + 放下书签（纯内存不进 HTML）。 */
export function trackAdoptedGhost(
  chapterId: string,
  bad: string,
  from: number,
  to: number,
  source: 'auto_ghost' | 'capsule' = 'auto_ghost',
): void {
  if (!chapterId || !bad.trim() || bad.length > PAIR_BAD_MAX) return
  _seq += 1
  tracked.set(`${chapterId}:${_seq}`, {
    id: `g-${_seq}`,
    bad,
    from,
    to,
    lastSubmittedGood: '',
    pairId: null,
    source,
  })
}

/** GhostTrack 插件随事务映射全部书签位置（塌缩=from==to 守原地）。 */
export function mapTrackedPositions(mapping: {
  map: (pos: number, assoc?: number) => number
}): void {
  for (const g of tracked.values()) {
    g.from = mapping.map(g.from, -1)
    g.to = mapping.map(g.to, 1)
    if (g.to < g.from) g.to = g.from // 塌缩保护（整段删除→零宽守原地）
  }
}

/** 供装饰器扩展读取未审范围（M3：转正段未审虚线标记）。 */
export function trackedRangesOf(chapterId: string): Array<{ id: string; from: number; to: number }> {
  const out: Array<{ id: string; from: number; to: number }> = []
  for (const [key, g] of tracked.entries()) {
    if (key.startsWith(`${chapterId}:`)) out.push({ id: key, from: g.from, to: g.to })
  }
  return out
}

// ============================================================
// 成对提交（保存时对比更新 / 切章定稿）
// ============================================================

/**
 * 冲账一章的书签：读现文 → 决策 → 提交/覆盖。返回本轮新提交的对 id 列表。
 * final=true（切章）时移除全部跟踪（塌缩书签=完全否决，不成对自然消融）。
 */
export async function flushGhostPairs(
  chapterId: string,
  bookId: string | null,
  readText: (from: number, to: number) => string,
  final = false,
): Promise<string[]> {
  const submitted: string[] = []
  for (const [key, g] of [...tracked.entries()]) {
    if (!key.startsWith(`${chapterId}:`)) continue
    const current = readText(g.from, g.to)
    const decision = decidePairAction(g.bad, g.lastSubmittedGood, current)
    if (decision.op === 'submit') {
      try {
        const r = await deaiApi.savePair({
          bad: g.bad,
          good: decision.good,
          book_id: bookId || undefined,
          chapter_id: chapterId,
          source: g.source,
        })
        // 覆盖语义：同一幽灵只留最新版（先 POST 新对再删旧对，删失败顶多暂留一版）
        if (g.pairId) void deaiApi.deletePair(g.pairId).catch(() => {})
        g.pairId = r.id
        g.lastSubmittedGood = decision.good
        submitted.push(r.id)
      } catch {
        // 提交失败静默——下次保存/切章再试（书签还在）
      }
    }
    if (final) tracked.delete(key)
  }
  return submitted
}

/** 切章定稿 + 聚合提示（含按批撤销——6 秒胶囊先例扩展）。 */
export async function finalizeGhostPairs(
  chapterId: string,
  bookId: string | null,
  readText: (from: number, to: number) => string,
): Promise<number> {
  const submitted = await flushGhostPairs(chapterId, bookId, readText, true)
  if (submitted.length > 0) {
    const { useToast } = await import('../../../composables/useToast')
    useToast().showToast(
      `本章为你记下 ${submitted.length} 对改稿样本（AI 原稿 vs 你的改定版）`,
      'success', 6000,
      {
        label: '撤销',
        onClick: () => {
          for (const id of submitted) void deaiApi.deletePair(id).catch(() => {})
          useToast().showToast('已撤销本章全部改稿样本', 'info')
        },
      },
    )
  }
  return submitted.length
}

/** 章内会话重置（换书）——书签是一章会话的寿命。 */
export function resetGhostPairs(): void {
  tracked.clear()
}
