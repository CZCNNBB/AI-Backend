import json
import logging
from typing import Any


logger = logging.getLogger("ai_backend.agent.streaming")


class AgentStreamEventParser:
    """Agent 流式消息解析器。

    该类只负责把 LangGraph messages 流分片转换为平台 SSE 事件，
    不关心 Agent 运行、数据库写入、会话持久化等业务流程。
    """

    def normalize_message_stream_chunk(self, chunk: Any, suppress_sub_agent: bool = True) -> list[dict[str, Any]]:
        """将 LangGraph messages 流分片转换为平台 SSE 事件。

        Args:
            chunk: agent.astream(stream_mode="messages") 产出的分片，通常是 (message, metadata)。
            suppress_sub_agent: 是否过滤 A2A 子 Agent 冒泡出来的裸 messages 分片。

        Returns:
            可序列化的平台事件列表。一个消息分片可能同时包含思考、正文和工具调用。
        """
        message, metadata = self.unpack_message_stream_chunk(chunk)
        if message is None:
            return []

        metadata_dict = self.to_metadata_dict(metadata)
        self.log_stream_metadata_summary(message, metadata_dict)
        if suppress_sub_agent and self.is_sub_agent_stream_metadata(metadata_dict):
            logger.debug("过滤裸子 Agent 流式分片: metadata=%s", metadata_dict)
            return []
        if self.is_summarization_stream_metadata(metadata_dict) or self.is_summarization_message(message):
            logger.debug("过滤会话总结内部流式分片: metadata=%s", metadata_dict)
            return []

        self.log_raw_stream_chunk(message, metadata)

        events: list[dict[str, Any]] = []

        # ToolMessage 是工具执行完成后的返回结果，不是模型自然语言输出。
        # 如果把它当成 model_delta，前端会误以为工具 JSON 是 Agent 正文。
        if self.is_tool_message(message):
            tool_result = self.extract_tool_result(message)
            if tool_result is not None:
                events.append({
                    "type": "tool_result",
                    "data": {
                        **tool_result,
                        "metadata": self.safe_event_value(metadata),
                    },
                })
            return events

        reasoning = self.extract_reasoning_text(message)
        content = self.extract_message_text(message)

        if reasoning:
            events.append({"type": "reasoning_delta", "data": {"content": reasoning}})
        else:
            self.log_reasoning_debug(message)
        if content:
            events.append({"type": "model_delta", "data": {"content": content}})

        for tool_call in self.extract_tool_calls(message):
            events.append({
                "type": "tool_call",
                "data": {
                    "tool_name": tool_call.get("name") or tool_call.get("tool_name") or "tool",
                    "args": self.safe_event_value(tool_call.get("args") or tool_call.get("input") or {}),
                    "id": tool_call.get("id"),
                    "metadata": self.safe_event_value(metadata),
                },
            })
        return events

    def unpack_message_stream_chunk(self, chunk: Any) -> tuple[Any, Any]:
        """解析 messages 流分片，兼容 tuple、list 和 dict 形态。

        Args:
            chunk: LangGraph messages 流返回的原始分片。

        Returns:
            (message, metadata) 二元组；无法解析时 metadata 返回 None。
        """
        if isinstance(chunk, tuple) and chunk:
            message = chunk[0]
            metadata = chunk[1] if len(chunk) > 1 else None
            return message, metadata
        if isinstance(chunk, list) and chunk:
            message = chunk[0]
            metadata = chunk[1] if len(chunk) > 1 else None
            return message, metadata
        if isinstance(chunk, dict):
            return chunk.get("message") or chunk.get("chunk") or chunk.get("messages"), chunk.get("metadata")
        return chunk, None

    def log_stream_metadata_summary(self, message: Any, metadata: Any) -> None:
        """在 DEBUG 级别打印流式分片 metadata 摘要，辅助区分主 Agent 与子 Agent。

        Args:
            message: LangGraph messages 流返回的消息对象。
            metadata: LangGraph messages 流返回的元数据。
        """
        if not logger.isEnabledFor(logging.DEBUG):
            return

        metadata_dict = self.to_metadata_dict(metadata)
        summary = {
            "message_class": message.__class__.__name__,
            "message_type": getattr(message, "type", None),
            "metadata_keys": sorted(metadata_dict.keys()),
            "thread_id": metadata_dict.get("thread_id"),
            "agent_thread_id": metadata_dict.get("agent_thread_id"),
            "agent_run_id": metadata_dict.get("agent_run_id"),
            "stream_scope": metadata_dict.get("_stream_scope"),
            "sub_run_id": metadata_dict.get("_sub_run_id"),
            "sub_agent_id": metadata_dict.get("_sub_agent_id"),
            "parent_run_id": metadata_dict.get("_parent_run_id"),
            "langgraph_node": metadata_dict.get("langgraph_node"),
            "langgraph_step": metadata_dict.get("langgraph_step"),
            "ls_model_name": metadata_dict.get("ls_model_name"),
            "checkpoint_ns": metadata_dict.get("checkpoint_ns"),
        }
        logger.debug("流式 metadata 诊断: %s", summary)

    def is_summarization_message(self, message: Any) -> bool:
        """判断消息对象是否为总结中间件写回的内部摘要消息。"""
        additional_kwargs = getattr(message, "additional_kwargs", None) or {}
        response_metadata = getattr(message, "response_metadata", None) or {}
        return (
            additional_kwargs.get("lc_source") == "summarization"
            or response_metadata.get("lc_source") == "summarization"
        )

    def is_summarization_stream_metadata(self, metadata: dict[str, Any]) -> bool:
        """判断当前分片是否属于会话总结模型的内部输出。"""
        tags = metadata.get("tags") or []
        return metadata.get("lc_source") == "summarization" or "nostream" in tags

    def is_sub_agent_stream_metadata(self, metadata: dict[str, Any]) -> bool:
        """判断当前 metadata 是否属于 A2A 子 Agent 的裸流式分片。

        Args:
            metadata: LangGraph messages 流分片 metadata。

        Returns:
            属于子 Agent 冒泡事件时返回 True。
        """
        return metadata.get("_stream_scope") == "sub_agent"

    def to_metadata_dict(self, metadata: Any) -> dict[str, Any]:
        """把 LangGraph metadata 转换成普通字典，便于日志摘要读取。

        Args:
            metadata: LangGraph messages 流分片携带的元数据。

        Returns:
            普通字典；无法转换时返回空字典。
        """
        if metadata is None:
            return {}
        if hasattr(metadata, "model_dump"):
            metadata = metadata.model_dump()
        return metadata if isinstance(metadata, dict) else {}

    def log_raw_stream_chunk(self, message: Any, metadata: Any) -> None:
        """在 DEBUG 级别打印 LangGraph messages 原始分片。

        Args:
            message: LangGraph messages 流返回的消息对象。
            metadata: LangGraph messages 流返回的元数据。
        """
        if not logger.isEnabledFor(logging.DEBUG):
            return

        safe_message = self.safe_event_value(message)
        safe_metadata = self.safe_event_value(metadata)
        logger.debug(
            "原始流式分片: message_class=%s message_type=%s message=%s metadata=%s",
            message.__class__.__name__,
            getattr(message, "type", None),
            safe_message,
            safe_metadata,
        )


    def log_reasoning_debug(self, message: Any) -> None:
        """在调试级别记录消息分片中的 reasoning 相关字段位置。

        Args:
            message: LangChain 消息对象或消息分片。
        """
        if not logger.isEnabledFor(logging.DEBUG):
            return
        additional_kwargs = getattr(message, "additional_kwargs", {}) or {}
        response_metadata = getattr(message, "response_metadata", {}) or {}
        content = getattr(message, "content", None)
        logger.debug(
            "流式分片未发现 reasoning: message_type=%s additional_keys=%s metadata_keys=%s content_type=%s",
            message.__class__.__name__,
            sorted(additional_kwargs.keys()),
            sorted(response_metadata.keys()),
            type(content).__name__,
        )

    def is_tool_message(self, message: Any) -> bool:
        """判断当前分片是否为工具返回消息。

        Args:
            message: LangChain 消息对象或消息字典。

        Returns:
            是工具返回消息时返回 True，否则返回 False。
        """
        if isinstance(message, dict):
            return message.get("type") == "tool"
        return getattr(message, "type", None) == "tool" or message.__class__.__name__ == "ToolMessage"

    def extract_tool_result(self, message: Any) -> dict[str, Any] | None:
        """从 ToolMessage 中提取工具返回结果。

        Args:
            message: LangChain ToolMessage 对象或序列化后的消息字典。

        Returns:
            工具结果事件数据；不是工具消息时返回 None。
        """
        if not self.is_tool_message(message):
            return None

        if isinstance(message, dict):
            tool_name = message.get("name")
            tool_call_id = message.get("tool_call_id")
            artifact = message.get("artifact")
            content = message.get("content")
        else:
            tool_name = getattr(message, "name", None)
            tool_call_id = getattr(message, "tool_call_id", None)
            artifact = getattr(message, "artifact", None)
            content = getattr(message, "content", None)

        # MCP / LangChain 工具可能把结构化结果放在 artifact.structured_content。
        # 优先返回结构化内容，方便前端调试面板直接渲染；没有时再退回 content 文本。
        output = None
        if isinstance(artifact, dict):
            output = artifact.get("structured_content") or artifact.get("data") or artifact
        if output is None:
            output = self.extract_content_value(content)

        return {
            "tool_name": tool_name or "tool",
            "tool_call_id": tool_call_id,
            "output": self.safe_event_value(output),
        }

    def extract_tool_calls(self, message: Any) -> list[dict[str, Any]]:
        """从消息分片中提取模型发出的完整工具调用。

        Args:
            message: LangChain 消息对象或消息分片。

        Returns:
            工具调用字典列表；没有完整工具调用时返回空列表。
        """
        raw_candidates: list[Any] = []
        if isinstance(message, dict):
            raw_candidates.extend(message.get("tool_calls") or [])
            additional_kwargs = message.get("additional_kwargs") or {}
        else:
            raw_candidates.extend(getattr(message, "tool_calls", None) or [])
            additional_kwargs = getattr(message, "additional_kwargs", {}) or {}

        raw_candidates.extend(additional_kwargs.get("tool_calls") or [])

        tool_calls: list[dict[str, Any]] = []
        seen_keys: set[tuple[str | None, str, str]] = set()
        for item in raw_candidates:
            normalized = self.normalize_tool_call(item)
            if normalized is None:
                continue
            # 同一个工具调用可能同时出现在 message.tool_calls 和 additional_kwargs.tool_calls，按稳定 key 去重。
            dedupe_key = (normalized.get("id"), str(normalized.get("name")), str(normalized.get("args")))
            if dedupe_key in seen_keys:
                continue
            seen_keys.add(dedupe_key)
            tool_calls.append(normalized)
        return tool_calls

    def normalize_tool_call(self, item: Any) -> dict[str, Any] | None:
        """把 LangChain 工具调用对象归一化为前端可展示的完整工具调用。

        Args:
            item: LangChain 返回的工具调用字典。

        Returns:
            完整工具调用字典；如果只是 tool_call_chunks 参数碎片则返回 None。
        """
        if not isinstance(item, dict):
            return None

        name = item.get("name") or item.get("tool_name")
        args = item.get("args") if "args" in item else item.get("input")
        call_id = item.get("id")

        # tool_call_chunks 的 args 常常是字符串碎片，例如 "{", "\"name\": ..."。
        # 这类内容不是完整工具调用，前端不应该展示为工具卡片。
        if not isinstance(name, str) or not name.strip() or name == "tool":
            return None
        if args is None:
            args = {}
        if not isinstance(args, dict):
            return None

        return {
            "name": name.strip(),
            "args": args,
            "id": call_id,
        }

    def extract_message_text(self, message: Any) -> str:
        """从模型消息或消息分片中提取普通文本。

        Args:
            message: LangChain 消息对象、消息分片或原生字符串。

        Returns:
            提取出的文本；没有文本时返回空字符串。
        """
        if message is None:
            return ""
        if isinstance(message, str):
            return message

        if isinstance(message, dict):
            content = message.get("content", "")
        else:
            content = getattr(message, "content", "")
        return self.extract_content_text(content)

    def extract_content_text(self, content: Any) -> str:
        """从 LangChain content 字段中提取可展示文本。

        Args:
            content: 消息 content，可能是字符串或内容块列表。

        Returns:
            拼接后的文本内容；没有文本时返回空字符串。
        """
        value = self.extract_content_value(content)
        return value if isinstance(value, str) else ""

    def extract_content_value(self, content: Any) -> Any:
        """从 LangChain content 字段中提取原始值。

        Args:
            content: 消息 content，可能是字符串或内容块列表。

        Returns:
            字符串、列表或字典形式的内容值。
        """
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            parts: list[str] = []
            values: list[Any] = []
            for item in content:
                if isinstance(item, str):
                    parts.append(item)
                    continue
                if isinstance(item, dict) and item.get("type") in {"text", "output_text"}:
                    text = item.get("text") or item.get("content") or ""
                    parts.append(str(text))
                    values.append(item)
            if parts:
                return "".join(parts)
            return values or content
        return content

    def extract_reasoning_text(self, message: Any) -> str:
        """从模型消息分片中提取供应商返回的思考内容。

        Args:
            message: LangChain 消息对象或消息分片。

        Returns:
            模型供应商显式返回的 reasoning 文本；不支持时返回空字符串。
        """
        if message is None:
            return ""

        if isinstance(message, dict):
            additional_kwargs = message.get("additional_kwargs") or {}
            response_metadata = message.get("response_metadata") or {}
            content = message.get("content")
        else:
            additional_kwargs = getattr(message, "additional_kwargs", {}) or {}
            response_metadata = getattr(message, "response_metadata", {}) or {}
            content = getattr(message, "content", None)

        # DeepSeek 等 OpenAI 兼容思考模型一般把思考内容放在 reasoning_content。
        # 其他供应商可能使用 reasoning / reasoning_text，这里一并兼容。
        for source in (message if isinstance(message, dict) else {}, additional_kwargs, response_metadata):
            if not isinstance(source, dict):
                continue
            for key in ("reasoning_content", "reasoning", "reasoning_text"):
                value = source.get(key)
                if isinstance(value, str) and value:
                    return value

        if isinstance(content, list):
            parts: list[str] = []
            for item in content:
                if isinstance(item, dict) and item.get("type") in {"reasoning", "thinking"}:
                    parts.append(str(item.get("text") or item.get("content") or ""))
            return "".join(parts)
        return ""

    def extract_task_plan_event(
        self,
        chunk: Any,
        run_id: str,
        thread_id: str,
    ) -> dict[str, Any] | None:
        """从 LangGraph updates 分片中提取 task_plan 更新事件。

        Args:
            chunk: LangGraph updates 模式返回的分片。
            run_id: 当前 Agent 运行 ID。
            thread_id: 当前 LangGraph thread ID。

        Returns:
            可直接返回给前端的 task_plan 事件；没有任务计划更新时返回 None。
        """
        task_plan = self.find_state_value(chunk, "task_plan")
        if not isinstance(task_plan, dict):
            return None

        return {
            "type": "task_plan",
            "data": {
                "run_id": run_id,
                "thread_id": thread_id,
                "task_plan": self.safe_event_value(task_plan),
            },
        }

    def extract_interrupt_event(
        self,
        chunk: Any,
        run_id: str,
        thread_id: str,
    ) -> dict[str, Any] | None:
        """从 LangGraph updates 分片中提取 interrupt 事件。

        Args:
            chunk: LangGraph updates 模式返回的分片。
            run_id: 当前 Agent 运行 ID。
            thread_id: 当前 LangGraph thread ID。

        Returns:
            可直接返回给前端的 interrupt 事件；没有中断时返回 None。
        """
        if not isinstance(chunk, dict):
            return None
        interrupts = chunk.get("__interrupt__")
        if not interrupts:
            return None

        first_interrupt = interrupts[0] if isinstance(interrupts, (list, tuple)) else interrupts
        if isinstance(first_interrupt, dict) and "value" in first_interrupt:
            payload = first_interrupt.get("value")
        else:
            payload = getattr(first_interrupt, "value", first_interrupt)
        safe_payload = self.safe_event_value(payload)
        if not isinstance(safe_payload, dict):
            safe_payload = {"type": "unknown", "data": {"value": safe_payload}}

        return {
            "type": "interrupt",
            "data": {
                "run_id": run_id,
                "thread_id": thread_id,
                "payload": safe_payload,
            },
        }


    def extract_interrupt_event_from_error(
        self,
        error: BaseException,
        run_id: str,
        thread_id: str,
    ) -> dict[str, Any] | None:
        """从 GraphInterrupt 异常中提取 interrupt 事件。

        Args:
            error: LangGraph 抛出的 GraphInterrupt 异常。
            run_id: 当前 Agent 运行 ID。
            thread_id: 当前 LangGraph thread ID。

        Returns:
            可直接返回给前端的 interrupt 事件；无法提取时返回 None。
        """
        interrupts = error.args[0] if getattr(error, "args", None) else None
        if not interrupts:
            return None

        first_interrupt = interrupts[0] if isinstance(interrupts, (list, tuple)) else interrupts
        payload = getattr(first_interrupt, "value", first_interrupt)
        safe_payload = self.safe_event_value(payload)
        if not isinstance(safe_payload, dict):
            safe_payload = {"type": "unknown", "data": {"value": safe_payload}}

        return {
            "type": "interrupt",
            "data": {
                "run_id": run_id,
                "thread_id": thread_id,
                "payload": safe_payload,
            },
        }

    def extract_task_plan_event_from_interrupt(
        self,
        interrupt_event: dict[str, Any] | None,
        run_id: str,
        thread_id: str,
    ) -> dict[str, Any] | None:
        """从 interrupt payload 中兜底提取 task_plan 事件。

        Args:
            interrupt_event: 已归一化的 interrupt 事件。
            run_id: 当前 Agent 运行 ID。
            thread_id: 当前 LangGraph thread ID。

        Returns:
            可直接返回给前端的 task_plan 事件；payload 中没有任务计划时返回 None。
        """
        if not isinstance(interrupt_event, dict):
            return None
        data = interrupt_event.get("data")
        if not isinstance(data, dict):
            return None
        payload = data.get("payload")
        if not isinstance(payload, dict):
            return None
        payload_data = payload.get("data")
        if not isinstance(payload_data, dict):
            return None
        task_plan = payload_data.get("task_plan")
        if not isinstance(task_plan, dict):
            return None

        return {
            "type": "task_plan",
            "data": {
                "run_id": run_id,
                "thread_id": thread_id,
                "task_plan": self.safe_event_value(task_plan),
            },
        }

    def find_state_value(self, value: Any, state_key: str) -> Any | None:
        """在 updates 分片中递归查找指定 state 字段。

        Args:
            value: LangGraph updates 原始分片或其子节点。
            state_key: 需要查找的 state 字段名。

        Returns:
            找到的 state 字段值；不存在时返回 None。
        """
        if isinstance(value, dict):
            if state_key in value:
                return value.get(state_key)
            for child_key, child_value in value.items():
                # __interrupt__ 不是普通 state 更新，避免从中断 payload 里误提取 task_plan。
                if child_key == "__interrupt__":
                    continue
                found = self.find_state_value(child_value, state_key)
                if found is not None:
                    return found
        if isinstance(value, (list, tuple)):
            for child_value in value:
                found = self.find_state_value(child_value, state_key)
                if found is not None:
                    return found
        return None

    def build_stable_signature(self, value: Any) -> str:
        """为流式 state 值构建稳定签名，用于本轮内去重。

        Args:
            value: 任意 state 值。

        Returns:
            JSON 字符串签名；遇到不可 JSON 化对象时会先安全转换。
        """
        safe_value = self.safe_event_value(value)
        return json.dumps(safe_value, ensure_ascii=False, sort_keys=True, default=str)

    @staticmethod
    def safe_event_value(obj: Any) -> Any:
        """把 LangChain 内部对象转换为安全的 JSON 值。

        Args:
            obj: 任意 LangChain 对象、Pydantic 模型或 Python 原生值。

        Returns:
            可被 jsonable_encoder / json.dumps 处理的值。
        """
        if obj is None or isinstance(obj, (str, int, float, bool)):
            return obj
        if isinstance(obj, dict):
            return {k: AgentStreamEventParser.safe_event_value(v) for k, v in obj.items()}
        if isinstance(obj, (list, tuple)):
            return [AgentStreamEventParser.safe_event_value(v) for v in obj]
        if hasattr(obj, "model_dump"):
            return AgentStreamEventParser.safe_event_value(obj.model_dump())
        if hasattr(obj, "dict") and callable(obj.dict):
            return AgentStreamEventParser.safe_event_value(obj.dict())
        return str(obj)
