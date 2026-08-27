-- 为 Agent 会话增加明确的 Agent 归属。
--
-- 已有会话优先从最近一次主 Agent 运行记录中回填 agent_id，避免清理开发期聊天历史。
-- 如果存在完全没有对应运行记录的旧会话，脚本会主动中止；处理这类数据后可重新执行。

BEGIN;

ALTER TABLE agent.agent_conversations
ADD COLUMN IF NOT EXISTS agent_id VARCHAR(100);

-- 每条会话采用最近一次主运行的 agent_id。正常情况下，同一会话的所有主运行都属于同一 Agent。
WITH latest_conversation_agent AS (
    SELECT DISTINCT ON (conversation_id)
        conversation_id,
        agent_id
    FROM agent.agent_runs
    WHERE conversation_id IS NOT NULL
      AND agent_id IS NOT NULL
      AND run_type = 'main'
    ORDER BY conversation_id, started_at DESC
)
UPDATE agent.agent_conversations AS conversation
SET agent_id = latest.agent_id
FROM latest_conversation_agent AS latest
WHERE conversation.conversation_id = latest.conversation_id
  AND conversation.agent_id IS NULL;

-- 不猜测无法回填的归属，防止历史会话被错误挂到某个 Agent。
DO $$
DECLARE
    unresolved_count BIGINT;
BEGIN
    SELECT COUNT(*)
    INTO unresolved_count
    FROM agent.agent_conversations
    WHERE agent_id IS NULL;

    IF unresolved_count > 0 THEN
        RAISE EXCEPTION
            '仍有 % 条会话无法从 agent_runs 回填 agent_id，请清理或手动补齐后重新执行',
            unresolved_count;
    END IF;
END
$$;

ALTER TABLE agent.agent_conversations
ALTER COLUMN agent_id SET NOT NULL;

CREATE INDEX IF NOT EXISTS idx_agent_conversations_platform_user_agent
ON agent.agent_conversations(platform_id, external_user_id, agent_id, updated_at DESC);

COMMENT ON COLUMN agent.agent_conversations.agent_id IS
'会话所属 Agent 模板的稳定业务 ID；同一会话不允许跨 Agent 继续执行。';

COMMIT;
