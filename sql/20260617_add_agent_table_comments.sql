-- 为能力层 Agent 相关表补充 PostgreSQL 表注释和字段注释。
-- 说明：
-- 1. 本脚本只添加 COMMENT，不修改表结构，也不会影响已有数据。
-- 2. Agent 业务表位于 agent schema。
-- 3. LangGraph PostgreSQL checkpointer 表由 langgraph-checkpoint-postgres 自动创建，
--    不同版本字段可能略有差异，所以字段注释全部使用存在性判断。

CREATE OR REPLACE FUNCTION pg_temp.comment_table_if_exists(
    p_schema_name TEXT,
    p_table_name TEXT,
    p_comment TEXT
) RETURNS VOID AS $$
BEGIN
    -- 只有表真实存在时才添加表注释，避免未启用 checkpointer 的环境执行失败。
    IF EXISTS (
        SELECT 1
        FROM information_schema.tables
        WHERE table_schema = p_schema_name
          AND table_name = p_table_name
    ) THEN
        EXECUTE format(
            'COMMENT ON TABLE %I.%I IS %L',
            p_schema_name,
            p_table_name,
            p_comment
        );
    END IF;
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION pg_temp.comment_column_if_exists(
    p_schema_name TEXT,
    p_table_name TEXT,
    p_column_name TEXT,
    p_comment TEXT
) RETURNS VOID AS $$
BEGIN
    -- 只有字段真实存在时才添加字段注释，兼容不同阶段和不同 LangGraph 版本的表结构。
    IF EXISTS (
        SELECT 1
        FROM information_schema.columns
        WHERE table_schema = p_schema_name
          AND table_name = p_table_name
          AND column_name = p_column_name
    ) THEN
        EXECUTE format(
            'COMMENT ON COLUMN %I.%I.%I IS %L',
            p_schema_name,
            p_table_name,
            p_column_name,
            p_comment
        );
    END IF;
END;
$$ LANGUAGE plpgsql;

-- ---------------------------------------------------------------------
-- agent.agent_conversations：Agent 会话主表
-- ---------------------------------------------------------------------

SELECT pg_temp.comment_table_if_exists(
    'agent',
    'agent_conversations',
    'Agent 会话主表：记录一个 conversation_id 对应的一组历史消息，用于 ContextService 管理会话上下文。'
);

SELECT pg_temp.comment_column_if_exists('agent', 'agent_conversations', 'id', '主键 ID。');
SELECT pg_temp.comment_column_if_exists('agent', 'agent_conversations', 'conversation_id', '会话唯一标识；系统通过该字段查询会话历史。');
SELECT pg_temp.comment_column_if_exists('agent', 'agent_conversations', 'title', '会话标题，可由前端或后续摘要逻辑生成。');
SELECT pg_temp.comment_column_if_exists('agent', 'agent_conversations', 'status', '会话状态，例如 active、archived、deleted。');
SELECT pg_temp.comment_column_if_exists('agent', 'agent_conversations', 'metadata', '会话扩展元数据，使用 JSONB 保存。');
SELECT pg_temp.comment_column_if_exists('agent', 'agent_conversations', 'created_at', '记录创建时间。');
SELECT pg_temp.comment_column_if_exists('agent', 'agent_conversations', 'updated_at', '记录更新时间。');

-- ---------------------------------------------------------------------
-- agent.agent_messages：Agent 会话消息表
-- ---------------------------------------------------------------------

SELECT pg_temp.comment_table_if_exists(
    'agent',
    'agent_messages',
    'Agent 会话消息表：记录用户输入、模型回复、工具调用摘要、工具结果摘要和错误消息等历史上下文。'
);

SELECT pg_temp.comment_column_if_exists('agent', 'agent_messages', 'id', '主键 ID。');
SELECT pg_temp.comment_column_if_exists('agent', 'agent_messages', 'conversation_id', '所属会话 ID，对应 agent.agent_conversations.conversation_id。');
SELECT pg_temp.comment_column_if_exists('agent', 'agent_messages', 'message_id', '消息唯一标识，用于追踪单条历史消息。');
SELECT pg_temp.comment_column_if_exists('agent', 'agent_messages', 'parent_message_id', '父消息 ID，用于表达消息之间的上下文或调用关系。');
SELECT pg_temp.comment_column_if_exists('agent', 'agent_messages', 'role', '消息角色，例如 user、assistant、system、tool。');
SELECT pg_temp.comment_column_if_exists('agent', 'agent_messages', 'message_type', '消息类型，例如 user_input、model_response、tool_call、tool_result、error。');
SELECT pg_temp.comment_column_if_exists('agent', 'agent_messages', 'content', '消息文本内容。');
SELECT pg_temp.comment_column_if_exists('agent', 'agent_messages', 'structured_content', '结构化消息内容，使用 JSONB 保存。');
SELECT pg_temp.comment_column_if_exists('agent', 'agent_messages', 'tool_name', '工具名称；当消息与工具调用相关时记录。');
SELECT pg_temp.comment_column_if_exists('agent', 'agent_messages', 'tool_call_id', '模型生成的工具调用 ID 或系统内部工具调用 ID。');
SELECT pg_temp.comment_column_if_exists('agent', 'agent_messages', 'status', '消息状态，例如 success、failed。');
SELECT pg_temp.comment_column_if_exists('agent', 'agent_messages', 'error_message', '消息处理失败时的错误信息。');
SELECT pg_temp.comment_column_if_exists('agent', 'agent_messages', 'metadata', '消息扩展元数据，使用 JSONB 保存。');
SELECT pg_temp.comment_column_if_exists('agent', 'agent_messages', 'created_at', '消息创建时间。');

-- ---------------------------------------------------------------------
-- agent.agent_templates：Agent 模板表
-- ---------------------------------------------------------------------

SELECT pg_temp.comment_table_if_exists(
    'agent',
    'agent_templates',
    'Agent 模板表：保存可复用的 Agent 配置模板，例如名称、描述、模型参数、工具配置和可选能力配置。'
);

SELECT pg_temp.comment_column_if_exists('agent', 'agent_templates', 'id', '主键 ID。');
SELECT pg_temp.comment_column_if_exists('agent', 'agent_templates', 'agent_id', 'Agent 模板稳定标识；仅用于模板管理，不直接绑定 /agent/run。');
SELECT pg_temp.comment_column_if_exists('agent', 'agent_templates', 'agent_name', 'Agent 模板名称。');
SELECT pg_temp.comment_column_if_exists('agent', 'agent_templates', 'description', 'Agent 模板说明。');
SELECT pg_temp.comment_column_if_exists('agent', 'agent_templates', 'config', 'Agent 模板配置，使用 JSONB 保存，结构可随 AgentRunRequest 演进。');
SELECT pg_temp.comment_column_if_exists('agent', 'agent_templates', 'status', '模板状态，例如 active、disabled。');
SELECT pg_temp.comment_column_if_exists('agent', 'agent_templates', 'created_at', '记录创建时间。');
SELECT pg_temp.comment_column_if_exists('agent', 'agent_templates', 'updated_at', '记录更新时间。');

-- ---------------------------------------------------------------------
-- agent.checkpoints：LangGraph Checkpoint 主表
-- ---------------------------------------------------------------------

SELECT pg_temp.comment_table_if_exists(
    'agent',
    'checkpoints',
    'LangGraph Checkpoint 主表：保存图运行状态快照，用于状态恢复、排查和中断续跑。'
);

SELECT pg_temp.comment_column_if_exists('agent', 'checkpoints', 'thread_id', 'LangGraph 线程 ID；当前通常使用本轮运行的 conversation_id 或运行上下文 ID。');
SELECT pg_temp.comment_column_if_exists('agent', 'checkpoints', 'checkpoint_ns', 'Checkpoint 命名空间，用于同一 thread 下隔离不同图或子图。');
SELECT pg_temp.comment_column_if_exists('agent', 'checkpoints', 'checkpoint_id', 'Checkpoint 唯一 ID。');
SELECT pg_temp.comment_column_if_exists('agent', 'checkpoints', 'parent_checkpoint_id', '父 Checkpoint ID，用于恢复状态链路。');
SELECT pg_temp.comment_column_if_exists('agent', 'checkpoints', 'type', 'Checkpoint 序列化类型。');
SELECT pg_temp.comment_column_if_exists('agent', 'checkpoints', 'checkpoint', 'Checkpoint 状态内容，通常保存 LangGraph state 的序列化结果。');
SELECT pg_temp.comment_column_if_exists('agent', 'checkpoints', 'metadata', 'Checkpoint 元数据，例如运行步骤、来源和调试信息。');

-- ---------------------------------------------------------------------
-- agent.checkpoint_blobs：LangGraph Checkpoint 二进制内容表
-- ---------------------------------------------------------------------

SELECT pg_temp.comment_table_if_exists(
    'agent',
    'checkpoint_blobs',
    'LangGraph Checkpoint Blob 表：保存 channel/version 维度的序列化二进制内容。'
);

SELECT pg_temp.comment_column_if_exists('agent', 'checkpoint_blobs', 'thread_id', 'LangGraph 线程 ID。');
SELECT pg_temp.comment_column_if_exists('agent', 'checkpoint_blobs', 'checkpoint_ns', 'Checkpoint 命名空间。');
SELECT pg_temp.comment_column_if_exists('agent', 'checkpoint_blobs', 'channel', 'LangGraph 状态通道名称。');
SELECT pg_temp.comment_column_if_exists('agent', 'checkpoint_blobs', 'version', '状态通道版本。');
SELECT pg_temp.comment_column_if_exists('agent', 'checkpoint_blobs', 'type', 'Blob 序列化类型。');
SELECT pg_temp.comment_column_if_exists('agent', 'checkpoint_blobs', 'blob', '序列化后的二进制状态内容。');

-- ---------------------------------------------------------------------
-- agent.checkpoint_writes：LangGraph Checkpoint 写入记录表
-- ---------------------------------------------------------------------

SELECT pg_temp.comment_table_if_exists(
    'agent',
    'checkpoint_writes',
    'LangGraph Checkpoint 写入记录表：保存图执行过程中每个任务对状态通道的写入记录。'
);

SELECT pg_temp.comment_column_if_exists('agent', 'checkpoint_writes', 'thread_id', 'LangGraph 线程 ID。');
SELECT pg_temp.comment_column_if_exists('agent', 'checkpoint_writes', 'checkpoint_ns', 'Checkpoint 命名空间。');
SELECT pg_temp.comment_column_if_exists('agent', 'checkpoint_writes', 'checkpoint_id', '所属 Checkpoint ID。');
SELECT pg_temp.comment_column_if_exists('agent', 'checkpoint_writes', 'task_id', 'LangGraph 内部任务 ID。');
SELECT pg_temp.comment_column_if_exists('agent', 'checkpoint_writes', 'task_path', 'LangGraph 内部任务路径。');
SELECT pg_temp.comment_column_if_exists('agent', 'checkpoint_writes', 'idx', '同一任务下写入记录的序号。');
SELECT pg_temp.comment_column_if_exists('agent', 'checkpoint_writes', 'channel', '被写入的状态通道名称。');
SELECT pg_temp.comment_column_if_exists('agent', 'checkpoint_writes', 'type', '写入内容的序列化类型。');
SELECT pg_temp.comment_column_if_exists('agent', 'checkpoint_writes', 'blob', '序列化后的写入内容。');

-- ---------------------------------------------------------------------
-- agent.checkpoint_migrations：LangGraph Checkpoint 迁移版本表
-- ---------------------------------------------------------------------

SELECT pg_temp.comment_table_if_exists(
    'agent',
    'checkpoint_migrations',
    'LangGraph Checkpoint 迁移版本表：记录 checkpointer 官方表结构迁移版本。'
);

SELECT pg_temp.comment_column_if_exists('agent', 'checkpoint_migrations', 'v', '已执行的 checkpointer 表结构迁移版本号。');
