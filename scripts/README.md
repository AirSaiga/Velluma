# scripts/ — 启动脚本

Velluma 的启动入口，**按平台分目录**，每个平台内含 dev / debug / prod 三模式。编排核心（端口协商、进程清理）Windows 与 macOS 各一份，行为契约一致。

```
scripts/
├── windows/                  # Windows（PowerShell + .bat）
│   ├── start.ps1             #   编排核心：-Mode dev/debug/prod
│   ├── start-dev.bat         #   开发模式入口（薄包装）
│   ├── start-debug.bat       #   调试模式入口（薄包装）
│   └── start-prod.bat        #   生产体验入口（薄包装）
├── macos/                    # macOS / Linux（bash）
│   ├── start.sh              #   编排核心：dev/debug/prod
│   ├── start-dev.sh          #   开发模式入口（薄包装）
│   ├── start-debug.sh        #   调试模式入口（薄包装）
│   └── start-prod.sh         #   生产体验入口（薄包装）
└── make_blank_atlas.py       # 工具脚本（非启动）：世界页空白舆图 SVG 生成器，平台无关
```

## 三种模式（两平台一致）

| 模式   | Windows 入口                    | macOS 入口             | 用途                                       | NODE_ENV     | 前端来源        | DevTools |
| ------ | ------------------------------- | ---------------------- | ------------------------------------------ | ------------ | --------------- | -------- |
| dev    | `windows\start-dev.bat`         | `macos/start-dev.sh`   | 日常开发（默认）                           | 未设置       | Vite dev server | 自动开   |
| debug  | `windows\start-debug.bat`       | `macos/start-debug.sh` | 调试：**后端热重载** + Vite + Electron     | 未设置       | Vite dev server | 自动开   |
| prod   | `windows\start-prod.bat`        | `macos/start-prod.sh`  | 生产体验：Electron 载入预构建的 `dist/`    | `production` | `frontend/dist/` | 不开     |

### dev / debug

两者都启动后端 + Vite dev server + Electron（连 `http://localhost:<port>`，自动 `openDevTools()`）。区别在于**后端启动方式**：

- **dev**：`python -m backend.main`（走 `main.py` 的 `__main__`，端口由后端内部扫描），改后端代码需手动重启。
- **debug**：`python -m uvicorn backend.main:app --reload --reload-dir backend`（脚本侧固定端口并写 `data/port.txt`），保存 `backend/` 下任意 `.py` 即自动重启后端，前端 API 调用无缝衔接，适合频繁改后端代码的开发场景。

> debug 模式端口固定：脚本会扫描 8002~8100 抢占一个空闲端口，写 `data/port.txt` 并设 `VELLUMA_PORT` 环境变量，让 `main.py` 跳过内部扫描——这是热重载期间端口不漂移、前端不断连的前提。退出时按进程树清理 reloader 的 worker 子进程（Windows 用 Win32_Process 递归，macOS 用 `pgrep -P` 递归），避免孤儿占用端口。

### prod

先 `npm run build` 生成 `frontend/dist/`，再以 `NODE_ENV=production` 启动 Electron——`main.cjs` 走 `loadFile('../dist/index.html')` 分支，不启动 Vite、不开 DevTools，模拟打包后的运行体验。后端仍由本地 `.venv` 启动。

## 使用

```powershell
# Windows（项目根目录）
.\scripts\windows\start-dev.bat       # 开发模式（默认）
.\scripts\windows\start-debug.bat     # 调试模式
.\scripts\windows\start-prod.bat      # 生产体验模式
.\scripts\windows\start.ps1 -Mode dev -DryRun   # 直接调编排核心
```

```bash
# macOS / Linux（项目根目录）
./scripts/macos/start-dev.sh          # 开发模式（默认）
./scripts/macos/start-debug.sh        # 调试模式
./scripts/macos/start-prod.sh         # 生产体验模式
./scripts/macos/start.sh dev --dry-run          # 直接调编排核心
```

### 常用参数

| Windows（PowerShell 开关） | macOS（长选项，亦接受 PowerShell 风格别名） | 说明                                   |
| -------------------------- | -------------------------------------------- | -------------------------------------- |
| `-Force`                   | `--force` / `-Force`                         | 端口被占用时强制清理后重启             |
| `-SkipBackend`             | `--skip-backend` / `-SkipBackend`            | 跳过后端启动（假设已运行）             |
| `-SkipFrontend`            | `--skip-frontend` / `-SkipFrontend`          | 跳过前端（dev：跳 Vite；prod：跳 build）|
| `-ElectronOnly`            | `--electron-only` / `-ElectronOnly`          | 只启动 Electron（假设前后端已就绪）    |
| `-DryRun`                  | `--dry-run` / `-DryRun`                      | 仅打印将执行的命令，不启动任何进程     |

示例：

```powershell
.\scripts\windows\start-dev.bat -Force
.\scripts\windows\start.ps1 -Mode prod -SkipBackend
.\scripts\windows\start.ps1 -Mode dev -DryRun
```

```bash
./scripts/macos/start-dev.sh --force
./scripts/macos/start.sh prod --skip-backend
./scripts/macos/start.sh dev --dry-run
```

## 两平台共同的行为契约

- **端口文件**：后端实际端口写 `data/port.txt`，前端端口写 `data/frontend_port.txt`（`vite.config.js` 代理与 `electron/main.cjs` 读取，两端脚本写法一致）。
- **Electron 环境变量**：编排核心为 Electron 设 `VELLUMA_BACKEND_PORT` / `VELLUMA_FRONTEND_PORT` / `VELLUMA_SERVICES_READY`，prod 另设 `NODE_ENV=production`。
- **项目根推导**：编排核心按 `$PSScriptRoot` / `BASH_SOURCE` 的祖父目录定位项目根，脚本可在任意 cwd 调用。
- **平台差异**：Python venv 路径（`Scripts\python.exe` vs `bin/python`）、端口探测（TcpClient vs `nc`/`/dev/tcp`）、进程清理（Win32_Process vs `lsof`/`pgrep`）；macOS 版要求 bash（系统自带 3.2 即可），Linux 未专门测试但依赖均为常见内置工具。

## 工具脚本（非启动）

- `make_blank_atlas.py`：从 Natural Earth 数据生成世界页空白舆图 SVG（`frontend/src/features/world/containers/blankAtlas.ts`），与平台启动无关，详见 `docs/world-unified-settings.md`。
