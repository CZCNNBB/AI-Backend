-- 本脚本必须连接到 career_ai 数据库后执行。
-- Knowledge 与 Agent 使用同一个数据库，通过 knowledge、agent Schema 隔离表。
BEGIN;

CREATE SCHEMA IF NOT EXISTS knowledge;

CREATE TABLE knowledge.knowledge_bases (
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

CREATE TABLE knowledge.knowledge_documents (
    id BIGSERIAL PRIMARY KEY,
    knowledge_id VARCHAR(100) NOT NULL
        REFERENCES knowledge.knowledge_bases(knowledge_id) ON DELETE CASCADE,
    file_id VARCHAR(100) NOT NULL
        REFERENCES agent.uploaded_files(file_id) ON DELETE RESTRICT,
    status VARCHAR(30) NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending', 'indexing', 'indexed', 'deleting', 'failed', 'deleted')),
    index_version INTEGER NOT NULL DEFAULT 1 CHECK (index_version > 0),
    chunk_count INTEGER NOT NULL DEFAULT 0 CHECK (chunk_count >= 0),
    index_config JSONB NOT NULL DEFAULT '{}'::jsonb,
    error_message TEXT,
    indexed_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_knowledge_documents_kb_file UNIQUE (knowledge_id, file_id)
);

CREATE TABLE knowledge.ingestion_runs (
    run_id VARCHAR(100) PRIMARY KEY,
    document_id BIGINT NOT NULL
        REFERENCES knowledge.knowledge_documents(id) ON DELETE CASCADE,
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
    completed_at TIMESTAMPTZ
);

CREATE TABLE knowledge.knowledge_chunks (
    id BIGSERIAL PRIMARY KEY,
    knowledge_id VARCHAR(100) NOT NULL,
    document_id BIGINT NOT NULL
        REFERENCES knowledge.knowledge_documents(id) ON DELETE CASCADE,
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
    CONSTRAINT uq_knowledge_chunks_kb_chunk UNIQUE (knowledge_id, chunk_id),
    CONSTRAINT uq_knowledge_chunks_document_version_index
        UNIQUE (document_id, index_version, chunk_index)
);

-- 数据库级防并发穿透：同一文档、同一操作最多只有一个待执行或运行中的任务。
CREATE UNIQUE INDEX uq_ingestion_runs_active_document
ON knowledge.ingestion_runs(document_id)
WHERE status IN ('pending', 'running');

CREATE INDEX idx_knowledge_bases_status
ON knowledge.knowledge_bases(status);

CREATE INDEX idx_knowledge_documents_status
ON knowledge.knowledge_documents(status);

CREATE INDEX idx_knowledge_documents_file_id
ON knowledge.knowledge_documents(file_id);

CREATE INDEX idx_ingestion_runs_queue
ON knowledge.ingestion_runs(status, available_at, priority DESC, created_at);

CREATE INDEX idx_ingestion_runs_heartbeat
ON knowledge.ingestion_runs(status, heartbeat_at);

CREATE INDEX idx_ingestion_runs_knowledge_id
ON knowledge.ingestion_runs(knowledge_id);

CREATE INDEX idx_knowledge_chunks_document
ON knowledge.knowledge_chunks(document_id, index_version, chunk_index);

CREATE INDEX idx_knowledge_chunks_file_id
ON knowledge.knowledge_chunks(file_id);

COMMENT ON TABLE knowledge.knowledge_bases IS '知识库定义与索引配置表';
COMMENT ON COLUMN knowledge.knowledge_bases.knowledge_id IS '对外使用的稳定知识库ID';
COMMENT ON COLUMN knowledge.knowledge_bases.collection_name IS '知识库对应的Milvus Collection名称';
COMMENT ON COLUMN knowledge.knowledge_bases.embedding_model IS '知识库绑定的model_configs.model_code，创建Collection、入库和检索始终使用该模型';
COMMENT ON COLUMN knowledge.knowledge_bases.embedding_dimension IS 'Embedding向量维度，创建后不可随意修改';
COMMENT ON COLUMN knowledge.knowledge_bases.split_config IS '默认切片方式或组合切片策略配置';
COMMENT ON COLUMN knowledge.knowledge_bases.metadata IS '非核心扩展元数据';

COMMENT ON TABLE knowledge.knowledge_documents IS '知识库与文件服务上传文件的逻辑关联及索引状态表';
COMMENT ON COLUMN knowledge.knowledge_documents.file_id IS '关联agent.uploaded_files.file_id的上传文件ID';
COMMENT ON COLUMN knowledge.knowledge_documents.index_version IS '当前或下一次索引版本，用于区分重建后的分块';
COMMENT ON COLUMN knowledge.knowledge_documents.index_config IS '最近一次入库实际使用的切片和模型配置快照';

COMMENT ON TABLE knowledge.ingestion_runs IS '知识入库任务队列与运行记录表';
COMMENT ON COLUMN knowledge.ingestion_runs.run_id IS '一次入库任务的全局唯一ID';
COMMENT ON COLUMN knowledge.ingestion_runs.operation IS '任务类型：ingest、reindex或delete';
COMMENT ON COLUMN knowledge.ingestion_runs.priority IS '任务优先级，数值越大越先执行';
COMMENT ON COLUMN knowledge.ingestion_runs.payload IS '任务提交时的非核心参数快照';
COMMENT ON COLUMN knowledge.ingestion_runs.heartbeat_at IS 'Worker最近一次心跳，用于识别僵尸任务';
COMMENT ON COLUMN knowledge.ingestion_runs.available_at IS '任务允许被Worker抢占的时间，用于失败退避重试';

COMMENT ON TABLE knowledge.knowledge_chunks IS '知识分块证据、顺序及Milvus向量映射表';
COMMENT ON COLUMN knowledge.knowledge_chunks.chunk_id IS '包含文件和索引版本的稳定分块ID';
COMMENT ON COLUMN knowledge.knowledge_chunks.raw_content IS '可追溯的原始分块正文';
COMMENT ON COLUMN knowledge.knowledge_chunks.context IS '标题路径等层级上下文文本';
COMMENT ON COLUMN knowledge.knowledge_chunks.vector_id IS '对应Milvus主键，当前与chunk_id保持一致';

COMMENT ON COLUMN knowledge.knowledge_bases.id IS '内部自增主键';
COMMENT ON COLUMN knowledge.knowledge_bases.name IS '知识库名称';
COMMENT ON COLUMN knowledge.knowledge_bases.description IS '知识库说明';
COMMENT ON COLUMN knowledge.knowledge_bases.status IS '知识库状态：active、disabled、deleted';
COMMENT ON COLUMN knowledge.knowledge_bases.created_at IS '创建时间';
COMMENT ON COLUMN knowledge.knowledge_bases.updated_at IS '更新时间';

COMMENT ON COLUMN knowledge.knowledge_documents.id IS '知识库文件关系内部主键';
COMMENT ON COLUMN knowledge.knowledge_documents.knowledge_id IS '所属知识库ID';
COMMENT ON COLUMN knowledge.knowledge_documents.status IS '索引状态：pending、indexing、indexed、deleting、failed、deleted';
COMMENT ON COLUMN knowledge.knowledge_documents.chunk_count IS '当前有效分块数量';
COMMENT ON COLUMN knowledge.knowledge_documents.error_message IS '最近一次索引失败原因';
COMMENT ON COLUMN knowledge.knowledge_documents.indexed_at IS '最近一次成功索引时间';
COMMENT ON COLUMN knowledge.knowledge_documents.created_at IS '创建时间';
COMMENT ON COLUMN knowledge.knowledge_documents.updated_at IS '更新时间';

COMMENT ON COLUMN knowledge.ingestion_runs.document_id IS '关联knowledge_documents.id';
COMMENT ON COLUMN knowledge.ingestion_runs.knowledge_id IS '冗余知识库ID，便于任务检索和日志追踪';
COMMENT ON COLUMN knowledge.ingestion_runs.file_id IS '冗余文件ID，便于任务检索和日志追踪';
COMMENT ON COLUMN knowledge.ingestion_runs.status IS '任务状态：pending、running、completed、failed、cancelled';
COMMENT ON COLUMN knowledge.ingestion_runs.worker_id IS '当前持有任务的Worker实例ID';
COMMENT ON COLUMN knowledge.ingestion_runs.retry_count IS '已经发生的失败重试次数';
COMMENT ON COLUMN knowledge.ingestion_runs.max_retries IS '允许的自动重试次数';
COMMENT ON COLUMN knowledge.ingestion_runs.error_message IS '最近一次执行失败原因';
COMMENT ON COLUMN knowledge.ingestion_runs.created_at IS '任务创建时间';
COMMENT ON COLUMN knowledge.ingestion_runs.updated_at IS '任务更新时间';
COMMENT ON COLUMN knowledge.ingestion_runs.started_at IS '任务首次开始执行时间';
COMMENT ON COLUMN knowledge.ingestion_runs.completed_at IS '任务最终完成或失败时间';

COMMENT ON COLUMN knowledge.knowledge_chunks.id IS '分块内部自增主键';
COMMENT ON COLUMN knowledge.knowledge_chunks.knowledge_id IS '所属知识库ID';
COMMENT ON COLUMN knowledge.knowledge_chunks.document_id IS '所属知识库文件关系ID';
COMMENT ON COLUMN knowledge.knowledge_chunks.file_id IS '来源上传文件ID';
COMMENT ON COLUMN knowledge.knowledge_chunks.index_version IS '生成该分块时的索引版本';
COMMENT ON COLUMN knowledge.knowledge_chunks.chunk_index IS '分块在文档中的顺序，从0开始';
COMMENT ON COLUMN knowledge.knowledge_chunks.content_hash IS '分块正文SHA-256哈希';
COMMENT ON COLUMN knowledge.knowledge_chunks.char_count IS '分块正文字符数量';
COMMENT ON COLUMN knowledge.knowledge_chunks.metadata IS '标题层级等结构化分块元数据';
COMMENT ON COLUMN knowledge.knowledge_chunks.created_at IS '分块创建时间';

COMMIT;
