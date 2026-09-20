#!/bin/bash
# =============================================================================
# Velluma 正式生产环境·macOS 构建前端（npm run build，前台运行）
# =============================================================================
# scripts/macos/prod/ 四件套之一，与本目录 start-all.sh 互不依赖、逻辑各自独立。
# prod 环境的「前端脚本」= 构建 dist/（不启 Vite）：Electron 生产壳由 main.cjs 走
# loadFile('../dist/index.html') 载入构建产物。构建完成校验 dist/index.html 在。
# =============================================================================
set -e
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd)"

FRONTEND_DIR="$PROJECT_ROOT/frontend"
DIST_INDEX="$FRONTEND_DIR/dist/index.html"

[[ -d "$FRONTEND_DIR/node_modules" ]] || { echo "node_modules not found. Please run: cd frontend && npm install" >&2; exit 1; }

echo ""
echo -e "\033[32m  Velluma · PROD 前端构建（npm run build）\033[0m"
echo ""

# 前台同步执行：构建输出实时进本终端，失败即中止
cd "$FRONTEND_DIR"
npm run build

[[ -f "$DIST_INDEX" ]] || { echo "[ERR] Build completed but dist/index.html not found at $DIST_INDEX" >&2; exit 1; }
echo -e "\033[32m[OK] 前端已构建到 $DIST_INDEX\033[0m"
