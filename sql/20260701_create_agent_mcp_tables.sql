-- Agent MCP 单表工具配置
-- 说明：一条记录代表一个可被 Agent 选择的 MCP 工具，不再拆分 MCP 服务表和工具表。

CREATE SCHEMA IF NOT EXISTS agent;

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

COMMENT ON TABLE agent.agent_mcp_tools IS 'Agent MCP工具配置表：一条记录代表一个可被Agent选择的MCP工具。';
COMMENT ON COLUMN agent.agent_mcp_tools.id IS '主键ID。';
COMMENT ON COLUMN agent.agent_mcp_tools.mcp_code IS '平台内MCP工具唯一编码，例如 job.search_job_skills。';
COMMENT ON COLUMN agent.agent_mcp_tools.name IS 'MCP服务中的真实工具名称，调用远端MCP工具时使用。';
COMMENT ON COLUMN agent.agent_mcp_tools.description IS '工具描述，用于前端展示和Agent理解工具用途。';
COMMENT ON COLUMN agent.agent_mcp_tools.base_url IS 'MCP服务访问地址，例如 http://127.0.0.1:8091/mcp/。';
COMMENT ON COLUMN agent.agent_mcp_tools.transport IS 'MCP传输协议，当前主要使用http。';
COMMENT ON COLUMN agent.agent_mcp_tools.auth_type IS '认证类型，第一阶段可为空。';
COMMENT ON COLUMN agent.agent_mcp_tools.auth_config IS '认证配置JSON，按MCP客户端配置透传。';
COMMENT ON COLUMN agent.agent_mcp_tools.input_schema IS '工具输入参数JSON Schema。';
COMMENT ON COLUMN agent.agent_mcp_tools.output_schema IS '工具输出参数JSON Schema。';
COMMENT ON COLUMN agent.agent_mcp_tools.status IS '工具状态：enabled=启用，disabled=停用。';
COMMENT ON COLUMN agent.agent_mcp_tools.created_at IS '创建时间。';
COMMENT ON COLUMN agent.agent_mcp_tools.updated_at IS '更新时间。';

CREATE INDEX IF NOT EXISTS idx_agent_mcp_tools_name ON agent.agent_mcp_tools(name);
CREATE INDEX IF NOT EXISTS idx_agent_mcp_tools_base_url ON agent.agent_mcp_tools(base_url);
CREATE INDEX IF NOT EXISTS idx_agent_mcp_tools_status ON agent.agent_mcp_tools(status);
CREATE INDEX IF NOT EXISTS idx_agent_mcp_tools_updated_at ON agent.agent_mcp_tools(updated_at);
