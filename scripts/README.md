# scripts/ — 启动脚本

> 本文自 AGENTS.md 拆分而来（编辑本领域代码前必读）；施工/事故史见 `docs/incidents/launcher.md`

2026-09-19 重组：启动脚本按**环境/功能完全隔离**分文件夹，每个文件夹自持、互不复用、互不引用——dev 侧改坏不影响 prod，monitor 侧改坏不影响任何前台启动。两种环境 × 四个入口（后端 / 前端 / Electron / 一键三端），另有一个完全独立的网页监控台文件夹；收摊脚本三平台三件放 scripts/ 根（全局通用）。

```
scripts/
├── dev/                       # 开发调试环境·Windows（后端热重载）
│   ├── start-all.bat / .ps1   #   一键三端编排核心（reload 后端 + Vite + Electron，控制台监控台）
│   ├── start-backend.bat / .ps1     #   单独后端：uvicorn --reload 前台直跑
│   ├── start-frontend.bat / .ps1    #   单独前端：Vite dev server 前台直跑
│   └── start-electron.bat / .ps1    #   单独 Electron：连 Vite（前置校验），关窗只退自己
├── prod/                      # 正式生产环境·Windows
│   ├── start-all.bat / .ps1   #   一键三端编排核心（后端 + npm run build + Electron 生产壳）
│   ├── start-backend.bat / .ps1     #   单独后端：python -m backend.main 前台直跑
│   ├── start-frontend.bat / .ps1    #   构建前端：npm run build（prod 的「前端」= 构建 dist）
│   └── start-electron.bat / .ps1    #   单独 Electron：NODE_ENV=production 载入 dist
├── monitor/                   # 网页监控台 / 后台监督者（完全隔离，自带全部依赖副本）
│   ├── start-background.vbs   #   后台模式·dev（python 监督者，无终端窗口，无热重载）
│   ├── start-background-debug.vbs   #   后台模式·debug（监督者 + mtime 热重载）
│   ├── start-background.sh    #   后台模式·macOS/Linux（nohup 拉起监督者）
│   └── dev_dashboard.py       #   监督者 + 网页监控台——本文件夹私有副本，永不与 dev/prod 共享
├── macos/                     # macOS/Linux · 同两模式
│   ├── dev/                   #   start-all.sh + 三件单服务脚本（与 Windows dev 同契约）
│   └── prod/                  #   start-all.sh + 三件（与 Windows prod 同契约）
├── stop-velluma.bat / .ps1 / .sh  # 全局一键收摊（dev/prod/monitor 通用，三平台各一件）
├── check_launcher_contract.py # 契约自检（CI 阻断步，见「契约自检」节）
└── *.py                       # 工具脚本（非启动，见「工具脚本」节）
```

## 两种环境

| 环境 | Windows 入口 | macOS 入口 | 后端 | 前端 | Electron |
| ---- | ------------ | ---------- | ---- | ---- | -------- |
| **dev（热重载）** | `scripts\dev\start-all.bat` | `scripts/macos/dev/start-all.sh` | uvicorn --reload（脚本侧固定端口 + 写 port.txt） | Vite dev server | loadURL 连 Vite，自动开 DevTools |
| **prod（生产）** | `scripts\prod\start-all.bat` | `scripts/macos/prod/start-all.sh` | python -m backend.main（main.py 自扫端口） | npm run build 产 dist/ | NODE_ENV=production 走 loadFile，不开 DevTools |

旧三模式（dev/debug/prod）已收敛为两模式：原 debug 的热重载形态就是现在的 dev；原 dev（无热重载控制台）退役。单服务入口是新增能力——每个脚本**前台直跑**、输出实时进本窗口、Ctrl+C 停止：

- `dev\start-backend.bat`：端口协商（环境变量 → 已记录且空闲 → 扫描 8002~8100）写 `data/port.txt` 后热重载直跑。uvicorn 直启不走 main.py `__main__`（save_port 不执行），端口文件必须脚本侧写好——固定端口是热重载不漂移的前提。
- `dev\start-frontend.bat`：前端端口同法协商（5175~5285）写 `data/frontend_port.txt` + 设同名环境变量（vite.config.js strictPort 读它）。
- `dev\start-electron.bat`：前置校验 Vite 在跑（dev 模式 Electron 必须连 Vite，否则白屏）；后端不强求（main.cjs 会自行拉起）。
- `prod\start-frontend.bat`：prod 的「前端」= `npm run build`；构建后校验 `dist/index.html` 在。
- `prod\start-electron.bat`：前置校验 dist 在 + NODE_ENV=production。

### 编排核心（start-all）

两个环境各有一份**完全独立**的编排核心（dev/start-all.ps1 与 prod/start-all.ps1，macOS 侧同构）——即使逻辑相似也按隔离纪律各自成文，互不复用。行为：

- 端口协商（dev 侧：环境变量 → 已记录且空闲 → 扫描；prod 侧：后端自扫、脚本只读端口文件）。
- 三端以输出重定向子进程运行，读线泵（Windows runspace / macOS prefix_stream）落 `logs/dev_backend.log` / `dev_vite.log`（仅 dev）/ `dev_electron.log` + 启动叙事进 `dev_sys.log`，**每次启动重建**。
- 控制台尽力而为显示（彩色前缀）；Windows 按键 `1`/`2`/`3` 聚焦单端、`0` 全部、`s` 状态、`q`/Ctrl+C 一键全停；每 15s 状态心跳行。
- backend/vite（仅 dev）意外退出自愈重启（上限 2 次）；**Electron 关窗 = 全部收摊**。
- 状态 JSON `data/dev_status.json` 心跳刷新（stop-velluma 读它按 PID 收摊；prod 无 Vite，vite 键恒空——schema 与 dev/监督者一致）。
- **网页监控台不在编排核心的职责内**（已隔离到 monitor/）；要网页监控用 monitor 下的入口。

### 常用参数（编排核心）

| Windows（PowerShell 开关） | macOS（长选项，亦接受 PowerShell 风格别名） | 说明 |
| -------------------------- | -------------------------------------------- | ---- |
| `-Force` | `--force` / `-Force` | 端口被占用时强制清理后重启（只杀命令行含本项目路径的监听者） |
| `-SkipBackend` | `--skip-backend` | 跳过后端（假设已运行） |
| `-SkipFrontend` | `--skip-frontend` | 跳过前端（dev：跳 Vite；prod：跳 build，断言 dist 已在） |
| `-ElectronOnly` | `--electron-only` | 只启动 Electron（假设前后端已就绪） |
| `-DryRun` | `--dry-run` | 仅打印将执行的命令，不启动任何进程、不写端口文件、不杀任何进程 |

单服务脚本支持 `-Force`（backend/frontend，强制清口重启）与 `-DryRun`。

```powershell
.\scripts\dev\start-all.bat                  # 日常开发（热重载三端）
.\scripts\dev\start-backend.bat              # 只起后端（另一个终端跑前端/Electron 也行）
.\scripts\prod\start-all.bat                 # 生产体验
.\scripts\dev\start-all.ps1 -DryRun          # 直接调核心试跑
```

```bash
./scripts/macos/dev/start-all.sh             # 开发（热重载）
./scripts/macos/prod/start-all.sh            # 生产体验
./scripts/macos/dev/start-all.sh --dry-run   # 试跑
```

## monitor/（网页监控台 + 后台监督者，完全隔离）

按用户拍板的隔离纪律：**monitor 文件夹自持，`.vbs` 与其依赖（dev_dashboard.py 私有副本）即使逻辑与其他脚本相同也单独一份，放在单独文件夹内，永不复用、互不引用**。

- `start-background.vbs`（dev，无热重载）/ `start-background-debug.vbs`（debug）双击即后台启动（无终端窗口）；`start-background.sh` 为 macOS/Linux 对称入口（nohup 拉起监督者）。
- 监督者 = `monitor/dev_dashboard.py --supervise`（python/pythonw 拥有进程树）：端口协商（同全端契约写 `data/port.txt` + `data/frontend_port.txt`）+ 拉起三端（stdin=DEVNULL、CREATE_NO_WINDOW/独立进程组、读线线程落 dev_*.log）+ 状态 JSON 心跳（**5s**）+ backend/vite 意外退出自愈（上限 2）+ electron 退出 = 收摊并写「全停」状态。
- **debug 监督者的 mtime 热重载**：uvicorn `--reload` 在无控制台环境（pythonw）是死路（CTRL_C_EVENT 打不到 worker，reloader 卡死在 process.join()，实测复现）——监督者自己轮询 `backend/**/*.py` mtime（排除 `__pypycache__`），变化即防抖 1.5s 杀树重拉，走同一条自愈链路。
- 网页监控台（监督者自带，8180 起扫空闲端口，浏览器自动打开）：tail 四个 dev_*.log（1s 增量、per-file 字节偏移协议 `GET /api/logs?after={...}`）+ 状态药丸（TCP 探活 + PID 存活核验）+ PHASE 进度横幅。
- **线程解剖钩子**：`threading.excepthook` 把线程异常强制落 `dev_sys.log`（pythonw 下 stderr 为 None，线程异常会静默蒸发）。
- **POSIX 干净停机**：监督者注册 SIGTERM/SIGINT 处理器（置停机标志 → ≤5s 内 stop_all 收摊）；Windows 侧 taskkill /F 是硬杀，由停脚本新鲜度闸兜底。
- **vbs 必须纯 ASCII+CRLF**（wscript 按 ANSI 读文件，UTF-8 中文注释会编译错）。
- **pythonw 断两进程对链**：venv `python.exe` 是「启动器+真解释器」两进程对，杀启动器会经控制台销毁连坐真解释器；`pythonw.exe` 无控制台，断此链。
- 单实例护栏：状态 JSON 新鲜且 dashboard pid 活着则拒启第二棵树（python 侧）；macOS sh 入口另用 pgrep 先挡一道。

## 收摊（stop-velluma，全局通用）

`scripts/stop-velluma.bat`（Windows）/ `stop-velluma.ps1`（逻辑本体）/ `stop-velluma.sh`（macOS/Linux），位于 scripts/ 根，dev / prod / monitor 全通用。

- Windows 顺序：
  1. 状态 JSON PID 杀（白名单 python/pythonw；dashboard 另须命令行含项目路径）+ **新鲜度闸：>120s 无心跳即跳过一切 JSON 衍生杀**（监督者心跳 5s / 控制台 15s）。
  2. 3s 优雅路径。
  3. 扫尾残余启动器（start-all.ps1 / 单服务 start-*.ps1，命令行含本项目路径才杀）+ recorded 端口（白名单+项目路径双闸）。
  4. **孤儿清扫**：端口段 5175~5285 / 8002~8100 监听者与 python/pythonw/node/electron 进程，命令行含本项目路径才判 OWNED。
- macOS：TERM 编排启动器（trap 清理子树）+ TERM 监督者（其信号处理器收拢服务树）+ 带归属闸的端口段清扫（单服务前台脚本 exec 后不是启动器子进程，trap 够不到，靠这里兜底）。

## 两平台共同的行为契约

- **端口段**：后端 `8002~8100`（与 `backend/core/config.py` 的 DEFAULT_PORT..MAX_PORT 对齐），前端 `5175~5285`（仅 dev 环境协商；prod 无 Vite）。协商优先级：环境变量（`VELLUMA_PORT` / `VELLUMA_FRONTEND_PORT`）→ 已记录端口且空闲则复用 → 扫描首个空闲端口。
- **端口文件**：后端实际端口写 `data/port.txt`，前端端口写 `data/frontend_port.txt`（`vite.config.js` 代理与 `electron/main.cjs` 读取）。
- **Electron 环境变量**：各入口为 Electron 设 `VELLUMA_BACKEND_PORT` / `VELLUMA_FRONTEND_PORT`（dev）/ `VELLUMA_SERVICES_READY`；prod 另设 `NODE_ENV=production`。
- **Electron 启动方式**：一切入口一律 `npm run electron:nobuild`（= 直接 `electron .`）——dev 下 `main.cjs` 走 `loadURL`（electron:dev 的 vite build 产物根本不会被加载，白等 30~60s）；prod 的 `dist/` 已显式构建并校验，再 build 一次纯属浪费。`loadURL`/`loadFile` 由 `NODE_ENV` 决定，与构建无关。
- **DryRun**：不写端口文件、不写日志、不杀任何进程、不启动任何东西。
- **项目根推导**：按 `$PSScriptRoot` / `BASH_SOURCE` 向上定位项目根（dev/prod 两级、scripts 根一级、macos/{dev,prod} 三级），脚本可在任意 cwd 调用。
- **平台差异**：venv 路径（`Scripts\python.exe` vs `bin/python`）、端口探测（TcpClient vs `nc`/`/dev/tcp`）、进程清理（Win32_Process vs `lsof`/`pgrep`）。

## 契约自检

```bash
python scripts/check_launcher_contract.py     # 一致退 0，漂移退 1（CI 阻断步）
```

隔离的代价 = 同一组数字写进更多文件（22 个检查面：双平台编排核心 ×4 + 单服务脚本 ×6 + monitor 副本 + 收摊脚本 + 前端 `frontend/src/services/api/transport/base.ts` 判定区间）。历史漂移：前端扫描上界 `5274` / `5275` / `5285` 三版并存、监控台覆盖段与收摊脚本孤儿清扫段对不上。

**改端口段或换 electron npm script 时**：改全部实现 → 改 `check_launcher_contract.py` 里的契约常量 → 跑一次确认变绿。它报错不是噪声，是刚拦下一次真实漂移。

## 日志架构（文件为真相源）

- 编排核心三端 stdout/stderr 由独立读线泵写 `logs/dev_*.log`（`"HH:mm:ss 原始行"` 格式，每次启动重建）；启动器叙事进 `logs/dev_sys.log`。泵与主线程完全异步——控制台/宿主冻结不影响落盘；控制台显示降级为尽力而为。
- 读线泵 / `prefix_stream` 剥 ANSI 色码（npm/vite 管道下仍发色码）。macOS 合流日志 `logs/console_<env>_<时间戳>.log` 受 `--no-log` 门控。
- 单服务前台脚本不落 dev_*.log（输出直进本窗口，看的是终端不是文件）。

## 子进程 stdin 一律切断（编排路径）

- Windows 编排侧 `RedirectStandardInput` 后立即 Close；macOS 编排侧 `</dev/null`。
- 契约依据：否则 vite 的 stdin 快捷键 readline 挂在共享 TTY 上，控制台输入侧一有变动就 EPIPE 崩掉整个 dev server；stdin=已关管道 ⇒ isTTY=false ⇒ vite 跳过快捷键注册。
- 单服务前台脚本例外：它独占本终端，stdin 挂真终端上 vite 交互快捷键（`r` 重启等）反而可用。

## PowerShell 编码坑（改 .ps1 前必读）

- `-f` 逗号表达式直接写在 .NET 方法调用参数位（如 `.WriteLine("..." -f $a, $b)`）时，逗号被解析成参数分隔符 → `FormatException` 被空 catch 吞成静默失效。规则：先在语句位求值到临时变量再传参。**新增 .NET 方法调用内联 `-f` 前先自查**。
- `.ps1` 必须 UTF-8 **带 BOM** + CRLF：PS 5.1 无 BOM 按 ANSI 解码，中文注释/字符串会乱。

## Electron 独立命令（frontend/ 下）

- `npm run electron:dev` / `electron:preview`：均 `npm run build && electron .`，不启 Vite，需 5175 已有服务。
- `npm run electron:nobuild`：跳过 vite build 直接 `electron .`，开发模式用。
- `npm run electron:build`：打包。

## 应用图标单源

- `frontend/electron/app-icon.png`：换图只动这一个文件——两处 `BrowserWindow` 的 `icon` 直读它，`build.win.icon` / `mac.icon` 同指它。要求：方形 PNG ≥256×256。
- `scripts/make_app_icon.py` 仅重新生成出厂占位图，日常换图无需跑。Windows 图标缓存可能滞后，重启应用或资源管理器刷新。

## 工具脚本（非启动）

- `make_blank_atlas.py`：从 Natural Earth 数据生成世界页空白舆图 SVG（`frontend/src/features/world/containers/blankAtlas.ts`），详见 `docs/reports/world-unified-settings.md`。
- `migrate_pg_to_sqlite.py`：存量 PG 库 → SQLite 一次性搬迁（拓扑序搬运+行数对照+外键校验），详见 `AGENTS.md` 数据库节。
- `calibrate_semantic_threshold.py`：文风语义扫描阈值（0.78）校准矩阵，手动跑不进 CI，详见 `docs/style-module-redesign.md`。
- `analyze_context_manifest.py`：解析 trace 的 context_manifest 事件，世界内核 B0.2 观测工具。
- `eval_selector_recall.py`：知识平面选择器 recall/precision 金标准评测，世界内核 B0.3 验收工具。
- `migrate_to_intents.py`：旧源 → world_intents 幂等复制，世界内核 B2 迁移工具。
- `gui_test_seed.py` / `smoke_book_backup.py`：GUI 测试种子 / 书备份冒烟（配合各自测试轮）。
