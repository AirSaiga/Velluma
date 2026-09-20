#Requires -Version 5.1
<#
.SYNOPSIS
    Velluma 正式生产环境 · 构建前端（npm run build，前台运行）。
.DESCRIPTION
    scripts/prod/ 四件套之一，与本目录 start-all.ps1 互不依赖、逻辑各自独立。
    prod 环境的「前端脚本」= 构建 dist/（不启 Vite）：Electron 生产壳由
    main.cjs 走 loadFile('../dist/index.html') 载入构建产物。
    构建完成校验 dist/index.html 在，不在即报错（别等到 Electron 白屏）。
#>
param(
    [switch]$DryRun    # 仅打印将执行的命令
)

$ErrorActionPreference = "Stop"

# 脚本位于 scripts/prod/ 下，项目根是 $PSScriptRoot 的祖父目录
$ProjectRoot = Split-Path (Split-Path $PSScriptRoot -Parent) -Parent

$FrontendDir = Join-Path $ProjectRoot "frontend"
$DistIndex   = Join-Path $FrontendDir "dist\index.html"

if (-not (Test-Path (Join-Path $FrontendDir "node_modules"))) {
    throw "node_modules not found. Please run: cd frontend && npm install"
}

Write-Host ""
Write-Host "  Velluma · PROD 前端构建（npm run build）" -ForegroundColor Green
Write-Host ""

if ($DryRun) {
    Write-Host "[DryRun] Would run: npm run build (cwd: $FrontendDir)" -ForegroundColor Gray
    return
}

# 前台同步执行：构建输出实时进本窗口，失败退出码原样透传
Push-Location $FrontendDir
$code = 1
try {
    & cmd.exe /c npm run build
    $code = $LASTEXITCODE
} finally {
    Pop-Location
}

if ($code -ne 0) {
    Write-Host "[ERR] npm run build failed with exit code $code" -ForegroundColor Red
    exit $code
}

if (-not (Test-Path $DistIndex)) {
    Write-Host "[ERR] Build completed but dist/index.html not found at $DistIndex" -ForegroundColor Red
    exit 1
}

Write-Host "[OK] 前端已构建到 $DistIndex" -ForegroundColor Green
exit 0
