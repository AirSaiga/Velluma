/**
 * 应用级设置入口开关（模块级单例，与 useToast/useConfirmDialog 同模式）。
 *
 * 2026-09-15 拆分：旧「设置」大弹窗一分为三——
 * - 外观 → 左缘无遮罩抽屉 AppearancePanel（换肤即时可见整个应用，开放入门）
 * - 模型与 API → 独立弹窗 ApiSettingsModal（Key/厂商/预设/向量/代理）
 * - 设置 → 通用弹窗 AppSettingsModal（仅通知偏好）
 * 三者互不嵌套、可并存（弹窗 z 层恒高于抽屉）。
 */
import { ref } from 'vue'

/** 通用设置弹窗（通知偏好） */
const visible = ref(false)
/** 模型与 API 弹窗 */
const apiVisible = ref(false)
/** 外观抽屉（toggle 语义：再点左下「外观」钮即收） */
const appearanceVisible = ref(false)

export function useAppSettings() {
  function open() {
    visible.value = true
  }
  function close() {
    visible.value = false
  }
  function openApi() {
    apiVisible.value = true
  }
  function closeApi() {
    apiVisible.value = false
  }
  function toggleAppearance() {
    appearanceVisible.value = !appearanceVisible.value
  }
  function closeAppearance() {
    appearanceVisible.value = false
  }

  return {
    visible,
    open,
    close,
    apiVisible,
    openApi,
    closeApi,
    appearanceVisible,
    toggleAppearance,
    closeAppearance,
  }
}
