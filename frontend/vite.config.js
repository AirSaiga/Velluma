import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

const BACKEND_PORT = process.env.VELLUMA_BACKEND_PORT || 8002
const BACKEND_URL = `http://127.0.0.1:${BACKEND_PORT}`

export default defineConfig({
  plugins: [
    vue({
      script: {
        defineModel: true
      }
    })
  ],
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
