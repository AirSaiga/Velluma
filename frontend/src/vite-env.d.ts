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
}

declare global {
  interface Window {
    electronAPI?: ElectronAPI
  }
}

export {}
