from typing import Any

from langchain_core.messages import ToolMessage
from langchain_core.tools import tool
from langgraph.prebuilt.tool_node import ToolRuntime
from langgraph.types import Command


VALID_STEP_STATUSES = {"waiting", "running", "done", "failed"}


def _normalize_step_status(status: str | None) -> str:
    """标准化任务步骤状态。

    Args:
        status: 模型传入的原始状态。

    Returns:
        平台内部使用的步骤状态；非法状态统一回退为 waiting。
    """
    cleaned_status = str(status or "").strip().lower()
    return cleaned_status if cleaned_status in VALID_STEP_STATUSES else "waiting"


def _get_current_task_plan(runtime: ToolRuntime) -> dict[str, Any] | None:
    """从 ToolRuntime.state 中读取当前任务计划。

    Args:
        runtime: LangGraph 注入的工具运行时对象。

    Returns:
        当前 state 中的 task_plan；不存在或结构异常时返回 None。
    """
    state = getattr(runtime, "state", None)
    if not isinstance(state, dict):
        return None

    task_plan = state.get("task_plan")
    return task_plan if isinstance(task_plan, dict) else None


def _build_tool_message(runtime: ToolRuntime, content: str) -> ToolMessage:
    """构建工具返回给模型的 ToolMessage。

    Args:
        runtime: LangGraph 注入的工具运行时对象。
        content: 工具执行结果摘要。

    Returns:
        ToolMessage，用于补齐本次工具调用对应的消息。
    """
    return ToolMessage(content=content, tool_call_id=runtime.tool_call_id)


def _normalize_steps(steps: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """标准化任务步骤列表。

    Args:
        steps: 模型传入的任务步骤列表。

    Returns:
        标准化后的步骤列表，每条步骤都有 step_id、title、description、status。

    Raises:
        RuntimeError: 步骤为空或步骤标题无效时抛出。
    """
    if not steps:
        raise RuntimeError("steps 至少需要包含一个任务步骤")

    normalized_steps: list[dict[str, Any]] = []
    for index, raw_step in enumerate(steps, start=1):
        if not isinstance(raw_step, dict):
            raise RuntimeError(f"第 {index} 个步骤必须是对象")

        title = str(raw_step.get("title") or "").strip()
        if not title:
            raise RuntimeError(f"第 {index} 个步骤缺少 title")

        step_id = str(raw_step.get("step_id") or f"step_{index}").strip()
        description = str(raw_step.get("description") or "").strip()
        status = _normalize_step_status(raw_step.get("status"))

        normalized_steps.append({
            "step_id": step_id,
            "title": title,
            "description": description or None,
            "status": status,
            "result": raw_step.get("result"),
        })
    return normalized_steps


def _merge_step_update(
    *,
    task_plan: dict[str, Any],
    step_id: str,
    status: str | None,
    result: str | None,
    note: str | None,
) -> dict[str, Any]:
    """把单个步骤更新合并进当前任务计划。

    Args:
        task_plan: 当前运行中的任务计划。
        step_id: 需要更新的步骤 ID。
        status: 新步骤状态；为空时保持原状态。
        result: 步骤结果；为空时保持原结果。
        note: 步骤备注；为空时保持原备注。

    Returns:
        合并后的任务计划。

    Raises:
        RuntimeError: 找不到步骤或状态非法时抛出。
    """
    cleaned_step_id = step_id.strip()
    if not cleaned_step_id:
        raise RuntimeError("step_id 不能为空")

    cleaned_status = status.strip() if isinstance(status, str) and status.strip() else None
    if cleaned_status is not None:
        cleaned_status = _normalize_step_status(cleaned_status)

    steps = list(task_plan.get("steps") or [])
    matched = False
    updated_steps: list[dict[str, Any]] = []
    for raw_step in steps:
        step = dict(raw_step) if isinstance(raw_step, dict) else {}
        if str(step.get("step_id") or "") == cleaned_step_id:
            matched = True
            if cleaned_status is not None:
                step["status"] = cleaned_status
            if result is not None:
                step["result"] = result
            if note is not None:
                step["note"] = note
        updated_steps.append(step)

    if not matched:
        raise RuntimeError(f"任务步骤不存在: {cleaned_step_id}")

    updated_plan = dict(task_plan)
    updated_plan["steps"] = updated_steps
    if updated_steps and all(step.get("status") == "done" for step in updated_steps):
        updated_plan["status"] = "completed"
    return updated_plan


@tool("set_task_plan")
async def set_task_plan(title: str, steps: list[dict[str, Any]], runtime: ToolRuntime) -> Command:
    """创建或重写规划模式的任务计划草稿。

    Args:
        title: 任务计划标题。
        steps: 任务步骤列表，每项建议包含 step_id、title、description。
        runtime: LangGraph 注入的工具运行时，用于读取当前 state 和写入 ToolMessage。

    Returns:
        Command，写入 task_plan、interrupt_payload 和工具消息；不主动控制 LangGraph 跳转。
    """
    current_plan = _get_current_task_plan(runtime)
    current_status = str((current_plan or {}).get("status") or "").strip()
    if current_status == "running":
        # 只有运行中的计划禁止整体重写，避免模型在执行过程中打乱已确认的任务步骤。
        return Command(
            update={
                "messages": [
                    _build_tool_message(runtime, "当前任务计划正在执行中，不能重写整体计划。请先完成或停止当前计划。")
                ]
            }
        )

    cleaned_title = title.strip() if isinstance(title, str) else ""
    if not cleaned_title:
        raise RuntimeError("title 不能为空")

    task_plan = {
        "title": cleaned_title,
        "status": "draft",
        "steps": _normalize_steps(steps),
    }

    return Command(
        update={
            "task_plan": task_plan,
            "interrupt_enabled": True,
            "interrupt_payload": {
                "type": "plan_confirmation",
                "data": {"task_plan": task_plan},
            },
            # 工具只负责写入任务计划和触发确认中断；后续执行规则统一以 <planning_mode> 注入内容为准。
            "messages": [
                _build_tool_message(
                    runtime,
                    "任务计划已创建成功，具体状态和下一步动作请以 <planning_mode> 中的系统提示为准。",
                )
            ],
        }
    )


@tool("update_task_step")
async def update_task_step(
    step_id: str,
    runtime: ToolRuntime,
    status: str | None = None,
    result: str | None = None,
    note: str | None = None,
) -> Command:
    """更新运行中任务计划的单个步骤。

    Args:
        step_id: 需要更新的步骤 ID。
        runtime: LangGraph 注入的工具运行时，用于读取当前任务计划。
        status: 新步骤状态，可选值 waiting/running/done/failed。
        result: 步骤执行结果。
        note: 步骤备注或阻塞原因。

    Returns:
        Command，写入更新后的 task_plan 和工具消息；不主动控制 LangGraph 跳转。
    """
    current_plan = _get_current_task_plan(runtime)
    if not current_plan:
        return Command(
            update={"messages": [_build_tool_message(runtime, "当前没有任务计划，无法更新步骤。")]}
        )

    current_status = str(current_plan.get("status") or "").strip()
    if current_status != "running":
        return Command(
            update={
                "messages": [
                    _build_tool_message(
                        runtime,
                        f"当前任务计划状态为 {current_status or 'unknown'}，只有 running 状态才能更新步骤。",
                    )
                ]
            }
        )

    updated_plan = _merge_step_update(
        task_plan=current_plan,
        step_id=step_id,
        status=status,
        result=result,
        note=note,
    )

    tool_message = f"任务步骤 {step_id} 已更新。"
    if updated_plan.get("status") == "completed":
        tool_message = "任务步骤已更新，任务计划已经全部完成。"

    return Command(
        update={
            "task_plan": updated_plan,
            "messages": [_build_tool_message(runtime, tool_message)],
        }
    )
