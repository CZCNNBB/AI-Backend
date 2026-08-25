"""规划模式中间件：注入任务计划规则，并处理计划确认的 resume_value。"""

from collections.abc import Awaitable, Callable
from typing import Any

from langchain.agents.middleware import AgentMiddleware
from langchain.agents.middleware.types import ModelRequest, ModelResponse
from langchain_core.messages import HumanMessage, SystemMessage
from typing_extensions import NotRequired

from app.server.agent.src.graph.state import CareerAgentState

class PlanningState(CareerAgentState, total=False):
    """规划模式使用的 LangGraph state 扩展。"""

    # task_plan 存放本次运行生命周期内的任务计划，不直接落业务库。
    task_plan: NotRequired[dict[str, Any]]


    # resume_value 是 InterruptMiddleware 写入的一次性恢复事件，由业务中间件消费后清理。
    resume_value: NotRequired[dict[str, Any] | None]


class PlanningMiddleware(AgentMiddleware[PlanningState]):
    """处理规划模式的提示词注入和计划确认结果。

    这个中间件只在 optional_features.planning_enabled=true 时装配。
    它不负责触发中断；中断由 InterruptMiddleware 根据 interrupt_enabled 统一处理。
    """

    state_schema = PlanningState

    def __init__(self, enabled: bool = True):
        """初始化规划模式中间件。

        Args:
            enabled: 是否启用规划模式逻辑。
        """
        self.enabled = enabled

    def before_model(self, state: PlanningState, runtime: Any) -> dict[str, Any] | None:
        """在模型调用前消费计划确认的 resume_value。

        Args:
            state: 当前 LangGraph state。
            runtime: LangGraph runtime，本方法当前不直接使用。

        Returns:
            需要合并回 state 的更新；没有可消费事件时返回 None。
        """
        if not self.enabled:
            return None

        resume_value = state.get("resume_value")
        if not isinstance(resume_value, dict):
            return None
        if resume_value.get("type") != "plan_confirmation":
            return None

        data = resume_value.get("data") if isinstance(resume_value.get("data"), dict) else {}
        action = self._normalize_confirmation_action(data.get("action"))
        task_plan = dict(state.get("task_plan") or {})
        if not task_plan:
            # 没有计划可处理时也要清理 resume_value，避免后续模型轮次重复消费。
            return {"resume_value": None}

        if action == "approve":
            task_plan["status"] = "running"
            return self._build_plan_resume_update(task_plan=task_plan, user_message="用户：确认任务计划")

        if action == "revise":
            task_plan["status"] = "draft"
            feedback = self._extract_revision_feedback(data)
            return self._build_plan_resume_update(
                task_plan=task_plan,
                user_message=self._build_revision_user_message(feedback),
            )

        if action == "cancel":
            task_plan["status"] = "cancelled"
            return self._build_plan_resume_update(task_plan=task_plan, user_message="用户：取消任务计划")

        # 未识别 action 时保留 draft，并把问题反馈给模型，让模型追问或提示用户重新确认。
        task_plan["status"] = "draft"
        return self._build_plan_resume_update(task_plan=task_plan, user_message="用户：提交了无法识别的任务计划操作")

    def _build_plan_resume_update(self, *, task_plan: dict[str, Any], user_message: str) -> dict[str, Any]:
        """构建计划确认恢复后的 state 更新。

        Args:
            task_plan: 已更新整体状态的任务计划。
            user_message: 需要追加给模型看的用户操作消息。

        Returns:
            合并回 LangGraph state 的更新内容。
        """
        return {
            "task_plan": task_plan,
            "messages": [HumanMessage(content=user_message)],
            "resume_value": None,
        }

    async def awrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], Awaitable[ModelResponse]],
    ) -> ModelResponse:
        """在模型调用前注入规划模式规则和当前计划状态。

        Args:
            request: LangChain 模型调用请求。
            handler: 后续模型调用处理器。

        Returns:
            模型调用结果。
        """
        if not self.enabled:
            return await handler(request)

        injected = self._build_planning_prompt(request.state or {})
        current_prompt = getattr(request.system_message, "content", "")
        new_system = SystemMessage(content=f"{current_prompt}\n\n{injected}")
        return await handler(request.override(system_message=new_system))

    def _normalize_confirmation_action(self, raw_action: object) -> str:
        """把前端传入的确认动作归一化为 approve/revise/cancel。

        Args:
            raw_action: 前端确认卡片传入的 action，可以是英文动作或中文动作。

        Returns:
            标准动作。无法识别时返回空字符串。
        """
        action = str(raw_action or "").strip().lower()
        if action in {"approve", "confirm", "confirmed", "ok", "yes", "execute", "start", "确认", "同意", "执行"}:
            return "approve"
        if action in {"revise", "modify", "change", "edit", "feedback", "update", "修改", "调整", "补充"}:
            return "revise"
        if action in {"cancel", "cancelled", "reject", "stop", "abort", "取消", "放弃", "停止"}:
            return "cancel"
        return ""

    def _build_revision_user_message(self, feedback: str) -> str:
        """构建用户修改任务计划时的自然语言操作文本。

        Args:
            feedback: 用户在确认卡片中提交的修改意见。

        Returns:
            追加到 messages 中的用户操作文本。
        """
        cleaned_feedback = feedback.strip() if isinstance(feedback, str) else ""
        if cleaned_feedback:
            return f"用户：修改任务计划。修改意见：{cleaned_feedback}"
        return "用户：修改任务计划，但没有提供具体修改意见"

    def _extract_revision_feedback(self, data: dict[str, Any]) -> str:
        """从恢复数据中提取用户对任务计划的修改意见。

        Args:
            data: plan_confirmation 的 data 字段。

        Returns:
            用户修改意见文本；没有则返回空字符串。
        """
        for key in ("feedback", "suggestion", "message", "text", "value"):
            value = data.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
        return ""

    def _build_planning_prompt(self, state: dict[str, Any]) -> str:
        """构建追加到 system prompt 末尾的固定规划模式协议。

        Args:
            state: 当前 LangGraph state。

        Returns:
            固定结构的规划模式提示词片段。
        """
        task_plan = state.get("task_plan") if isinstance(state.get("task_plan"), dict) else None
        status = str((task_plan or {}).get("status") or "none")

        lines = [
            "<planning_mode>",
            "规划模式已启用。以下内容只描述当前任务计划状态和固定规则；用户确认、取消、修改等操作会作为最后一条用户消息出现在 messages 中。",
            "",
            "## 当前状态",
            f"status: {status}",
        ]

        self._append_task_plan_snapshot(lines, task_plan)
        self._append_fixed_rules(lines)

        lines.append("</planning_mode>")
        return "\n".join(lines)

    def _append_task_plan_snapshot(self, lines: list[str], task_plan: dict[str, Any] | None) -> None:
        """追加当前任务计划快照。

        Args:
            lines: 正在构建的提示词行列表。
            task_plan: 当前 LangGraph state 中的任务计划；没有计划时为 None。
        """
        lines.extend(["", "## 当前任务计划"])
        if not task_plan:
            lines.append("当前还没有任务计划。")
            return

        title = str(task_plan.get("title") or "")
        steps = task_plan.get("steps") if isinstance(task_plan.get("steps"), list) else []
        lines.append(f"title: {title}")
        lines.append("steps:")

        for index, raw_step in enumerate(steps, start=1):
            if not isinstance(raw_step, dict):
                continue
            step_id = str(raw_step.get("step_id") or index)
            step_title = str(raw_step.get("title") or "")
            step_description = str(raw_step.get("description") or "")
            step_status = str(raw_step.get("status") or "waiting")
            step_result = raw_step.get("result")
            step_note = raw_step.get("note")

            lines.append(
                f"- {index}. step_id={step_id}; status={step_status}; title={step_title}; description={step_description}"
            )
            if step_result not in (None, ""):
                lines.append(f"  result={step_result}")
            if step_note:
                lines.append(f"  note={step_note}")

    def _append_fixed_rules(self, lines: list[str]) -> None:
        """追加固定规划协议规则，不在代码里按状态分支生成不同提示。

        Args:
            lines: 正在构建的提示词行列表。
        """
        lines.extend([
            "",
            "## 固定规则",
            "1. 规划模式是可用能力，不是强制流程。简单任务必须直接完成，不要调用 set_task_plan。",
            "2. 简单任务包括但不限于：寒暄、解释概念、回答单个问题、总结一段已给内容、查看附件并直接说明内容、轻量建议、无需工具或只需一次工具调用即可完成的任务。",
            "3. 只有任务明显复杂或需要多步协作时，才调用 set_task_plan 创建任务计划草稿。复杂任务通常具备以下特征之一：需要多个阶段、需要多个工具/子 Agent 串联、需要先产出中间结果再继续、需要用户确认执行方案、任务范围较大且直接执行风险高。",
            "4. status=none 表示当前没有任务计划；如果本轮用户任务是简单任务，直接回答；如果确认为复杂多步骤任务，才调用 set_task_plan。",
            "5. status=draft 表示任务计划草稿未确认；不能执行任务步骤。",
            "6. 如果最后一条用户消息表达确认任务计划，说明当前计划已进入 running，可以按步骤执行。",
            "7. 如果最后一条用户消息表达修改任务计划，必须调用 set_task_plan 按用户意见重写任务计划草稿，不能继续等待旧计划确认，不能执行旧计划。",
            "8. 如果最后一条用户消息表达取消任务计划，不能执行旧计划；如果用户没有提出新任务，只确认计划已取消。",
            "9. status=running 表示任务计划已确认；必须按步骤顺序执行，从第一个 waiting 或 running 步骤开始。",
            "10. 执行某个步骤前，必须调用 update_task_step 将该步骤状态设为 running。",
            "11. 步骤完成后，必须调用 update_task_step 将该步骤状态设为 done，并在 result 中写清结果。",
            "12. 步骤失败时，必须调用 update_task_step 将该步骤状态设为 failed，并在 note 或 result 中写清原因，然后回复用户失败原因。",
            "13. status=completed 表示任务计划已完成；只输出最终总结，不再继续执行任务。",
            "14. status=cancelled 表示旧任务计划已取消；如果用户提出新的复杂多步骤任务，可以重新调用 set_task_plan 创建新草稿；如果是简单任务，直接完成。",
            "15. set_task_plan 用于创建或重写整体任务计划；只有 status=running 时禁止调用。",
            "16. update_task_step 只允许在 status=running 时更新单个步骤，禁止用它重写整体计划。",
        ])
