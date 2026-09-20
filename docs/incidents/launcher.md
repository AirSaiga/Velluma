# 桌面启动器施工日志

桌面应用启动器（start.ps1 / start.sh / dev_dashboard.py 监督者 / 后台模式 / 停止脚本 / 端口契约 / 日志架构 / Electron 命令与图标）的时效施工与事故记录。稳定契约见 `scripts/README.md`（编辑该领域代码前必读）；本文是时效叙事的唯一追溯处。

### 监控台改造与控制台冻结事故两连（2026-09-04/05）

- 动机：vite 此前是隐藏窗口，输出完全不可见，代理 wedge 类故障无法排障——`start.ps1` 改为三端全部输出重定向子进程（勿回退各开终端/隐藏窗口）。
- 事故：监控循环曾两次卡死在第一行输出前（子进程照跑/日志零写入）。首次确认 QuickEdit 点选文本阻塞 Write-Host（已加启动禁用+退出恢复）；二轮禁用后仍复现一次、阻塞因素未究。
- 结论：日志架构改为**文件真相源**——泵与主线程完全异步，控制台/宿主冻结不影响日志落盘与网页监控台；控制台显示降级为尽力而为（显示层可弃，数据不丢）。

### 三模式统一 electron:nobuild（2026-09-05）

- dev/debug 下 main.cjs 走 loadURL，`electron:dev` 里的 vite build 产物根本不会被加载、白等 30~60 秒；prod 的 dist 由编排核心显式 `npm run build` 构建并校验，再 build 一次同属浪费——三模式统一 `electron:nobuild`（= 直接 `electron .`）。

### DryRun 护栏由来

- 试跑曾误杀在跑后端 → DryRun 不写端口文件、不杀任何树/端口。

### 后台模式改用 python 监督者（2026-09-05）

- 隐藏 powershell 主循环在本机屡次冻在入场、整树被外部静默终止；python 实测存活率压倒性——后台关键路径改为 `.venv\Scripts\pythonw.exe` 跑 `dev_dashboard.py --supervise`，powershell 不参与。

### 子进程 stdin 切断（2026-09-05 vite EPIPE 事故）

- vite 的 stdin 快捷键 readline 挂在共享 TTY 上，控制台输入侧一有变动就 EPIPE 崩掉整个 dev server → 子进程 stdin 一律切断（Windows `RedirectStandardInput` 后立即 Close / macOS `</dev/null`）；顺带 isTTY=false 使 vite 跳过快捷键注册。

### pythonw 下 uvicorn --reload 死路与 mtime 热重载（2026-09-06）

- pythonw 无控制台下 CTRL_C_EVENT 打不到 worker、reloader 卡死在 process.join()（实测复现死路）→ debug 监督者不再传 `--reload`，改 `_backend_reload_watcher` 轮询 `backend/**/*.py` mtime（排除 `__pycache__`）杀树重拉、走自愈链路；服务锁改 RLock（热重载线程持锁内再拿锁须同线程可重入）。控制台模式 start-debug.bat 直启 uvicorn --reload 路径不变。

### PHASE 心跳线程静默蒸发（2026-09-05/06）

- PHASE 漏加 global 的 UnboundLocalError 致心跳线程首拍即死；pythonw 下 stderr 为 None，线程异常静默蒸发——靠 `threading.excepthook` 强制落 dev_sys.log 定位，钩子保留为常驻设施。

### PowerShell -f 逗号坑三连踩

- `.WriteLine("..." -f $a, $b)` 类 .NET 方法调用参数位内联 `-f`：逗号被解析成参数分隔符，FormatException 被空 catch 吞成静默失效。三连踩点：Write-SessionLog / Write-SysLog / 泵脚本块。规则留在 `scripts/README.md`（语句位先求值到临时变量再传参）。

### 端口契约漂移史（契约自检 2026-09-10 落地前后）

- 前端扫描上界 5274 / 5275 / 5285 三版并存；监控台覆盖段与收摊脚本孤儿清扫段对不上。`check_launcher_contract.py` 成为 CI 阻断步后兜底（漂移史也见 `scripts/README.md` 契约自检节）。

### 收摊误伤两修（2026-09-11）

- `stop_all` 曾对被 Windows 回收的死 PID taskkill `/T` 整树误杀（并非「仅报错无副作用」）→ 只杀活 PID：死条目一律跳过、自愈放弃即时出册、停机末笔状态 JSON 改写「全停」防陈旧 PID 流传。
- 陈旧 JSON 里的 PID 被回收后同名进程照样过白名单 → 新鲜度闸：>120s 无心跳即跳过一切 JSON 衍生杀（心跳正常 5~15s；冻结的启动器/监督者由活进程扫尾兜住）。
- `Kill-ProcessOnPort` 增加项目路径闸：拒杀命令行不含本项目路径的监听者。
- 孤儿清扫 OWNED 判定（命令行含本项目路径）实测正确跳过 QQ/搜狗输入法进程。

### 应用图标单源化（2026-09-13）

- 换图收敛到 `frontend/electron/app-icon.png` 单文件（两处 BrowserWindow icon 直读 + build.win.icon/mac.icon 同指），替代此前散落的图标路径；`scripts/make_app_icon.py` 只生成出厂占位图。Windows 图标缓存可能滞后属已知现象。

### 目录重组：环境/功能完全隔离（2026-09-19）

- 用户拍板按**环境/功能完全隔离**重排 scripts/：`scripts/dev/`（开发调试·后端热重载）与 `scripts/prod/`（生产）各四入口（backend/frontend/electron/all），`scripts/monitor/` 网页监控台+后台监督者完全自持（vbs 与其依赖 `dev_dashboard.py` 私有副本——即使逻辑相同也单独一份、永不复用），`scripts/macos/{dev,prod}/` 对称两模式，收摊脚本 `scripts/stop-velluma.{bat,ps1,sh}` 升 scripts/ 根全局通用。旧三模式收敛为两模式（原 debug 热重载形态=新 dev；原无热重载 dev 退役）。
- 编排核心由现役 `start.ps1`/`start.sh` 派生后**模式硬焊死**（dev 副本只留 reload 分支、prod 副本只留 main.py/`__main__`+build 分支），互不复用；单服务脚本是新增能力（前台直跑、端口协商与全端同契约、编排核心的 stdin 切断纪律不适用——独占终端时 vite 交互快捷键反而可用）。
- 网页监控台从编排核心剥离（控制台 start-all 不再自动拉 dashboard/开浏览器）——监控台成为 monitor 文件夹专属产品；`scripts/dev_dashboard.py` 根副本删除，唯一实现=monitor 私有副本。
- `check_launcher_contract.py` 检查面从 5 扩到 22（双平台编排×4 + 单服务×6 + monitor 副本 + 收摊 + 前端判定）；前端端口段仅 dev 侧持有（prod 无 Vite）。
- monitor 副本补 POSIX SIGTERM/SIGINT 处理器（置停机标志→≤5s stop_all 收拢服务树）：新 `monitor/start-background.sh`（macOS 后台入口，nohup 拉监督者，不再走控制台 start.sh）需要它，否则 TERM 打死监督者后独立进程组里的子服务全孤儿。`stop-velluma.sh` 重写：TERM 编排启动器+TERM 监督者+带归属闸（`grep -qF 项目根`）的端口段清扫（单服务前台脚本 exec 后不是启动器子进程，trap 够不到）。
- 施工误触与意外收获：验证 vbs 时误用 `cscript` 直接执行（会拉起整棵服务树含 Electron 窗口）——当场用新 `stop-velluma.ps1` 收干净（status JSON 杀监督者 + 孤儿清扫扫其余），反而完成了一次 vbs→监督者→三端→收摊的全链路实测。**教训：vbs 没有 parse-only 模式，cscript 即执行，验证只能靠审读。**
- 同步面：scripts/README.md 重写、AGENTS.md 启动器章节（新增「环境/功能隔离纪律勿回退」不变量）、根 README 四段、前端三处注释（vite.config.js / main.cjs / base.ts，纯注释）。CI 命令路径不变（`python scripts/check_launcher_contract.py`）。
- 编码纪律新增：`.ps1` 必须 UTF-8 带 BOM+CRLF（PS 5.1 无 BOM 按 ANSI 解码中文即乱）；新 .bat/.vbs CRLF、.sh LF。
