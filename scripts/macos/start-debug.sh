#!/bin/bash
# 调试模式：后端 uvicorn --reload 热重载 + Vite dev server + Electron（自动开 DevTools）
# 保存 backend/ 下任意 .py 即自动重启后端，前端无需手动刷新 API。
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec bash "$DIR/start.sh" debug "$@"
