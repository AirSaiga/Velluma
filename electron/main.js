/**
 * Velluma AI - Electron 主进程
 * 负责启动 Python 后端并管理应用窗口
 */

const { app, BrowserWindow } = require('electron');
const { spawn } = require('child_process');
const path = require('path');
const net = require('net');

// 配置
const PYTHON_PATH = 'python'; // 或指定完整路径如 'C:\\Python312\\python.exe'
const BACKEND_HOST = '127.0.0.1';
const BACKEND_START_TIMEOUT = 30000; // 30秒超时
const WINDOW_WIDTH = 1400;
const WINDOW_HEIGHT = 900;

let mainWindow = null;
let backendProcess = null;
let backendPort = null;

/**
 * 查找可用端口
 */
function findAvailablePort() {
  return new Promise((resolve, reject) => {
    const server = net.createServer();
    server.listen(0, BACKEND_HOST, () => {
      const port = server.address().port;
      server.close(() => resolve(port));
    });
    server.on('error', reject);
  });
}

/**
 * 等待后端服务启动
 */
function waitForBackend(port, timeout = BACKEND_START_TIMEOUT) {
  return new Promise((resolve, reject) => {
    const startTime = Date.now();
    const checkInterval = setInterval(() => {
      const client = new net.Socket();
      client.setTimeout(1000);
      
      client.connect(port, BACKEND_HOST, () => {
        clearInterval(checkInterval);
        client.destroy();
        resolve(true);
      });
      
      client.on('error', () => {
        client.destroy();
        if (Date.now() - startTime > timeout) {
          clearInterval(checkInterval);
          reject(new Error('后端服务启动超时'));
        }
      });
      
      client.on('timeout', () => {
        client.destroy();
      });
    }, 500);
  });
}

/**
 * 启动 Python 后端服务
 */
async function startBackend() {
  backendPort = await findAvailablePort();
  console.log(`🚀 启动后端服务，端口: ${backendPort}`);
  
  // 设置环境变量
  const env = {
    ...process.env,
    PYTHONPATH: path.join(__dirname, '..'),
    VELLUMA_PORT: backendPort.toString()
  };
  
  // 启动 Python 后端
  const backendScript = path.join(__dirname, '..', 'backend', 'main.py');
  backendProcess = spawn(PYTHON_PATH, [backendScript], {
    env,
    stdio: 'pipe'
  });
  
  backendProcess.stdout.on('data', (data) => {
    console.log(`[Backend] ${data.toString().trim()}`);
  });
  
  backendProcess.stderr.on('data', (data) => {
    console.error(`[Backend Error] ${data.toString().trim()}`);
  });
  
  backendProcess.on('close', (code) => {
    console.log(`后端进程退出，代码: ${code}`);
  });
  
  // 等待后端就绪
  await waitForBackend(backendPort);
  console.log('✅ 后端服务已启动');
  
  return backendPort;
}

/**
 * 停止后端服务
 */
function stopBackend() {
  if (backendProcess) {
    console.log('🛑 停止后端服务...');
    backendProcess.kill();
    backendProcess = null;
  }
}

/**
 * 创建主窗口
 */
function createWindow() {
  const isDev = !app.isPackaged;
  
  mainWindow = new BrowserWindow({
    width: WINDOW_WIDTH,
    height: WINDOW_HEIGHT,
    minWidth: 1000,
    minHeight: 600,
    title: 'Velluma AI 小说写作助手',
    webPreferences: {
      nodeIntegration: false,
      contextIsolation: true,
      preload: path.join(__dirname, 'preload.js')
    }
  });
  
  // 加载页面
  if (isDev) {
    // 开发模式：连接 Vite 开发服务器
    const devUrl = 'http://localhost:5173';
    console.log(`🛠️ 开发模式: 连接到 ${devUrl}`);
    mainWindow.loadURL(devUrl);
    mainWindow.webContents.openDevTools();
  } else {
    // 生产模式：连接本地后端
    const backendUrl = `http://${BACKEND_HOST}:${backendPort}`;
    console.log(`📦 生产模式: 连接到 ${backendUrl}`);
    mainWindow.loadURL(backendUrl);
  }
  
  mainWindow.on('closed', () => {
    mainWindow = null;
  });
}

// Electron 应用生命周期
app.whenReady().then(async () => {
  try {
    const isDev = !app.isPackaged;
    
    if (!isDev) {
      // 生产模式：启动 Python 后端
      await startBackend();
    }
    
    createWindow();
    
    app.on('activate', () => {
      if (BrowserWindow.getAllWindows().length === 0) {
        createWindow();
      }
    });
  } catch (error) {
    console.error('启动失败:', error);
    app.quit();
  }
});

app.on('window-all-closed', () => {
  stopBackend();
  if (process.platform !== 'darwin') {
    app.quit();
  }
});

app.on('before-quit', () => {
  stopBackend();
});

// 处理未捕获的异常
process.on('uncaughtException', (error) => {
  console.error('未捕获的异常:', error);
  stopBackend();
  app.quit();
});
