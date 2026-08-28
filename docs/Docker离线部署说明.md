# AI-backend Docker 离线部署说明

## 1. 部署目标

本方案面向无法直接从互联网拉取镜像的 Linux AMD64 服务器。构建机负责联网构建和导出镜像，服务器只负责加载镜像并启动容器。

首次部署创建全新的空环境，不迁移开发机上的 PostgreSQL、Milvus 或上传文件数据。

完整服务包括：

| Compose 服务 | 镜像 | 职责 |
| --- | --- | --- |
| `ai-web` | `ai-web:<版本>` | Vue 管理前端与 Nginx `/api` 代理 |
| `ai-backend` | `ai-backend:<版本>` | FastAPI、Agent、FastMCP、文件和知识库服务 |
| `postgres` | `postgres-rag:pg18` | PostgreSQL 18 业务数据与 Checkpointer |
| `milvus-standalone` | `milvusdb/milvus:v3.0.0` | Milvus Standalone |
| `milvus-etcd` | `quay.io/coreos/etcd:v3.5.25` | Milvus 元数据 |
| `milvus-minio` | `minio/minio:RELEASE.2024-05-28T17-19-04Z` | Milvus 对象存储 |

## 2. 持久化数据

Compose 使用以下命名卷：

| 数据卷 | 内容 |
| --- | --- |
| `ai-postgres-data` | PostgreSQL 18 数据目录 |
| `ai-milvus-data` | Milvus 本地数据 |
| `ai-milvus-etcd-data` | etcd 元数据 |
| `ai-milvus-minio-data` | MinIO 对象数据 |
| `ai-backend-uploads` | 用户上传文件和解析结果 |

普通的 `docker compose down` 不删除这些数据。禁止在未备份时执行：

```bash
docker compose down --volumes
```

## 3. PostgreSQL 空库初始化

Compose 把以下脚本只读挂载到 PostgreSQL 官方初始化目录：

```text
sql/00000000_init_empty_database.sql
→ /docker-entrypoint-initdb.d/001-ai-backend.sql
```

只有 `ai-postgres-data` 为空时才会执行该脚本。脚本创建 Agent、文件、知识库、MCP、业务平台和模型配置所需的全部业务表。

LangGraph Checkpointer 表由 AI-backend 首次启动时通过官方 `setup()` 自动创建。

## 4. 构建机要求

- Windows PowerShell 7 或兼容 PowerShell。
- Docker Engine 正常运行。
- Docker Compose V2。
- Docker 平台为 `linux/amd64`。
- 本地已有当前验证过的 `postgres-rag:pg18` 镜像。
- 能够拉取 Python、Node、Nginx 和 Milvus 固定版本镜像。

检查：

```powershell
docker version
docker compose version
docker info --format '{{.OSType}}/{{.Architecture}}'
docker image inspect postgres-rag:pg18
```

## 5. 构建并生成离线包

在仓库根目录执行：

```powershell
.\docker\scripts\build_offline_package.ps1 -Version 1.0.0
```

脚本会依次执行：

1. 检查 Docker Engine 和 Linux AMD64 架构。
2. 检查 `postgres-rag:pg18`。
3. 检查或拉取 Milvus、etcd 和 MinIO 固定镜像。
4. 构建 `ai-backend:<版本>` 和 `ai-web:<版本>`。
5. 使用 `docker image save` 生成统一的 `images.tar`。
6. 生成 `SHA256SUMS`。
7. 生成最终 `tar.gz` 离线部署包。

发布物位于：

```text
release/ai-backend-<版本>-linux-amd64-<时间戳>.tar.gz
```

## 6. Docker 镜像源故障

如果 Docker Hub 访问失败，可以在 Docker Desktop 的 Docker Engine 配置中增加
`registry-mirrors`，不需要修改 Windows 的 DNS 或其他网络设置。

修改后重启 Docker Engine，并先验证：

```powershell
docker pull python:3.12-slim-bookworm
docker pull node:22-alpine
docker pull nginx:1.29-alpine
```

三条命令成功后再执行离线打包脚本。

## 7. 上传并部署到服务器

上传生成的 `tar.gz`，然后在服务器执行：

```bash
tar -xzf ai-backend-1.0.0-linux-amd64-<时间戳>.tar.gz
cd ai-backend-1.0.0-linux-amd64-<时间戳>

vim docker/compose.yaml
chmod +x start.sh stop.sh logs.sh
./start.sh
```

首次启动前必须在 `docker/compose.yaml` 中修改两处相同的数据库密码：

```yaml
POSTGRES_PASSWORD: 服务器使用的安全密码
```

端口、连接池、Milvus、MinerU 等运行参数也都在该 Compose 文件中，可以在
服务器解压后临时调整，不需要返回构建机重新制作离线包。

`start.sh` 会校验 `images.tar`、导入镜像并使用以下限制启动：

```bash
docker compose \
  --file docker/compose.yaml \
  up --detach --no-build --pull never
```

`--pull never` 保证服务器不会因为无网络而尝试访问镜像仓库。

## 8. 地址与端口

默认地址：

```text
管理前端：http://服务器IP/
AI-backend：http://服务器IP:8090/
OpenAPI：http://服务器IP:8090/docs
```

默认端口策略：

| 端口 | 绑定范围 | 说明 |
| --- | --- | --- |
| `80` | 所有网卡 | 管理前端 |
| `8090` | 所有网卡 | 外部业务平台调用 AI-backend |
| `5433` | `127.0.0.1` | PostgreSQL 管理端口 |
| `19530` | `127.0.0.1` | Milvus API 管理端口 |
| `9091` | `127.0.0.1` | Milvus WebUI |

远程访问本机限定端口时使用 SSH 隧道，例如：

```bash
ssh -L 5433:127.0.0.1:5433 -L 9091:127.0.0.1:9091 user@server
```

## 9. 启动检查

```bash
docker compose --file docker/compose.yaml ps
./logs.sh
./logs.sh ai-backend
```

首次启动顺序为：

```text
PostgreSQL 初始化 SQL
etcd + MinIO
Milvus 健康
AI-backend 初始化 Checkpointer 与知识库 Worker
AI-web
```

Milvus 首次初始化通常比其他组件慢。只有前置服务健康后，Compose 才会启动 AI-backend。

## 10. MinerU

当前离线包不包含 MinerU，默认：

```env
MINERU_ENABLED=false
```

PDF 解析会回退到 `pymupdf4llm`。如果以后在同一服务器宿主机运行 MinerU，可以配置：

```env
MINERU_ENABLED=true
MINERU_BASE_URL=http://host.docker.internal:18000
```

Compose 已为 Linux Docker Engine 显式配置 `host.docker.internal:host-gateway`。

## 11. 日常操作

停止服务但保留数据：

```bash
./stop.sh
```

再次启动：

```bash
./start.sh
```

查看指定服务日志：

```bash
./logs.sh ai-backend
./logs.sh milvus-standalone
./logs.sh postgres
```
