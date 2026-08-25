from typing import Any

from langchain.agents import AgentState
from typing_extensions import NotRequired


class CareerAgentState(AgentState, total=False):
    """平台通用 Agent 的 LangGraph 状态定义。

    这个 state 会被 LangChain create_agent 底层的 LangGraph 使用。
    它和 runtime context 不一样：
    - context 存放本次调用的外部业务参数，例如 agent_id、thread_id、inputs。
    - state 存放 Agent 执行过程中的内部状态，例如工具轨迹、结构化结果、画像草稿。
    """

    # tool_trace 用来记录工具调用过程，后续可以用于排查工具为什么被调用、入参是什么、耗时多少。
    tool_trace: NotRequired[list[dict[str, Any]]]


    # profile_draft 是岗位画像类 Agent 的预留状态，后续岗位画像生成流程可以逐步写入草稿。
    profile_draft: NotRequired[dict[str, Any]]

    # metadata 用来存放不适合放入消息里的运行过程元信息。
    metadata: NotRequired[dict[str, Any]]


# 兼容旧命名：之前 graph/state.py 暴露的是 AgentGraphState。
# 后续新代码优先使用 CareerAgentState。
AgentGraphState = CareerAgentState
