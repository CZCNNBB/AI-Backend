-- AI-backend 空数据库初始化脚本。
--
-- 适用场景：
-- 1. PostgreSQL 数据库已经创建，但数据库中还没有 AI-backend 业务表。
-- 2. 希望一次性创建当前代码所需的全部业务 Schema、表、约束、索引和注释。
--
-- 使用说明：
-- 1. 请连接到目标业务数据库后执行本脚本，例如：
--    psql -h 127.0.0.1 -p 5433 -U <用户名> -d <数据库名> -f sql/00000000_init_empty_database.sql
-- 2. 本脚本使用 CREATE TABLE IF NOT EXISTS，不会删除已经存在的表或数据。
-- 3. 本脚本面向“空数据库初始化”，不会修正已有但结构不一致的旧表；旧库应使用增量迁移脚本。
-- 4. LangGraph Checkpointer 的 checkpoints、checkpoint_writes 等表不在本脚本中，
--    它们由当前安装版本的 langgraph-checkpoint-postgres 在首次 setup() 时维护。
-- 5. 本脚本只创建表结构，不写入模型 API Key、Agent 模板或其他业务数据。

BEGIN;

-- Agent、文件服务共用 agent Schema；知识库表放在 knowledge Schema。
CREATE SCHEMA IF NOT EXISTS agent;
CREATE SCHEMA IF NOT EXISTS knowledge;

-- =====================================================================
-- 1. 平台模型配置
-- =====================================================================

CREATE TABLE IF NOT EXISTS public.model_configs (
    id BIGSERIAL PRIMARY KEY,
    model_code VARCHAR(100) NOT NULL UNIQUE,
    model_name VARCHAR(255) NOT NULL,
    model_type VARCHAR(50) NOT NULL,
    base_url TEXT NOT NULL,
    api_key TEXT,
    api_type VARCHAR(50) NOT NULL DEFAULT 'openai_compatible',
    support_stream BOOLEAN NOT NULL DEFAULT FALSE,
    support_tool_calling BOOLEAN NOT NULL DEFAULT FALSE,
    support_structured_output BOOLEAN NOT NULL DEFAULT FALSE,
    is_multimodal BOOLEAN NOT NULL DEFAULT FALSE,
    enabled BOOLEAN NOT NULL DEFAULT TRUE,
    extra_config JSONB,
    description TEXT,
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_model_configs_model_type
ON public.model_configs(model_type);

CREATE INDEX IF NOT EXISTS idx_model_configs_enabled
ON public.model_configs(enabled);

CREATE INDEX IF NOT EXISTS idx_model_configs_updated_at
ON public.model_configs(updated_at);

COMMENT ON TABLE public.model_configs IS '平台模型配置表：保存聊天、Embedding、Rerank 等模型的连接和能力配置。';
COMMENT ON COLUMN public.model_configs.model_code IS '平台内模型唯一编码，Agent 和知识库通过该编码引用模型。';
COMMENT ON COLUMN public.model_configs.model_type IS '模型类型，例如 chat、embedding、rerank。';
COMMENT ON COLUMN public.model_configs.base_url IS '模型服务基础地址。';
COMMENT ON COLUMN public.model_configs.api_key IS '模型服务密钥；生产环境应进一步使用加密或密钥管理服务保护。';
COMMENT ON COLUMN public.model_configs.extra_config IS '模型供应商特有的扩展配置。';

-- =====================================================================
-- 2. Agent 模板、会话与消息
-- =====================================================================

CREATE TABLE IF NOT EXISTS agent.agent_templates (
    id BIGSERIAL PRIMARY KEY,
    agent_id VARCHAR(100) NOT NULL UNIQUE,
    agent_name VARCHAR(255) NOT NULL,
    description TEXT,
    config JSONB NOT NULL DEFAULT '{}'::jsonb,
    status VARCHAR(30) NOT NULL DEFAULT 'active',
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_agent_templates_status
ON agent.agent_templates(status);

CREATE INDEX IF NOT EXISTS idx_agent_templates_updated_at
ON agent.agent_templates(updated_at);

COMMENT ON TABLE agent.agent_templates IS 'Agent 模板表：保存提示词、模型、MCP 工具和内部能力开关等完整配置。';
COMMENT ON COLUMN agent.agent_templates.agent_id IS 'Agent 模板稳定唯一标识。';
COMMENT ON COLUMN agent.agent_templates.config IS 'Agent 完整配置 JSON，包括提示词、模型、工具及运行选项。';
COMMENT ON COLUMN agent.agent_templates.status IS '模板状态，例如 active、disabled。';

CREATE TABLE IF NOT EXISTS agent.agent_conversations (
    id BIGSERIAL PRIMARY KEY,
    conversation_id VARCHAR(100) NOT NULL UNIQUE,
    title VARCHAR(255),
    status VARCHAR(30) NOT NULL DEFAULT 'active',
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_agent_conversations_status
ON agent.agent_conversations(status);

CREATE INDEX IF NOT EXISTS idx_agent_conversations_updated_at
ON agent.agent_conversations(updated_at);

COMMENT ON TABLE agent.agent_conversations IS 'Agent 会话主表：记录一个 conversation_id 对应的一组历史消息。';
COMMENT ON COLUMN agent.agent_conversations.conversation_id IS '会话唯一标识。';
COMMENT ON COLUMN agent.agent_conversations.metadata IS '会话扩展元数据。';

CREATE TABLE IF NOT EXISTS agent.agent_messages (
    id BIGSERIAL PRIMARY KEY,
    conversation_id VARCHAR(100) NOT NULL,
    message_id VARCHAR(100) NOT NULL UNIQUE,
    parent_message_id VARCHAR(100),
    role VARCHAR(50) NOT NULL,
    message_type VARCHAR(50) NOT NULL,
    content TEXT,
    structured_content JSONB,
    tool_name VARCHAR(100),
    tool_call_id VARCHAR(100),
    status VARCHAR(30) NOT NULL DEFAULT 'success',
    error_message TEXT,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    CONSTRAINT fk_agent_messages_conversation
        FOREIGN KEY (conversation_id)
        REFERENCES agent.agent_conversations(conversation_id)
        ON DELETE CASCADE
);

-- 会话历史通常按 conversation_id 过滤并按 id 倒序读取，使用联合索引减少回表和排序成本。
CREATE INDEX IF NOT EXISTS idx_agent_messages_conversation_id_id
ON agent.agent_messages(conversation_id, id DESC);

CREATE INDEX IF NOT EXISTS idx_agent_messages_parent_message_id
ON agent.agent_messages(parent_message_id);

CREATE INDEX IF NOT EXISTS idx_agent_messages_created_at
ON agent.agent_messages(created_at);

COMMENT ON TABLE agent.agent_messages IS 'Agent 会话消息表：保存用户输入、模型回复、工具消息和错误消息。';
COMMENT ON COLUMN agent.agent_messages.conversation_id IS '所属会话 ID。';
COMMENT ON COLUMN agent.agent_messages.message_id IS '消息唯一标识。';
COMMENT ON COLUMN agent.agent_messages.parent_message_id IS '父消息 ID，用于表达消息调用或上下文关系。';
COMMENT ON COLUMN agent.agent_messages.structured_content IS '结构化消息内容。';
COMMENT ON COLUMN agent.agent_messages.metadata IS '消息扩展元数据。';

-- =====================================================================
-- 3. Agent 运行记录与 MCP 工具配置
-- =====================================================================

CREATE TABLE IF NOT EXISTS agent.agent_runs (
    run_id VARCHAR(100) PRIMARY KEY,
    run_type VARCHAR(30) NOT NULL DEFAULT 'main',
    parent_run_id VARCHAR(100),
    agent_id VARCHAR(100),
    conversation_id VARCHAR(100),
    user_message_id VARCHAR(100),
    assistant_message_id VARCHAR(100),
    query TEXT,
    answer TEXT,
    status VARCHAR(30) NOT NULL DEFAULT 'running',
    error_message TEXT,
    elapsed_ms DOUBLE PRECISION,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    started_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    finished_at TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_agent_runs_run_type
ON agent.agent_runs(run_type);

CREATE INDEX IF NOT EXISTS idx_agent_runs_parent_run_id
ON agent.agent_runs(parent_run_id);

CREATE INDEX IF NOT EXISTS idx_agent_runs_agent_id
ON agent.agent_runs(agent_id);

CREATE INDEX IF NOT EXISTS idx_agent_runs_conversation_id
ON agent.agent_runs(conversation_id);

CREATE INDEX IF NOT EXISTS idx_agent_runs_user_message_id
ON agent.agent_runs(user_message_id);

CREATE INDEX IF NOT EXISTS idx_agent_runs_assistant_message_id
ON agent.agent_runs(assistant_message_id);

CREATE INDEX IF NOT EXISTS idx_agent_runs_status
ON agent.agent_runs(status);

CREATE INDEX IF NOT EXISTS idx_agent_runs_started_at
ON agent.agent_runs(started_at);

COMMENT ON TABLE agent.agent_runs IS 'Agent 运行记录表：统一记录主 Agent 和 A2A 子 Agent 的业务运行台账。';
COMMENT ON COLUMN agent.agent_runs.run_id IS '本次 Agent 运行 ID，同时作为主键。';
COMMENT ON COLUMN agent.agent_runs.run_type IS '运行类型：main 表示主 Agent，sub 表示 A2A 子 Agent。';
COMMENT ON COLUMN agent.agent_runs.parent_run_id IS '父级 Agent 运行 ID；主 Agent 为空。';
COMMENT ON COLUMN agent.agent_runs.status IS '运行状态，例如 running、success、failed、interrupted。';
COMMENT ON COLUMN agent.agent_runs.elapsed_ms IS '运行耗时，单位毫秒。';
COMMENT ON COLUMN agent.agent_runs.metadata IS '运行扩展元数据。';

CREATE TABLE IF NOT EXISTS agent.agent_mcp_tools (
    id BIGSERIAL PRIMARY KEY,
    mcp_code VARCHAR(150) NOT NULL UNIQUE,
    name VARCHAR(255) NOT NULL,
    description TEXT,
    base_url TEXT NOT NULL,
    transport VARCHAR(50) NOT NULL DEFAULT 'http',
    auth_type VARCHAR(50),
    auth_config JSONB,
    input_schema JSONB,
    output_schema JSONB,
    status VARCHAR(30) NOT NULL DEFAULT 'enabled',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_agent_mcp_tools_name
ON agent.agent_mcp_tools(name);

CREATE INDEX IF NOT EXISTS idx_agent_mcp_tools_base_url
ON agent.agent_mcp_tools(base_url);

CREATE INDEX IF NOT EXISTS idx_agent_mcp_tools_status
ON agent.agent_mcp_tools(status);

CREATE INDEX IF NOT EXISTS idx_agent_mcp_tools_updated_at
ON agent.agent_mcp_tools(updated_at);

COMMENT ON TABLE agent.agent_mcp_tools IS 'Agent MCP 工具配置表：一条记录代表一个可被 Agent 选择的 MCP 工具。';
COMMENT ON COLUMN agent.agent_mcp_tools.mcp_code IS '平台内 MCP 工具唯一编码。';
COMMENT ON COLUMN agent.agent_mcp_tools.name IS 'MCP 服务中的真实工具名称。';
COMMENT ON COLUMN agent.agent_mcp_tools.base_url IS 'MCP 服务访问地址。';
COMMENT ON COLUMN agent.agent_mcp_tools.auth_config IS 'MCP 服务认证配置。';
COMMENT ON COLUMN agent.agent_mcp_tools.input_schema IS '工具输入参数 JSON Schema。';
COMMENT ON COLUMN agent.agent_mcp_tools.output_schema IS '工具输出参数 JSON Schema。';

-- =====================================================================
-- 4. 文件服务
-- =====================================================================

CREATE TABLE IF NOT EXISTS agent.uploaded_files (
    file_id VARCHAR(100) PRIMARY KEY,
    original_name VARCHAR(500) NOT NULL,
    stored_name VARCHAR(255) NOT NULL,
    storage_path TEXT NOT NULL,
    extension VARCHAR(50) NOT NULL DEFAULT '',
    mime_type VARCHAR(255),
    size_bytes BIGINT NOT NULL DEFAULT 0,
    status VARCHAR(30) NOT NULL DEFAULT 'uploaded',
    content_path TEXT,
    content_type VARCHAR(30) NOT NULL DEFAULT 'pending',
    conversion_status VARCHAR(30) NOT NULL DEFAULT 'pending',
    conversion_error TEXT,
    converter_name VARCHAR(100),
    converted_at TIMESTAMP,
    metadata JSONB,
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_uploaded_files_original_name
ON agent.uploaded_files(original_name);

CREATE INDEX IF NOT EXISTS idx_uploaded_files_conversion_status
ON agent.uploaded_files(conversion_status);

CREATE INDEX IF NOT EXISTS idx_uploaded_files_created_at
ON agent.uploaded_files(created_at);

COMMENT ON TABLE agent.uploaded_files IS 'AI-backend 文件服务上传文件记录表。';
COMMENT ON COLUMN agent.uploaded_files.file_id IS '文件 ID，上传后返回给前端、Agent 和知识库使用。';
COMMENT ON COLUMN agent.uploaded_files.storage_path IS '服务端原始文件存储路径。';
COMMENT ON COLUMN agent.uploaded_files.content_path IS 'Agent 实际读取的内容源路径。';
COMMENT ON COLUMN agent.uploaded_files.conversion_status IS '转换状态：pending、processing、success、failed 或 not_required。';
COMMENT ON COLUMN agent.uploaded_files.metadata IS '文件扩展元数据。';

-- =====================================================================
-- 5. 知识库
-- =====================================================================

CREATE TABLE IF NOT EXISTS knowledge.knowledge_bases (
    id BIGSERIAL PRIMARY KEY,
    knowledge_id VARCHAR(100) NOT NULL UNIQUE,
    name VARCHAR(255) NOT NULL,
    description TEXT,
    collection_name VARCHAR(255) NOT NULL UNIQUE,
    embedding_model VARCHAR(255) NOT NULL,
    embedding_dimension INTEGER NOT NULL CHECK (embedding_dimension > 0),
    split_config JSONB NOT NULL DEFAULT '{}'::jsonb,
    status VARCHAR(30) NOT NULL DEFAULT 'active'
        CHECK (status IN ('active', 'disabled', 'deleted')),
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS knowledge.knowledge_documents (
    id BIGSERIAL PRIMARY KEY,
    knowledge_id VARCHAR(100) NOT NULL,
    file_id VARCHAR(100) NOT NULL,
    status VARCHAR(30) NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending', 'indexing', 'indexed', 'deleting', 'failed', 'deleted')),
    index_version INTEGER NOT NULL DEFAULT 1 CHECK (index_version > 0),
    chunk_count INTEGER NOT NULL DEFAULT 0 CHECK (chunk_count >= 0),
    index_config JSONB NOT NULL DEFAULT '{}'::jsonb,
    error_message TEXT,
    indexed_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_knowledge_documents_kb_file
        UNIQUE (knowledge_id, file_id),
    CONSTRAINT fk_knowledge_documents_knowledge_base
        FOREIGN KEY (knowledge_id)
        REFERENCES knowledge.knowledge_bases(knowledge_id)
        ON DELETE CASCADE,
    CONSTRAINT fk_knowledge_documents_uploaded_file
        FOREIGN KEY (file_id)
        REFERENCES agent.uploaded_files(file_id)
        ON DELETE RESTRICT
);

CREATE TABLE IF NOT EXISTS knowledge.ingestion_runs (
    run_id VARCHAR(100) PRIMARY KEY,
    document_id BIGINT NOT NULL,
    knowledge_id VARCHAR(100) NOT NULL,
    file_id VARCHAR(100) NOT NULL,
    operation VARCHAR(30) NOT NULL DEFAULT 'ingest'
        CHECK (operation IN ('ingest', 'reindex', 'delete')),
    status VARCHAR(30) NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending', 'running', 'completed', 'failed', 'cancelled')),
    priority INTEGER NOT NULL DEFAULT 0,
    payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    worker_id VARCHAR(150),
    heartbeat_at TIMESTAMPTZ,
    retry_count INTEGER NOT NULL DEFAULT 0 CHECK (retry_count >= 0),
    max_retries INTEGER NOT NULL DEFAULT 3 CHECK (max_retries >= 0),
    available_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    error_message TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    started_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,
    CONSTRAINT fk_ingestion_runs_document
        FOREIGN KEY (document_id)
        REFERENCES knowledge.knowledge_documents(id)
        ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS knowledge.knowledge_chunks (
    id BIGSERIAL PRIMARY KEY,
    knowledge_id VARCHAR(100) NOT NULL,
    document_id BIGINT NOT NULL,
    file_id VARCHAR(100) NOT NULL,
    chunk_id VARCHAR(100) NOT NULL,
    index_version INTEGER NOT NULL CHECK (index_version > 0),
    chunk_index INTEGER NOT NULL CHECK (chunk_index >= 0),
    raw_content TEXT NOT NULL,
    content_hash VARCHAR(64) NOT NULL,
    char_count INTEGER NOT NULL CHECK (char_count >= 0),
    context TEXT,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    vector_id VARCHAR(100) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_knowledge_chunks_kb_chunk
        UNIQUE (knowledge_id, chunk_id),
    CONSTRAINT uq_knowledge_chunks_document_version_index
        UNIQUE (document_id, index_version, chunk_index),
    CONSTRAINT fk_knowledge_chunks_document
        FOREIGN KEY (document_id)
        REFERENCES knowledge.knowledge_documents(id)
        ON DELETE CASCADE
);

-- 同一文档最多只能有一个正在等待或执行的入库任务，防止并发重复入库。
CREATE UNIQUE INDEX IF NOT EXISTS uq_ingestion_runs_active_document
ON knowledge.ingestion_runs(document_id)
WHERE status IN ('pending', 'running');

CREATE INDEX IF NOT EXISTS idx_knowledge_bases_status
ON knowledge.knowledge_bases(status);

CREATE INDEX IF NOT EXISTS idx_knowledge_documents_knowledge_id
ON knowledge.knowledge_documents(knowledge_id);

CREATE INDEX IF NOT EXISTS idx_knowledge_documents_status
ON knowledge.knowledge_documents(status);

CREATE INDEX IF NOT EXISTS idx_knowledge_documents_file_id
ON knowledge.knowledge_documents(file_id);

CREATE INDEX IF NOT EXISTS idx_ingestion_runs_document_id
ON knowledge.ingestion_runs(document_id);

CREATE INDEX IF NOT EXISTS idx_ingestion_runs_queue
ON knowledge.ingestion_runs(status, available_at, priority DESC, created_at);

CREATE INDEX IF NOT EXISTS idx_ingestion_runs_heartbeat
ON knowledge.ingestion_runs(status, heartbeat_at);

CREATE INDEX IF NOT EXISTS idx_ingestion_runs_knowledge_id
ON knowledge.ingestion_runs(knowledge_id);

CREATE INDEX IF NOT EXISTS idx_ingestion_runs_file_id
ON knowledge.ingestion_runs(file_id);

CREATE INDEX IF NOT EXISTS idx_ingestion_runs_worker_id
ON knowledge.ingestion_runs(worker_id);

CREATE INDEX IF NOT EXISTS idx_knowledge_chunks_knowledge_id
ON knowledge.knowledge_chunks(knowledge_id);

CREATE INDEX IF NOT EXISTS idx_knowledge_chunks_document
ON knowledge.knowledge_chunks(document_id, index_version, chunk_index);

CREATE INDEX IF NOT EXISTS idx_knowledge_chunks_file_id
ON knowledge.knowledge_chunks(file_id);

CREATE INDEX IF NOT EXISTS idx_knowledge_chunks_chunk_id
ON knowledge.knowledge_chunks(chunk_id);

COMMENT ON TABLE knowledge.knowledge_bases IS '知识库定义与索引配置表。';
COMMENT ON COLUMN knowledge.knowledge_bases.knowledge_id IS '对外使用的稳定知识库 ID。';
COMMENT ON COLUMN knowledge.knowledge_bases.collection_name IS '对应的 Milvus Collection 名称。';
COMMENT ON COLUMN knowledge.knowledge_bases.embedding_model IS '绑定的 model_configs.model_code。';
COMMENT ON COLUMN knowledge.knowledge_bases.embedding_dimension IS 'Embedding 向量维度。';
COMMENT ON COLUMN knowledge.knowledge_bases.split_config IS '默认切片方式或组合切片策略。';

COMMENT ON TABLE knowledge.knowledge_documents IS '知识库与上传文件的关联及索引状态表。';
COMMENT ON COLUMN knowledge.knowledge_documents.file_id IS '关联 agent.uploaded_files.file_id。';
COMMENT ON COLUMN knowledge.knowledge_documents.index_version IS '文档当前索引版本。';
COMMENT ON COLUMN knowledge.knowledge_documents.index_config IS '最近一次入库实际使用的配置快照。';

COMMENT ON TABLE knowledge.ingestion_runs IS '知识入库任务队列与运行记录表。';
COMMENT ON COLUMN knowledge.ingestion_runs.operation IS '任务类型：ingest、reindex 或 delete。';
COMMENT ON COLUMN knowledge.ingestion_runs.priority IS '任务优先级，数值越大越先执行。';
COMMENT ON COLUMN knowledge.ingestion_runs.heartbeat_at IS 'Worker 最近一次心跳时间。';
COMMENT ON COLUMN knowledge.ingestion_runs.available_at IS '任务允许被 Worker 抢占的时间。';

COMMENT ON TABLE knowledge.knowledge_chunks IS '知识分块证据、顺序及 Milvus 向量映射表。';
COMMENT ON COLUMN knowledge.knowledge_chunks.chunk_id IS '包含文件和索引版本的稳定分块 ID。';
COMMENT ON COLUMN knowledge.knowledge_chunks.raw_content IS '可追溯的原始分块正文。';
COMMENT ON COLUMN knowledge.knowledge_chunks.context IS '标题路径等层级上下文。';
COMMENT ON COLUMN knowledge.knowledge_chunks.vector_id IS '对应的 Milvus 主键。';

COMMIT;
