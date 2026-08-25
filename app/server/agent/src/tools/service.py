import inspect
import logging
from typing import Any

from sqlmodel import Session

from app.common.core.exceptions import BusinessException
from app.server.agent.src.mcp import MCPService
from app.server.agent.src.tools.a2a_tool import a2a_call
from app.server.agent.src.tools.base import AgentToolDefinition
from app.server.agent.src.tools.file_tools import read_uploaded_file
from app.server.agent.src.tools.knowledge_tools import search_knowledge_base
from app.server.agent.src.tools.planning_tools import set_task_plan, update_task_step
from app.server.agent.src.tools.registry import AgentToolRegistry
from app.server.agent.src.tools.schemas import AgentToolInfo

logger = logging.getLogger("ai_backend.agent.tools")


class AgentToolService:
    """Agent 工具服务，负责系统内置能力工具、MCP 外接工具和工具调试调用。"""

    def __init__(self, registry: AgentToolRegistry | None = None, mcp_service: MCPService | None = None):
        """初始化 Agent 工具服务。

        Args:
            registry: 可选工具注册表；不传时使用默认注册表。
            mcp_service: MCP 工具服务；不传时使用默认服务。
        """
        self.registry = registry or AgentToolRegistry()
        self.mcp_service = mcp_service or MCPService()
        if registry is None:
            self._register_builtin_tools()

    def _register_builtin_tools(self) -> None:
        """注册 AI-backend 内部工具。

        规划工具属于内部动态工具：
        - 工具管理页可以展示它们的参数和说明。
        - 真正运行时由 optional_features.planning_enabled 自动注入。
        - 因为依赖 LangGraph ToolRuntime.state，不允许在工具测试页直接调用。
        """
        self.registry.register(AgentToolDefinition(
            name=set_task_plan.name,
            description=set_task_plan.description or "创建或重写任务计划草稿，并触发用户确认。",
            callable_ref=set_task_plan,
        ))
        self.registry.register(AgentToolDefinition(
            name=update_task_step.name,
            description=update_task_step.description or "更新运行中任务计划的单个步骤。",
            callable_ref=update_task_step,
        ))
        self.registry.register(AgentToolDefinition(
            name=read_uploaded_file.name,
            description=read_uploaded_file.description or "读取本次请求中用户上传的单个文件内容。",
            callable_ref=read_uploaded_file,
        ))
        self.registry.register(AgentToolDefinition(
            name=search_knowledge_base.name,
            description=search_knowledge_base.description or "检索本次 Agent 已挂载的知识库。",
            callable_ref=search_knowledge_base,
        ))

    def _build_args_schema(self, tool: Any) -> dict[str, Any]:
        """提取工具暴露给模型的参数 JSON Schema。

        Args:
            tool: LangChain tool 或兼容的可调用工具对象。

        Returns:
            工具参数 JSON Schema；无法提取时返回空字典。
        """
        # LangChain tool.args 通常已经过滤掉 ToolRuntime 等注入参数，优先使用它给前端展示。
        args = getattr(tool, "args", None)
        if isinstance(args, dict):
            return args

        args_schema = getattr(tool, "args_schema", None)
        if args_schema is not None and hasattr(args_schema, "model_json_schema"):
            try:
                return args_schema.model_json_schema()
            except Exception as error:  # noqa: BLE001
                logger.warning("工具参数 schema 构建失败: name=%s error=%s", getattr(tool, "name", "unknown"), error)
        return {}

    def _to_tool_info(self, definition) -> AgentToolInfo:
        """把内部工具定义转换为前端展示结构。

        Args:
            definition: 注册中心中的工具定义。

        Returns:
            工具管理页展示使用的 AgentToolInfo。
        """
        is_planning_tool = definition.name in {set_task_plan.name, update_task_step.name}
        is_file_tool = definition.name == read_uploaded_file.name
        is_knowledge_tool = definition.name == search_knowledge_base.name
        return AgentToolInfo(
            name=definition.name,
            description=definition.description,
            group=(
                "planning"
                if is_planning_tool
                else "file"
                if is_file_tool
                else "knowledge"
                if is_knowledge_tool
                else "internal"
            ),
            invokable=False,
            template_selectable=False,
            activation_mode="feature",
            invoke_note=(
                "规划工具是系统内置能力，只能通过 planning_enabled 自动启用，不能配置到模板 tools。"
                if is_planning_tool
                else "附件读取工具会在 file_ids 非空时自动启用，不能配置到模板 tools，也不能在工具测试页直接调用。"
                if is_file_tool
                else "知识库检索工具由模板 knowledge_enabled 和本次调用 knowledge 白名单共同启用，不能配置到模板 tools。"
                if is_knowledge_tool
                else "内置工具由系统能力开关自动挂载，不能配置到模板 tools。"
            ),
            args_schema=self._build_args_schema(definition.callable_ref),
        )

    def _build_a2a_tool_info(self) -> AgentToolInfo:
        """构建动态 A2A 工具的前端展示信息。

        Returns:
            A2A 工具元数据。该工具依赖运行时 a2a.sub_agent_list，不能在工具管理页直接测试。
        """
        return AgentToolInfo(
            name=a2a_call.name,
            description=a2a_call.description,
            group="a2a",
            invokable=False,
            template_selectable=False,
            activation_mode="feature",
            invoke_note=(
                "a2a_call 是系统内置能力工具，会在 a2a.sub_agent_list 非空时自动挂载，"
                "不能配置到模板 tools，也不能在工具测试页直接调用。"
            ),
            args_schema=self._build_args_schema(a2a_call),
        )

    def list_tools(self) -> list[str]:
        """查询系统内置能力工具名称。

        Returns:
            内置能力工具名称列表。它们仅用于能力说明，不能配置到模板 tools。
        """
        return self.registry.list_tools()

    def get_internal_tool_names(self) -> set[str]:
        """获取不能配置到模板 tools 的系统内置工具名称。

        Returns:
            内置工具名称集合，包括规划工具和 A2A 动态工具。
        """
        return set(self.registry.list_tools()) | {a2a_call.name}

    def list_tool_details(self, include_dynamic: bool = True) -> list[AgentToolInfo]:
        """查询前端可展示的内置工具详情。

        Args:
            include_dynamic: 是否包含 A2A 这类动态工具。

        Returns:
            工具元数据列表。MCP 外部工具请通过 /agent/mcp/search 查询。
        """
        items = [self._to_tool_info(definition) for definition in self.registry.list_definitions()]
        if include_dynamic:
            items.append(self._build_a2a_tool_info())
        return items

    async def get_tools(self, tool_names: list[str] | None = None, db: Session | None = None) -> list[Any]:
        """解析模板配置中的 MCP 外接工具。

        Args:
            tool_names: 模板 tools 白名单。该字段只允许填写 MCP 工具编码；None 或空列表表示不加载外接工具。
            db: 数据库会话；加载 MCP 工具时必须传入或临时打开只读会话。

        Returns:
            可传给 LangChain create_agent 的 MCP 工具对象列表。

        Raises:
            RuntimeError: tools 中包含系统内置工具时抛出，避免模板绕过能力开关直接挂载内置工具。
        """
        if not tool_names:
            return []

        # 模板 tools 只表示外接 MCP 工具。规划、A2A 等内置工具必须通过功能参数自动挂载。
        cleaned_names = [str(name or "").strip() for name in tool_names if str(name or "").strip()]
        internal_names = self.get_internal_tool_names()
        invalid_internal_names = [name for name in cleaned_names if name in internal_names]
        if invalid_internal_names:
            raise RuntimeError(
                "模板 tools 只允许配置 MCP 外接工具，内置工具请通过能力参数启用: "
                + ", ".join(invalid_internal_names)
            )

        # 去重但保留用户配置顺序，便于日志排查。
        mcp_tool_codes = list(dict.fromkeys(cleaned_names))
        if db is not None:
            return await self.mcp_service.load_langchain_tools(db, mcp_tool_codes)

        # A2A 子 Agent 等内部调用场景可能不传 db，此时短暂打开一个
        # 只读会话，仅用于加载 MCP 工具配置，不写业务会话记录。
        from app.common.db.postgres_db import get_db_session

        with get_db_session() as inner_db:
            return await self.mcp_service.load_langchain_tools(inner_db, mcp_tool_codes)

    async def invoke_tool(self, tool_name: str, args: dict[str, Any], db: Session | None = None) -> Any:
        """从工具管理页测试调用一个工具。

        Args:
            tool_name: 工具名称或 MCP 工具编码。
            args: 工具调用参数。
            db: 数据库会话；调试调用 MCP 工具时必须传入。

        Returns:
            工具执行结果。
        """
        cleaned_name = tool_name.strip()
        if cleaned_name == a2a_call.name:
            raise BusinessException(
                code=400,
                msg="a2a_call 是动态工具，需要通过 /agent/run 的 A2A 配置启用，不能直接测试调用。",
            )
        if cleaned_name in {set_task_plan.name, update_task_step.name}:
            raise BusinessException(
                code=400,
                msg="规划工具依赖 LangGraph 运行态，请通过 /agent/run 开启 planning_enabled 后由 Agent 调用。",
            )
        if cleaned_name == read_uploaded_file.name:
            raise BusinessException(
                code=400,
                msg="附件读取工具依赖本次 Agent 运行的 file_ids 白名单，请通过 /agent/messages 携带 file_ids 后由 Agent 调用。",
            )
        if cleaned_name == search_knowledge_base.name:
            raise BusinessException(
                code=400,
                msg="知识库检索工具依赖模板 knowledge_enabled 和本次调用的 knowledge.knowledge_base_ids。",
            )
        if not self.registry.has_tool(cleaned_name):
            if db is None:
                raise BusinessException(code=404, msg=f"工具不存在或未注册: {cleaned_name}")
            try:
                mcp_tools = await self.mcp_service.load_langchain_tools(db, [cleaned_name])
            except RuntimeError as error:
                raise BusinessException(code=404, msg=str(error)) from error
            if not mcp_tools:
                raise BusinessException(code=404, msg=f"工具不存在或未注册: {cleaned_name}")
            return await mcp_tools[0].ainvoke(args)

        tool = self.registry.get_tool(cleaned_name)
        if hasattr(tool, "ainvoke"):
            return await tool.ainvoke(args)
        if hasattr(tool, "invoke"):
            result = tool.invoke(args)
            if inspect.isawaitable(result):
                return await result
            return result
        if callable(tool):
            result = tool(**args)
            if inspect.isawaitable(result):
                return await result
            return result
        raise BusinessException(code=400, msg=f"工具不可调用: {cleaned_name}")
