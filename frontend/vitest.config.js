import { defineConfig } from 'vitest/config'

// Velluma 前端单测配置（独立于 vite.config.js 的应用构建配置）。
// engine 层是纯 TS，不依赖 Vue 运行时，测试无需 jsdom。
export default defineConfig({
  test: {
    include: ['src/**/__tests__/**/*.test.ts'],
  },
})
