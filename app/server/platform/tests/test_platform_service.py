"""业务平台 API Key、资源绑定和 Agent 归属规则测试。"""

import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock

from app.common.core.exceptions import BusinessException
from app.server.agent.src.runtime.service import AgentRuntimeContextService
from app.server.agent.src.schemas.request import AgentRunRequest
from app.server.platform.src.security import generate_platform_api_key, hash_platform_api_key
from app.server.platform.src.schemas import (
    AgentPlatformAccessRequest,
    BusinessPlatformAPIKeyCreateRequest,
    BusinessPlatformAPIKeyListRequest,
)
from app.server.platform.src.service import BusinessPlatformService


class BusinessPlatformSecurityTestCase(unittest.TestCase):
    """验证平台 API Key 与资源平台集合的核心安全规则。"""

    def test_generated_api_key_has_prefix_and_stable_hash(self) -> None:
        """完整平台 API Key 应具备前缀，数据库摘要不应包含明文。"""
        api_key, key_prefix = generate_platform_api_key()
        key_hash = hash_platform_api_key(api_key)

        self.assertTrue(api_key.startswith(f"{key_prefix}_"))
        self.assertEqual(len(key_hash), 64)
        self.assertNotIn(api_key, key_hash)

    def test_created_api_key_keeps_plaintext_for_internal_management(self) -> None:
        """内网模式签发 API Key 时应同时保存明文和鉴权 Hash。"""
        repository = MagicMock()
        repository.get_platform_by_code.return_value = SimpleNamespace(
            id=7,
            platform_code="erp",
            platform_name="ERP",
            status="enabled",
        )
        repository.get_api_key_by_name.return_value = None

        def save_api_key(_db, api_key_record):
            """模拟 Repository 保存后补齐数据库主键。"""
            api_key_record.id = 19
            return api_key_record

        repository.save_api_key.side_effect = save_api_key
        service = BusinessPlatformService(repository=repository)

        response = service.create_api_key(
            MagicMock(),
            BusinessPlatformAPIKeyCreateRequest(platform_code="erp", key_name="default"),
        )
        saved_record = repository.save_api_key.call_args.args[1]

        self.assertEqual(saved_record.api_key, response.api_key)
        self.assertEqual(saved_record.key_hash, hash_platform_api_key(response.api_key))

    def test_agent_access_options_return_platform_plaintext_key(self) -> None:
        """Agent 调试选项应返回关联平台最近可用的明文 API Key。"""
        repository = MagicMock()
        repository.list_platforms_for_agent.return_value = [
            SimpleNamespace(id=7, platform_code="erp", platform_name="ERP")
        ]
        repository.get_default_api_key_for_platform.return_value = SimpleNamespace(
            id=19,
            key_name="default",
            api_key="aik_internal_test",
        )
        service = BusinessPlatformService(repository=repository)

        options = service.list_agent_platform_access_options(
            MagicMock(),
            AgentPlatformAccessRequest(agent_id="erp-agent"),
        )

        self.assertEqual(len(options), 1)
        self.assertEqual(options[0].platform_id, 7)
        self.assertEqual(options[0].api_key, "aik_internal_test")

    def test_api_key_list_returns_plaintext_for_internal_management(self) -> None:
        """内网平台 Key 列表应返回可复制的完整明文。"""
        repository = MagicMock()
        repository.get_platform_by_code.return_value = SimpleNamespace(id=7)
        repository.list_api_keys_for_platform.return_value = [
            SimpleNamespace(
                id=19,
                platform_id=7,
                key_name="production",
                key_prefix="aik_abcd",
                api_key="aik_abcd_complete_key",
                status="enabled",
                expires_at=None,
                created_at=None,
                updated_at=None,
            )
        ]
        service = BusinessPlatformService(repository=repository)

        api_keys = service.list_api_keys(
            MagicMock(),
            BusinessPlatformAPIKeyListRequest(platform_code="erp"),
        )

        self.assertEqual(len(api_keys), 1)
        self.assertEqual(api_keys[0].api_key, "aik_abcd_complete_key")

    def test_agent_tool_platforms_require_complete_coverage(self) -> None:
        """Agent 的每个平台都必须包含在每一个已选 MCP Tool 的绑定集合中。"""
        repository = MagicMock()
        repository.get_tool_platform_ids_by_names.return_value = {
            "shared_tool": {1, 2},
            "platform_one_tool": {1},
        }
        service = BusinessPlatformService(repository=repository)

        service.validate_agent_tool_platforms(
            MagicMock(),
            platform_ids=[1, 2],
            tool_names=["shared_tool"],
        )
        with self.assertRaises(BusinessException):
            service.validate_agent_tool_platforms(
                MagicMock(),
                platform_ids=[1, 2],
                tool_names=["platform_one_tool"],
            )

    def test_rejects_deleting_tool_used_by_agent(self) -> None:
        """仍被 Agent 模板引用的 MCP Tool 不允许直接删除。"""
        repository = MagicMock()
        repository.list_agent_templates_using_tool.return_value = [
            SimpleNamespace(agent_id="customer-service-agent")
        ]
        service = BusinessPlatformService(repository=repository)

        with self.assertRaises(BusinessException) as exception_context:
            service.validate_tools_can_be_deleted(MagicMock(), ["query_order"])

        self.assertIn("query_order", exception_context.exception.msg)
        self.assertIn("customer-service-agent", exception_context.exception.msg)

    def test_checkpoint_thread_id_contains_platform_user_and_conversation(self) -> None:
        """持久会话的内部 Checkpoint thread_id 必须包含完整租户命名空间。"""
        request = AgentRunRequest(
            platform_id=12,
            external_user_id="user-10086",
            query="测试",
            conversation_id="conv-001",
        )

        context = AgentRuntimeContextService().build_context(request)

        self.assertEqual(context.thread_id, "conv-001")
        self.assertEqual(
            context.checkpoint_thread_id,
            "platform:12:user:user-10086:conversation:conv-001",
        )


if __name__ == "__main__":
    unittest.main()
