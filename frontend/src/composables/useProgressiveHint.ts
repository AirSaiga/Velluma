import { computed, ref } from 'vue'
import type { ComputedRef, Ref } from 'vue'
import { loadUiPrefs, saveUiPrefs } from './useUiPrefs'

/**
 * 渐进引导（引导体系重构 2026-09-20）：就地提示的「看过 N 次自动淡出」控制器。
 *
 * 消费契约：提示确实显示过才算一次（组件在「本回合显示过」的落沿调 markSeen），
 * 次数持久化在 useUiPrefs.hintsSeen（localStorage velluma_ui_prefs_v1）。
 * 同一 key 多处消费共享同一实例（模块级缓存）——各自 new ref 会在
 * CursorLayer 的浮层可见性判断与行内组件之间漂移。
 */
export interface ProgressiveHint {
  visible: ComputedRef<boolean>
  seenCount: Ref<number>
  markSeen: () => void
}

const DEFAULT_MAX_SHOWS = 3
const _cache = new Map<string, ProgressiveHint>()

export function useProgressiveHint(key: string, maxShows: number = DEFAULT_MAX_SHOWS): ProgressiveHint {
  const cached = _cache.get(key)
  if (cached) return cached

  const seenCount = ref(Number(loadUiPrefs().hintsSeen?.[key]) || 0)
  const visible = computed(() => seenCount.value < maxShows)

  function markSeen(): void {
    seenCount.value += 1
    const prefs = loadUiPrefs()
    saveUiPrefs({ ...prefs, hintsSeen: { ...prefs.hintsSeen, [key]: seenCount.value } })
  }

  const instance: ProgressiveHint = { visible, seenCount, markSeen }
  _cache.set(key, instance)
  return instance
}
