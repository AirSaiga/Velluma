# scripts/ — 启动脚本

Velluma 的启动入口。所有脚本通过 `start.ps1 -Mode <mode>` 区分运行方式。

## 三种模式

| 入口                 | 模式   | 用途                                           | NODE_ENV       | 前端来源              | DevTools |
| -------------------- | ------ | ---------------------------------------------- | -------------- | --------------------- | -------- |
| `start-dev.bat`      | dev    | 日常开发（默认，根目录 `start.bat` 等价于此）  | 未设置         | Vite dev server       | 自动开   |
| `start-debug.bat`    | debug  | 调试入口：**后端热重载** + Vite + Electron     | 未设置         | Vite dev server       | 自动开   |
| `start-prod.bat`     | prod   | 生产体验：Electron 载入预构建的 `dist/`        | `production`   | `frontend/dist/` 文件 | 不开     |

### dev / debug
两者都启动后端 + Vite dev server + Electron（连 `http://localhost:<port>`，自动 `openDevTools()`）。区别在于**后端启动方式**：

- **dev**：`python -m backend.main`（走 `main.py` 的 `__main__`，端口由后端内部扫描），改后端代码需手动重启。
- **debug**：`python -m uvicorn backend.main:app --reload --reload-dir backend`（脚本侧固定端口并写 `data/port.txt`），保存 `backend/` 下任意 `.py` 即自动重启后端，前端 API 调用无缝衔接，适合频繁改后端代码的开发场景。

> debug 模式端口固定：脚本会扫描 8002~8100 抢占一个空闲端口，写 `data/port.txt` 并设 `VELLUMA_PORT` 环境变量，让 `main.py` 跳过内部扫描——这是热重载期间端口不漂移、前端不断连的前提。退出时按进程树清理 reloader 的 worker 子进程，避免孤儿占用端口。

### prod
先 `npm run build` 生成 `frontend/dist/`，再以 `NODE_ENV=production` 启动 Electron——`main.cjs` 走 `loadFile('../dist/index.html')` 分支，不启动 Vite、不开 DevTools，模拟打包后的运行体验。后端仍由本地 `.venv` 启动。

## 使用

在项目根目录运行：

```powershell
.\scripts\start-dev.bat           # 开发模式（默认）
.\scripts\start-debug.bat         # 调试模式
.\scripts\start-prod.bat          # 生产体验模式

.\start.bat                       # 根目录兼容入口 = start-dev.bat
```

### 常用参数（透传给 start.ps1）

| 参数             | 说明                                   |
| ---------------- | -------------------------------------- |
| `-Force`         | 端口被占用时强制清理后重启             |
| `-SkipBackend`   | 跳过后端启动（假设已运行）             |
| `-SkipFrontend`  | 跳过前端（dev：跳 Vite；prod：跳 build）|
| `-ElectronOnly`  | 只启动 Electron（假设前后端已就绪）    |
| `-DryRun`        | 仅打印将执行的命令，不启动任何进程     |

示例：

```powershell
.\scripts\start-dev.bat -Force
.\scripts\start.ps1 -Mode prod -SkipBackend   # 直接调用 ps1 也行
.\scripts\start.ps1 -Mode dev -DryRun         # 检查将启动的进程与路径
```

## 路径说明

脚本位于 `scripts/`，项目根由 `Split-Path $PSScriptRoot -Parent` 推导，端口文件仍写入项目根的 `data/port.txt` 与 `data/frontend_port.txt`（与后端 `backend/core/config.py`、`frontend/electron/main.cjs` 协调一致）。
