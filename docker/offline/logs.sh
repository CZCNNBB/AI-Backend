#!/usr/bin/env bash

set -Eeuo pipefail

# 默认跟踪全部服务日志；Ctrl+C 只退出日志查看，不会停止容器。
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

if [[ ! -f "docker/compose.yaml" ]]; then
    echo "错误：当前目录缺少 docker/compose.yaml。" >&2
    exit 1
fi

docker compose --file "docker/compose.yaml" logs --follow --tail 200 "$@"
