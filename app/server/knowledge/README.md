# Knowledge 服务

Knowledge 是 AI-backend 内部的统一知识库模块。切片、向量化、Milvus 存储、检索和 PostgreSQL 入库队列都由该模块管理，不单独部署。

## 核心存储

- PostgreSQL：统一使用 career_ai 数据库；Agent 与 Knowledge 分别使用 agent、knowledge Schema。
- knowledge Schema：保存知识库定义、文件关联、入库任务、分块证据与索引配置快照。
- 文件服务：保存原始上传文件和转换后的 content.md。
- Milvus：保存分块向量、全文检索字段和检索元数据。

Agent、文件服务、知识库、MCP 和业务平台共用统一的空数据库初始化脚本：
`sql/00000000_init_empty_database.sql`。当前项目不再维护独立的 Knowledge 建表或增量迁移脚本。

## 入库流程

    上传文件
      -> 创建知识库
      -> 提交 documents/submit
      -> ingestion_runs 进入 pending
      -> Worker 使用 FOR UPDATE SKIP LOCKED 抢占
      -> 文件内容源 -> Split -> Embedding -> Milvus
      -> knowledge_chunks
      -> 任务 completed / 文档 indexed

Worker 会随 AI-backend 自动启动。入库按 Embedding 模型 extra_config.batch_size 分批调用模型并批量写入 Milvus；未配置时每批 32 条，允许范围为 1 到 256。

## 文档切片配置

创建知识库时的 split_config 是默认切片配置。提交或重建文档时可以通过 split_method 或 split_strategy 覆盖，两者只能选择一个。配置快照保存到 ingestion_runs.payload.split_config，自动重试和人工重试继续使用同一配置。

## 可用性检查

AI-backend 启动时固定检查 PostgreSQL 和 Milvus，任一基础依赖不可用都会终止服务启动。/knowledge/health 只表示路由已挂载；/knowledge/health/readiness 用于检查实际依赖状态。

## 当前接口

    GET  /knowledge/health
    GET  /knowledge/health/readiness
    GET  /knowledge/capabilities

    POST /knowledge/bases/create
    POST /knowledge/bases/detail
    POST /knowledge/bases/search
    POST /knowledge/bases/update
    POST /knowledge/bases/delete

    POST /knowledge/documents/submit
    POST /knowledge/documents/search
    POST /knowledge/documents/detail
    POST /knowledge/documents/reindex
    POST /knowledge/documents/delete

    POST /knowledge/ingestion/status
    POST /knowledge/ingestion/search
    POST /knowledge/ingestion/cancel
    POST /knowledge/ingestion/retry

    POST /knowledge/split/preview
    POST /knowledge/embedding/preview
    POST /knowledge/retrieval/search

文档删除通过 PostgreSQL 任务队列异步执行，Worker 会依次清理 Milvus 文件向量和 knowledge_chunks 分块证据。知识库删除会拒绝仍有活跃任务的知识库，并回收整个 Collection。

Agent 侧已经通过内部工具 search_knowledge_base 接入检索。模板负责开启 knowledge_enabled，每次运行通过 knowledge.knowledge_base_ids 传入允许访问的知识库白名单。
