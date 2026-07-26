/// <reference types="vite/client" />

declare module '*.vue' {
  import type { DefineComponent } from 'vue'
  const component: DefineComponent<{}, {}, any>
  export default component
}

interface ElectronAPI {
  send: (channel: string, data: any) => void
  on: (channel: string, func: (...args: any[]) => void) => void
  removeListener: (channel: string, func: (...args: any[]) => void) => void
  /** 触发生成完成的系统通知（Task 6 会收紧为白名单） */
  showCompletionNotification: (payload: { title?: string; body?: string }) => void
}

declare global {
  interface Window {
    electronAPI?: ElectronAPI
  }
}

export {}
