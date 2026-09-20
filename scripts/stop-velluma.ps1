#Requires -Version 5.1
<#
.SYNOPSIS
    Velluma 一键收摊：停止后台/前台启动的全部服务（dev / prod / monitor 通用）。
.DESCRIPTION
    位于 scripts/ 根，项目根 = $PSScriptRoot 的父目录。停止顺序（给优雅路径优先权）：
      1. 按状态 JSON（data/dev_status.json）杀 Electron + 后台监督者（monitor）
         ——启动器探测到 Electron 退出后会自行清理后端/前端并退出；
      2. 等 3 秒后扫尾：残余 start-all.ps1 / 单服务 start-*.ps1 启动器、
         recorded 端口上的残留监听者。
    ⚠ 三重防误杀（2026-09-11 加固）：
      a. PID 重用：只杀进程名在白名单内的 PID；监控台还须命令行含本项目路径
         （electron 是 cmd /c npm 包装、命令行无路径，靠新鲜度闸兜底）；
      b. 状态 JSON 新鲜度闸（>120s 无心跳 = 没有活会话）：跳过一切 JSON 衍生杀
         （PID + recorded 端口），只跑活进程扫尾——监督者心跳 5s / 控制台 15s，
         新鲜 JSON 里的 PID 才可信；陈旧 PID 被 Windows 回收后同名照样过白名单。
         冻结的启动器/监督者由第 2 段/第 4c 段的活进程扫尾兜住；
      c. 端口/进程扫尾只认命令行含本项目路径者（他人项目/无关进程不碰）。
#>
$ErrorActionPreference = "SilentlyContinue"

# 本脚本位于 scripts/ 根，项目根 = $PSScriptRoot 的父目录
$ProjectRoot = Split-Path $PSScriptRoot -Parent
$StatusPath = Join-Path $ProjectRoot "data\dev_status.json"
$projectMarker = "*" + $ProjectRoot + "*"

function Test-Allowed([string]$Name, [string[]]$Allowed) {
    if (-not $Name) { return $false }
    $n = $Name.ToLower()
    foreach ($a in $Allowed) {
        if ($n -eq $a -or $n -eq "$a.exe") { return $true }
    }
    return $false
}

function Stop-ByPid([int]$ProcId, [string[]]$Allowed, [string]$What, [switch]$RequireOwned) {
    if ($ProcId -le 0) { return }
    $proc = Get-CimInstance Win32_Process -Filter "ProcessId=$ProcId" -ErrorAction SilentlyContinue
    if (-not (Test-Allowed $proc.Name $Allowed)) {
        Write-Host "  skip $What pid ${ProcId}（进程名 '$($proc.Name)' 不在白名单，防 PID 重用误杀）" -ForegroundColor DarkGray
        return
    }
    if ($RequireOwned -and -not $proc.CommandLine -like $projectMarker) {
        Write-Host "  skip $What pid ${ProcId}（命令行不含本项目路径，防 PID 重用误杀）" -ForegroundColor DarkGray
        return
    }
    & taskkill /T /F /PID $ProcId 2>&1 | Out-Null
    Write-Host "  stopped $What (pid ${ProcId}, $($proc.Name))" -ForegroundColor Green
}

Write-Host "Velluma 停止中..."

# 新鲜度闸：监督者/启动器心跳 5~15s 一次；>120s 无心跳 = 没有活会话，JSON 里的
# PID/端口可能早已易主，一切 JSON 衍生杀跳过（活进程扫尾照常）
$statusFresh = $false
$services = $null
if (Test-Path $StatusPath) {
    $status = Get-Content $StatusPath -Raw | ConvertFrom-Json
    $services = $status.services
    $age = [int]((Get-Date) - (Get-Item $StatusPath).LastWriteTime).TotalSeconds
    $statusFresh = ($age -le 120)
    if ($statusFresh) {
        Stop-ByPid ([int]$status.dashboard.pid) @('python', 'pythonw') "dashboard" -RequireOwned
    } else {
        Write-Host "  状态 JSON 已 ${age}s 无心跳（无活会话），跳过按 PID/recorded 端口停止，只做扫尾" -ForegroundColor DarkGray
    }
}

# 1. 先杀 Electron：启动器随后会走"Electron 退出 → 自行清理后端/前端并退出"的优雅路径
if ($statusFresh -and $services) {
    Stop-ByPid ([int]$services.electron.pid) @('cmd', 'electron') "electron"
}

Start-Sleep -Seconds 3

# 2. 扫尾：残余启动器（正常应已自退；卡死/冻结的在这里收掉）——命令行须含本项目
#    路径，别的项目同名脚本不连坐（2026-09-11）。匹配新布局的四类入口：
#    start-all.ps1（编排核心）与 start-backend/frontend/electron.ps1（单服务前台脚本，
#    其子进程是真正的服务，由端口段/孤儿清扫兜住，这里收脚本宿主本身）
Get-CimInstance Win32_Process -Filter "Name='powershell.exe'" -ErrorAction SilentlyContinue |
    Where-Object { $_.CommandLine -like '*start-all.ps1*' -and $_.CommandLine -like $projectMarker } |
    ForEach-Object {
        Write-Host "  stopped launcher (pid $($_.ProcessId))" -ForegroundColor Green
        & taskkill /T /F /PID $_.ProcessId 2>&1 | Out-Null
    }
Get-CimInstance Win32_Process -Filter "Name='powershell.exe'" -ErrorAction SilentlyContinue |
    Where-Object { $_.CommandLine -like '*\scripts\dev\start-*.ps1*' -or $_.CommandLine -like '*\scripts\prod\start-*.ps1*' } |
    Where-Object { $_.CommandLine -like $projectMarker } |
    ForEach-Object {
        Write-Host "  stopped standalone script (pid $($_.ProcessId))" -ForegroundColor Green
        & taskkill /T /F /PID $_.ProcessId 2>&1 | Out-Null
    }

# 3. 兜底：recorded 端口上的残留监听者（白名单 + 本项目路径双闸）
if ($statusFresh -and $services) {
    foreach ($key in @('backend', 'vite')) {
        $port = $services.$key.port
        if (-not $port -or $port -le 0) { continue }
        $conn = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1
        if ($conn) {
            $proc = Get-CimInstance Win32_Process -Filter "ProcessId=$($conn.OwningProcess)" -ErrorAction SilentlyContinue
            if ($proc -and (Test-Allowed $proc.Name @('python', 'node', 'cmd')) -and $proc.CommandLine -like $projectMarker) {
                & taskkill /T /F /PID $proc.ProcessId 2>&1 | Out-Null
                Write-Host "  stopped port ${port} listener (pid $($proc.ProcessId), $($proc.Name))" -ForegroundColor Green
            }
        }
    }
}

# 4. 孤儿清扫：历次启动残留的 vite/uvicorn（每次启动端口扫描会顺延，残留会堆积）。
# ownership 判定=命令行含本项目路径（精确到本项目的进程才杀，他人项目的同名进程不碰）；
# 端口段与 backend/core/config.py 及 vite 扫描范围一致（8002~8100 / 5175~5285）。
$listeners = Get-NetTCPConnection -State Listen -ErrorAction SilentlyContinue |
    Where-Object { ($_.LocalPort -ge 5175 -and $_.LocalPort -le 5285) -or ($_.LocalPort -ge 8002 -and $_.LocalPort -le 8100) }
foreach ($conn in $listeners) {
    $proc = Get-CimInstance Win32_Process -Filter "ProcessId=$($conn.OwningProcess)" -ErrorAction SilentlyContinue
    if ($proc -and $proc.CommandLine -like $projectMarker) {
        & taskkill /T /F /PID $proc.ProcessId 2>&1 | Out-Null
        Write-Host "  reaped orphan on port $($conn.LocalPort) (pid $($proc.ProcessId), $($proc.Name))" -ForegroundColor Green
    }
}
# 4b. 残留的 Electron（dev 二进制，命令行含本项目路径）
Get-CimInstance Win32_Process -Filter "Name='electron.exe'" -ErrorAction SilentlyContinue |
    Where-Object { $_.CommandLine -like $projectMarker } |
    ForEach-Object {
        & taskkill /T /F /PID $_.ProcessId 2>&1 | Out-Null
        Write-Host "  reaped electron (pid $($_.ProcessId))" -ForegroundColor Green
    }

# 4c. 残留的 python/node（孤儿网页监控台/uvicorn reload 父进程等——不监听上述端口段
# 的漏网者；命令行含本项目路径才判定是自己的）
Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
    Where-Object { ($_.Name -eq 'python.exe' -or $_.Name -eq 'pythonw.exe' -or $_.Name -eq 'node.exe') -and $_.CommandLine -like $projectMarker } |
    ForEach-Object {
        & taskkill /T /F /PID $_.ProcessId 2>&1 | Out-Null
        Write-Host "  reaped $($_.Name) (pid $($_.ProcessId))" -ForegroundColor Green
    }

Write-Host "完成。"
