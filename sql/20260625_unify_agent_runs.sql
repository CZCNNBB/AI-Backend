BEGIN;

ALTER TABLE agent.agent_runs
ADD COLUMN IF NOT EXISTS run_type VARCHAR(30) NOT NULL DEFAULT 'main',
ADD COLUMN IF NOT EXISTS parent_run_id VARCHAR(100),
ADD COLUMN IF NOT EXISTS agent_id VARCHAR(100);

COMMENT ON TABLE agent.agent_runs IS 'Agent 运行记录表，用于统一记录主 Agent 和 A2A 子 Agent 的业务运行台账。';
COMMENT ON COLUMN agent.agent_runs.run_type IS '运行类型：main=主 Agent，sub=A2A 子 Agent。';
COMMENT ON COLUMN agent.agent_runs.parent_run_id IS '父级 Agent 运行 ID；主 Agent 为空，子 Agent 关联主 Agent。';
COMMENT ON COLUMN agent.agent_runs.agent_id IS '当前运行的 Agent 模板 ID；无模板时为空。';

CREATE INDEX IF NOT EXISTS idx_agent_runs_run_type
ON agent.agent_runs(run_type);

CREATE INDEX IF NOT EXISTS idx_agent_runs_parent_run_id
ON agent.agent_runs(parent_run_id);

CREATE INDEX IF NOT EXISTS idx_agent_runs_agent_id
ON agent.agent_runs(agent_id);

DROP TABLE IF EXISTS agent.agent_sub_runs;

ALTER TABLE agent.agent_runs DROP COLUMN IF EXISTS parent_thread_id;
ALTER TABLE agent.agent_runs DROP COLUMN IF EXISTS thread_id;
ALTER TABLE agent.agent_runs DROP COLUMN IF EXISTS agent_name;
ALTER TABLE agent.agent_runs DROP COLUMN IF EXISTS stream;
ALTER TABLE agent.agent_runs DROP COLUMN IF EXISTS stateless;
ALTER TABLE agent.agent_runs DROP COLUMN IF EXISTS created_at;
ALTER TABLE agent.agent_runs DROP COLUMN IF EXISTS updated_at;

COMMIT;