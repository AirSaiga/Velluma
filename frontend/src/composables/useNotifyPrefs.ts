import { ref } from 'vue'

/**
 * 通知偏好（模块级单例，与 useToast/useConfirmDialog 同模式）。
 *
 * 职责：管理"生成完成提示"的两层开关（应用内弹窗 / Windows 系统通知）。
 * 存储：localStorage key `velluma:prefs:notify`。
 * 默认：两项均开。
 */

export interface NotifyPrefs {
  /** 应用内完成弹窗（前台时弹出） */
  inApp: boolean
  /** Windows 系统通知（后台时由主进程兜底判断焦点后弹出） */
  system: boolean
}

const STORAGE_KEY = 'velluma:prefs:notify'

function loadPrefs(): NotifyPrefs {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    if (!raw) return { inApp: true, system: true }
    const parsed = JSON.parse(raw)
    return {
      inApp: typeof parsed.inApp === 'boolean' ? parsed.inApp : true,
      system: typeof parsed.system === 'boolean' ? parsed.system : true,
    }
  } catch {
    return { inApp: true, system: true }
  }
}

// 模块级单例状态（所有 useNotifyPrefs() 调用共享同一份）
const prefs = ref<NotifyPrefs>(loadPrefs())

export function useNotifyPrefs() {
  function setInApp(v: boolean) {
    prefs.value = { ...prefs.value, inApp: v }
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(prefs.value))
    } catch {
      // localStorage 满：静默
    }
  }

  function setSystem(v: boolean) {
    prefs.value = { ...prefs.value, system: v }
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(prefs.value))
    } catch {
      // 静默
    }
  }

  return {
    prefs,
    setInApp,
    setSystem,
  }
}
