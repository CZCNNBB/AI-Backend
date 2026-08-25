import logging
from typing import Any

from langchain.agents.middleware import AgentMiddleware
from langgraph.types import interrupt
from typing_extensions import NotRequired

from app.server.agent.src.graph.state import CareerAgentState

logger = logging.getLogger(__name__)


class InterruptState(CareerAgentState, total=False):
    """通用中断中间件使用的 LangGraph state 扩展。

    interrupt_enabled 和 interrupt_payload 由工具或业务中间件写入。
    InterruptMiddleware 只负责触发中断，并把用户通过 resume 传回的数据规范化为 resume_value。
    """

    # 是否触发中断；这是控制信号，不和 payload 混在一起。
    interrupt_enabled: NotRequired[bool]

    # 中断时返回给前端的内容；固定外层格式为 {"type": str, "data": dict}。
    interrupt_payload: NotRequired[dict[str, Any] | None]

    # 用户通过 /agent/resume 传回的内容；固定外层格式为 {"type": str, "data": dict}。
    resume_value: NotRequired[dict[str, Any] | None]


class InterruptMiddleware(AgentMiddleware[InterruptState]):
    """通用中断中间件。

    该中间件不理解任何业务语义，只负责：
    1. 检测 interrupt_enabled。
    2. 调用 LangGraph interrupt(interrupt_payload)。
    3. 在恢复后把用户返回值写入 resume_value。
    4. 清理 interrupt_enabled / interrupt_payload。
    """

    state_schema = InterruptState

    def before_model(self, state: InterruptState, runtime: Any) -> dict[str, Any] | None:
        """在每次模型调用前检查是否需要中断（同步版）。

        Args:
            state: 当前 LangGraph state。
            runtime: LangGraph runtime，本中间件暂不读取 runtime。

        Returns:
            不中断时返回 None；恢复后返回需要写入 state 的更新字段。
        """
        if not state.get("interrupt_enabled"):
            return None

        payload = self._normalize_interrupt_payload(state.get("interrupt_payload"))
        logger.info("Agent 触发中断: type=%s", payload.get("type"))

        # 第一次运行到这里时 interrupt 会暂停图执行；
        # 用户通过 Command(resume=...) 恢复后，该函数会重新执行，并从这里拿到 raw_resume_value。
        raw_resume_value = interrupt(payload)
        resume_value = self._normalize_resume_value(payload, raw_resume_value)

        return {
            "interrupt_enabled": False,
            "interrupt_payload": None,
            "resume_value": resume_value,
        }

    async def abefore_model(self, state: InterruptState, runtime: Any) -> dict[str, Any] | None:
        """在每次模型调用前检查是否需要中断（异步版）。

        LangGraph 在 astream/ainvoke 等异步上下文中会优先调用 abefore_model。
        当前实现直接委托给同步版，避免维护两套逻辑。
        """
        return self.before_model(state, runtime)

    def _normalize_interrupt_payload(self, payload: object) -> dict[str, Any]:
        """规范化中断 payload，保证传给前端的是 {type, data} 结构。

        Args:
            payload: 工具或业务中间件写入 state 的原始 interrupt_payload。

        Returns:
            标准中断 payload。缺失 type 时使用 unknown。
        """
        if not isinstance(payload, dict):
            return {"type": "unknown", "data": {}}

        interrupt_type = str(payload.get("type") or "unknown")
        data = payload.get("data")
        return {
            "type": interrupt_type,
            "data": data if isinstance(data, dict) else {},
        }

    def _normalize_resume_value(self, payload: dict[str, Any], raw_resume_value: object) -> dict[str, Any]:
        """规范化用户恢复值，保证业务中间件只消费 {type, data}。

        Args:
            payload: 本次中断发给前端的标准 payload。
            raw_resume_value: /agent/resume 通过 Command(resume=...) 传回的原始值。

        Returns:
            标准 resume_value。type 优先沿用本次 interrupt_payload.type，避免前端传错 type 导致业务错路由。
        """
        payload_type = str(payload.get("type") or "unknown")
        if not isinstance(raw_resume_value, dict):
            return {"type": payload_type, "data": {"value": raw_resume_value}}

        # 兼容未来 API 层直接把 {resume_value: {...}} 作为 Command(resume=...) 传入的情况。
        candidate = raw_resume_value.get("resume_value")
        if isinstance(candidate, dict):
            raw_resume_value = candidate

        data = raw_resume_value.get("data")
        return {
            "type": payload_type,
            "data": data if isinstance(data, dict) else {},
        }
