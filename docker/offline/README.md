# AI-backend 离线部署包

本包面向 `Linux AMD64` 服务器，包含 AI-backend、管理前端、PostgreSQL 18、Milvus 3.0、etcd 和 MinIO 的全部 Docker 镜像。

## 首次部署

```bash
vim docker/compose.yaml
chmod +x start.sh stop.sh logs.sh
./start.sh
```

`docker/compose.yaml` 是唯一部署配置源。首次启动前请修改其中两处
`POSTGRES_PASSWORD`，端口、连接池、Milvus、MinerU 等配置也可以按服务器环境
直接调整，不需要重新制作离线包。

首次启动会创建全新的空数据卷。PostgreSQL 会自动执行：

```text
sql/00000000_init_empty_database.sql
```

初始化 SQL 只在 PostgreSQL 数据卷为空时执行一次。

## 查看状态与日志

```bash
docker compose --file docker/compose.yaml ps
./logs.sh
./logs.sh ai-backend
```

## 停止与再次启动

```bash
./stop.sh
./start.sh
```

`stop.sh` 不删除数据卷。不要随意执行 `docker compose down --volumes`，该命令会删除 PostgreSQL、Milvus、etcd、MinIO 和上传文件数据。

## 默认访问地址

```text
管理前端：http://服务器IP/
后端接口：http://服务器IP:8090/
OpenAPI：http://服务器IP:8090/docs
```

PostgreSQL、Milvus API 和 Milvus WebUI 默认只绑定服务器的 `127.0.0.1`。需要远程管理时建议使用 SSH 隧道，不要直接向公网开放这些端口。

## MinerU

本包不包含 MinerU，默认配置为：

```yaml
MINERU_ENABLED: "false"
```

PDF 会回退到 `pymupdf4llm`。如果以后部署 MinerU，需要把 `MINERU_BASE_URL` 配置成 AI-backend 容器能够访问的地址。
