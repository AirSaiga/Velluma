const { app, BrowserWindow, session, Notification, ipcMain } = require('electron')
const { join, dirname } = require('path')
const { spawn } = require('child_process')
const net = require('net')
const http = require('http')
const fs = require('fs')

const isDev = process.env.NODE_ENV !== 'production' && !app.isPackaged

// 白屏事故收口（2026-09-16，真根因=style.css 主题批的 CSS 相对颜色语法
// `rgb(from color-mix(...))` 在 Electron 28 (Chromium 120) 渲染器上原生崩溃，
// 已改为预计算 rgba——见 style.css 五主题 .dark 块。以下为共存保险，可摘：
// ① 软渲染保险已于 2026-09-17 摘除（app.disableHardwareAcceleration()）：
//    排查期误判 GPU 所加；真根因修复后软件渲染成为全页切换卡顿的主放大器
//    （Leaflet 画布/路由双树过渡/遮罩层逐帧 CPU 光栅）。若白屏复发，先清
//    %APPDATA%\velluma 的 GPUCache 再排查，勿直接加回本行。

// ② renderer 观测：Chromium 层 console/崩溃原因写日志文件——renderer 崩溃在
// Windows 事件日志与 Crashpad 均无记录，此开关是唯一第一手死因来源（本次靠它
// 拿到 reason/exitCode 破案）。⚠ 必须用 file 形态：默认 stderr 形态会强制弹一个
// 独立黑色控制台窗口（2026-09-16 实测被当成「莫名其妙的终端」）。
if (isDev) {
  app.commandLine.appendSwitch('enable-logging', 'file')
  app.commandLine.appendSwitch('log-file', join(dirname(dirname(__dirname)), 'logs', 'electron_chrome.log'))
}

// ③ 与本机安全/反作弊软件（腾讯 ACE 等）共存：其注入模块会触发 Windows
// RendererCodeIntegrity 杀进程（同 STATUS_BREAKPOINT 症状）。Slack/Discord/
// VSCode 同问题标准修复。代价：renderer 对注入 DLL 的防御下降（本地写作应用可接受）。
app.commandLine.appendSwitch('disable-features', 'RendererCodeIntegrity')

let backendProcess = null
// 主窗口引用缓存（供 IPC handler 引用，避免闭包丢失窗口实例）
let mainWindow = null

// CP-dynamic-port: 前端端口也动态协商（与后端 port.txt 对称）
// 优先级：环境变量 VELLUMA_FRONTEND_PORT → data/frontend_port.txt → 默认 5175
const DEFAULT_VITE_PORT = 5175
const DEFAULT_BACKEND_PORT = parseInt(process.env.VELLUMA_BACKEND_PORT) || 8002

// =============================================================================
// 端口文件路径（与后端 core/config.py 中 PORT_FILE 对应）
// =============================================================================
const PORT_FILE = join(dirname(dirname(__dirname)), 'data', 'port.txt')
const FRONTEND_PORT_FILE = join(dirname(dirname(__dirname)), 'data', 'frontend_port.txt')

function readFrontendPortFromFile() {
  // 优先环境变量（启动脚本 start-all.ps1 / start-all.sh / 单服务 electron 脚本会设置 VELLUMA_FRONTEND_PORT）
  if (process.env.VELLUMA_FRONTEND_PORT) {
    const p = parseInt(process.env.VELLUMA_FRONTEND_PORT, 10)
    if (!isNaN(p) && p > 0) return p
  }
  try {
    if (fs.existsSync(FRONTEND_PORT_FILE)) {
      const port = parseInt(fs.readFileSync(FRONTEND_PORT_FILE, 'utf-8').trim(), 10)
      if (!isNaN(port) && port > 0) return port
    }
  } catch (e) {
    console.warn('[FrontendPortFile] 读取前端端口文件失败:', e.message)
  }
  return DEFAULT_VITE_PORT
}

function readPortFromFile() {
  try {
    if (fs.existsSync(PORT_FILE)) {
      const port = parseInt(fs.readFileSync(PORT_FILE, 'utf-8').trim(), 10)
      if (!isNaN(port) && port > 0) return port
    }
  } catch (e) {
    console.warn('[PortFile] 读取端口文件失败:', e.message)
  }
  return null
}

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
  // 尝试从端口文件读取（后端可能已在运行）
  const filePort = readPortFromFile()
  if (filePort) {
    try {
      await waitForPort(filePort, { timeout: 500, serviceName: 'Backend' })
      console.log(`[Backend] Already running on port ${filePort} (from port file)`)
      return { port: filePort, started: false }
    } catch {
      // 端口文件记录的端口不可用，继续启动流程
    }
  }

  // 尝试默认端口
  const port = DEFAULT_BACKEND_PORT
  try {
    await waitForPort(port, { timeout: 500, serviceName: 'Backend' })
    console.log(`[Backend] Already running on port ${port}`)
    return { port, started: false }
  } catch {
    // Not running, need to start
  }
  
  // 启动后端（后端会自动寻找可用端口并写入 data/port.txt）
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
    env: { ...process.env, PYTHONUNBUFFERED: "1" },
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

  // 等待后端启动，轮询端口文件获取实际端口
  let actualPort = null
  const startTime = Date.now()
  const pollTimeout = 60000
  
  while (Date.now() - startTime < pollTimeout) {
    await new Promise(r => setTimeout(r, 500))
    actualPort = readPortFromFile()
    if (actualPort) {
      try {
        await waitForPort(actualPort, { timeout: 2000, serviceName: 'Backend' })
        break
      } catch {
        actualPort = null
      }
    }
  }
  
  if (!actualPort) {
    throw new Error('Backend failed to start: could not detect port')
  }
  
  console.log(`[Backend] Detected on port ${actualPort}`)
  
  const health = await checkHealth(`http://127.0.0.1:${actualPort}/api/health`, { retries: 5 })
  console.log(`[Backend] Health check:`, health.healthy ? 'OK' : 'Warning')
  
  return { port: actualPort, started: true }
}

async function waitForFrontend() {
  const port = readFrontendPortFromFile()
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
    icon: join(__dirname, 'app-icon.png'),  // 应用图标唯一源（换图只换这一个文件）
    webPreferences: {
      nodeIntegration: false,
      contextIsolation: true
    }
  })
  
  const html = `<!DOCTYPE html>
<html>
<head>
  <meta charset="UTF-8">
  <!-- data: URL 无响应头可注 CSP，meta 兜底——纯静态 loading 页只放行内联样式 -->
  <meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'">
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
  
  let backendResult = { port: DEFAULT_BACKEND_PORT }
  let vitePort = readFrontendPortFromFile()
  
  try {
    if (isDev) {
      if (process.env.VELLUMA_SERVICES_READY !== '1') {
        backendResult = await startBackend()
      } else {
        console.log('[Main] Services ready flag set')
        await waitForPort(backendResult.port, { timeout: 10000, serviceName: 'Backend' })
      }
      
      await waitForFrontend()
      
      if (loadingWin && !loadingWin.isDestroyed()) {
        loadingWin.close()
      }
    }
    
    const win = new BrowserWindow({
      width: 1400,
      height: 900,
      // V3.1 F2：三栏布局（binder + 编辑器 + inspector）需要更宽的最小窗口
      minWidth: 1200,
      minHeight: 700,
      show: true,
      icon: join(__dirname, 'app-icon.png'),  // 应用图标唯一源——窗口左上角/任务栏/打包 exe 都从它出
      webPreferences: {
        nodeIntegration: false,
        contextIsolation: true,
        preload: join(__dirname, 'preload.cjs')
      }
    })
    mainWindow = win  // 缓存到模块级，供 IPC handler 引用

    // 窗口关闭时清空引用，避免悬空指针
    win.on('closed', () => {
      mainWindow = null
    })

    // renderer 死因观测（2026-09-16 白屏排查）：仅记录 reason/exitCode，无任何自动动作。
    // Crashpad 在本机不落盘，这是唯一能拿到崩溃分类（oom/segfault 等）的通道。
    win.webContents.on('render-process-gone', (_e, details) => {
      console.error(`[Main] renderer gone: reason=${details.reason} exitCode=${details.exitCode}`)
    })

    if (isDev) {
      session.defaultSession.webRequest.onHeadersReceived((details, callback) => {
        callback({
          responseHeaders: {
            ...details.responseHeaders,
            // script-src 不含 unsafe-eval/unsafe-inline：Vite dev 走原生 ESM + ws HMR，
            // 均不需要二者；保留会触发 Electron 的 Insecure CSP 安全警告。
            // index.html 内联防闪脚本以 sha256 hash 放行——hash 按 LF 归一化后的脚本
            // 文本计算（HTML 解析器会把 CRLF 归一为 LF）；改防闪脚本必须重算并同步此处
            // img-src：外观纹理/自定义背景是 data:image/svg+xml 与压缩产物 data URL
            // （useAppearance.ts/AppearancePanel.vue），blob: 是图片压缩解码中转，
            // 后端 localhost 是世界页底图（Leaflet ImageOverlay 直连 :8002 段）
            'Content-Security-Policy': ["default-src 'self'; script-src 'self' 'sha256-cYp2XYhQFdE+TDwcR5h3VNrB5Od7GHzE5eMVgVUuKzY='; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob: http://localhost:* http://127.0.0.1:*; connect-src 'self' http://localhost:* ws://localhost:* http://127.0.0.1:* ws://127.0.0.1:*"]
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

// =============================================================================
// IPC：系统通知（生成完成时由渲染进程触发，主进程判断焦点后弹原生通知）
// =============================================================================

ipcMain.on('show-notification', (_event, payload = {}) => {
  const { title, body } = payload
  // 分层兜底：仅当主窗口非聚焦或最小化/隐藏时才打扰用户（前台不打扰）
  const shouldNotify = !mainWindow
    || mainWindow.isMinimized()
    || !mainWindow.isVisible()
    || !mainWindow.isFocused()
  if (!shouldNotify) return
  if (!Notification.isSupported()) return

  const notification = new Notification({
    title: title || 'Velluma AI',
    body: body || '',
    silent: false,
  })
  notification.on('click', () => {
    // 点击通知拉回窗口
    if (mainWindow) {
      if (mainWindow.isMinimized()) mainWindow.restore()
      mainWindow.show()
      mainWindow.focus()
    }
    notification.close()
  })
  notification.show()
})

// =============================================================================
// 应用生命周期
// =============================================================================

app.whenReady().then(async () => {
  try {
    // Windows：设置 AppUserModelId，让系统通知正确归属到 Velluma（开发模式下默认显示为 "Electron"）
    if (process.platform === 'win32') {
      app.setAppUserModelId('com.velluma.app')
    }
    await createMainWindow()

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
