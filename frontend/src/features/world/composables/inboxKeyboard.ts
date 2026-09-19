/**
 * 收件箱键盘裁决（02 候选回流修缮 M3）——纯函数，三宿主共用：
 * WorldSceneSlice 收件箱 / WorldView 待确认抽屉 / BatchAcceptModal 批量预览。
 *
 * 键位契约：↑/↓ 循环移动光标；→/Enter = ✓ 采纳；←/Delete/Backspace = ✗ 丢弃。
 * 批量模态复用移动键 + Space 勾选剔除（toggle 语义由宿主解释，此处只认键位）。
 * 鼠标路径零变化——键盘是并行动线，不是替代。
 */

/** ↑/↓ → 移动量；其他键 0（不拦截） */
export function inboxNavKey(key: string): -1 | 1 | 0 {
  if (key === 'ArrowUp') return -1
  if (key === 'ArrowDown') return 1
  return 0
}

/** 光标循环移动（首行按 ↑ 到末行）；空列表返回 -1（无光标态） */
export function moveInboxIndex(index: number, delta: -1 | 1, length: number): number {
  if (length <= 0) return -1
  const cur = index >= 0 && index < length ? index : 0
  return (cur + delta + length) % length
}

/** 裁决键 → 动作；非裁决键 null（不拦截） */
export function verdictFromKey(key: string): 'accept' | 'reject' | null {
  if (key === 'ArrowRight' || key === 'Enter') return 'accept'
  if (key === 'ArrowLeft' || key === 'Delete' || key === 'Backspace') return 'reject'
  return null
}

/** 批量预览勾选键（Space）；其他 false */
export function isToggleKey(key: string): boolean {
  return key === ' '
}
