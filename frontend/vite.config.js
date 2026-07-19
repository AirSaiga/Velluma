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

const BACKEND_PORT = resolveBackendPort()
const BACKEND_URL = `http://127.0.0.1:${BACKEND_PORT}`

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
    port: 5175,
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
            // 添加请求超时处理
            proxyReq.setTimeout(30000, () => {
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
