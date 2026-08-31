import { ref } from 'vue'

/**
 * deai 训练对两步配对状态机（docs/deai-integration.md §5a）。
 *
 * 流程：选中卡片舱生成的原样文本 →「记改前」暂存 → 作者亲手改 →
 * 选中改后文本 →「记改后」成对提交（RichTextEditor 负责调 deaiApi.savePair）。
 *
 * 状态为模块级单例：浮窗随选区开合销毁重建，pending 必须跨开合存活；
 * 换书作废（bookKey 守卫）。纯状态机，零 IO——API 调用与 toast 留在组件层，
 * 便于单测。
 */

/** 一条待完成的配对（记改前暂存） */
export interface PendingBad {
  text: string
  bookKey: string
  ts: number
}

export interface MarkResult {
  ok: boolean
  message: string
  /** markGood 成功时携带暂存的改前文本（调用方提交成功后自行 clearPending） */
  bad?: string
}

/** 契约 C1 输入上限，与后端 BAD_MAX_CHARS 同步改 */
export const DEAI_BAD_MAX_CHARS = 100

const pendingBad = ref<PendingBad | null>(null)

export function useDeaiPairMark() {
  /** 第一步：暂存改前文本。超 100 字契约窗直接拒（标记了也进不了训练集）。 */
  function markBad(text: string, bookKey: string): MarkResult {
    const trimmed = (text || '').trim()
    if (!trimmed) return { ok: false, message: '请先选中要标记的文本' }
    if (trimmed.length > DEAI_BAD_MAX_CHARS) {
      return {
        ok: false,
        message: `这段 ${trimmed.length} 字超过 ${DEAI_BAD_MAX_CHARS} 字——小模型只学百字内的短段，选短一点`,
      }
    }
    pendingBad.value = { text: trimmed, bookKey, ts: Date.now() }
    return {
      ok: true,
      message: `已记改前（${trimmed.length} 字）——改完这段后，选中改后的文字点「记改后」`,
    }
  }

  /**
   * 第二步：取改后文本与暂存配对。成功**不清** pending——调用方 API 提交
   * 成功后再 clearPending（失败可直接重试）；换书则清空作废。
   */
  function markGood(text: string, bookKey: string): MarkResult {
    const pending = pendingBad.value
    if (!pending) {
      return { ok: false, message: '先选中一段原文点「记改前」，改完再回来点「记改后」' }
    }
    if (pending.bookKey !== bookKey) {
      pendingBad.value = null
      return { ok: false, message: '改前标记来自另一本书，已作废——请从「记改前」重新开始' }
    }
    const good = (text || '').trim()
    if (!good) return { ok: false, message: '请先选中改后的文本' }
    return { ok: true, bad: pending.text, message: '' }
  }

  function clearPending() {
    pendingBad.value = null
  }

  return { pendingBad, markBad, markGood, clearPending }
}
