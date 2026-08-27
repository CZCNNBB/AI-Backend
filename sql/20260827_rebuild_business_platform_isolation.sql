-- 业务平台接入、资源绑定和会话隔离重建脚本。
--
-- 警告：本脚本面向开发阶段，会清空 Agent 会话、消息、运行记录和 LangGraph Checkpoint 数据。
-- 执行前必须停止 AI-backend，确认目标数据库无须保留上述数据。

BEGIN;

-- 先清理 Checkpointer 状态，避免旧 conversation_id 的状态继续被新隔离模型读取。
DO $$
DECLARE
    checkpoint_table_name TEXT;
BEGIN
    FOREACH checkpoint_table_name IN ARRAY ARRAY[
        'checkpoint_writes',
        'checkpoint_blobs',
        'checkpoints'
    ]
    LOOP
        IF to_regclass('agent.' || checkpoint_table_name) IS NOT NULL THEN
            EXECUTE format('TRUNCATE TABLE agent.%I CASCADE', checkpoint_table_name);
        END IF;
    END LOOP;
END
$$;

-- 会话、消息和运行记录不做旧数据迁移，直接按外键依赖顺序清空。
TRUNCATE TABLE agent.agent_messages RESTART IDENTITY CASCADE;
TRUNCATE TABLE agent.agent_runs RESTART IDENTITY CASCADE;
TRUNCATE TABLE agent.agent_conversations RESTART IDENTITY CASCADE;

-- platform schema 仍处于开发阶段，直接重建可避免残留旧约束和临时表。
DROP SCHEMA IF EXISTS platform CASCADE;
CREATE SCHEMA platform;

CREATE TABLE platform.business_platforms (
    id BIGSERIAL PRIMARY KEY,
    platform_code VARCHAR(100) NOT NULL UNIQUE,
    platform_name VARCHAR(200) NOT NULL,
    description TEXT,
    status VARCHAR(30) NOT NULL DEFAULT 'enabled',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT ck_business_platforms_status CHECK (status IN ('enabled', 'disabled'))
);

CREATE TABLE platform.business_platform_api_keys (
    id BIGSERIAL PRIMARY KEY,
    platform_id BIGINT NOT NULL REFERENCES platform.business_platforms(id) ON DELETE CASCADE,
    key_name VARCHAR(100) NOT NULL DEFAULT 'default',
    key_prefix VARCHAR(30) NOT NULL,
    api_key VARCHAR(255) NOT NULL,
    key_hash VARCHAR(64) NOT NULL UNIQUE,
    status VARCHAR(30) NOT NULL DEFAULT 'enabled',
    expires_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_platform_api_keys_name UNIQUE (platform_id, key_name),
    CONSTRAINT ck_platform_api_keys_status CHECK (status IN ('enabled', 'disabled'))
);

CREATE INDEX idx_platform_api_keys_platform_id
ON platform.business_platform_api_keys(platform_id);

-- 旧会话数据已经清空，因此直接添加非空归属字段，不保留 nullable 过渡状态。
ALTER TABLE agent.agent_conversations
DROP COLUMN IF EXISTS platform_id,
DROP COLUMN IF EXISTS external_user_id;

ALTER TABLE agent.agent_conversations
ADD COLUMN platform_id BIGINT NOT NULL,
ADD COLUMN external_user_id VARCHAR(150) NOT NULL,
ADD CONSTRAINT fk_agent_conversations_platform
    FOREIGN KEY (platform_id) REFERENCES platform.business_platforms(id);

CREATE INDEX idx_agent_conversations_platform_user
ON agent.agent_conversations(platform_id, external_user_id, updated_at DESC);

CREATE INDEX idx_agent_conversations_owner
ON agent.agent_conversations(platform_id, external_user_id, conversation_id);

ALTER TABLE agent.agent_runs
DROP COLUMN IF EXISTS platform_id,
DROP COLUMN IF EXISTS external_user_id;

ALTER TABLE agent.agent_runs
ADD COLUMN platform_id BIGINT NOT NULL,
ADD COLUMN external_user_id VARCHAR(150) NOT NULL,
ADD CONSTRAINT fk_agent_runs_platform
    FOREIGN KEY (platform_id) REFERENCES platform.business_platforms(id);

CREATE INDEX idx_agent_runs_platform_user
ON agent.agent_runs(platform_id, external_user_id, started_at DESC);

ALTER TABLE mcp.mcp_tools
DROP CONSTRAINT IF EXISTS ck_mcp_tools_auth_type;

ALTER TABLE mcp.mcp_tools
ADD CONSTRAINT ck_mcp_tools_auth_type
CHECK (auth_type IN ('none', 'bearer', 'basic', 'api_key', 'runtime_bearer'));

CREATE TABLE platform.business_platform_agents (
    platform_id BIGINT NOT NULL REFERENCES platform.business_platforms(id) ON DELETE CASCADE,
    agent_template_id BIGINT NOT NULL REFERENCES agent.agent_templates(id) ON DELETE CASCADE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (platform_id, agent_template_id)
);

CREATE TABLE platform.business_platform_mcp_tools (
    platform_id BIGINT NOT NULL REFERENCES platform.business_platforms(id) ON DELETE CASCADE,
    mcp_tool_id BIGINT NOT NULL REFERENCES mcp.mcp_tools(id) ON DELETE CASCADE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (platform_id, mcp_tool_id)
);

CREATE INDEX idx_platform_agents_agent_id
ON platform.business_platform_agents(agent_template_id);

CREATE INDEX idx_platform_mcp_tools_tool_id
ON platform.business_platform_mcp_tools(mcp_tool_id);

COMMENT ON TABLE platform.business_platforms IS '接入 AI-backend 的外部业务平台。';
COMMENT ON TABLE platform.business_platform_api_keys IS '平台调用 API Key，内网模式保存明文并同时保留鉴权哈希。';
COMMENT ON COLUMN platform.business_platform_api_keys.api_key IS '内网管理调试使用的完整 API Key，请勿写入日志。';
COMMENT ON TABLE platform.business_platform_agents IS '业务平台与 Agent 模板的多对多绑定。';
COMMENT ON TABLE platform.business_platform_mcp_tools IS '业务平台与 MCP Tool 的多对多绑定。';
COMMENT ON COLUMN agent.agent_conversations.platform_id IS '会话所属业务平台。';
COMMENT ON COLUMN agent.agent_conversations.external_user_id IS '业务平台中的稳定用户 ID。';
COMMENT ON COLUMN agent.agent_runs.platform_id IS '运行所属业务平台。';
COMMENT ON COLUMN agent.agent_runs.external_user_id IS '业务平台中的稳定用户 ID。';
COMMENT ON COLUMN mcp.mcp_tools.auth_type IS '目标 API 认证类型；runtime_bearer 表示使用本次 Agent 请求的业务用户 Token。';

COMMIT;
