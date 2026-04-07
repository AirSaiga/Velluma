# Velluma 启动脚本

Velluma AI Novel Writing Assistant 的启动脚本。

## 快速开始

```batch
start.bat
```

## 使用方法

### 正常启动
```batch
.\start.bat
```

### 强制模式（清理端口占用）
```batch
.\start.bat -Force
```

### 跳过部分服务
```powershell
# 跳过后端（假设后端已在运行）
.\start.ps1 -SkipBackend

# 跳过前端（假设前端已在运行）
.\start.ps1 -SkipFrontend

# 只启动 Electron（假设前后端都已在运行）
.\start.ps1 -ElectronOnly
```

## 启动流程

1. **启动后端** (端口 8002)
   - 检查虚拟环境 (.venv 或 venv)
   - 等待健康检查通过

2. **启动前端** (端口 5175)
   - 启动 Vite 开发服务器
   - 等待服务就绪

3. **启动 Electron**
   - 显示加载窗口
   - 重试机制确保连接成功
   - 加载主窗口

## 特性

### 1. 依次启动
- 后端就绪后才启动前端
- 前端就绪后才启动 Electron
- 避免连接失败问题

### 2. 重连机制

**Vite 代理层：**
- 后端不可用时返回 503 + 可重试标记
- 30秒请求超时
- 连接错误优雅降级

**Electron 层：**
- 启动时等待后端和前端端口就绪
- HTTP 健康检查重试（最多5次）
- 加载 URL 失败时自动重试（最多10次）
- 显示加载状态窗口

### 3. 优雅关闭
- Ctrl+C 停止所有服务
- 自动清理端口占用
- 进程树完整退出

## 服务地址

| 服务 | URL |
|------|-----|
| 后端 API | http://127.0.0.1:8002 |
| 前端 Dev | http://127.0.0.1:5175 |
| API 文档 | http://127.0.0.1:8002/docs |
| 健康检查 | http://127.0.0.1:8002/api/health |

## 故障排除

### 端口被占用

```powershell
# 查看端口占用
Get-NetTCPConnection -LocalPort 8002
Get-NetTCPConnection -LocalPort 5175

# 强制清理后启动
.\start.bat -Force
```

### 前端连接失败

Electron 会自动重试连接（最多10次，每次间隔1秒）。如果仍失败：
1. 检查后端是否运行：`curl http://127.0.0.1:8002/api/health`
2. 检查前端是否运行：`curl http://127.0.0.1:5175`

### 虚拟环境找不到

确保项目根目录有以下之一：
- `.venv\Scripts\python.exe`
- `venv\Scripts\python.exe`
