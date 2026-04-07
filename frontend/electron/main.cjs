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

function waitForPort(port, options = {}) {
  const { 
    timeout = 30000, 
    interval = 500,
    serviceName = 'Service'
  } = options
  
  return new Promise((resolve, reject) => {
    const startTime = Date.now()
    let currentAttempt = 0
    
    const check = () => {
      currentAttempt++
      const client = new net.Socket()
      client.setTimeout(2000)
      
      client.once('connect', () => {
        client.destroy()
        console.log(`[${serviceName}] Port ${port} ready (${currentAttempt} attempts)`)
        resolve({ port, attempts: currentAttempt, elapsed: Date.now() - startTime })
      })
      
      client.once('error', () => {
        client.destroy()
        if (Date.now() - startTime > timeout) {
          reject(new Error(`${serviceName} timeout after ${timeout}ms`))
        } else {
          setTimeout(check, interval)
        }
      })
      
      client.once('timeout', () => {
        client.destroy()
        setTimeout(check, interval)
      })
      
      client.connect(port, '127.0.0.1')
    }
    
    check()
  })
}

function checkHealth(url, options = {}) {
  const { timeout = 5000, retries = 3 } = options
  
  return new Promise((resolve) => {
    let attempts = 0
    
    const tryCheck = () => {
      attempts++
      const req = http.get(url, { timeout }, (res) => {
        if (res.statusCode < 500) {
          resolve({ healthy: true, statusCode: res.statusCode, attempts })
        } else if (attempts < retries) {
          setTimeout(tryCheck, 1000)
        } else {
          resolve({ healthy: false, statusCode: res.statusCode, attempts })
        }
      })
      
      req.on('error', () => {
        if (attempts < retries) {
          setTimeout(tryCheck, 1000)
        } else {
          resolve({ healthy: false, error: 'Request failed', attempts })
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

async function startBackend() {
  const port = FIXED_BACKEND_PORT
  console.log(`[Backend] Checking port ${port}...`)

  try {
    await waitForPort(port, { timeout: 500, serviceName: 'Backend' })
    console.log(`[Backend] Already running on port ${port}`)
    return { port, started: false }
  } catch {
    // Not running, need to start
  }
  
  const projectRoot = dirname(dirname(__dirname))
  const venvPaths = [
    join(projectRoot, '.venv', 'Scripts', 'python.exe'),
    join(projectRoot, 'venv', 'Scripts', 'python.exe'),
  ]
  
  let pythonPath = venvPaths.find(p => require('fs').existsSync(p))
  if (!pythonPath) {
    throw new Error('Python venv not found')
  }
  
  console.log(`[Backend] Starting: ${pythonPath}`)

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
    console.error(`[Backend] ${data.toString().trim()}`)
  })

  backendProcess.on('close', (code) => {
    console.log(`[Backend] Exited with code ${code}`)
    backendProcess = null
  })

  await waitForPort(port, { timeout: 60000, serviceName: 'Backend' })
  
  const health = await checkHealth(`http://127.0.0.1:${port}/api/health`, { retries: 5 })
  console.log(`[Backend] Health check:`, health.healthy ? 'OK' : 'Warning')
  
  return { port, started: true }
}

async function waitForFrontend() {
  const port = FIXED_VITE_PORT
  console.log(`[Frontend] Waiting for port ${port}...`)
  
  await waitForPort(port, { timeout: 60000, serviceName: 'Frontend' })
  console.log(`[Frontend] Ready on port ${port}`)
  return { port }
}

// =============================================================================
// 窗口管理
// =============================================================================

function createLoadingWindow() {
  const win = new BrowserWindow({
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
  
  const html = `<!DOCTYPE html>
<html>
<head>
  <meta charset="UTF-8">
  <style>
    * { margin: 0; padding: 0; box-sizing: border-box; }
    body {
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
    @keyframes spin { to { transform: rotate(360deg); } }
    h2 { margin: 0 0 10px; font-size: 18px; font-weight: 500; }
    p { margin: 0; font-size: 13px; opacity: 0.7; }
  </style>
</head>
<body>
  <div class="spinner"></div>
  <h2>Velluma AI</h2>
  <p>正在启动服务...</p>
</body>
</html>`
  
  win.loadURL(`data:text/html;charset=utf-8,${encodeURIComponent(html)}`)
  return win
}

async function createMainWindow() {
  let loadingWin = null
  
  if (isDev) {
    loadingWin = createLoadingWindow()
  }
  
  let backendResult = { port: FIXED_BACKEND_PORT }
  let vitePort = FIXED_VITE_PORT
  
  try {
    if (isDev) {
      if (process.env.VELLUMA_SERVICES_READY !== '1') {
        backendResult = await startBackend()
      } else {
        console.log('[Main] Services ready flag set')
        await waitForPort(FIXED_BACKEND_PORT, { timeout: 10000, serviceName: 'Backend' })
      }
      
      await waitForFrontend()
      
      if (loadingWin && !loadingWin.isDestroyed()) {
        loadingWin.close()
      }
    }
    
    const win = new BrowserWindow({
      width: 1400,
      height: 900,
      minWidth: 1000,
      minHeight: 700,
      show: true,
      webPreferences: {
        nodeIntegration: false,
        contextIsolation: true,
        preload: join(__dirname, 'preload.cjs')
      }
    })
    
    if (isDev) {
      session.defaultSession.webRequest.onHeadersReceived((details, callback) => {
        callback({
          responseHeaders: {
            ...details.responseHeaders,
            'Content-Security-Policy': ["default-src 'self'; script-src 'self' 'unsafe-eval' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; connect-src 'self' http://localhost:* ws://localhost:* http://127.0.0.1:* ws://127.0.0.1:*"]
          }
        })
      })
    }
    
    if (isDev) {
      const url = `http://localhost:${vitePort}?backendPort=${backendResult.port}`
      console.log(`[Main] Loading: ${url}`)
      
      // Retry loading
      let attempts = 0
      const maxAttempts = 10
      
      while (attempts < maxAttempts) {
        attempts++
        try {
          await win.loadURL(url)
          console.log(`[Main] Loaded after ${attempts} attempts`)
          win.webContents.openDevTools()
          break
        } catch (err) {
          if (attempts >= maxAttempts) throw err
          console.log(`[Main] Load attempt ${attempts} failed, retrying...`)
          await new Promise(r => setTimeout(r, 1000))
        }
      }
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

function createDebugWindow(backendPort, vitePort) {
  const debugWin = new BrowserWindow({
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
    debugWin.loadURL(`http://localhost:${vitePort}?backendPort=${backendPort}&debug=true`)
  } else {
    debugWin.loadFile(join(__dirname, '../dist/index.html'), { query: { debug: 'true' } })
  }

  return debugWin
}

// =============================================================================
// 应用生命周期
// =============================================================================

app.whenReady().then(async () => {
  try {
    const { win, backendPort, vitePort } = await createMainWindow()
    
    const debugWin = createDebugWindow(backendPort, vitePort)
    
    debugWin.on('closed', () => {})
    
    ipcMain.on('prompt-data', (event, data) => {
      if (debugWin && !debugWin.isDestroyed()) {
        debugWin.webContents.send('prompt-data', data)
      }
    })
    
    win.on('closed', () => {
      if (!debugWin.isDestroyed()) debugWin.close()
    })

    app.on('activate', () => {
      if (BrowserWindow.getAllWindows().length === 0) {
        createMainWindow()
      }
    })
    
  } catch (err) {
    console.error('[App] Failed:', err)
    const { dialog } = require('electron')
    dialog.showErrorBox('启动失败', err.message)
    app.quit()
  }
})

app.on('window-all-closed', () => {
  if (backendProcess) {
    console.log('[App] Stopping backend...')
    backendProcess.kill()
  }
  if (process.platform !== 'darwin') {
    app.quit()
  }
})

process.on('uncaughtException', (err) => {
  console.error('[App] Uncaught:', err)
})
