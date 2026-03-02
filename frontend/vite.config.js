import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

export default defineConfig({
  plugins: [
    vue({
      script: {
        defineModel: true
      }
    })
  ],
  server: {
    port: 5175,
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:8002',
        changeOrigin: true
      }
    }
  },
  build: {
    outDir: 'dist',
    assetsDir: 'assets'
  }
})
