-- HTTP API 转 MCP Tool 表初始化脚本。
-- 当前表没有业务数据，开发阶段直接重建，不保留旧的外部 MCP Server 注册结构。

CREATE SCHEMA IF NOT EXISTS mcp;

DROP TABLE IF EXISTS agent.agent_mcp_tools;
DROP TABLE IF EXISTS mcp.mcp_tools;

CREATE TABLE mcp.mcp_tools (
    id BIGSERIAL PRIMARY KEY,

    -- name 同时作为 FastMCP 真实 Tool 名和 Agent 配置唯一标识。
    name VARCHAR(150) NOT NULL UNIQUE,
    description TEXT,

    -- 目标业务 HTTP API 配置。
    api_url TEXT NOT NULL,
    http_method VARCHAR(10) NOT NULL DEFAULT 'POST',
    static_headers JSONB NOT NULL DEFAULT '{}'::jsonb,
    parameters JSONB NOT NULL DEFAULT '[]'::jsonb,

    -- 认证值只由平台执行器使用，不会进入 MCP Tool 输入 Schema。
    auth_type VARCHAR(50) NOT NULL DEFAULT 'none',
    auth_config JSONB NOT NULL DEFAULT '{}'::jsonb,
    input_schema JSONB NOT NULL DEFAULT '{"type":"object","properties":{},"additionalProperties":false}'::jsonb,
    output_schema JSONB,

    timeout_seconds DOUBLE PRECISION NOT NULL DEFAULT 30,
    status VARCHAR(30) NOT NULL DEFAULT 'draft',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT ck_mcp_tools_http_method
        CHECK (http_method IN ('GET', 'POST', 'PUT', 'PATCH', 'DELETE')),
    CONSTRAINT ck_mcp_tools_auth_type
        CHECK (auth_type IN ('none', 'bearer', 'basic', 'api_key')),
    CONSTRAINT ck_mcp_tools_status
        CHECK (status IN ('draft', 'enabled', 'disabled')),
    CONSTRAINT ck_mcp_tools_timeout
        CHECK (timeout_seconds > 0 AND timeout_seconds <= 600)
);

COMMENT ON TABLE mcp.mcp_tools IS '普通 HTTP API 转换型 MCP Tool 配置表。';
COMMENT ON COLUMN mcp.mcp_tools.name IS 'FastMCP Tool 真实名称，Agent 模板直接引用。';
COMMENT ON COLUMN mcp.mcp_tools.api_url IS '目标业务 HTTP API 地址，支持 {参数名} path 占位符。';
COMMENT ON COLUMN mcp.mcp_tools.http_method IS '目标 API 的 HTTP 方法。';
COMMENT ON COLUMN mcp.mcp_tools.static_headers IS '固定 HTTP 请求头，不暴露给模型。';
COMMENT ON COLUMN mcp.mcp_tools.parameters IS 'Tool/runtime/static 参数到 path/query/header/body 的映射列表。';
COMMENT ON COLUMN mcp.mcp_tools.auth_config IS 'Bearer、Basic 或 API Key 认证配置。';
COMMENT ON COLUMN mcp.mcp_tools.input_schema IS '由 source=tool 的参数自动生成的 MCP 输入 JSON Schema。';
COMMENT ON COLUMN mcp.mcp_tools.output_schema IS '可选的 MCP 输出 JSON Schema。';
COMMENT ON COLUMN mcp.mcp_tools.status IS 'draft=草稿，enabled=已发布，disabled=已停用。';

CREATE INDEX idx_mcp_tools_status ON mcp.mcp_tools(status);
CREATE INDEX idx_mcp_tools_api_url ON mcp.mcp_tools(api_url);
CREATE INDEX idx_mcp_tools_updated_at ON mcp.mcp_tools(updated_at);
