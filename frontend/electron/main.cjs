const { app, BrowserWindow, session } = require('electron')
const { join, dirname } = require('path')
const { spawn } = require('child_process')
const net = require('net')

const isDev = process.env.NODE_ENV !== 'production' && !app.isPackaged

let backendProcess = null
let pythonCmd = process.platform === 'win32' ? 'python.exe' : 'python'

const VITE_PORTS = [5173, 5174, 5175, 5176, 5177, 5178, 5179, 5180]
const BACKEND_START_PORT = 8001

function findAvailablePort(startPort = BACKEND_START_PORT) {
  return new Promise((resolve) => {
    const server = net.createServer()
    server.listen(startPort, () => {
      const address = server.address()
      server.close(() => {
        resolve(address.port)
      })
    })
    server.on('error', () => {
      resolve(findAvailablePort(startPort + 1))
    })
  })
}

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

async function findVitePort() {
  for (const port of VITE_PORTS) {
    try {
      await waitForPort(port, 2000)
      return port
    } catch {
      continue
    }
  }
  throw new Error('Vite server not found')
}

async function startBackend() {
  const port = await findAvailablePort()
  console.log(`Starting backend on port ${port}`)
  
  const projectRoot = dirname(dirname(__dirname))
  const env = { ...process.env, VELLUMA_PORT: port.toString() }

  backendProcess = spawn(pythonCmd, ['-m', 'backend.main'], {
    cwd: projectRoot,
    env,
    stdio: ['ignore', 'pipe', 'pipe']
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
  let vitePort = 5173

  if (isDev) {
    session.defaultSession.webRequest.onHeadersReceived((details, callback) => {
      const csp = "default-src 'self'; script-src 'self' 'unsafe-eval'; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; font-src 'self' data:; connect-src 'self' http://localhost:* ws://localhost:*"
      callback({
        responseHeaders: {
          ...details.responseHeaders,
          'Content-Security-Policy': [csp]
        }
      })
    })

    try {
      vitePort = await findVitePort()
      console.log(`Found Vite on port ${vitePort}`)
    } catch (e) {
      console.error('Vite server not found:', e)
    }

    try {
      backendPort = await startBackend()
    } catch (e) {
      console.error('Backend start failed:', e)
    }
  }

  const win = new BrowserWindow({
    width: 1200,
    height: 800,
    webPreferences: {
      nodeIntegration: false,
      contextIsolation: true,
      preload: join(__dirname, 'preload.cjs')
    }
  })

  if (isDev) {
    win.loadURL(`http://localhost:${vitePort}`)
    win.webContents.openDevTools()
  } else {
    win.loadFile(join(__dirname, '../dist/index.html'))
  }
}

app.whenReady().then(() => {
  createWindow()

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
