# scripts/ — 启动脚本

> 本文自 AGENTS.md 拆分而来（编辑本领域代码前必读）

Velluma 的启动入口，**按平台分目录**，每个平台内含 dev / debug / prod 三模式。编排核心（端口协商、进程清理）Windows 与 macOS 各一份，另有一份两平台共用的 python 监督者（后台模式），三份实现行为契约一致——契约里的数字（端口段、npm script 名）没法共享代码，由 `check_launcher_contract.py` 对拍防漂移。

```
scripts/
├── windows/                    # Windows（PowerShell + .bat/.vbs）
│   ├── start.ps1               #   编排核心：-Mode dev/debug/prod
│   ├── start-dev.bat           #   开发模式入口（薄包装）
│   ├── start-debug.bat         #   调试模式入口（薄包装）
│   ├── start-prod.bat          #   生产体验入口（薄包装）
│   ├── start-background.vbs    #   后台模式（python 监督者，无终端窗口）
│   ├── start-background-debug.vbs
│   └── stop-velluma.bat / .ps1 #   一键收摊（状态 JSON → 树杀 → 孤儿清扫）
├── macos/                      # macOS / Linux（bash）
│   ├── start.sh                #   编排核心：dev/debug/prod
│   ├── start-dev.sh            #   开发模式入口（薄包装）
│   ├── start-debug.sh          #   调试模式入口（薄包装）
│   ├── start-prod.sh           #   生产体验入口（薄包装）
│   ├── start-background.sh     #   后台模式（nohup 脱离终端）
│   └── stop-velluma.sh         #   一键收摊（TERM 启动器走 trap 清理）
├── dev_dashboard.py            # 网页监控台；--supervise = 后台模式进程树主人
├── check_launcher_contract.py  # 三端契约自检（CI 阻断步，见「契约自检」节）
└── *.py                        # 工具脚本（非启动，见下「工具脚本」节）
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

- **端口段**：后端 `8002~8100`（与 `backend/core/config.py` 的 DEFAULT_PORT..MAX_PORT 对齐），前端 `5175~5285`（避开其它项目的 Vite；`stop-velluma` 的孤儿清扫段与之对齐）。协商优先级三端一致：环境变量（`VELLUMA_PORT` / `VELLUMA_FRONTEND_PORT`）→ 已记录端口且空闲则复用 → 扫描首个空闲端口。
- **端口文件**：后端实际端口写 `data/port.txt`，前端端口写 `data/frontend_port.txt`（`vite.config.js` 代理与 `electron/main.cjs` 读取，两端脚本写法一致）。
- **Electron 环境变量**：编排核心为 Electron 设 `VELLUMA_BACKEND_PORT` / `VELLUMA_FRONTEND_PORT` / `VELLUMA_SERVICES_READY`，prod 另设 `NODE_ENV=production`。
- **Electron 启动方式**：三模式一律 `npm run electron:nobuild`（= 直接 `electron .`）——dev/debug 下 `main.cjs` 走 `loadURL`，`electron:dev` 里的 vite build 产物根本不会被加载；prod 的 `dist/` 已由编排核心显式构建并校验（`--skip-frontend` 时会断言 `dist/index.html` 在），再 build 一次纯属浪费。`loadURL`/`loadFile` 由 `NODE_ENV` 决定，与是否构建无关。
- **日志**：每次启动重建 `logs/dev_*.log`（前端车道供网页监控台增量 tail）＋启动器叙事进 `logs/dev_sys.log`；DryRun 不写日志、不写端口文件、不杀任何进程。
- **项目根推导**：编排核心按 `$PSScriptRoot` / `BASH_SOURCE` 的祖父目录定位项目根，脚本可在任意 cwd 调用。
- **平台差异**：Python venv 路径（`Scripts\python.exe` vs `bin/python`）、端口探测（TcpClient vs `nc`/`/dev/tcp`）、进程清理（Win32_Process vs `lsof`/`pgrep`）；macOS 版要求 bash（系统自带 3.2 即可），Linux 未专门测试但依赖均为常见内置工具。

## 契约自检

```bash
python scripts/check_launcher_contract.py     # 一致退 0，漂移退 1（CI 阻断步）
```

三份编排（`windows/start.ps1` / `macos/start.sh` / `dev_dashboard.py` 监督者）＋ 收摊脚本 ＋ 前端 `frontend/src/services/api/transport/base.ts` 的 dev-server 判定区间，共用同一组数字却无法共享代码，只能靠对拍。历史漂移：前端扫描上界 `5274` / `5275` / `5285` 三版并存、监控台覆盖段与收摊脚本孤儿清扫段对不上。

**改端口段或换 electron npm script 时**：改全部实现 → 改 `check_launcher_contract.py` 里的契约常量 → 跑一次确认变绿。它报错不是噪声，是刚拦下一次真实漂移。

## 日志架构（文件为真相源）

- 三端（backend/vite/electron）全部以**输出重定向子进程**运行，`start.ps1` 不再各开终端；vite 不得回退隐藏窗口（输出不可见则代理 wedge 类故障无法排障）。
- 三端 stdout/stderr 由**独立 runspace 读线泵**阻塞 `ReadLine` 直写 `logs/dev_backend.log` / `logs/dev_vite.log` / `logs/dev_electron.log`（`"HH:mm:ss 原始行"` 格式，**每次启动重建**）；启动器叙事进 `logs/dev_sys.log`。
- **泵与主线程完全异步**：控制台/宿主冻结不影响日志落盘与网页监控台；控制台显示降级为尽力而为——泵同时入 `ConcurrentQueue`，主循环非阻塞排水上屏。
- 控制台彩色前缀 backend 青 / vite 绿 / electron 黄；按键 `1`/`2`/`3` 聚焦单端、`0` 全部、`s` 状态、`q`/Ctrl+C 一键全停；每 15s 状态心跳行 + 意外退出红告警。
- 读线泵 / `prefix_stream` 剥 ANSI 色码（npm/vite 管道下仍发色码，剥掉保日志与网页干净）。
- macOS 对称：`prefix_stream` 直写 dev_*.log + 合流日志 + 仪表盘（无终端按键交互，Ctrl+C 走 trap 清理）；**每次启动截断 dev_*.log**（追加模式跨会话堆积、且仪表盘「文件变小=新一轮启动」的清屏判定永不触发）；启动叙事同样落 `dev_sys.log`（远程监控台 sys 车道不空）；`write_port_file` 带 DryRun 不落盘护栏（与 Windows `Write-PortFile` 对齐）。

## 网页监控台（scripts/dev_dashboard.py）

- 纯标准库；启动器拉起本地服务（**8180 起扫空闲端口**）自动开浏览器；`-NoDashboard` / `--no-dashboard` 关闭。
- tail 四个 dev_*.log：1s 增量、per-file 字节偏移协议 `GET /api/logs?after={backend:0,...}`。
- 状态药丸 = TCP 探活 + PID 存活核验；支持聚焦/暂停。
- 状态 JSON `data/dev_status.json`（心跳/状态变化重写）。**改协议字段须同步 dashboard 的 `build_status` / `LINE_RE` / `FILES`**。
- **PHASE 状态机**：booting→backend→vite→electron→ready 写进状态 JSON `phase` 字段，仪表盘顶部进度横幅。
- macOS 监控台门控只看 `--no-dashboard` / `--dry-run`（不受 `--no-log` 连坐——它读的是恒写的 dev_*.log）。

## 后台模式（python 监督者）

- `start-background.vbs` / `start-background-debug.vbs`（WScript 隐藏窗口）直拉 python 监督者：`.venv\Scripts\pythonw.exe` 跑 `dev_dashboard.py --supervise`；**powershell 不参与后台关键路径**（用户拍板：隐藏 powershell 实测屡冻，python 存活率压倒性）。
- 监督者 = 进程树主人：端口协商（同 start.ps1 契约写 `data/port.txt` + `data/frontend_port.txt`）+ 拉起三端（**stdin=DEVNULL、CREATE_NO_WINDOW**、stdout 由读线线程加时间戳落 dev_*.log）+ 状态 JSON 心跳（**5s**）+ backend/vite 意外退出自愈重启（**上限 2**）。
- **内建 mtime 热重载（仅 debug 监督者）**：backend 子进程不传 uvicorn `--reload`；`_backend_reload_watcher` 轮询 `backend/**/*.py` mtime（排除 `__pycache__`）变化即杀树重拉、走同一条自愈链路；服务锁为 **RLock**（热重载线程持锁内再拿锁须同线程可重入）。控制台模式 `start-debug.bat` 走 start.ps1 直启 uvicorn `--reload`，此路径不变。
- **线程解剖钩子**：`threading.excepthook` 把线程异常强制落 `dev_sys.log`——pythonw 下 stderr 为 None，线程异常会静默蒸发。
- **vbs 必须纯 ASCII+CRLF**（wscript 按 ANSI 读文件，UTF-8 中文注释会编译错）。
- **pythonw 断两进程对链**：venv `python.exe` 是「启动器+真解释器」两进程对，杀启动器会经控制台销毁连坐真解释器；`pythonw.exe` 无控制台，断此链。
- 单实例护栏：状态 JSON 新鲜且 dashboard pid 活着则拒启第二棵树（Windows 监督者）；macOS 启动器用 pgrep 拒第二棵树。macOS 对称后台入口 `start-background.sh`（nohup+disown）。

## electron 退出 = 收摊契约

- Electron 关窗 ⇒ 停掉其余进程并全部收摊（控制台模式与后台模式同契约）。
- 后台监督者 `stop_all` **只杀活 PID**：死条目一律跳过、自愈放弃即时出册（taskkill 对被 Windows 回收的死 PID 是 `/T` 整树误杀而非「仅报错无副作用」）；停机末笔把状态 JSON 改写为「全停」防陈旧 PID 流传。
- 收摊端口扫尾只认本会话 `Register-OwnedPort` 登记过的端口——「已在运行」attach 的外部服务 / 陈旧 port.txt 占用者不连坐。
- `Kill-ProcessOnPort` 拒杀命令行不含本项目路径的监听者。

## 停止（stop-velluma）

- Windows `scripts/windows/stop-velluma.bat`；macOS 对称 `stop-velluma.sh`（pkill -TERM 启动器走 trap 清理）。顺序：
  1. 状态 JSON PID 杀（白名单 python/pythonw；dashboard 另须命令行含项目路径）+ **新鲜度闸：>120s 无心跳即跳过一切 JSON 衍生杀**（监督者/启动器心跳 5~15s；冻结的启动器/监督者由活进程扫尾兜住）。
  2. 3s 优雅路径。
  3. 扫尾残余启动器（命令行含本项目路径，他人项目同名 start.ps1 不连坐）+ recorded 端口（白名单+项目路径双闸）。
  4. **孤儿清扫**：端口段 5175~5285 / 8002~8100 监听者与 python/pythonw/node/electron 进程，命令行含本项目路径才判 OWNED。

## 子进程 stdin 一律切断

- Windows 侧 `RedirectStandardInput` 后立即 Close；macOS 侧 `</dev/null`。
- 契约依据：否则 vite 的 stdin 快捷键 readline 挂在共享 TTY 上，控制台输入侧一有变动就 EPIPE 崩掉整个 dev server；stdin=已关管道 ⇒ isTTY=false ⇒ vite 跳过快捷键注册。

## PowerShell 编码坑（改 start.ps1 前必读）

- `-f` 逗号表达式直接写在 .NET 方法调用参数位（如 `.WriteLine("..." -f $a, $b)`）时，逗号被解析成参数分隔符 → `FormatException` 被空 catch 吞成静默失效。
- 规则：先在语句位求值到临时变量再传参；cmdlet 的 `-Param (...)` 分组括号位安全。**新增 .NET 方法调用内联 `-f` 前先自查**。

## Electron 独立命令（frontend/ 下）

- `npm run electron:dev` / `electron:preview`：均 `npm run build && electron .`，不启 Vite，需 5175 已有服务。
- `npm run electron:nobuild`：跳过 vite build 直接 `electron .`，开发模式用——main.cjs 走 loadURL，build 产物不加载。
- `npm run electron:build`：打包。

## 应用图标单源

- `frontend/electron/app-icon.png`：换图只动这一个文件——两处 `BrowserWindow` 的 `icon` 直读它（开发模式窗口左上角/任务栏），`build.win.icon` / `mac.icon` 同指它（electron-builder 打包时自动转 ico/icns）。
- 要求：方形 PNG ≥256×256。
- `scripts/make_app_icon.py` 仅重新生成出厂占位图，日常换图无需跑。
- Windows 图标缓存可能滞后，重启应用或资源管理器刷新。

## 工具脚本（非启动）

- `make_blank_atlas.py`：从 Natural Earth 数据生成世界页空白舆图 SVG（`frontend/src/features/world/containers/blankAtlas.ts`），与平台启动无关，详见 `docs/world-unified-settings.md`。
- `migrate_pg_to_sqlite.py`：存量 PG 库 → SQLite 一次性搬迁（拓扑序搬运+行数对照+外键校验），详见 `AGENTS.md` 数据库节。
- `calibrate_semantic_threshold.py`：文风语义扫描阈值（0.78）校准矩阵，手动跑不进 CI，详见 `docs/style-module-redesign.md`。
- `analyze_context_manifest.py`：解析 trace 的 context_manifest 事件（注入未消费率/前缀稳定性/块体积分布），世界内核 B0.2 观测工具，详见 `docs/world-kernel-construction-plan.md`。
- `eval_selector_recall.py`：知识平面选择器 recall/precision 金标准评测（--make-template 生成标注模板 / --eval 评测），世界内核 B0.3 验收工具。
- `migrate_to_intents.py`：旧源 → world_intents 幂等复制（手动跑，不进启动链），世界内核 B2 迁移工具。
