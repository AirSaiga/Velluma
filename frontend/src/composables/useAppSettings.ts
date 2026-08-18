/**
 * 全局设置弹窗开关（模块级单例，与 useToast/useConfirmDialog 同模式）。
 *
 * 设置内容是应用级配置（模型 / 代理 / 通知偏好，全局生效、与书籍无关），
 * 入口钉在 AppRail 底部齿轮，任何页面（含无书的书架页）均可达。
 */
import { ref } from 'vue'

const visible = ref(false)

export function useAppSettings() {
  function open() {
    visible.value = true
  }

  function close() {
    visible.value = false
  }

  return { visible, open, close }
}
