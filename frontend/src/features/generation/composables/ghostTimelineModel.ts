import { computed, type ComputedRef } from 'vue'
import type { GenerationSession } from './useGenerationSession'
import { ghostActive } from './useGhostDraft'

/**
 * NLE-ADF 2.0 幽灵时间线共享数据模型（GhostTimeline 组件与顶栏进度共用）。
 *
 * 节点语义：
 *   locked ● = 已锁碎片 / 已锁拍的全部节点
 *   active ◐ = 当前创作拍（或渲染中/待裁决拍）的下一个节点
 *   future ○ = 估算的未来碎片（拍 target_word_count ÷ 100 预算）
 * 分母 = Σ 各拍估算碎片（写超了轴自然生长：committed 超过估算时轴伸长）。
 */

export interface TimelineNode {
  key: string
  beatId: string
  state: 'locked' | 'active' | 'future'
  /** 当前创作拍内的碎片序号（1-based；0=不可回拨节点） */
  fragIndex: number
  beatIndex: number
}

/** 拍的估算碎片数（每碎片 ~200 字，单拍 clamp 1..8——章级节点 ~12-36，
 *  防大字数章节时间轴过密过吵：4800 字章按 100 字/点会出 48 个点的噪音轴） */
export function estimateFragments(targetWordCount?: number): number {
  return Math.min(8, Math.max(1, Math.round((targetWordCount || 500) / 200)))
}

export function useTimelineModel(session: GenerationSession): {
  nodes: ComputedRef<TimelineNode[]>
  lockedCount: ComputedRef<number>
  totalCount: ComputedRef<number>
  timelineVisible: ComputedRef<boolean>
} {
  const nodes = computed<TimelineNode[]>(() => {
    if (!session.steppingEnabled.value || !session.beatSlots.value.length) return []
    const out: TimelineNode[] = []
    const locked = session.lockedBeatIds.value
    const counts = session.fragmentCounts.value
    const currentBeatId =
      session.authoringBeatId.value || session.renderingBeatId.value || session.readyBeatId.value
    session.beatSlots.value.forEach((slot, beatIndex) => {
      const estimated = estimateFragments(slot.target_word_count)
      const committed = counts[slot.beat_id] || 0
      const isCurrent = slot.beat_id === currentBeatId
      const isLocked = locked.has(slot.beat_id)
      const total = Math.max(estimated, committed)
      for (let k = 1; k <= total; k++) {
        let state: TimelineNode['state'] = 'future'
        if (isLocked) {
          state = 'locked'
        } else if (isCurrent) {
          if (k <= committed) state = 'locked'
          else if (k === committed + 1) state = 'active'
        }
        out.push({
          key: `${slot.beat_id}:${k}`,
          beatId: slot.beat_id,
          state,
          fragIndex: isCurrent && state === 'locked' ? k : 0,
          beatIndex,
        })
      }
    })
    return out
  })

  const lockedCount = computed(() => nodes.value.filter((n) => n.state === 'locked').length)
  const totalCount = computed(() => nodes.value.length)
  const timelineVisible = computed(() => nodes.value.length > 0)

  return { nodes, lockedCount, totalCount, timelineVisible }
}

export { ghostActive }
