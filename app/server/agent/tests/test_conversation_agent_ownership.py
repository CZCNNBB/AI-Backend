import unittest
from datetime import datetime
from unittest.mock import MagicMock

from app.common.core.exceptions import BusinessException
from app.server.agent.src.context.models import AgentConversation
from app.server.agent.src.context.schemas import AgentConversationSearchRequest
from app.server.agent.src.context.service import AgentContextService


class ConversationAgentOwnershipTestCase(unittest.TestCase):
    """验证 Agent 会话的 Agent 归属和列表过滤规则。"""

    def test_existing_conversation_rejects_different_agent(self) -> None:
        """已有会话不能更换 Agent 后继续执行。"""
        repository = MagicMock()
        repository.get_conversation.return_value = AgentConversation(
            conversation_id="conv-1",
            platform_id=1,
            external_user_id="user-1",
            agent_id="agent-a",
            title="测试会话",
        )
        service = AgentContextService(repository=repository)

        with self.assertRaises(BusinessException) as error_context:
            service.ensure_conversation(
                MagicMock(),
                platform_id=1,
                external_user_id="user-1",
                agent_id="agent-b",
                conversation_id="conv-1",
            )

        self.assertEqual(error_context.exception.code, 409)
        self.assertIn("属于 Agent agent-a", error_context.exception.msg)
        repository.touch_conversation.assert_not_called()

    def test_search_conversations_filters_and_returns_agent_id(self) -> None:
        """会话列表应按 Agent ID 查询，并在返回视图中保留 Agent ID。"""
        repository = MagicMock()
        repository.list_conversations.return_value = (
            [
                AgentConversation(
                    conversation_id="conv-1",
                    platform_id=1,
                    external_user_id="user-1",
                    agent_id="agent-a",
                    title="测试会话",
                    created_at=datetime(2026, 8, 27, 10, 0, 0),
                    updated_at=datetime(2026, 8, 27, 11, 0, 0),
                )
            ],
            1,
        )
        service = AgentContextService(repository=repository)

        response = service.search_conversations(
            MagicMock(),
            platform_id=1,
            request=AgentConversationSearchRequest(
                external_user_id="user-1",
                agent_id="agent-a",
                page=1,
                page_size=20,
            ),
        )

        repository.list_conversations.assert_called_once_with(
            unittest.mock.ANY,
            platform_id=1,
            external_user_id="user-1",
            agent_id="agent-a",
            conversation_id=None,
            page=1,
            page_size=20,
        )
        self.assertEqual(response.items[0].agent_id, "agent-a")


if __name__ == "__main__":
    unittest.main()
