from typing import Any

from langchain_core.messages import AIMessageChunk
from langchain_core.outputs import ChatGenerationChunk
from langchain_openai import ChatOpenAI


class ReasoningChatOpenAI(ChatOpenAI):
    """保留 OpenAI 兼容接口中 reasoning_content 字段的 ChatOpenAI。

    DeepSeek 等思考模型会在 Chat Completions 流式响应里返回
    choices[0].delta.reasoning_content。当前 langchain_openai 的 chat/completions
    转换逻辑不会把这个非标准字段放入 AIMessageChunk，所以平台流式层无法拿到思考过程。

    这里只在 LangChain 完成原有 chunk 转换后，把原始响应中的 reasoning_content
    补充到 message.additional_kwargs，后续仍然沿用 LangChain Agent / LangGraph 的执行流程。
    """

    def _convert_chunk_to_generation_chunk(
        self,
        chunk: dict[str, Any],
        default_chunk_class: type,
        base_generation_info: dict | None,
    ) -> ChatGenerationChunk | None:
        """转换流式 chunk，并保留供应商返回的思考内容。

        Args:
            chunk: OpenAI 兼容接口返回的原始流式分片。
            default_chunk_class: LangChain 当前默认消息分片类型。
            base_generation_info: LangChain 透传的基础生成信息。

        Returns:
            ChatGenerationChunk；没有有效内容时返回 None。
        """
        generation_chunk = super()._convert_chunk_to_generation_chunk(
            chunk,
            default_chunk_class,
            base_generation_info,
        )
        if generation_chunk is None:
            return None

        reasoning_content = self._extract_reasoning_content_from_raw_chunk(chunk)
        if reasoning_content and isinstance(generation_chunk.message, AIMessageChunk):
            # 保留在 additional_kwargs 中，交给 AgentStreamEventParser 输出 reasoning_delta。
            generation_chunk.message.additional_kwargs["reasoning_content"] = reasoning_content

        return generation_chunk

    def _extract_reasoning_content_from_raw_chunk(self, chunk: dict[str, Any]) -> str:
        """从原始 OpenAI 兼容流式 chunk 中提取 reasoning_content。

        Args:
            chunk: OpenAI 兼容接口返回的原始流式分片。

        Returns:
            当前分片携带的思考文本；不存在时返回空字符串。
        """
        choices = chunk.get("choices") or chunk.get("chunk", {}).get("choices") or []
        if not choices:
            return ""

        delta = choices[0].get("delta") or {}
        reasoning_content = delta.get("reasoning_content")
        return reasoning_content if isinstance(reasoning_content, str) else ""
