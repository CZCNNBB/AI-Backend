#!/usr/bin/env bash

set -Eeuo pipefail

# docker compose down 只移除容器和网络，不使用 --volumes，业务数据仍会保留。
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

if [[ ! -f "docker/compose.yaml" ]]; then
    echo "错误：当前目录缺少 docker/compose.yaml。" >&2
    exit 1
fi

docker compose --file "docker/compose.yaml" down
echo "服务已停止，PostgreSQL、Milvus 和上传文件数据卷均已保留。"
