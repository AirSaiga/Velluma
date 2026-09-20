const API_BASE = '/api'
// 开发服务器端口区间：启动脚本扫描段 5175~5285（scripts/dev/、scripts/macos/dev/，
// 全端契约见 scripts/check_launcher_contract.py）＋ Vite 自身
// 默认端口 5173/5174（不经启动脚本裸跑 `npm run dev` 的场景）。
// ⚠ 勿改回端口白名单常量：脚本扫描上界一变，白名单就静默失效。
const DEV_SERVER_PORT_MIN = 5173
const DEV_SERVER_PORT_MAX = 5285

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
  const devPort = parseInt(window.location.port, 10)
  const isDevServer =
    window.location.port !== '' &&
    devPort >= DEV_SERVER_PORT_MIN &&
    devPort <= DEV_SERVER_PORT_MAX

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
