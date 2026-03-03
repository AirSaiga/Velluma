const { app, BrowserWindow, session, ipcMain } = require('electron')
const { join, dirname } = require('path')
const { spawn } = require('child_process')
const net = require('net')

const isDev = process.env.NODE_ENV !== 'production' && !app.isPackaged

let backendProcess = null

const FIXED_VITE_PORT = 5175
const FIXED_BACKEND_PORT = 8002

function waitForPort(port, timeout = 30000) {
  return new Promise((resolve, reject) => {
    const startTime = Date.now()
    const check = () => {
      const client = new net.Socket()
      client.setTimeout(1000)
      client.connect(port, '127.0.0.1', () => {
        client.destroy()
        resolve(true)
      })
      client.on('error', () => {
        client.destroy()
        if (Date.now() - startTime > timeout) {
          reject(new Error('Timeout'))
        } else {
          setTimeout(check, 500)
        }
      })
      client.on('timeout', () => {
        client.destroy()
        setTimeout(check, 500)
      })
    }
    check()
  })
}

async function startBackend() {
  const port = FIXED_BACKEND_PORT
  console.log(`Starting backend on fixed port ${port}`)

  try {
    await waitForPort(port, 300)
    console.log(`Backend already running on port ${port}`)
    return port
  } catch {}
  
  const projectRoot = dirname(dirname(__dirname))
  const venvPython = process.platform === 'win32' 
    ? join(projectRoot, 'venv', 'Scripts', 'python.exe')
    : join(projectRoot, 'venv', 'bin', 'python')

  backendProcess = spawn(venvPython, ['-m', 'backend.main'], {
    cwd: projectRoot,
    env: { ...process.env, VELLUMA_PORT: port.toString() },
    stdio: ['ignore', 'pipe', 'pipe']
  })

  backendProcess.on('error', (err) => {
    console.error('Backend spawn failed:', err)
  })

  backendProcess.stdout.on('data', (data) => {
    console.log(`[Backend] ${data.toString().trim()}`)
  })

  backendProcess.stderr.on('data', (data) => {
    console.error(`[Backend Error] ${data.toString().trim()}`)
  })

  backendProcess.on('close', (code) => {
    console.log(`Backend process exited with code ${code}`)
  })

  await waitForPort(port)
  console.log(`Backend ready on port ${port}`)
  
  return port
}

async function createWindow() {
  let backendPort = null
  let vitePort = FIXED_VITE_PORT

  if (isDev) {
    session.defaultSession.webRequest.onHeadersReceived((details, callback) => {
      const csp = "default-src 'self'; script-src 'self' 'unsafe-eval'; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; font-src 'self' data:; connect-src 'self' http://localhost:* ws://localhost:* http://127.0.0.1:* ws://127.0.0.1:*"
      callback({
        responseHeaders: {
          ...details.responseHeaders,
          'Content-Security-Policy': [csp]
        }
      })
    })

    try {
      await waitForPort(FIXED_VITE_PORT, 2000)
      console.log(`Found Vite on port ${FIXED_VITE_PORT}`)
    } catch (e) {
      console.error(`Vite server not found on port ${FIXED_VITE_PORT}, please start Vite first`)
    }

    try {
      backendPort = await startBackend()
    } catch (e) {
      console.error('Backend start failed:', e)
    }
  }

  const win = new BrowserWindow({
    width: 1920,
    height: 1080,
    webPreferences: {
      nodeIntegration: false,
      contextIsolation: true,
      preload: join(__dirname, 'preload.cjs')
    }
  })

  if (isDev) {
    const url = `http://localhost:${vitePort}?backendPort=${backendPort}`
    console.log(`Loading URL: ${url}`)
    win.loadURL(url)
    win.webContents.openDevTools()
  } else {
    win.loadFile(join(__dirname, '../dist/index.html'))
  }

  return { win, backendPort, vitePort }
}

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

app.whenReady().then(async () => {
  const { win, backendPort, vitePort } = await createWindow()
  
  let debugWin = createDebugWindow(backendPort, vitePort)
  
  debugWin.on('closed', () => {
    debugWin = null
  })
  
  ipcMain.on('prompt-data', (event, data) => {
    if (debugWin && !debugWin.isDestroyed()) {
      debugWin.webContents.send('prompt-data', data)
    }
  })

  app.on('activate', () => {
    if (BrowserWindow.getAllWindows().length === 0) {
      createWindow()
    }
  })
})

app.on('window-all-closed', () => {
  if (backendProcess) {
    backendProcess.kill()
  }
  if (process.platform !== 'darwin') {
    app.quit()
  }
})
