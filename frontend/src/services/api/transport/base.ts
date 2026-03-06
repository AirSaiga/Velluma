const API_BASE = '/api'
const DEV_SERVER_PORTS = [5173, 5174, 5175, 5176, 5177]

let cachedPort: number | null = null
let apiBasePromise: Promise<string> | null = null

try {
  const urlParams = new URLSearchParams(window.location.search)
  const portParam = urlParams.get('backendPort')
  if (portParam && portParam !== 'null' && portParam !== 'undefined') {
    const port = parseInt(portParam, 10)
    if (!Number.isNaN(port) && port > 0) {
      cachedPort = port
      console.log(`✅ 从 URL 参数获取到后端端口: ${cachedPort}`)
    }
  }
} catch (e) {
  console.warn('解析 URL 参数失败', e)
}

async function getBackendPort(): Promise<number> {
  if (cachedPort) return cachedPort

  try {
    const portRes = await fetch('/api/port')
    if (portRes.ok) {
      const data = await portRes.json()
      if (data.port) {
        cachedPort = data.port
        return cachedPort
      }
    }
  } catch (e) {
    console.warn('获取后端端口失败，使用默认端口')
  }

  cachedPort = 8002
  return cachedPort
}

async function resolveApiBase(): Promise<string> {
  const isDevServer =
    window.location.port !== '' &&
    DEV_SERVER_PORTS.includes(parseInt(window.location.port, 10))

  if (isDevServer) {
    const port = await getBackendPort()
    return `http://127.0.0.1:${port}/api`
  }

  return API_BASE
}

export async function getApiBase(): Promise<string> {
  if (!apiBasePromise) {
    apiBasePromise = resolveApiBase()
  }
  return apiBasePromise
}
