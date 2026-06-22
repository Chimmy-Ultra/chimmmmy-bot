#!/bin/sh
# 容器啟動腳本：修正持久卷權限後，降權到 node 使用者執行。
# Claude CLI 在 root 下會拒絕 bypassPermissions，所以最終一定以 node 身分跑。
set -e

DATA_DIR="${DATA_DIR:-/app}"
CLAUDE_CONFIG_DIR="${CLAUDE_CONFIG_DIR:-/home/node/.claude}"

mkdir -p "$DATA_DIR" "$CLAUDE_CONFIG_DIR"

# 持久卷（如 Fly volume）預設由 root 擁有；若以 root 啟動就修正權限再降權。
if [ "$(id -u)" = "0" ]; then
  chown -R node:node "$DATA_DIR" "$CLAUDE_CONFIG_DIR" 2>/dev/null || true
  exec gosu node "$@"
fi

exec "$@"
