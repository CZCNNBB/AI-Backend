BEGIN;

-- 运行表当前为空，因此可以直接调整主键和删除冗余列。
ALTER TABLE agent.agent_runs
DROP CONSTRAINT IF EXISTS agent_runs_pkey;

ALTER TABLE agent.agent_runs
DROP COLUMN IF EXISTS id,
DROP COLUMN IF EXISTS thread_id,
DROP COLUMN IF EXISTS agent_name,
DROP COLUMN IF EXISTS stream,
DROP COLUMN IF EXISTS stateless,
DROP COLUMN IF EXISTS created_at,
DROP COLUMN IF EXISTS updated_at,
DROP COLUMN IF EXISTS parent_thread_id;

ALTER TABLE agent.agent_runs
ALTER COLUMN run_id SET NOT NULL;

ALTER TABLE agent.agent_runs
ADD CONSTRAINT agent_runs_pkey PRIMARY KEY (run_id);

COMMENT ON TABLE agent.agent_runs IS 'Agent 运行记录表，用于统一记录主 Agent 和 A2A 子 Agent 的业务运行台账。';
COMMENT ON COLUMN agent.agent_runs.run_id IS 'Agent 本次运行 ID，同时作为主键。';
COMMENT ON COLUMN agent.agent_runs.run_type IS '运行类型：main=主 Agent，sub=A2A 子 Agent。';
COMMENT ON COLUMN agent.agent_runs.parent_run_id IS '父级 Agent 运行 ID；主 Agent 为空，子 Agent 关联主 Agent。';
COMMENT ON COLUMN agent.agent_runs.agent_id IS '当前运行的 Agent 模板 ID；无模板时为空。';
COMMENT ON COLUMN agent.agent_runs.conversation_id IS '用户会话 ID；子 Agent 记录父级会话 ID，便于按会话查询完整运行链路。';
COMMENT ON COLUMN agent.agent_runs.started_at IS '运行开始时间。';
COMMENT ON COLUMN agent.agent_runs.finished_at IS '运行结束时间。';

DROP INDEX IF EXISTS idx_agent_runs_thread_id;

COMMIT;