#!/bin/bash
# 生产体验模式：npm run build 预构建 dist，Electron 载入本地 dist（NODE_ENV=production）
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec bash "$DIR/start.sh" prod "$@"
