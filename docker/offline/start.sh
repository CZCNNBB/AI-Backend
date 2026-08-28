#!/usr/bin/env bash

set -Eeuo pipefail

# 始终在离线包目录执行，避免从其他目录启动出不同的 Compose 项目。
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

if ! command -v docker >/dev/null 2>&1; then
    echo "错误：未安装 Docker。" >&2
    exit 1
fi

if ! docker compose version >/dev/null 2>&1; then
    echo "错误：未安装 Docker Compose V2。" >&2
    exit 1
fi

# Compose 是离线部署的唯一配置源，可以在服务器解压后直接修改。
if [[ ! -f "docker/compose.yaml" ]]; then
    echo "错误：当前目录缺少 docker/compose.yaml。" >&2
    exit 1
fi

# 禁止使用示例密码启动；Compose 中 PostgreSQL 服务和后端服务的密码需要同时修改。
if grep -Eq '^[[:space:]]*POSTGRES_PASSWORD:[[:space:]]*(change_me_before_deploy|change_me)[[:space:]]*$' "docker/compose.yaml"; then
    echo "错误：请先在 docker/compose.yaml 中修改两处 POSTGRES_PASSWORD。" >&2
    exit 1
fi

if [[ ! -f "images.tar" ]]; then
    echo "错误：当前目录缺少 images.tar。" >&2
    exit 1
fi

if [[ -f "SHA256SUMS" ]] && command -v sha256sum >/dev/null 2>&1; then
    sha256sum --check "SHA256SUMS"
fi

echo "正在导入离线 Docker 镜像……"
docker image load --input "images.tar"

echo "正在启动 AI-backend、PostgreSQL 与 Milvus……"
docker compose --file "docker/compose.yaml" up --detach --no-build --pull never

echo "当前容器状态："
docker compose --file "docker/compose.yaml" ps

echo "启动命令已提交。首次初始化 Milvus 和 PostgreSQL 可能需要数分钟。"
echo "实际访问端口以 docker/compose.yaml 中 ai-web 和 ai-backend 的 ports 配置为准。"
