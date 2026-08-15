import { ref, watch } from 'vue'
import { chapterEditorHandle } from '../../chapter-editor/editorHandle'
import type { DirectionCard } from '../../../services/api/domain/adaptive.api'
import { computeCursorDockPos, hideSparkDock } from './useSparkDock'

/**
 * NLE-ADF 走向卡舱（Beat Dock）状态控制器。
 *
 * 定位：段落级连写（burst）的方向选择器。卡片舱给的是"下几句话的镜头碎片"，
 * 走向卡给的是"接下来几段的剧情走向"（后端层 3 推测的首 beat，一句话级）。
 *
 * 交互：
 * - Ctrl+Space（或卡片舱「多写几段」按钮）→ 光标处弹出 2-3 张走向卡 + 自由发挥
 * - 数字键 1~4 / 点击 → 选定走向，立即触发 burst 连写（幽灵草稿形态）
 * - Esc / 打字 / 动光标 → 关闭
 *
 * 数据来源：心跳响应的 direction_cards（useAdaptiveAssist 缓存后经 setBeatCards 注入）。
 * 无卡时舱仍可开（只剩"自由发挥"项）——不阻塞作者的连写意图。
 */

export const beatDockVisible = ref(false)
export const beatDockPos = ref({ top: 0, left: 0 })
export const beatCards = ref<DirectionCard[]>([])

/** 注入心跳缓存的走向卡（由 useAdaptiveAssist 在心跳响应后调用） */
export function setBeatCards(cards: DirectionCard[]): void {
  beatCards.value = cards || []
}

/** 打开走向卡舱（与卡片舱互斥；定位失败则不开） */
export function showBeatDock(): void {
  hideSparkDock()
  const pos = computeCursorDockPos()
  if (!pos) return
  beatDockPos.value = pos
  beatDockVisible.value = true
}

export function hideBeatDock(): void {
  beatDockVisible.value = false
}

// 编辑器活动（打字/动光标）即关闭——与卡片舱的非 sticky 行为一致
function _onEditorActivity(): void {
  if (beatDockVisible.value) hideBeatDock()
}

watch(
  chapterEditorHandle,
  (editor, prev) => {
    prev?.off('update', _onEditorActivity)
    prev?.off('selectionUpdate', _onEditorActivity)
    editor?.on('update', _onEditorActivity)
    editor?.on('selectionUpdate', _onEditorActivity)
  },
  { immediate: true },
)

export function useBeatDock() {
  return {
    beatDockVisible,
    beatDockPos,
    beatCards,
    setBeatCards,
    showBeatDock,
    hideBeatDock,
  }
}
