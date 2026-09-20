import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import fs from 'fs'
import path from 'path'
import { fileURLToPath } from 'url'

const __dirname = path.dirname(fileURLToPath(import.meta.url))

// 动态读取后端端口：优先环境变量 → 端口文件 → 默认值 8002
const PORT_FILE = path.resolve(__dirname, '..', 'data', 'port.txt')
function resolveBackendPort() {
  const envPort = process.env.VELLUMA_BACKEND_PORT
  if (envPort) return parseInt(envPort) || 8002
  try {
    if (fs.existsSync(PORT_FILE)) {
      const port = parseInt(fs.readFileSync(PORT_FILE, 'utf-8').trim(), 10)
      if (!isNaN(port) && port > 0) return port
    }
  } catch (e) {
    // 读取失败，使用默认值
  }
  return 8002
}

// 动态读取前端端口：优先环境变量 → 端口文件 → 默认值 5175
// 与后端端口协商机制对称（data/port.txt），避免与其它项目（如 world-atlas）的 Vite 冲突
const FRONTEND_PORT_FILE = path.resolve(__dirname, '..', 'data', 'frontend_port.txt')
function resolveFrontendPort() {
  const envPort = process.env.VELLUMA_FRONTEND_PORT
  if (envPort) return parseInt(envPort) || 5175
  try {
    if (fs.existsSync(FRONTEND_PORT_FILE)) {
      const port = parseInt(fs.readFileSync(FRONTEND_PORT_FILE, 'utf-8').trim(), 10)
      if (!isNaN(port) && port > 0) return port
    }
  } catch (e) {
    // 读取失败，使用默认值
  }
  return 5175
}

const BACKEND_PORT = resolveBackendPort()
const BACKEND_URL = `http://127.0.0.1:${BACKEND_PORT}`
const FRONTEND_PORT = resolveFrontendPort()

export default defineConfig({
  plugins: [
    vue({
      script: {
        defineModel: true
      }
    })
  ],
  resolve: {
    alias: {
      '@': path.resolve(__dirname, 'src')
    }
  },
  server: {
    host: "127.0.0.1",
    port: FRONTEND_PORT,
    // strictPort: true 保留 —— 端口已由启动脚本（scripts/dev/start-all.ps1、scripts/dev/start-frontend.ps1、
    // scripts/macos/dev/ 等，全端契约见 scripts/check_launcher_contract.py）预先扫描为空闲，
    // 若仍冲突则直接报错（不自动换端口，避免与 Electron 加载的 URL 不一致）
    strictPort: true,
    proxy: {
      '/api': {
        target: BACKEND_URL,
        changeOrigin: true,
        // 代理错误处理 - 当后端不可用时提供友好的错误信息
        configure: (proxy, options) => {
          proxy.on('error', (err, req, res) => {
            console.log('[Vite Proxy] Backend connection error:', err.message)
            if (!res.headersSent) {
              res.writeHead(503, {
                'Content-Type': 'application/json',
              })
              res.end(JSON.stringify({
                error: 'Backend not available',
                message: '后端服务暂时不可用，请稍后重试',
                retryable: true
              }))
            }
          })
          proxy.on('proxyReq', (proxyReq, req, res) => {
            // SSE 长连接端点不设超时，避免长流被代理掐断。
            // 2026-09-04 审计修复：白名单已过期——advance-beat 随 BS-ADF 归档，
            // 现役主 SSE /adaptive/stitch-ghost 与 /style/audition 不含旧关键词，
            // 落入下方 120s 超时桶（stitch-ghost 先完整生成含最多 3 次返修环
            // LLM 调用再播帧，慢模型下超 120s 静默被掐=「续写失败」无终帧）。
            const url = req.url || ''
            const isSse =
              url.includes('stitch-ghost') ||
              url.includes('audition') ||
              url.includes('generate') ||
              url.includes('refinery') ||
              url.includes('advance-beat') // 已归档引擎，保留匹配仅为兼容旧 dev 会话
            if (isSse) return
            // 普通请求添加超时处理
            proxyReq.setTimeout(120000, () => {
              console.log('[Vite Proxy] Request timeout')
              proxyReq.destroy()
            })
          })
        }
      }
    }
  },
  build: {
    outDir: 'dist',
    assetsDir: 'assets'
  },
  // 开发环境优化
  optimizeDeps: {
    include: ['vue', '@tiptap/starter-kit']
  }
})
