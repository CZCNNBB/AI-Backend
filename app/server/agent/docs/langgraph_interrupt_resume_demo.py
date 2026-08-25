r"""LangGraph 中断与恢复的最小可运行示例。

运行方式：
    D:\Anaconda\envs\job_spider\python.exe -B langgraph_interrupt_resume_demo.py

这个示例不调用大模型，只演示 LangGraph 的 interrupt/resume 核心机制。
"""

from typing import Any, TypedDict

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt


class DemoState(TypedDict, total=False):
    """示例工作流状态。"""

    task: str
    approval: dict[str, Any]
    result: str


def request_approval(state: DemoState) -> dict[str, Any]:
    """暂停工作流并等待用户审批。

    第一次执行到 interrupt() 时，LangGraph 会保存当前状态并暂停。
    使用 Command(resume=...) 恢复后，本节点会重新执行，
    此时 interrupt() 不再暂停，而是返回 Command 中携带的恢复值。
    """
    interrupt_payload = {
        "type": "task_confirmation",
        "data": {
            "question": "是否确认执行这个任务？",
            "task": state["task"],
        },
    }

    # 首次运行：这里暂停，并把 interrupt_payload 返回给调用方。
    # 恢复运行：这里直接得到 Command(resume=...) 传入的数据。
    resume_value = interrupt(interrupt_payload)

    print("\n[节点内部] 已收到恢复数据：", resume_value)
    return {"approval": resume_value}


def execute_task(state: DemoState) -> dict[str, str]:
    """根据用户审批结果执行或取消任务。"""
    approval_data = state.get("approval", {}).get("data", {})
    action = approval_data.get("action")

    if action == "approve":
        result = f"任务已执行：{state['task']}"
    else:
        result = f"任务已取消：{state['task']}"

    return {"result": result}


def build_graph():
    """构建带 Checkpointer 的 LangGraph 工作流。"""
    graph_builder = StateGraph(DemoState)
    graph_builder.add_node("request_approval", request_approval)
    graph_builder.add_node("execute_task", execute_task)

    graph_builder.add_edge(START, "request_approval")
    graph_builder.add_edge("request_approval", "execute_task")
    graph_builder.add_edge("execute_task", END)

    # 中断必须依赖 Checkpointer 保存执行位置和 State。
    checkpointer = InMemorySaver()
    return graph_builder.compile(checkpointer=checkpointer)


def main() -> None:
    """依次演示首次中断和恢复执行。"""
    graph = build_graph()

    # thread_id 是查找 Checkpoint 的关键。
    # 恢复时必须继续使用完全相同的 thread_id。
    config = {"configurable": {"thread_id": "interrupt-demo-thread"}}

    print("第一步：首次运行工作流")
    interrupted_result = graph.invoke(
        {"task": "生成一份活动策划方案"},
        config=config,
    )
    print("[调用方] 工作流已暂停：", interrupted_result)

    checkpoint_state = graph.get_state(config)
    print("[调用方] Checkpoint 中保存的 State：", checkpoint_state.values)

    print("\n第二步：携带用户审批结果恢复工作流")
    resume_value = {
        "type": "task_confirmation",
        "data": {
            "action": "approve",
            "message": "确认执行",
        },
    }
    completed_result = graph.invoke(
        Command(resume=resume_value),
        config=config,
    )
    print("[调用方] 工作流恢复完成：", completed_result)


if __name__ == "__main__":
    main()
