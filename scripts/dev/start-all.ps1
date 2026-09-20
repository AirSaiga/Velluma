#Requires -Version 5.1
<#
.SYNOPSIS
    Velluma 开发调试环境·一键三端（后端热重载）。
.DESCRIPTION
    scripts/dev/ 四件套的编排核心（与 prod/start-all.ps1 完全独立、互不复用）。
    本脚本位于 scripts/dev/ 子目录，项目根 = $PSScriptRoot 的祖父目录。
      - 后端：uvicorn --reload 热重载（保存 backend/ 下任意 .py 即自动重启），
        端口由脚本侧协商固定并写 data/port.txt；
      - 前端：Vite dev server（端口协商写 data/frontend_port.txt）；
      - Electron：载入 http://localhost:<vitePort>，自动 openDevTools()。
    日志架构（文件为真相源）：三端 stdout/stderr 由独立读线线程（runspace 泵）
    直接写入 logs/dev_backend.log / dev_vite.log / dev_electron.log，与控制台完全
    解耦——控制台（或任何宿主怪癖）冻结都不影响日志落盘。控制台显示为尽力而为：
    读线线程同时入队，主循环非阻塞排水上屏（彩色前缀）：
      1/2/3     只看 后端 / Vite / Electron      0     回到全部视图
      s         立即打印各端状态                 q / Ctrl+C  停止全部服务并退出
    网页监控台不归本脚本管（scripts/monitor/ 单独隔离）；要网页监控用 monitor 下的入口。
    服务状态写 data/dev_status.json（心跳/状态变化时刷新，stop-velluma 读它按 PID 收摊）。
    Electron 关窗等于全部收摊。
    端口契约（与 prod/start-all.ps1、macos 双端、monitor/dev_dashboard.py 监督者共用）：
    后端 8002~8100，前端 5175~5285；scripts/check_launcher_contract.py 锁这些实现
    （改一处须同步）。
.NOTES
    入口：本目录 start-all.bat（薄包装透传参数）。单服务调试用同目录
    start-backend.bat / start-frontend.bat / start-electron.bat（各自独立，前台运行）。
#>
param(
    [switch]$Force,
    [switch]$SkipBackend,
    [switch]$SkipFrontend,
    [switch]$ElectronOnly,
    [switch]$DryRun
)

$ErrorActionPreference = "Stop"

# =============================================================================
# Config
# =============================================================================
# 脚本位于 scripts/dev/ 下，项目根是 $PSScriptRoot 的祖父目录
$ProjectRoot = Split-Path (Split-Path $PSScriptRoot -Parent) -Parent

$Config = @{
    DefaultBackendPort   = 8002
    BackendPortMax       = 8100   # 与 backend/core/config.py、stop-velluma.ps1 孤儿清扫段对齐
    DefaultFrontendPort  = 5175   # 起始扫描端口（向后兼容）
    FrontendPortMax      = 5285   # 与 stop-velluma.ps1 孤儿清扫段对齐
    FrontendPort         = $null  # 实际端口（运行时由 Resolve-FrontendPort 填充）
    ProjectRoot          = $ProjectRoot
    BackendTimeout       = 60
    FrontendTimeout      = 30
    HealthCheckInterval  = 500
    VenvPaths            = @(
        ".venv\Scripts\python.exe"
        "venv\Scripts\python.exe"
    )
    PortFile             = Join-Path $ProjectRoot "data\port.txt"
    FrontendPortFile     = Join-Path $ProjectRoot "data\frontend_port.txt"
    # 监控台
    MonitorPollMs        = 60     # 监控循环轮询间隔
    StatusHeartbeatSec   = 15     # 状态心跳行间隔（秒）
    LogDir               = Join-Path $ProjectRoot "logs"
    StatusFile           = Join-Path $ProjectRoot "data\dev_status.json"   # stop-velluma 数据源
}

$Global:ChildProcesses  = @()   # 全部子进程（Process 对象），退出时按树清理
$Global:Pumps           = @()   # 读线线程（powershell 实例），退出时释放
$Global:LogWriters      = @{}   # key → StreamWriter（各服务日志文件，AutoFlush）
$Global:LogLock         = New-Object System.Object   # 同一服务 stdout/stderr 双泵共写一文件的锁
$Global:DisplayQueue    = New-Object System.Collections.Concurrent.ConcurrentQueue[string]
$Global:TrackedProcs    = @()   # 服务级跟踪（每服务一条，供状态行/退出告警）
$Global:Focus           = 'all' # 当前视图：all | backend | vite | electron
$Global:OrigConsoleMode = $null # QuickEdit 禁用前的控制台模式（退出时恢复）
$Global:RestartCount    = @{}   # backend/vite 意外退出的自愈重启计数（上限 2 次）
$Global:OwnedPorts      = @()   # 本会话「自己启动过服务」的端口登记（收摊端口扫尾只认这些）
$Global:CleanupDone     = $false

# =============================================================================
# Port File Helpers
# =============================================================================
# 端口契约（后端 8002~8100 / 前端 5175~5285）由本脚本、prod/start-all.ps1、macos 双端、
# monitor/dev_dashboard.py 监督者共用——scripts/check_launcher_contract.py 锁一致性。
function ConvertTo-PortOrZero {
    # 环境变量等外部输入 → 合法端口号；非数字/越界一律归零（调用方按"未指定"处理），
    # 不抛异常（旧实现 [int]$env 遇脏值直接崩启动链）
    $port = 0
    if ($Value -and [int]::TryParse([string]$Value, [ref]$port) -and $port -gt 0) { return $port }
    return 0
}

function Read-PortFile([string]$Path, [int]$Fallback = 0) {
    # 读端口文件；缺失/非法/非正数 → 回退值
    if (Test-Path $Path) {
        try {
            $port = [int]((Get-Content $Path -Raw).Trim())
            if ($port -gt 0) { return $port }
        } catch {}
    }
    return $Fallback
}

function Write-PortFile([string]$Path, $Port, [string]$What = "port") {
    # DryRun 只做演示不落盘：否则一次试跑就会把端口文件改指到扫描出的空端口，
    # 正在运行的实例与下次启动的端口协商都会被带偏
    if ($DryRun) { return }
    try {
        $dir = Split-Path $Path -Parent
        if (-not (Test-Path $dir)) { New-Item -ItemType Directory -Path $dir -Force | Out-Null }
        [System.IO.File]::WriteAllText($Path, ([int]$Port).ToString())
    } catch {
        Log-Error "Failed to write $What port file: $_"
    }
}

function Find-FreePort([int]$Start, [int]$End) {
    # 扫描 [Start, End] 找第一个空闲端口（避开其它项目的 Vite/服务占用）
    for ($port = $Start; $port -le $End; $port++) {
        if (-not (Test-PortOpen -Port $port)) { return $port }
    }
    throw "No free port in range $Start..$End"
}

function Resolve-Port {
    # 端口协商，优先级：
    # 1. 环境变量（用户强制指定，透传给后端/前端）
    # 2. 已记录端口（data/*.txt）且该端口空闲 → 复用
    # 3. 扫描空闲端口（Default 起）
    # 选中后落盘（-Persist）。固定端口是 debug 热重载的前提：reload 重启 worker 时
    # 端口不能漂移，否则前端断连。
    param([int]$Default, [int]$Max, [int]$EnvPort, $Recorded, [scriptblock]$Persist)
    if ($EnvPort -gt 0) { & $Persist $EnvPort; return $EnvPort }
    if ($Recorded -and $Recorded -gt 0 -and -not (Test-PortOpen -Port $Recorded)) {
        & $Persist $Recorded
        return $Recorded
    }
    $free = Find-FreePort -Start $Default -End $Max
    & $Persist $free
    return $free
}

function Get-ActualBackendPort {
    return Read-PortFile $Config.PortFile $Config.DefaultBackendPort
}

function Get-ActualFrontendPort {
    # 前端无「默认端口」语义：文件缺失/非法 → $null（调用方自行决定回退）
    $port = Read-PortFile $Config.FrontendPortFile 0
    if ($port -gt 0) { return $port }
    return $null
}

function Set-BackendPortFile($Port) { Write-PortFile $Config.PortFile $Port "backend" }
function Set-FrontendPortFile($Port) { Write-PortFile $Config.FrontendPortFile $Port "frontend" }

function Resolve-BackendPort {
    # 供 debug 热重载：先协商固定端口并写 data/port.txt + 设 VELLUMA_PORT，
    # 让 main.py 跳过内部扫描（__main__ 不执行 → save_port 不会被调用）
    return Resolve-Port -Default $Config.DefaultBackendPort -Max $Config.BackendPortMax `
        -EnvPort (ConvertTo-PortOrZero $env:VELLUMA_PORT) `
        -Recorded (Get-ActualBackendPort) `
        -Persist { param($p) Set-BackendPortFile $p }
}

function Resolve-FrontendPort {
    # 选中端口写 frontend_port.txt，供 vite.config.js 和 electron/main.cjs 读取
    return Resolve-Port -Default $Config.DefaultFrontendPort -Max $Config.FrontendPortMax `
        -EnvPort (ConvertTo-PortOrZero $env:VELLUMA_FRONTEND_PORT) `
        -Recorded (Get-ActualFrontendPort) `
        -Persist { param($p) Set-FrontendPortFile $p }
}

# =============================================================================
# Utility Functions
# =============================================================================
function Log-Success($Message) {
    Write-Host "[OK] $Message" -ForegroundColor Green
    Write-SysLog $Message
}

function Log-Error($Message) {
    Write-Host "[ERR] $Message" -ForegroundColor Red
    Write-SysLog $Message
}

function Log-Info($Message) {
    Write-Host "[*] $Message" -ForegroundColor Gray
    Write-SysLog $Message
}

# =============================================================================
# Port and Process Management
# =============================================================================
function Test-PortOpen($Port) {
    try {
        $client = New-Object System.Net.Sockets.TcpClient
        $result = $client.BeginConnect("127.0.0.1", $Port, $null, $null)
        $success = $result.AsyncWaitHandle.WaitOne(1000, $false)
        if ($success) {
            $client.EndConnect($result)
            $client.Close()
            return $true
        }
        $client.Close()
        return $false
    } catch {
        return $false
    }
}

function Get-ProcessOnPort($Port) {
    try {
        $conn = Get-NetTCPConnection -LocalPort $Port -ErrorAction SilentlyContinue |
                Where-Object { $_.State -eq "Listen" } |
                Select-Object -First 1
        if ($conn) {
            return Get-Process -Id $conn.OwningProcess -ErrorAction SilentlyContinue
        }
    } catch {}
    return $null
}

function Register-OwnedPort([int]$Port) {
    # 本会话端口登记：只有自己亲手启动的服务端口才进册（2026-09-11）——收摊端口
    # 扫尾只认册上的端口。「已在运行」attach 进来的外部服务（状态 JSON 标 external）
    # 与陈旧 port.txt 上的无关占用者不连坐。
    if ($Port -gt 0 -and $Global:OwnedPorts -notcontains $Port) { $Global:OwnedPorts += $Port }
}

function Kill-ProcessOnPort($Port, $Name) {
    # 只杀「自己的」监听者：进程命令行须含本项目路径（与 stop-velluma.ps1 孤儿清扫
    # 同款判据，2026-09-11）。自家服务三形态全带绝对路径：后端=venv python 绝对路径
    # （uvicorn 另带 --app-dir 绝对）、vite 真正监听的 node=node_modules 绝对脚本
    # 路径、监督者 backend 同构。他人项目/无关进程占口 → 拒杀留活（dev/prod 模式
    # 后端内部会顺延扫下一空闲端口，不会卡死启动）。
    $proc = Get-ProcessOnPort -Port $Port
    if ($proc) {
        $cim = Get-CimInstance Win32_Process -Filter "ProcessId=$($proc.Id)" -ErrorAction SilentlyContinue
        $marker = "*" + $Config.ProjectRoot + "*"
        if (-not $cim -or -not $cim.CommandLine -like $marker) {
            Log-Info "Port $Port held by non-Velluma process (pid $($proc.Id), $($proc.Name)) - not killing"
            return $false
        }
        Log-Info "Stopping $Name on port $Port (PID: $($proc.Id))..."
        try {
            Stop-Process -Id $proc.Id -Force -ErrorAction SilentlyContinue
            Start-Sleep -Seconds 2
            return $true
        } catch {
            return $false
        }
    }
    return $false
}

function Stop-ProcessTree($ParentProcessId, $Name = "process") {
    # 递归终止进程树：先杀子进程再杀父进程
    # 用途：uvicorn --reload 的 reloader 父进程会 spawn 一个 worker 子进程，
    #       仅杀父进程会留下 worker 孤儿进程继续占用端口，导致下次启动端口冲突
    # 依赖：CIM_Process.ProcessId/ParentProcessId（Win32 内置，无需外部命令）
    if (-not $ParentProcessId) { return }
    try {
        $children = Get-CimInstance -ClassName Win32_Process -Filter "ParentProcessId=$ParentProcessId" -ErrorAction SilentlyContinue
        foreach ($child in $children) {
            Stop-ProcessTree -ParentProcessId $child.ProcessId -Name $Name
        }
        Stop-Process -Id $ParentProcessId -Force -ErrorAction SilentlyContinue
    } catch {
        # 父进程可能已自行退出，忽略
    }
}

function Wait-ForService($Port, $Name, $TimeoutSeconds = 30) {
    # 静默轮询（就绪/超时由调用方出行，避免中间点阵噪声）
    $sw = [System.Diagnostics.Stopwatch]::StartNew()
    while ($sw.Elapsed.TotalSeconds -lt $TimeoutSeconds) {
        if (Test-PortOpen -Port $Port) {
            return $true
        }
        Start-Sleep -Milliseconds $Config.HealthCheckInterval
    }
    throw "$Name timeout on port $Port (${TimeoutSeconds}s)"
}

# =============================================================================
# Log Plumbing（文件为真相源）
# =============================================================================
# 设计：三端 stdout/stderr 各由一个独立 runspace 泵阻塞式 ReadLine，落文件 + 入显示
# 队列。泵与主线程完全异步——主线程（或控制台宿主）冻结都不影响日志落盘与网页监控台；
# 控制台显示降级为尽力而为（主循环非阻塞排水）。
function ConvertTo-ArgumentString([string[]]$Parts) {
    # PS 5.1（.NET Framework）的 ProcessStartInfo 没有 ArgumentList，只能拼字符串：
    # 含空格的参数包引号（路径场景），内部引号转义
    ($Parts | ForEach-Object {
        if ($_ -match '\s') { '"' + ($_ -replace '"', '\"') + '"' } else { $_ }
    }) -join ' '
}

function New-ServiceLogWriter([string]$Key) {
    # 各服务日志文件（每次启动重建）：logs/dev_<key>.log，行格式 "HH:mm:ss 原始行"
    if ($Global:LogWriters.ContainsKey($Key)) { return $Global:LogWriters[$Key] }
    try {
        if (-not (Test-Path $Config.LogDir)) {
            New-Item -ItemType Directory -Path $Config.LogDir -Force | Out-Null
        }
        $path = Join-Path $Config.LogDir ("dev_{0}.log" -f $Key)
        $writer = New-Object System.IO.StreamWriter($path, $false, [System.Text.UTF8Encoding]::new($false))
        $writer.AutoFlush = $true
        $Global:LogWriters[$Key] = $writer
        return $writer
    } catch {
        Log-Error "Failed to open service log ($Key): $_"
        return $null
    }
}

function Write-SysLog([string]$Line) {
    # 启动器叙事（[..]/[OK]/[ERR]）也进 dev_sys.log，网页监控台可见完整启动故事
    try {
        $writer = New-ServiceLogWriter "sys"
        if ($writer) {
            # ⚠ -f 逗号表达式不能直接写在 .WriteLine(...) 方法参数位（方法调用的逗号是
            # 参数分隔符 → FormatException 被吞成静默空文件）——先语句位求值再传参
            $entry = "{0} {1}" -f (Get-Date -Format 'HH:mm:ss'), $Line
            [System.Threading.Monitor]::Enter($Global:LogLock)
            try { $writer.WriteLine($entry) } finally { [System.Threading.Monitor]::Exit($Global:LogLock) }
        }
    } catch {}
}

function Start-StreamPump {
    # 一个 runspace 泵：阻塞 ReadLine → 带时间戳写服务日志（双泵共写一文件，锁串行）
    # → 入显示队列（供主线程尽力而为上屏）。泵永不碰控制台——宿主冻结与此无关。
    param($Reader, [string]$Key, [string]$Label, $Writer, $Lock, $Queue)

    $script = {
        param($Reader, $Key, $Label, $Writer, $Lock, $Queue)
        try {
            while ($true) {
                $line = $Reader.ReadLine()
                if ($null -eq $line) { break }
                # 剥掉子进程输出的 ANSI 色码（npm/vite 在管道下仍会发）：日志与网页保持干净
                $line = $line -replace '\u001b\[[0-9;]*[A-Za-z]', ''
                $ts = (Get-Date).ToString('HH:mm:ss')
                try {
                    # ⚠ 同 Write-SysLog：-f 表达式先语句位求值，不得内联在 WriteLine 参数位
                    $entry = "{0} {1}" -f $ts, $line
                    [System.Threading.Monitor]::Enter($Lock)
                    try { $Writer.WriteLine($entry) } finally { [System.Threading.Monitor]::Exit($Lock) }
                } catch {}
                # 队列防爆炸：控制台冻结时主线程不消费，超限丢最旧（文件里都有，不丢数据）
                while ($Queue.Count -gt 5000) { $out = $null; [void]$Queue.TryDequeue([ref]$out) }
                $Queue.Enqueue(("$ts|$Label|$line"))
            }
        } catch { }
    }

    $rs = [runspacefactory]::CreateRunspace()
    $rs.Open()
    $ps = [powershell]::Create()
    $ps.Runspace = $rs
    [void]$ps.AddScript($script).AddArgument($Reader).AddArgument($Key).AddArgument($Label).AddArgument($Writer).AddArgument($Lock).AddArgument($Queue)
    $handle = $ps.BeginInvoke()
    $Global:Pumps += @{ PS = $ps; RS = $rs; Handle = $handle }
}

function Invoke-DrainDisplayQueue {
    # 主线程非阻塞排水：队列 → 彩色控制台行（聚焦过滤）。控制台冻结时卡在 Write-Host
    # 也不影响泵与文件——这就是"尽力而为"的显示层。
    $item = $null
    while ($Global:DisplayQueue.TryDequeue([ref]$item)) {
        $parts = $item.Split('|', 3)
        if ($parts.Count -lt 3) { continue }
        $ts = $parts[0]; $label = $parts[1]; $line = $parts[2]
        if ($Global:Focus -eq 'all' -or $Global:Focus -eq $label) {
            $color = switch ($label) { 'backend' { [ConsoleColor]::Cyan } 'vite' { [ConsoleColor]::Green } 'electron' { [ConsoleColor]::Yellow } default { [ConsoleColor]::Gray } }
            Write-Host ("{0} " -f $ts) -ForegroundColor DarkGray -NoNewline
            Write-Host ($label.PadRight(8)) -ForegroundColor $color -NoNewline
            Write-Host "│ " -ForegroundColor DarkGray -NoNewline
            Write-Host $line -ForegroundColor Gray
        }
    }
}

function Show-StartupOutputTail {
    # 启动失败（超时/异常）前把已到达的输出冲上屏（文件里的不会丢，这里是给控制台的）
    Invoke-DrainDisplayQueue
    Start-Sleep -Milliseconds 400
    Invoke-DrainDisplayQueue
}

function Disable-QuickEdit {
    # ⚠ 控制台快速编辑模式（Windows 默认开）：在窗口里点选文本会进入选择状态，
    # 此后所有 Write-Host 阻塞——曾致监控循环卡死（日志架构重构后只损失显示层）。
    # 启动时清掉 QUICK_EDIT 位，退出时恢复原模式。
    # 代价：本窗口不可划选复制——复制需求走网页监控台。
    try {
        if (-not ('Velluma.Native.ConsoleMode' -as [type])) {
            Add-Type -Namespace Velluma.Native -Name ConsoleMode -MemberDefinition @'
[DllImport("kernel32.dll", SetLastError = true)]
public static extern IntPtr GetStdHandle(int nStdHandle);
[DllImport("kernel32.dll", SetLastError = false)]
public static extern bool GetConsoleMode(IntPtr hConsoleHandle, out int lpMode);
[DllImport("kernel32.dll", SetLastError = true)]
public static extern bool SetConsoleMode(IntPtr hConsoleHandle, int dwMode);
'@
        }
        $h = [Velluma.Native.ConsoleMode]::GetStdHandle(-10)   # STD_INPUT_HANDLE
        $m = 0
        if ([Velluma.Native.ConsoleMode]::GetConsoleMode($h, [ref]$m)) {
            $Global:OrigConsoleMode = $m
            $new = ($m -band (-bnot 0x0040)) -bor 0x0080        # 清 QUICK_EDIT，置 EXTENDED_FLAGS
            return [bool][Velluma.Native.ConsoleMode]::SetConsoleMode($h, $new)
        }
    } catch {}
    return $false
}

function Restore-ConsoleMode {
    if ($null -ne $Global:OrigConsoleMode) {
        try {
            $h = [Velluma.Native.ConsoleMode]::GetStdHandle(-10)
            [void][Velluma.Native.ConsoleMode]::SetConsoleMode($h, $Global:OrigConsoleMode)
            $Global:OrigConsoleMode = $null
        } catch {}
    }
}

function Start-MonitoredProcess {
    # 以"输出重定向子进程"启动一个服务并挂入读线泵（stdout/stderr 各一泵）。
    # -Quiet：不挂泵也不跟踪（网页监控台等后台件）——重定向一并关闭，
    #   防止无人读取的管道缓冲写满后把子进程卡死；它异常时输出直落控制台反而可见。
    # 返回 Process 对象（供退出等待/树清理用）。
    param(
        [string]$FilePath,
        [string[]]$ArgumentList,
        [string]$WorkingDirectory,
        [string]$Key,
        [string]$Label,
        [hashtable]$EnvVars = @{},
        [switch]$Quiet
    )

    $psi = New-Object System.Diagnostics.ProcessStartInfo
    $psi.FileName = $FilePath
    if ($ArgumentList -and $ArgumentList.Count -gt 0) {
        $psi.Arguments = ConvertTo-ArgumentString $ArgumentList
    }
    $psi.WorkingDirectory = $WorkingDirectory
    $psi.UseShellExecute = $false
    $psi.CreateNoWindow = $true

    if (-not $Quiet) {
        $psi.RedirectStandardOutput = $true
        $psi.RedirectStandardError = $true
        # ⚠ stdin 也重定向并在启动后立即关闭：切断子进程对控制台输入缓冲的继承。
        # 否则 vite 的 stdin 快捷键 readline 挂在我们共享的 TTY 上，控制台输入侧
        # 一有变动（按键被监控台读走/模式切换/宿主抖动）就 EPIPE 把整个 vite 崩掉
        # （2026-09-05 实机事故）。stdin=已关管道 → isTTY=false → vite 跳过快捷键注册。
        $psi.RedirectStandardInput = $true
        # 子进程管道输出按 UTF-8 解码：python 管道下默认跟随系统代码页（GBK），中文日志会乱码
        $psi.StandardOutputEncoding = [System.Text.Encoding]::UTF8
        $psi.StandardErrorEncoding = [System.Text.Encoding]::UTF8
    }

    foreach ($k in $EnvVars.Keys) {
        if ($null -eq $EnvVars[$k]) {
            $psi.EnvironmentVariables.Remove($k) | Out-Null
        } else {
            $psi.EnvironmentVariables[$k] = [string]$EnvVars[$k]
        }
    }

    $proc = [System.Diagnostics.Process]::Start($psi)
    try {
        # 立即关闭 stdin 写端：子进程读到干净的 EOF（vite 据此跳过快捷键监听）
        $proc.StandardInput.Close()
    } catch {}

    $Global:ChildProcesses += $proc

    if (-not $Quiet) {
        $writer = New-ServiceLogWriter $Key
        Start-StreamPump -Reader $proc.StandardOutput -Key $Key -Label $Key -Writer $writer -Lock $Global:LogLock -Queue $Global:DisplayQueue
        Start-StreamPump -Reader $proc.StandardError -Key $Key -Label $Key -Writer $writer -Lock $Global:LogLock -Queue $Global:DisplayQueue
        $Global:TrackedProcs += @{ Key = $Key; Label = $Key; Proc = $proc; Alerted = $false }
    }

    return $proc
}

function Write-DevStatus {
    # 状态 JSON（stop-velluma 数据源）：启动完成、心跳、状态变化时重写。
    # 网页监控台已隔离到 scripts/monitor/（本环境无 dashboard 子进程，恒写 null）。
    # 前后端协议见 monitor/dev_dashboard.py 的 build_status（两端改字段须同步）。
    try {
        $knownPorts = @{
            backend  = Get-ActualBackendPort
            vite     = if ($Config.FrontendPort) { $Config.FrontendPort } else { Get-ActualFrontendPort }
            electron = $null
        }
        $services = @{}
        foreach ($key in @('backend', 'vite', 'electron')) {
            $t = $Global:TrackedProcs | Where-Object { $_.Key -eq $key } | Select-Object -First 1
            if ($t) {
                $state = if ($t.Proc.HasExited) { "exited" } else { "running" }
                $services[$key] = @{ pid = $t.Proc.Id; port = $knownPorts[$key]; state = $state }
            } else {
                $port = $knownPorts[$key]
                $state = if ($port -and (Test-PortOpen -Port $port)) { "external" } else { "-" }
                $services[$key] = @{ pid = $null; port = $port; state = $state }
            }
        }
        $payload = @{
            mode       = "dev"
            hidden     = $false
            started_at = (Get-Date -Format 'yyyy-MM-dd HH:mm:ss')
            log_dir    = $Config.LogDir
            services   = $services
            dashboard  = @{ pid = $null; port = $null }
        }
        $dir = Split-Path $Config.StatusFile -Parent
        if (-not (Test-Path $dir)) { New-Item -ItemType Directory -Path $dir -Force | Out-Null }
        [IO.File]::WriteAllText($Config.StatusFile, ($payload | ConvertTo-Json -Depth 5), (New-Object System.Text.UTF8Encoding $false))
    } catch {}
}

function Show-MonitorStatus {
    # 状态心跳行：各服务存活态 + 端口 + 当前视图
    $parts = @()
    foreach ($t in $Global:TrackedProcs) {
        $state = if (-not $t.Proc.HasExited) { "运行" } else { "退出" }
        $port = ""
        if ($t.Key -eq 'backend') { $port = " :$(Get-ActualBackendPort)" }
        elseif ($t.Key -eq 'vite' -and $Config.FrontendPort) { $port = " :$($Config.FrontendPort)" }
        $parts += ("{0}({1}{2})" -f $t.Label, $state, $port)
    }
    if ($parts.Count -eq 0) { $parts = @("无被监控服务") }
    $focusLabel = if ($Global:Focus -eq 'all') { "全部" } else { $Global:Focus }
    Write-Host ("── {0}  {1}  │ 视图: {2} ──" -f (Get-Date -Format 'HH:mm:ss'), ($parts -join ' | '), $focusLabel) -ForegroundColor DarkGray
}

function Set-Restarter {
    # 服务自愈的重启入口（键 → 启动函数）；已预注入（harness）则不覆盖
    if ($Global:Restarters -and $Global:Restarters.Count -gt 0) { return }
    $Global:Restarters = @{
        backend  = { Start-Backend }
        vite     = { Start-Frontend }
    }
}

function Restart-ServiceByKey([string]$Key) {
    # 摘除旧跟踪项后重走启动函数（内部自带端口协商与"已在运行"复用）。
    # electron 不参与自愈——它的退出是收摊契约的锚点。
    if (-not $Global:Restarters.ContainsKey($Key)) { return }
    $Global:TrackedProcs = @($Global:TrackedProcs | Where-Object { $_.Key -ne $Key })
    $Global:RestartCount[$Key] = [int]$Global:RestartCount[$Key] + 1
    Write-Host ("[sys] {0} 正在自动重启（第 {1}/2 次）..." -f $Key, $Global:RestartCount[$Key]) -ForegroundColor Yellow
    Write-SysLog ("{0} 自动重启（第 {1}/2 次）" -f $Key, $Global:RestartCount[$Key])
    try {
        & $Global:Restarters[$Key]
    } catch {
        Log-Error "restart ${Key} failed: $_"
    }
}

function Start-MonitorLoop {
    # 监控主循环：排水（显示）+ 按键 + 心跳 + 退出检测，直到 Electron 退出或用户按 q/Ctrl+C。
    # ⚠ 日志落盘不依赖本循环（读线泵独立）——本循环冻结只损失控制台显示与状态心跳。
    param($ElectronProc)

    # 监控循环期接管 Ctrl+C（作为普通按键读入，统一走"停全部"清理路径）。
    # 启动阶段保持默认语义：Ctrl+C 直接中断管线，由 finally 兜底清理。
    $tookOverCtrlC = $false
    try { [Console]::TreatControlCAsInput = $true; $tookOverCtrlC = $true } catch {}

    # 输入被重定向（如从别的脚本/CI 调起）时 KeyAvailable 不可用 → 降级为无键盘模式，
    # 仍保留排水 + 心跳 + Electron 退出即收摊
    $keyboardOk = $true
    try { $null = [Console]::KeyAvailable } catch { $keyboardOk = $false }

    try {
        Write-Host ""

        if ($keyboardOk) {
            Write-Host "  按键 → [1] 后端  [2] 前端  [3] Electron  [0] 全部  [s] 状态  [q] 停止全部（Ctrl+C 同）" -ForegroundColor DarkGray
        } else {
            Write-Host "  （输入未接终端，按键不可用；关闭 Electron 窗口或 Ctrl+C 停止全部）" -ForegroundColor DarkGray
        }
        Write-Host ""

        Show-MonitorStatus
        Write-DevStatus
        Set-Restarter
        $lastStatus = Get-Date
        $running = $true

        while ($running) {
            Invoke-DrainDisplayQueue

            if ($keyboardOk) {
                try {
                    while ([Console]::KeyAvailable) {
                        $key = [Console]::ReadKey($true)
                        $isCtrlC = ($key.Key -eq [ConsoleKey]::C) -and (($key.Modifiers -band [ConsoleModifiers]::Control) -ne 0)
                        switch ($key.Key) {
                            'D1'      { Set-Focus 'backend' }
                            'D2'      { Set-Focus 'vite' }
                            'D3'      { Set-Focus 'electron' }
                            'D0'      { Set-Focus 'all' }
                            'NumPad1' { Set-Focus 'backend' }
                            'NumPad2' { Set-Focus 'vite' }
                            'NumPad3' { Set-Focus 'electron' }
                            'NumPad0' { Set-Focus 'all' }
                            'S'       { Show-MonitorStatus }
                            'Q'       { $running = $false }
                            'C'       { if ($isCtrlC) { $running = $false } }
                        }
                        if (-not $running) { break }
                    }
                } catch { $keyboardOk = $false }
            }

            if (-not $running) {
                Log-Info "Stopping all services..."
                break
            }

            # 状态心跳
            if (((Get-Date) - $lastStatus).TotalSeconds -ge $Config.StatusHeartbeatSec) {
                Show-MonitorStatus
                Write-DevStatus
                $lastStatus = Get-Date
            }

            # 服务意外退出：红色告警 + 写入 dev_sys.log（隐藏模式下控制台不可见，文件是唯一可见渠道）
            # + 后端/前端自愈重启（上限 2 次）。Electron 除外——它的退出是收摊契约的锚点。
            foreach ($t in $Global:TrackedProcs) {
                if ($t.Key -ne 'electron' -and $t.Proc.HasExited -and -not $t.Alerted) {
                    $t.Alerted = $true
                    Write-Host ("[sys] {0} 进程已退出 (code {1})" -f $t.Label, $t.Proc.ExitCode) -ForegroundColor Red
                    Write-SysLog ("{0} 进程已退出 (code {1})" -f $t.Label, $t.Proc.ExitCode)
                    Write-DevStatus
                    if ([int]$Global:RestartCount[$t.Key] -lt 2) {
                        Restart-ServiceByKey -Key $t.Key
                        Write-DevStatus
                    } else {
                        Write-Host ("[sys] {0} 已达重启上限，放弃（按 q 停止全部）" -f $t.Label) -ForegroundColor Red
                        Write-SysLog ("{0} 已达重启上限，放弃" -f $t.Label)
                    }
                }
            }

            # Electron 退出 = 全部服务收摊（与旧契约一致：关窗即停）
            if ($ElectronProc -and $ElectronProc.HasExited) {
                Show-StartupOutputTail
                Write-Host ""
                Log-Info "Electron exited (code $($ElectronProc.ExitCode))"
                $running = $false
                break
            }

            Start-Sleep -Milliseconds $Config.MonitorPollMs
        }
    } finally {
        if ($tookOverCtrlC) { try { [Console]::TreatControlCAsInput = $false } catch {} }
    }
}

# =============================================================================
# Startup Progress（紧凑单行进度，避免噪声）
# =============================================================================
function Write-ProgressLine([string]$Text, [ConsoleColor]$Color) {
    # 行内覆盖：[..] starting... → 完成后同位置改写为 [OK]/[ERR]
    Write-Host ("`r" + $Text.PadRight([Math]::Max($Text.Length + 4, 70))) -ForegroundColor $Color -NoNewline
    Write-SysLog $Text
}

function Clear-ProgressLine {
    Write-Host ("`r" + (" " * 78) + "`r") -NoNewline
    Write-Host ""
}

# =============================================================================
# Cleanup
# =============================================================================
function Invoke-Cleanup() {
    if ($Global:CleanupDone) { return }
    $Global:CleanupDone = $true

    Restore-ConsoleMode

    # DryRun 只做演示：绝不杀树/杀端口，否则一次试跑会清掉正在运行的服务
    #（实锤过：DryRun 试跑曾误杀 8002 上的在跑后端）
    if ($DryRun) { return }

    foreach ($proc in $Global:ChildProcesses) {
        if ($proc -and !$proc.HasExited) {
            try {
                # 用进程树清理：debug 模式下后端是 uvicorn --reload，
                # reloader 父进程会 spawn worker 子进程，必须先杀子再杀父，否则留下孤儿占用端口
                Stop-ProcessTree -ParentProcessId $proc.Id
            } catch {}
        }
    }

    # 端口扫尾只认本会话登记过的端口（Register-OwnedPort，2026-09-11）：「已在运行」
    # attach 的外部服务绝不收掉（旧实现关 Electron 会把并行会话/用户自启的后端一并
    # 杀掉）；启动早期失败（如 venv 缺失）时 port.txt 的陈旧端口也不再误伤当时的
    # 占用者。prod 模式无 Vite 自然不在册，无需模式特判。Kill-ProcessOnPort 内部
    # 另有归属核验（命令行含项目路径）双保险。
    foreach ($port in @($Global:OwnedPorts)) {
        Kill-ProcessOnPort -Port $port -Name "service" | Out-Null
    }

    # 子进程树已杀 → 管道关闭 → 泵自然退出；稍候释放资源
    Start-Sleep -Milliseconds 300
    foreach ($p in $Global:Pumps) {
        try { $p.PS.Dispose() } catch {}
        try { $p.RS.Dispose() } catch {}
    }
    foreach ($w in $Global:LogWriters.Values) {
        try { $w.Dispose() } catch {}
    }

    Log-Success "All stopped"
}

# =============================================================================
# Service Startup
# =============================================================================
function Find-Python() {
    foreach ($path in $Config.VenvPaths) {
        $fullPath = Join-Path $Config.ProjectRoot $path
        if (Test-Path $fullPath) {
            return $fullPath
        }
    }
    throw "Python venv not found. Please ensure .venv or venv exists."
}

function Start-Backend() {
    $backendPort = Get-ActualBackendPort
    if ($SkipBackend -or $ElectronOnly) {
        if (Test-PortOpen -Port $backendPort) {
            Write-ProgressLine "[..] backend   已在运行 (:${backendPort})" ([ConsoleColor]::DarkGray)
            Write-Host ""
            return
        }
        throw "Backend not running but skip flag set"
    }

    # uvicorn --reload 后端热重载（dev 环境唯一形态）：保存 Python 文件即自动重启
    # 热重载的关键约束：
    #   1. --reload 必须传 import path（backend.main:app），不能传 app 对象（main.py 的 __main__ 不走）
    #   2. reload 重启 worker 时端口必须固定，否则前端断连 → 由脚本侧协商端口并设 VELLUMA_PORT
    #   3. main.py 的 __main__ 不会执行 → save_port 不会被调用 → port.txt 必须由脚本侧写好
    # 先抢占固定端口并写 data/port.txt + 设环境变量，让 main.py 跳过内部扫描
    $backendPort = Resolve-BackendPort

    Write-ProgressLine "[..] backend   starting..." ([ConsoleColor]::DarkYellow)

    if (Test-PortOpen -Port $backendPort) {
        if ($Force) {
            Kill-ProcessOnPort -Port $backendPort -Name "backend" | Out-Null
        } else {
            Write-ProgressLine "[OK] backend   已在运行 http://127.0.0.1:$backendPort" ([ConsoleColor]::Cyan)
            Write-Host ""
            return
        }
    }

    $pythonPath = Find-Python

    if ($DryRun) {
        Clear-ProgressLine
        Log-Info "[DryRun] Would start (reload): $pythonPath -m uvicorn backend.main:app --port $backendPort --reload"
        return
    }

    # PYTHONIOENCODING：管道下 python 默认跟随系统代码页（GBK），中文日志经 UTF-8 解码会乱码
    $backendEnv = @{ PYTHONUNBUFFERED = "1"; PYTHONIOENCODING = "utf-8"; VELLUMA_PORT = $backendPort.ToString() }

    # uvicorn --reload：reloader 父进程 + worker 子进程
    # --app-dir .：让 backend.main 可作为顶层模块 import（cwd 已是项目根）
    # --reload-dir backend：仅监听 backend/ 下的 .py 变更，避免 frontend/data/logs 触发误重启
    # 输出由读线泵落 logs/dev_backend.log + 尽力而为上屏；重启 worker 继承同一管道，日志不断流
    $backendDir = Join-Path $Config.ProjectRoot "backend"
    $argList = @(
        "-m", "uvicorn", "backend.main:app",
        "--host", "127.0.0.1",
        "--port", $backendPort.ToString(),
        "--reload",
        "--reload-dir", $backendDir,
        "--app-dir", $Config.ProjectRoot
    )
    $proc = Start-MonitoredProcess -FilePath $pythonPath `
        -ArgumentList $argList `
        -WorkingDirectory $Config.ProjectRoot `
        -Key "backend" `
        -EnvVars $backendEnv
    Register-OwnedPort $backendPort   # 端口由本会话协商固定，入收摊杀册

    try {
        $null = Wait-ForService -Port $backendPort -Name "Backend (reload)" -TimeoutSeconds $Config.BackendTimeout
    } catch {
        Clear-ProgressLine
        Show-StartupOutputTail
        throw
    }
    $note = if ($backendPort -ne $Config.DefaultBackendPort) { "（$($Config.DefaultBackendPort) 被占）" } else { "" }
    Write-ProgressLine "[OK] backend   http://127.0.0.1:$backendPort (hot-reload ON)$note" ([ConsoleColor]::Cyan)
    Write-Host ""
}

function Start-Electron() {
    Write-ProgressLine "[..] electron  starting..." ([ConsoleColor]::DarkYellow)

    $frontendDir = Join-Path $Config.ProjectRoot "frontend"
    $backendPort = Get-ActualBackendPort

    # 公共环境变量（按进程精确注入，不污染脚本会话环境）
    $electronEnv = @{
        VELLUMA_BACKEND_PORT   = $backendPort.ToString()
        VELLUMA_SERVICES_READY = "1"
    }
    if ($Config.FrontendPort) {
        $electronEnv["VELLUMA_FRONTEND_PORT"] = $Config.FrontendPort.ToString()
    } else {
        $electronEnv["VELLUMA_FRONTEND_PORT"] = $null
    }

    # dev 环境：显式删除 NODE_ENV（外部环境残留会让 main.cjs 误判走 loadFile 分支）
    $electronEnv["NODE_ENV"] = $null

    if ($DryRun) {
        Clear-ProgressLine
        Log-Info "[DryRun] Would run: npm run electron:nobuild (cwd: $frontendDir)"
        return
    }

    # electron:nobuild（= 直接 "electron ."）：main.cjs 走 loadURL 加载 vite dev server，
    # electron:dev 里的 vite build 产物根本不会被加载，白等 30~60 秒；
    # loadURL/loadFile 由 NODE_ENV 决定，与构建无关。
    $proc = Start-MonitoredProcess -FilePath "cmd.exe" `
        -ArgumentList @("/c", "npm", "run", "electron:nobuild") `
        -WorkingDirectory $frontendDir `
        -Key "electron" `
        -EnvVars $electronEnv

    Write-ProgressLine "[OK] electron  pid $($proc.Id)" ([ConsoleColor]::Yellow)
    Write-Host ""

    return $proc
}

function Start-Frontend() {
    # 开发/调试模式：启动 Vite dev server（端口动态协商）
    # 协商前端端口（动态扫描空闲端口，避免与其它项目冲突）
    $frontendPort = Resolve-FrontendPort
    $Config.FrontendPort = $frontendPort

    if ($SkipFrontend -or $ElectronOnly) {
        if (Test-PortOpen -Port $frontendPort) {
            Write-ProgressLine "[..] vite      已在运行 (:${frontendPort})" ([ConsoleColor]::DarkGray)
            Write-Host ""
            return
        }
        throw "Frontend not running but skip flag set"
    }

    Write-ProgressLine "[..] vite      starting..." ([ConsoleColor]::DarkYellow)

    $frontendDir = Join-Path $Config.ProjectRoot "frontend"

    if (!(Test-Path (Join-Path $frontendDir "node_modules"))) {
        Clear-ProgressLine
        throw "node_modules not found. Please run: cd frontend && npm install"
    }

    if (Test-PortOpen -Port $frontendPort) {
        if ($Force) {
            Kill-ProcessOnPort -Port $frontendPort -Name "frontend" | Out-Null
        } else {
            Write-ProgressLine "[OK] vite      已在运行 http://127.0.0.1:$frontendPort" ([ConsoleColor]::Green)
            Write-Host ""
            return
        }
    }

    if ($DryRun) {
        Clear-ProgressLine
        Log-Info "[DryRun] Would start: npm run dev (cwd: $frontendDir, port $frontendPort)"
        return
    }

    # Vite dev server：旧版用隐藏窗口启动，输出完全不可见（代理 wedge 类故障无法排障）；
    # 现由读线泵落 logs/dev_vite.log + 尽力而为上屏
    $proc = Start-MonitoredProcess -FilePath "cmd.exe" `
        -ArgumentList @("/c", "npm", "run", "dev") `
        -WorkingDirectory $frontendDir `
        -Key "vite" `
        -EnvVars @{ VELLUMA_FRONTEND_PORT = $frontendPort.ToString() }
    Register-OwnedPort $frontendPort   # 端口由本会话协商固定，入收摊杀册

    try {
        $null = Wait-ForService -Port $frontendPort -Name "Frontend" -TimeoutSeconds $Config.FrontendTimeout
    } catch {
        Clear-ProgressLine
        Show-StartupOutputTail
        throw
    }
    $note = if ($frontendPort -ne $Config.DefaultFrontendPort) { "（$($Config.DefaultFrontendPort) 被占）" } else { "" }
    Write-ProgressLine "[OK] vite      http://127.0.0.1:$frontendPort$note" ([ConsoleColor]::Green)
    Write-Host ""
}

# =============================================================================
# Main
# =============================================================================
function Show-Header() {
    Write-Host ""
    Write-Host "  Velluma · DEV（热重载）" -ForegroundColor Cyan
    Write-Host ""
}

function Show-ReadyBlock() {
    Write-Host ("─" * 74) -ForegroundColor DarkGray
    Write-Host "  日志        logs\dev_backend.log · dev_vite.log · dev_electron.log" -ForegroundColor DarkGray
    Write-Host "  网页监控台  scripts\monitor\（独立文件夹，与本次启动互不影响）" -ForegroundColor DarkGray
    Write-Host "  关闭 Electron 窗口 / 按 q → 停止全部服务；后台收摊 → scripts\stop-velluma.bat" -ForegroundColor Yellow
    Write-Host ("─" * 74) -ForegroundColor DarkGray
    Write-Host ""
}

function Main() {
    Show-Header

    # QuickEdit 禁用须最先做（DryRun 除外）：启动期间用户点击窗口同样会冻结输出
    $quickEditOff = Disable-QuickEdit
    if (-not $quickEditOff) {
        Log-Info "（未能禁用快速编辑模式：请勿在本窗口点选文本，会冻结监控输出）"
    }

    try {
        Start-Backend
        Start-Frontend

        $electronProc = Start-Electron

        if ($DryRun) {
            Log-Info "DryRun complete, no processes started"
            return
        }

        Write-DevStatus
        Show-ReadyBlock

        # 监控主循环：排水（显示）+ 状态心跳 + 按键交互；Electron 退出 = 全部收摊
        Start-MonitorLoop -ElectronProc $electronProc

    } catch {
        Clear-ProgressLine
        Write-Host ""
        Log-Error "Startup failed: $_"
        exit 1
    } finally {
        Invoke-Cleanup
    }
}

# Run
Main
