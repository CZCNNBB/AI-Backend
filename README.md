# AI-backend

`AI-backend` 是可独立部署、可复用的通用 AI 能力服务，提供 Agent、模型调用、文件处理、知识库和外部工具接入能力。

它不负责登录、权限、用户、菜单、岗位采集和岗位业务数据管理。业务系统可以通过 HTTP 调用 AI 能力，也可以通过 MCP 向 Agent 提供自己的查询、保存和审批工具。

## 职责边界

当前后端实际挂载三个公共模块：

```text
/agent       # Agent、会话、模板、运行记录、模型、MCP 和 A2A
/file        # 文件上传、删除、解析和读取
/knowledge   # 知识库、文档入库、切片、向量化和检索
```

当前代码没有挂载 `/spider` 路由。招聘平台爬虫、岗位数据入库、岗位技能和岗位画像等业务能力位于 `orchestration-backend`。

## 目录结构

```text
app/
  common/                  # 配置、数据库、日志、响应和异常处理
  server/
    agent/                 # Agent 服务
    file/                  # 文件服务
    knowledge/             # 知识库服务
sql/                       # 空数据库初始化脚本
docker/                    # Docker 构建、Compose 和离线交付文件
web/                       # 独立的 Vue 管理前端
```

## Agent 能力

Agent 模块当前包括：

- 统一消息调用和流式输出。
- 会话历史、消息记录和上下文总结。
- Agent 模板管理和运行记录查询。
- Chat、Embedding、Reranker 模型配置管理。
- 规划模式、中断恢复和 PostgreSQL Checkpointer。
- 文件上下文和知识库检索。
- A2A 子 Agent 调度。
- MCP 外部工具登记、同步、测试和调用。

常用接口：

```text
GET  /agent/health
GET  /agent/capabilities
POST /agent/messages

POST /agent/conversations/search
POST /agent/conversations/messages

POST /agent/templates/search
POST /agent/templates/detail
POST /agent/templates/upsert
POST /agent/templates/delete

POST /agent/runs/search
POST /agent/runs/detail
POST /agent/runs/chain

POST /agent/models/search
POST /agent/models/detail
POST /agent/models/upsert
POST /agent/models/delete

POST /agent/mcp/search
POST /agent/mcp/detail
POST /agent/mcp/upsert
POST /agent/mcp/delete
POST /agent/mcp/test
POST /agent/mcp/sync
POST /agent/mcp/invoke
```

完整、实时的请求结构和响应结构请以服务启动后的 `/docs` OpenAPI 页面为准。

## 文件能力

文件模块用于保存用户上传的材料，并将可解析文档转换为适合 Agent 按行读取的 Markdown 内容。

主要接口：

```text
POST /file/upload  # 只保存原文件并返回 file_ids
POST /file/parse   # 根据 file_id 显式构建内容源
POST /file/delete  # 删除文件记录和磁盘文件
```

Agent 在一次调用中只能读取请求明确授权的 `file_ids`，避免不同请求之间直接访问未授权附件。

## 知识库能力

知识库模块当前包括：

- 知识库创建、查询、修改和删除。
- 文档提交、重建索引、删除和状态查询。
- PostgreSQL 队列和后台入库 Worker。
- 文本切片和 Embedding。
- Milvus 向量写入与检索。
- 可选 Reranker 重排。

主要接口前缀：

```text
GET  /knowledge/health
GET  /knowledge/health/readiness
POST /knowledge/bases/*
POST /knowledge/documents/*
POST /knowledge/ingestion/*
POST /knowledge/split/preview
POST /knowledge/embedding/preview
POST /knowledge/retrieval/search
```

## 内置工具与 MCP 工具

系统内置能力包括：

- `set_task_plan`、`update_task_step`：规划模式工具。
- `read_uploaded_file`：读取本次 Agent 调用授权的附件。
- `search_knowledge_base`：检索本次 Agent 调用挂载的知识库。
- `a2a_call`：调用模板允许的子 Agent。

内置工具由运行参数和能力开关自动挂载，不应填写到模板的 `tools` 数组中。

模板的 `tools` 数组只用于选择已经登记的 MCP 外部工具。接入其他业务系统时，推荐把业务数据查询、保存和审批操作封装成 MCP 工具，而不是让 `AI-backend` 直接访问业务数据库。

仓库中的岗位画像 Agent 模板仍引用 `job.*` 业务 MCP 工具。单独部署 `AI-backend` 时，应先删除、停用或替换这些业务工具配置，否则对应岗位 Agent 无法完成查询和保存。

## 数据与基础设施

`AI-backend` 运行需要：

- PostgreSQL：保存 Agent 模板、会话、消息、运行记录、模型配置、MCP 配置、上传文件和知识库元数据。
- Milvus：保存和检索知识库向量。
- Chat 模型：执行 Agent 对话。
- Embedding 模型：执行知识库向量化。
- 可选 Reranker 模型：执行检索结果重排。
- 文件上传目录：保存原始文件和解析后的 Markdown。

应用启动时会检查本地切片能力、PostgreSQL 和 Milvus，并在检查通过后启动知识入库 Worker。任何必需依赖未就绪时，当前版本都会终止启动。

空数据库初始化脚本位于：

```text
sql/00000000_init_empty_database.sql
```

部署新环境时，连接目标 PostgreSQL 业务数据库并执行一次该脚本即可。当前项目处于开发阶段，
不再维护旧数据库的逐版本迁移脚本；数据库结构发生不兼容调整时，应先清理开发数据，
再使用最新初始化脚本重建业务表。

## 安全边界

当前服务没有提供完整的登录、JWT、权限和租户鉴权体系。生产接入时应由业务后端或 API 网关完成：

- 用户身份认证和权限校验。
- API 访问控制与限流。
- 调用方用户 ID、租户 ID 等运行上下文注入。
- MCP 服务的网络访问控制和密钥管理。

## 后端启动

推荐使用 Python 3.12。

```powershell
cd D:\study\get_job_data\backend\AI-backend
pip install -r requirements.txt
python app/main.py
```

默认地址：

```text
http://127.0.0.1:8090
```

API 文档：

```text
http://127.0.0.1:8090/docs
```

## 管理前端启动

`web` 是独立的 Vue/Vite 工程，不会由 FastAPI 自动托管。

```powershell
cd D:\study\get_job_data\backend\AI-backend\web
npm install
npm run dev
```

前端通过 `web/.env` 中的 `VITE_BACKEND_URL` 指向 `AI-backend`。开发环境的 `/api` 请求由 Vite 代理到后端。

## Docker 离线部署

Dockerfile、Compose、Nginx 和离线打包脚本统一位于 `docker/`。生成 Linux AMD64 离线部署包：

```powershell
.\docker\scripts\build_offline_package.ps1 -Version 1.0.0
```

完整说明见 `docs/Docker离线部署说明.md`。

## 常用环境变量

后端配置文件为 `.env`，可以从 `.env.example` 复制后按部署环境修改。

```text
FASTAPI_HOST
FASTAPI_PORT
LOG_LEVEL

POSTGRES_HOST
POSTGRES_PORT
POSTGRES_USER
POSTGRES_PASSWORD
POSTGRES_DATABASE
POSTGRES_CONNECT_TIMEOUT

AI_BACKEND_UPLOAD_DIR
FILE_MAX_FILES_PER_UPLOAD
FILE_MAX_SINGLE_FILE_MB
FILE_MAX_TOTAL_UPLOAD_MB

MILVUS_URI
MILVUS_TOKEN
MILVUS_DATABASE

KNOWLEDGE_INGESTION_WORKER_COUNT
KNOWLEDGE_INGESTION_MAX_RETRIES

LANGSMITH_TRACING
LANGSMITH_API_KEY
LANGSMITH_ENDPOINT
LANGSMITH_PROJECT

CHECKPOINTER_TYPE
CHECKPOINTER_POSTGRES_SCHEMA
```

模型连接参数通过模型配置管理接口或管理前端维护。API Key 属于敏感信息，不应提交到 Git。
