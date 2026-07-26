/// <reference types="vite/client" />

declare module '*.vue' {
  import type { DefineComponent } from 'vue'
  const component: DefineComponent<{}, {}, any>
  export default component
}

interface ElectronAPI {
  /** 触发生成完成的 Windows 系统通知（主进程会判断窗口焦点兜底分层） */
  showCompletionNotification: (payload: { title?: string; body?: string }) => void
}

declare global {
  interface Window {
    electronAPI?: ElectronAPI
  }
}

export {}
