#Requires -Version 5.1
<#
.SYNOPSIS
    Velluma 一键收摊：停止后台/前台启动的全部服务。
.DESCRIPTION
    停止顺序（给优雅路径优先权）：
      1. 按状态 JSON（data/dev_status.json）杀 Electron + 网页监控台
         ——启动器探测到 Electron 退出后会自行清理后端/前端并退出；
      2. 等 3 秒后扫尾：残余 start.ps1 启动器、recorded 端口上的残留监听者。
    ⚠ 防 PID 重用误杀：只杀进程名在白名单内的 PID（python/cmd/node/electron），
      名字对不上一律跳过（status JSON 可能是上一次运行留下的旧文件）。
#>
$ErrorActionPreference = "SilentlyContinue"

$ProjectRoot = Split-Path (Split-Path $PSScriptRoot -Parent) -Parent
$StatusPath = Join-Path $ProjectRoot "data\dev_status.json"

function Test-Allowed([string]$Name, [string[]]$Allowed) {
    if (-not $Name) { return $false }
    $n = $Name.ToLower()
    foreach ($a in $Allowed) {
        if ($n -eq $a -or $n -eq "$a.exe") { return $true }
    }
    return $false
}

function Stop-ByPid([int]$ProcId, [string[]]$Allowed, [string]$What) {
    if ($ProcId -le 0) { return }
    $name = (Get-CimInstance Win32_Process -Filter "ProcessId=$ProcId" -ErrorAction SilentlyContinue).Name
    if (-not (Test-Allowed $name $Allowed)) {
        Write-Host "  skip $What pid ${ProcId}（进程名 '$name' 不在白名单，防 PID 重用误杀）" -ForegroundColor DarkGray
        return
    }
    & taskkill /T /F /PID $ProcId | Out-Null
    Write-Host "  stopped $What (pid ${ProcId}, $name)" -ForegroundColor Green
}

Write-Host "Velluma 停止中..."

$services = $null
if (Test-Path $StatusPath) {
    $status = Get-Content $StatusPath -Raw | ConvertFrom-Json
    $services = $status.services
    Stop-ByPid ([int]$status.dashboard.pid) @('python', 'pythonw') "dashboard"
}

# 1. 先杀 Electron：启动器随后会走"Electron 退出 → 自行清理后端/前端并退出"的优雅路径
if ($services) {
    Stop-ByPid ([int]$services.electron.pid) @('cmd', 'electron') "electron"
}

Start-Sleep -Seconds 3

# 2. 扫尾：残余启动器（正常应已自退；卡死/冻结的在这里收掉）
Get-CimInstance Win32_Process -Filter "Name='powershell.exe'" -ErrorAction SilentlyContinue |
    Where-Object { $_.CommandLine -like '*start.ps1*' } |
    ForEach-Object {
        Write-Host "  stopped launcher (pid $($_.ProcessId))" -ForegroundColor Green
        & taskkill /T /F /PID $_.ProcessId | Out-Null
    }

# 3. 兜底：recorded 端口上的残留监听者（仅白名单内进程）
if ($services) {
    foreach ($key in @('backend', 'vite')) {
        $port = $services.$key.port
        if (-not $port -or $port -le 0) { continue }
        $conn = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1
        if ($conn) {
            $name = (Get-CimInstance Win32_Process -Filter "ProcessId=$($conn.OwningProcess)" -ErrorAction SilentlyContinue).Name
            if (Test-Allowed $name @('python', 'node', 'cmd')) {
                & taskkill /T /F /PID $conn.OwningProcess | Out-Null
                Write-Host "  stopped port ${port} listener (pid $($conn.OwningProcess), $name)" -ForegroundColor Green
            }
        }
    }
}

# 4. 孤儿清扫：历次启动残留的 vite/uvicorn（每次启动端口扫描会顺延，残留会堆积）。
# ownership 判定=命令行含本项目路径（精确到本项目的进程才杀，他人项目的同名进程不碰）；
# 端口段与 backend/core/config.py 及 vite 扫描范围一致（8002~8100 / 5175~5285）。
$projectMarker = "*" + $ProjectRoot + "*"
$listeners = Get-NetTCPConnection -State Listen -ErrorAction SilentlyContinue |
    Where-Object { ($_.LocalPort -ge 5175 -and $_.LocalPort -le 5285) -or ($_.LocalPort -ge 8002 -and $_.LocalPort -le 8100) }
foreach ($conn in $listeners) {
    $proc = Get-CimInstance Win32_Process -Filter "ProcessId=$($conn.OwningProcess)" -ErrorAction SilentlyContinue
    if ($proc -and $proc.CommandLine -like $projectMarker) {
        & taskkill /T /F /PID $proc.ProcessId | Out-Null
        Write-Host "  reaped orphan on port $($conn.LocalPort) (pid $($proc.ProcessId), $($proc.Name))" -ForegroundColor Green
    }
}
# 4b. 残留的 Electron（dev 二进制，命令行含本项目路径）
Get-CimInstance Win32_Process -Filter "Name='electron.exe'" -ErrorAction SilentlyContinue |
    Where-Object { $_.CommandLine -like $projectMarker } |
    ForEach-Object {
        & taskkill /T /F /PID $_.ProcessId | Out-Null
        Write-Host "  reaped electron (pid $($_.ProcessId))" -ForegroundColor Green
    }

# 4c. 残留的 python/node（孤儿网页监控台/uvicorn reload 父进程等——不监听上述端口段
# 的漏网者；命令行含本项目路径才判定是自己的）
Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
    Where-Object { ($_.Name -eq 'python.exe' -or $_.Name -eq 'pythonw.exe' -or $_.Name -eq 'node.exe') -and $_.CommandLine -like $projectMarker } |
    ForEach-Object {
        & taskkill /T /F /PID $_.ProcessId | Out-Null
        Write-Host "  reaped $($_.Name) (pid $($_.ProcessId))" -ForegroundColor Green
    }

Write-Host "完成。"
