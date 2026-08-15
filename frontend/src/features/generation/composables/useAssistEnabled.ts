/**
 * AI 辅助总开关（UX 修复：给作者「纯手写模式」）。
 *
 * 关闭后：打字不自动激活 adaptive 辅助层（无停顿心跳/卡片舱/走向卡），
 * Space 恢复为普通空格输入，点火卡不再弹出。
 * 默认开启（保持 NLE-ADF 3.0 既有交互不变）。
 *
 * 模块级单例 ref（同 useToast 模式），localStorage 持久化。
 */
import { ref } from 'vue'

const STORAGE_KEY = 'velluma:assist:enabled'

function load(): boolean {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    return raw === null ? true : raw === '1'
  } catch {
    return true
  }
}

export const assistEnabled = ref<boolean>(load())

export function setAssistEnabled(v: boolean): void {
  assistEnabled.value = v
  try {
    localStorage.setItem(STORAGE_KEY, v ? '1' : '0')
  } catch {
    // 静默：持久化失败不影响本次会话内生效
  }
}
