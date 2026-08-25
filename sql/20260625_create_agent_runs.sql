CREATE SCHEMA IF NOT EXISTS agent;

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

COMMENT ON TABLE agent.agent_runs IS 'Agent 运行记录表，用于统一记录主 Agent 和 A2A 子 Agent 的业务运行台账。';
COMMENT ON COLUMN agent.agent_runs.run_id IS 'Agent 本次运行 ID，同时作为主键。';
COMMENT ON COLUMN agent.agent_runs.run_type IS '运行类型：main=主 Agent，sub=A2A 子 Agent。';
COMMENT ON COLUMN agent.agent_runs.parent_run_id IS '父级 Agent 运行 ID；主 Agent 为空，子 Agent 关联主 Agent。';
COMMENT ON COLUMN agent.agent_runs.agent_id IS '当前运行的 Agent 模板 ID；无模板时为空。';
COMMENT ON COLUMN agent.agent_runs.conversation_id IS '用户会话 ID；子 Agent 记录父级会话 ID，便于按会话查询完整运行链路。';
COMMENT ON COLUMN agent.agent_runs.user_message_id IS '本次主 Agent 运行对应的用户消息 ID。';
COMMENT ON COLUMN agent.agent_runs.assistant_message_id IS '本次主 Agent 运行对应的助手最终回复消息 ID。';
COMMENT ON COLUMN agent.agent_runs.query IS '本次运行的用户输入或任务指令。';
COMMENT ON COLUMN agent.agent_runs.answer IS 'Agent 最终回复文本。';
COMMENT ON COLUMN agent.agent_runs.status IS '运行状态：running/success/failed。';
COMMENT ON COLUMN agent.agent_runs.error_message IS '失败原因。';
COMMENT ON COLUMN agent.agent_runs.elapsed_ms IS '运行耗时，单位毫秒。';
COMMENT ON COLUMN agent.agent_runs.metadata IS '运行扩展元数据，例如工具列表、A2A 白名单、结构化输出开关等。';
COMMENT ON COLUMN agent.agent_runs.started_at IS '运行开始时间。';
COMMENT ON COLUMN agent.agent_runs.finished_at IS '运行结束时间。';

CREATE INDEX IF NOT EXISTS idx_agent_runs_run_type
ON agent.agent_runs(run_type);

CREATE INDEX IF NOT EXISTS idx_agent_runs_parent_run_id
ON agent.agent_runs(parent_run_id);

CREATE INDEX IF NOT EXISTS idx_agent_runs_conversation_id
ON agent.agent_runs(conversation_id);

CREATE INDEX IF NOT EXISTS idx_agent_runs_user_message_id
ON agent.agent_runs(user_message_id);

CREATE INDEX IF NOT EXISTS idx_agent_runs_assistant_message_id
ON agent.agent_runs(assistant_message_id);

CREATE INDEX IF NOT EXISTS idx_agent_runs_agent_id
ON agent.agent_runs(agent_id);

CREATE INDEX IF NOT EXISTS idx_agent_runs_status
ON agent.agent_runs(status);

CREATE INDEX IF NOT EXISTS idx_agent_runs_started_at
ON agent.agent_runs(started_at);