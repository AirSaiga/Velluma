#!/bin/bash
# 开发模式：后端 + Vite dev server + Electron（自动开 DevTools）
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec bash "$DIR/start.sh" dev "$@"
