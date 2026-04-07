const { app, BrowserWindow, session, ipcMain } = require('electron')
const { join, dirname } = require('path')
const { spawn } = require('child_process')
const net = require('net')
const http = require('http')

const isDev = process.env.NODE_ENV !== 'production' && !app.isPackaged

let backendProcess = null

const FIXED_VITE_PORT = 5175
const FIXED_BACKEND_PORT = parseInt(process.env.VELLUMA_BACKEND_PORT) || 8002

// =============================================================================
// 工具函数
// =============================================================================

/**
 * 等待端口就绪 - 带重试机制
 */
function waitForPort(port, options = {}) {
  const { 
    timeout = 30000, 
    interval = 500,
    serviceName = 'Service'
  } = options
  
  return new Promise((resolve, reject) => {
    const startTime = Date.now()
    const attempts = Math.ceil(timeout / interval)
    let currentAttempt = 0
    
    const check = () => {
      currentAttempt++
      const client = new net.Socket()
      client.setTimeout(2000)
      
      client.connect(port, '127.0.0.1', () => {
        client.destroy()
        console.log(`[${serviceName}] Port ${port} is ready after ${currentAttempt} attempts`)
        resolve({ port, attempts: currentAttempt, elapsed: Date.now() - startTime })
      })
      
      client.on('error', (err) => {
        client.destroy()
        if (Date.now() - startTime > timeout) {
          reject(new Error(`${serviceName} timeout after ${timeout}ms`))
        } else {
          setTimeout(check, interval)
        }
      })
      
      client.on('timeout', () => {
        client.destroy()
        setTimeout(check, interval)
      })
    }
    
    check()
  })
}

/**
 * 检查 HTTP 服务健康状态
 */
function checkHealth(url, options = {}) {
  const { timeout = 5000, retries = 3 } = options
  
  return new Promise((resolve, reject) => {
    let attempts = 0
    
    const tryCheck = () => {
      attempts++
      const req = http.get(url, { timeout }, (res) => {
        if (res.statusCode < 500) {
          resolve({ healthy: true, statusCode: res.statusCode, attempts })
        } else {
          if (attempts < retries) {
            setTimeout(tryCheck, 1000)
          } else {
            resolve({ healthy: false, statusCode: res.statusCode, attempts })
          }
        }
      })
      
      req.on('error', (err) => {
        if (attempts < retries) {
          setTimeout(tryCheck, 1000)
        } else {
          resolve({ healthy: false, error: err.message, attempts })
        }
      })
      
      req.on('timeout', () => {
        req.destroy()
        if (attempts < retries) {
          setTimeout(tryCheck, 1000)
        } else {
          resolve({ healthy: false, error: 'Timeout', attempts })
        }
      })
    }
    
    tryCheck()
  })
}

/**
 * 启动后端服务
 */
async function startBackend() {
  const port = FIXED_BACKEND_PORT
  console.log(`[Backend] Checking port ${port}...`)

  // 检查是否已在运行
  try {
    await waitForPort(port, { timeout: 500, serviceName: 'Backend Check' })
    console.log(`[Backend] Already running on port ${port}`)
    return { port, started: false }
  } catch {
    // Not running, need to start
  }
  
  const projectRoot = dirname(dirname(__dirname))
  const venvPaths = [
    join(projectRoot, '.venv', 'Scripts', 'python.exe'),
    join(projectRoot, 'venv', 'Scripts', 'python.exe'),
    join(projectRoot, '.venv', 'bin', 'python'),
    join(projectRoot, 'venv', 'bin', 'python'),
  ]
  
  let pythonPath = venvPaths.find(p => require('fs').existsSync(p))
  if (!pythonPath) {
    throw new Error('Python venv not found')
  }
  
  console.log(`[Backend] Starting with Python: ${pythonPath}`)

  backendProcess = spawn(pythonPath, ['-m', 'backend.main'], {
    cwd: projectRoot,
    env: { ...process.env, VELLUMA_PORT: port.toString(), PYTHONUNBUFFERED: "1" },
    stdio: ['ignore', 'pipe', 'pipe']
  })

  backendProcess.on('error', (err) => {
    console.error('[Backend] Spawn failed:', err)
  })

  backendProcess.stdout.on('data', (data) => {
    console.log(`[Backend] ${data.toString().trim()}`)
  })

  backendProcess.stderr.on('data', (data) => {
    console.error(`[Backend Error] ${data.toString().trim()}`)
  })

  backendProcess.on('close', (code) => {
    console.log(`[Backend] Process exited with code ${code}`)
    backendProcess = null
  })

  // 等待后端就绪
  await waitForPort(port, { 
    timeout: 60000, 
    serviceName: 'Backend',
    interval: 500 
  })
  
  // 健康检查
  const health = await checkHealth(`http://127.0.0.1:${port}/health`, { retries: 5 })
  if (!health.healthy) {
    console.warn('[Backend] Health check warning:', health)
  }
  
  console.log(`[Backend] Ready on port ${port}`)
  return { port, started: true }
}

/**
 * 等待前端服务就绪
 */
async function waitForFrontend() {
  const port = FIXED_VITE_PORT
  console.log(`[Frontend] Waiting for Vite on port ${port}...`)
  
  const result = await waitForPort(port, { 
    timeout: 60000, 
    serviceName: 'Frontend',
    interval: 500 
  })
  
  console.log(`[Frontend] Vite ready on port ${port}`)
  return { port }
}

// =============================================================================
// 窗口管理
// =============================================================================

/**
 * 创建加载窗口
 */
function createLoadingWindow() {
  const loadingWin = new BrowserWindow({
    width: 400,
    height: 300,
    frame: false,
    alwaysOnTop: true,
    resizable: false,
    webPreferences: {
      nodeIntegration: false,
      contextIsolation: true
    }
  })
  
  loadingWin.loadURL(`data:text/html;charset=utf-8,${encodeURIComponent(`
    <!DOCTYPE html>
    <html>
    <head>
      <style>
        body {
          margin: 0;
          padding: 0;
          display: flex;
          flex-direction: column;
          align-items: center;
          justify-content: center;
          height: 100vh;
          background: linear-gradient(135deg, #1a1a2e 0%, #16213e 100%);
          color: #fff;
          font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
        }
        .spinner {
          width: 40px;
          height: 40px;
          border: 3px solid rgba(255,255,255,0.1);
          border-top-color: #00d4aa;
          border-radius: 50%;
          animation: spin 1s linear infinite;
          margin-bottom: 20px;
        }
        @keyframes spin {
          to { transform: rotate(360deg); }
        }
        h2 { margin: 0 0 10px; font-size: 18px; font-weight: 500; }
        p { margin: 0; font-size: 13px; opacity: 0.7; }
        .status { margin-top: 15px; font-size: 12px; color: #00d4aa; }
      </style>
    </head>
    <body>
      <div class="spinner"></div>
      <h2>Velluma AI</h2>
      <p>正在启动服务...</p>
      <p class="status" id="status">检查后端服务</p>
      <script>
        const statuses = [
          '检查后端服务',
          '连接前端开发服务器',
          '加载应用资源',
          '即将完成...'
        ];
        let i = 0;
        setInterval(() => {
          document.getElementById('status').textContent = statuses[i % statuses.length];
          i++;
        }, 2000);
      </script>
    </body>
    </html>
  `)}`)
  
  return loadingWin
}

/**
 * 创建主窗口
 */
async function createMainWindow() {
  let loadingWin = null
  
  if (isDev) {
    loadingWin = createLoadingWindow()
  }
  
  let backendResult = { port: FIXED_BACKEND_PORT }
  let vitePort = FIXED_VITE_PORT
  
  try {
    // 开发模式下确保服务就绪
    if (isDev) {
      // 1. 检查/启动后端
      if (process.env.VELLUMA_SERVICES_READY !== '1') {
        backendResult = await startBackend()
      } else {
        console.log('[Main] Services marked as ready by launcher')
        await waitForPort(FIXED_BACKEND_PORT, { timeout: 10000, serviceName: 'Backend' })
      }
      
      // 2. 等待前端就绪
      await waitForFrontend()
      
      // 关闭加载窗口
      if (loadingWin && !loadingWin.isDestroyed()) {
        loadingWin.close()
      }
    }
    
    // 创建主窗口
    const win = new BrowserWindow({
      width: 1400,
      height: 900,
      minWidth: 1000,
      minHeight: 700,
      show: true,
      webPreferences: {
        nodeIntegration: false,
        contextIsolation: true,
        preload: join(__dirname, 'preload.cjs'),
        // 添加重连相关的安全设置
        webSecurity: true,
        allowRunningInsecureContent: false
      }
    })
    
    // 开发模式 CSP 设置
    if (isDev) {
      session.defaultSession.webRequest.onHeadersReceived((details, callback) => {
        const csp = "default-src 'self'; " +
          "script-src 'self' 'unsafe-eval' 'unsafe-inline'; " +
          "style-src 'self' 'unsafe-inline'; " +
          "img-src 'self' data: blob:; " +
          "font-src 'self' data:; " +
          "connect-src 'self' http://localhost:* ws://localhost:* http://127.0.0.1:* ws://127.0.0.1:*"
        callback({
          responseHeaders: {
            ...details.responseHeaders,
            'Content-Security-Policy': [csp]
          }
        })
      })
    }
    
    // 加载 URL
    if (isDev) {
      const url = `http://localhost:${vitePort}?backendPort=${backendResult.port}`
      console.log(`[Main] Loading URL: ${url}`)
      
      // 使用 retry 机制加载
      let loadAttempts = 0
      const maxAttempts = 10
      
      const tryLoad = async () => {
        loadAttempts++
        try {
          await win.loadURL(url)
          console.log(`[Main] Loaded successfully after ${loadAttempts} attempts`)
          win.webContents.openDevTools()
        } catch (err) {
          if (loadAttempts < maxAttempts) {
            console.log(`[Main] Load attempt ${loadAttempts} failed, retrying in 1s...`)
            setTimeout(tryLoad, 1000)
          } else {
            console.error('[Main] Failed to load after max attempts')
            throw err
          }
        }
      }
      
      await tryLoad()
    } else {
      win.loadFile(join(__dirname, '../dist/index.html'))
    }
    
    return { win, backendPort: backendResult.port, vitePort }
    
  } catch (err) {
    if (loadingWin && !loadingWin.isDestroyed()) {
      loadingWin.close()
    }
    throw err
  }
}

/**
 * 创建调试窗口
 */
function createDebugWindow(backendPort, vitePort) {
  const debugWindow = new BrowserWindow({
    width: 800,
    height: 600,
    title: 'Prompt Debug',
    webPreferences: {
      nodeIntegration: false,
      contextIsolation: true,
      preload: join(__dirname, 'preload.cjs')
    }
  })

  if (isDev) {
    debugWindow.loadURL(`http://localhost:${vitePort}?backendPort=${backendPort}&debug=true`)
  } else {
    debugWindow.loadFile(join(__dirname, '../dist/index.html'), { query: { debug: 'true' } })
  }

  return debugWindow
}

// =============================================================================
// 应用生命周期
// =============================================================================

app.whenReady().then(async () => {
  try {
    const { win, backendPort, vitePort } = await createMainWindow()
    
    let debugWin = createDebugWindow(backendPort, vitePort)
    
    debugWin.on('closed', () => {
      debugWin = null
    })
    
    ipcMain.on('prompt-data', (event, data) => {
      if (debugWin && !debugWin.isDestroyed()) {
        debugWin.webContents.send('prompt-data', data)
      }
    })
    
    // 窗口关闭处理
    win.on('closed', () => {
      if (debugWin && !debugWin.isDestroyed()) {
        debugWin.close()
      }
    })

    app.on('activate', () => {
      if (BrowserWindow.getAllWindows().length === 0) {
        createMainWindow()
      }
    })
    
  } catch (err) {
    console.error('[App] Failed to start:', err)
    
    // 显示错误对话框
    const { dialog } = require('electron')
    dialog.showErrorBox('启动失败', `无法启动 Velluma: ${err.message}`)
    app.quit()
  }
})

app.on('window-all-closed', () => {
  if (backendProcess) {
    console.log('[App] Stopping backend process...')
    backendProcess.kill()
    backendProcess = null
  }
  if (process.platform !== 'darwin') {
    app.quit()
  }
})

// 处理未捕获的错误
process.on('uncaughtException', (err) => {
  console.error('[App] Uncaught exception:', err)
})

process.on('unhandledRejection', (reason, promise) => {
  console.error('[App] Unhandled rejection at:', promise, 'reason:', reason)
})
