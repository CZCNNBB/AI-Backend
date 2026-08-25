# Agent State 模式说明

## 背景

我们当前的 Agent 服务使用 LangChain 的 `create_agent` 来组装通用 Agent。

需要注意的是，`create_agent` 并不是脱离 LangGraph 的简单封装。它底层会创建一套 LangGraph 执行图，负责处理模型调用、工具调用、消息流转、状态更新和 checkpoint。

因此，我们可以在继续使用 `create_agent` 的同时，通过 `middleware.state_schema` 扩展 LangGraph 的 state。

这个模式参考了 `agent_engine` 项目中的知识库检索实现。

## 核心概念

### messages

`messages` 是 Agent 默认状态的一部分，用来保存用户消息、模型消息和工具消息。

它主要面向模型对话流程。

### context

`context` 是本次运行的外部业务上下文，由 `context_schema` 定义。

它适合放这些内容：

- `thread_id`
- `allowed_tools`
- `inputs`

这些数据通常不需要直接展示给模型，但工具和中间件可以读取。

例如知识库检索工具需要 `knowledge_base_id`，这个值可以从 `context.inputs` 中获取，而不是让模型自己生成。

### state

`state` 是 LangGraph 内部流转状态，由 `AgentState` 以及中间件声明的 `state_schema` 定义。

它适合放 Agent 执行过程中的中间结果：

- 检索到的知识库内容
- 工具调用轨迹
- 结构化输出
- 岗位画像草稿
- 技能抽取结果
- 引用来源映射

state 可以随着图执行流转，也可以通过 checkpointer 持久化。

## 当前项目的基础实现

当前项目已经定义了平台通用 state：

```python
class CareerAgentState(AgentState, total=False):
    tool_trace: NotRequired[list[dict[str, Any]]]
    structured_output: NotRequired[dict[str, Any]]
    profile_draft: NotRequired[dict[str, Any]]
    metadata: NotRequired[dict[str, Any]]
```

基础中间件会声明：

```python
class ToolLoggingMiddleware(AgentMiddleware[CareerAgentState]):
    state_schema = CareerAgentState
```

`AgentService.assemble_agent()` 会把中间件传给 `create_agent`：

```python
agent = create_agent(
    model=model,
    tools=tools,
    system_prompt=system_prompt,
    context_schema=context_schema,
    middleware=middlewares,
    checkpointer=checkpointer,
)
```

这样 LangChain 在创建底层 LangGraph 时，会读取中间件的 `state_schema`，并把这些字段合并到 Agent state 中。

## 知识库检索模式

`agent_engine` 中的知识库检索不是简单地把大段检索内容直接作为工具返回值交给模型。

它采用的是：

```text
工具拿数据
  -> state 存中间结果
  -> ToolMessage 只返回简短状态
  -> middleware 在下一轮模型调用前注入 prompt
```

完整流程如下：

```text
1. create_agent 加载知识库中间件。
2. 知识库中间件通过 state_schema 声明 retrieval_context、reference_map 等字段。
3. 模型判断需要检索知识库，调用知识库检索工具。
4. 工具执行检索，拿到大段检索内容和来源映射。
5. 工具返回 Command(update=...)。
6. Command.update 把检索内容写入 state.retrieval_context。
7. ToolMessage 只告诉模型“工具调用完成”。
8. 下一轮模型调用前，中间件读取 state.retrieval_context。
9. 中间件把检索内容拼接到 system prompt。
10. 模型基于注入后的资料继续回答。
```

伪代码如下：

```python
return Command(
    update={
        "messages": [
            ToolMessage(content="知识库检索完成", tool_call_id=runtime.tool_call_id)
        ],
        "retrieval_context": [{"run_id": current_run_id, "content": retrieval_context}],
        "reference_map": reference_map,
    }
)
```

中间件在模型调用前读取 state：

```python
retrieval_context = request.state.get("retrieval_context", [])

if retrieval_context:
    final_system_prompt = f"""
{request.system_message.content}

<knowledge_context>
{retrieval_context}
</knowledge_context>
"""
    return await handler(
        request.override(system_message=SystemMessage(content=final_system_prompt))
    )
```

## 为什么不直接把大段内容作为工具返回值

直接把大段内容作为工具返回值会带来几个问题：

- 工具消息会非常长，影响模型上下文管理。
- 多次检索结果容易堆在 messages 中，难以合并和去重。
- 引用来源、正文内容、展示要求混在一起，不利于维护。
- 不方便通过 checkpointer 排查“当时检索到了什么”。

写入 state 后再由中间件统一注入 prompt，可以让系统更可控。

## 岗位画像中的应用方式

后续岗位画像 Agent 可以采用相同模式。

例如定义岗位画像 state：

```python
class JobProfileState(CareerAgentState, total=False):
    job_postings_context: NotRequired[str]
    source_job_ids: NotRequired[list[int]]
    extracted_requirements: NotRequired[list[dict[str, Any]]]
    skill_summary: NotRequired[dict[str, Any]]
```

岗位数据工具可以这样工作：

```text
query_job_postings 工具
  -> 查询数据库中的岗位 JD
  -> 整理成适合模型阅读的 job_postings_context
  -> 返回 Command(update=...)
  -> 把 job_postings_context 写入 state
  -> ToolMessage 返回“岗位数据读取完成”
```

岗位画像中间件可以这样工作：

```text
JobProfilePromptMiddleware
  -> 在模型下一轮调用前读取 state.job_postings_context
  -> 把岗位 JD 内容注入 system prompt
  -> 让模型基于招聘数据生成岗位画像
```

## 当前项目状态

当前项目已经完成：

- 定义平台基础 `CareerAgentState`
- 基础 middleware 声明 `state_schema`
- `create_agent` 装配中间件
- `checkpointer` 接入 PostgreSQL
- 基础 middleware 已声明 `state_schema = CareerAgentState`
- 模型可见的跨轮会话记忆由 checkpointer 按 thread_id 恢复，不再使用 `RemoveMessage(REMOVE_ALL_MESSAGES)` 清理历史 messages

当前项目还没有完成：

- 业务工具返回 `Command(update=...)`
- 业务 state，例如 `JobProfileState`
- 业务中间件读取 state 并注入 system prompt
- 岗位画像生成的完整 LangGraph state 闭环

## 推荐落地顺序

1. 新增岗位画像 state，例如 `JobProfileState`。
2. 新增岗位数据读取工具，先从 `job_postings` 查询 JD 原文。
3. 工具返回 `Command(update=...)`，把岗位数据写入 state。
4. 新增 `JobProfilePromptMiddleware`，在模型调用前注入岗位数据。
5. 在岗位画像 Agent 模板中启用对应工具和中间件。
6. 使用 checkpointer 验证 state 是否被正确持久化。

## 设计原则

- 工具负责获取数据。
- state 负责保存中间结果。
- middleware 负责控制模型能看到什么。
- context 负责传递本次运行的外部业务参数。
- messages 只保留对话和工具调用的必要消息。
- checkpointer 负责持久化 LangGraph state，便于恢复和排查。
