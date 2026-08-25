# Agent 构建模式说明

## 文档目标

本文档说明平台 Agent 从接口调用到最终回复的完整生命周期。

当前设计目标是让 `/agent/run` 成为一个干净的通用执行器：

- 不绑定 `agent_id`
- 不接收 `request_id`
- 不接收调用方 `metadata`
- 不接收外部 `input_messages`
- 不提供 `dry_run`
- 不提供 `inspect`

如果调用方需要基于模板运行，应先通过模板接口获取配置，再把配置展开后传给 `/agent/run`。

## 当前请求模型

`AgentRunRequest` 当前只包含本次运行真正需要的字段：

```json
{
  "query": "用户问题或任务指令",
  "conversation_id": "可选会话ID",
  "stream": false,
  "system_prompt": "可选系统提示词",
  "response_format": null,
  "inputs": {},
  "file_ids": [],
  "tools": [],
  "optional_features": {
    "long_term_memory_enabled": false
  },
  "runtime_options": {
    "model": "chat_main",
    "temperature": 0.2,
    "timeout_seconds": null,
    "max_retries": 2
  }
}
```

其中：

- `query` 是本轮用户问题或任务指令。
- `conversation_id` 用于控制是否复用会话记忆：非空时作为 LangGraph thread_id；为空时生成临时 thread_id。
- `stream` 控制 `/agent/run` 的响应协议：false 返回统一 JSON，true 返回 SSE `text/event-stream`。
- `system_prompt` 控制本次 Agent 的系统提示词。
- `response_format` 接收可选 JSON Schema，非空时启用 LangChain 结构化输出。
- `inputs` 是业务变量，供 prompt、工具、中间件读取。
- `file_ids` 是附件上下文。
- `tools` 是本次允许加载的 MCP 外接工具编码白名单；A2A、规划等内置工具不允许写在这里。
- `optional_features` 是本次运行的能力开关。
- `context_summarization` 仅由 Agent 模板配置；对象存在时启用独立的会话总结模型和中间件。
- `runtime_options` 是主 Agent 模型运行参数。
- `runtime_options.model` 是 Agent 根目录 `model_gateway.yaml` 中的模型别名，空值使用网关默认聊天模型。

## 总体生命周期

一次 `/agent/run` 的完整链路如下：

```text
HTTP 请求
  -> agent_api.py
  -> AgentRunRequest
  -> AgentService.run()
  -> 构建 runtime context
  -> 根据 conversation_id 判断是否准备用户可见会话记录
  -> assemble_agent()
  -> create_agent()
  -> 构建 LangGraph messages 输入
  -> agent.ainvoke()
  -> 提取模型回复
  -> 按需写入 ContextService
  -> AgentRunResponse
  -> Result.success()
  -> HTTP 响应
```

更细的步骤：

```text
1. 接口接收请求
2. 请求参数校验
3. 构建 runtime context
4. 如果 conversation_id 非空，则准备用户可见会话记录
5. 生成 Agent 装配配置
6. 渲染 system prompt
7. 加载工具
8. 构建 context_schema
9. 加载 middleware
10. 识别 middleware state_schema
11. 获取 checkpointer
12. 调用 create_agent
13. 构建 messages 输入
14. 只追加本轮用户消息，历史由 checkpointer 按 thread_id 恢复
15. 执行 agent.ainvoke
16. 提取最终回答
17. 处理长期记忆占位逻辑
18. 如果 conversation_id 非空，则保存用户消息和 Agent 回复
19. 返回统一响应
```

## 接口入口

当前 Agent 运行入口是：

```text
POST /agent/run
```

对应文件：

```text
backend/app/server/agent/api/agent_api.py
```

接口层只负责：

```text
1. 接收 AgentRunRequest
2. 获取数据库 Session
3. 调用 AgentService.run()
4. 返回 Result.success(...)
```

接口层不写 Agent 装配逻辑，也不写具体业务逻辑。

## Runtime Context

进入 `AgentService.run()` 后，第一步是构建 runtime context：

```python
context = self.runtime_context_service.build_context(request)
```

Runtime context 是本次调用的外部业务上下文，不是 prompt，也不是 messages。

当前包含：

```text
thread_id
query
sys_var
user_var
inputs
file_ids
allowed_tools
optional_features
memory_enabled
```

其中 `thread_id` 的生成规则是：

```python
thread_id = request.conversation_id or uuid4().hex
```

也就是说：

- 如果传入 `conversation_id`，本次运行沿用这条会话线，模型可见历史由同一个 checkpointer thread 恢复，并写入用户可见会话记录。
- 如果没有传入，系统生成一个临时线程 ID，适合 A2A 子 Agent 或一次性任务调用；不会写入用户可见会话记录。

## 会话记忆与展示记录

当前设计里，Agent 可见的会话记忆和用户可见的会话记录是两套东西。

```text
Checkpointer
  负责模型可见的跨轮会话记忆和 LangGraph state。
  同一个 conversation_id 会作为同一个 thread_id 传给 LangGraph，
  因此模型可以从 checkpoint 中恢复历史 messages。

ContextService / agent_messages
  只负责用户可见的展示记录。
  它保存用户问题和 Agent 最终回复，方便前端展示、后续摘要和业务查询。
  它不再作为模型下一轮输入的历史来源。
```

当 `conversation_id` 非空时，服务会确保 `agent_conversations` 存在，并在运行前后写入用户可见消息；但不会从 `agent_messages` 读取历史再注入给模型。

当 `conversation_id` 为空时，本次调用使用临时 thread_id，只保留 checkpointer 执行状态，不写入 `agent_messages`。

当前输入构造方式：

```python
input_messages = [
    {"role": "user", "content": request.query},
]
```

运行时仍然使用同一个 `thread_id`：

```python
result = await agent.ainvoke(
    {"messages": input_messages},
    config={"configurable": {"thread_id": context.thread_id}},
)
```

这样可以保证：

```text
模型看到的跨轮历史来自 checkpointer。
用户看到的聊天记录来自 agent_messages。
工具调用、多轮执行状态和中间 state 保留在 LangGraph checkpoint / 后续 run_events 中。
```

## Agent 装配配置

Agent 构建从这里开始：

```python
build_config = self.build_agent_assembly_config(request)
```

`build_agent_assembly_config()` 会把 API 请求转换成内部装配配置。

它主要决定：

```text
使用哪段 system_prompt
允许使用哪些工具
启用哪些内部能力
checkpointer 是平台默认基础能力，不再通过 optional_features 开关控制
是否启用长期记忆
是否启用延迟工具筛选
```

它不会处理：

```text
会话创建
展示会话准备
消息写入
业务数据查询
岗位画像落库
```

## System Prompt 渲染

系统提示词通过 PromptService 渲染：

```python
system_prompt = self.prompt_service.render_system_prompt(
    build_config.system_prompt,
    context.inputs,
)
```

`context.inputs` 可以提供业务变量。

例如：

```json
{
  "job_direction": "AI应用开发"
}
```

后续模板服务可以提供默认 system prompt，请求也可以传入本次覆盖的 system prompt。

## 工具加载

工具加载通过：

```python
tools = self.tool_service.get_tools(build_config.tool_names)
```

`request.tools` 只表示本次允许使用的 MCP 外接工具编码。

例如岗位画像 Agent 可以配置：

```text
job.search_job_skills
job.create_job_skills
```

A2A 工具、任务规划工具等属于系统内置能力工具，不允许配置在 `tools` 中。它们分别由 `a2a.sub_agent_list`、`optional_features.planning_enabled` 等能力参数自动挂载。工具本身应该保持业务能力函数属性，不要直接承担 Agent 编排逻辑。

## Context Schema

LangChain runtime context schema 通过：

```python
context_schema = self.runtime_context_service.get_context_schema()
```

它定义工具和中间件可以读取哪些 runtime context 字段。

当前字段包括：

```text
thread_id
query
sys_var
user_var
inputs
file_ids
allowed_tools
optional_features
memory_enabled
```

## Middleware 装配

Middleware 通过工厂创建：

```python
middlewares = self.middleware_factory.build_langchain_middlewares(build_config.features)
```

当前基础中间件包括：

```text
ToolErrorHandlerMiddleware
ToolArgsInjectMiddleware
ToolLoggingMiddleware
MemoryPlaceholderMiddleware
```

Middleware 可以拦截：

```text
模型调用前
模型调用后
工具调用前
工具调用后
Agent 执行前后
```

## State Schema

每个 middleware 可以声明自己的 LangGraph state：

```python
class ToolLoggingMiddleware(AgentMiddleware[CareerAgentState]):
    state_schema = CareerAgentState
```

当前平台基础 state 是：

```python
class CareerAgentState(AgentState, total=False):
    tool_trace: NotRequired[list[dict[str, Any]]]
    structured_output: NotRequired[dict[str, Any]]
    profile_draft: NotRequired[dict[str, Any]]
    metadata: NotRequired[dict[str, Any]]
```

这些 state 字段会被 `create_agent` 合并到底层 LangGraph state 中。

## Checkpointer

如果开启：

```json
{
  "optional_features": {
  }
}
```

运行时会默认获取 PostgreSQL checkpointer：

```python
checkpointer = await self.checkpoint_service.get_checkpointer()
```

然后传入：

```python
create_agent(..., checkpointer=checkpointer)
```

注意：

```text
checkpointer 保存 LangGraph state。
ContextService 保存业务会话历史。
```

运行开始时不清理 checkpoint messages；同一个 thread_id 下的历史 messages 会作为模型可见会话记忆继续保留。

## create_agent

最终通过 LangChain 的 `create_agent` 创建 Agent：

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

这些参数分别表示：

```text
model:
  Agent 使用哪个模型。

tools:
  Agent 可以调用哪些工具。

system_prompt:
  Agent 的角色、目标和约束。

context_schema:
  runtime context 的结构定义。

middleware:
  模型和工具调用链路上的横切能力。

checkpointer:
  LangGraph state 持久化组件。
```

## Agent 执行

真实执行发生在：

```python
result = await assembly.agent.ainvoke(
    {"messages": input_messages},
    config={
        "configurable": {
            "thread_id": context.thread_id
        },
        "recursion_limit": 50,
    },
    context=context.to_langchain_context(),
)
```

这里有三类输入：

```text
messages:
  模型可见的消息包括 checkpointer 恢复的历史 messages 和本轮用户消息。

config.configurable.thread_id:
  LangGraph checkpointer 使用的线程 ID。

context:
  工具和中间件可读取的 runtime context。
```

## 模型和工具循环

`agent.ainvoke()` 内部会进入 LangGraph 执行流程：

```text
1. 模型读取 messages 和 system prompt。
2. 模型决定是否调用工具。
3. 如果调用工具，进入工具节点。
4. middleware 可以拦截工具调用。
5. 工具可以返回 ToolMessage 或 Command(update=...)。
6. 如果返回 Command(update=...)，LangGraph 合并 state。
7. 模型进入下一轮调用。
8. middleware 可以在下一轮模型调用前读取 state 并注入 prompt。
9. 模型输出最终回答。
```

例如知识库检索：

```text
工具检索到资料
  -> Command(update={"retrieval_context": [{"run_id": "...", "content": "..."}]})
  -> ToolMessage("工具调用完成")
  -> middleware 下一轮按 run_id 读取当前运行的 retrieval_context
  -> 注入 system prompt
  -> 模型基于资料回答
```

## 消息写入

如果 `conversation_id` 非空，运行前会写入用户消息：

```python
self.context_service.add_user_message(
    db,
    conversation_id=context.thread_id,
    content=request.query,
    metadata={},
)
```

运行后会写入 Agent 回复：

```python
self.context_service.add_assistant_message(
    db,
    conversation_id=context.thread_id,
    content=answer,
    metadata={},
)
```

当前用户可见会话记录不记录 `agent_id`、`request_id` 或调用方 metadata。

会话历史只围绕：

```text
conversation_id
role
content
created_at
```

## 流式输出

`/agent/run` 支持通过 `stream` 参数切换流式返回：

```json
{
  "query": "你好",
  "stream": true
}
```

当 `stream=false` 时，接口返回统一 `code/msg/data` JSON。

当 `stream=true` 时，接口返回 `text/event-stream`，不再使用统一 Result 包装。当前事件类型包括：

```text
run_start
agent_assembled
model_start
reasoning_delta
model_delta
model_end
tool_call_start
tool_call_result
final
run_end
error
```

其中 `reasoning_delta` 只有模型供应商显式返回思考内容时才会出现。
## 返回响应

最终返回：

```python
AgentRunResponse(
    answer=answer,
    structured_output=result.get("structured_response") or result.get("structured_output"),
)
```

统一 API 响应格式：

```json
{
  "code": 0,
  "msg": "success",
  "data": {
    "answer": "...",
    "structured_output": {}
  }
}
```

## 与 agent_engine 的差异

我们参考了 `agent_engine` 的 state / checkpointer 思路，但当前项目的会话记忆边界做了调整：

```text
conversation_id
  -> 作为 LangGraph thread_id
  -> checkpointer 恢复模型可见历史 messages
  -> 本轮只追加当前 user message
  -> agent_messages 只保存用户可见问题和最终回复
```

因此本项目不再使用 `RemoveMessage(REMOVE_ALL_MESSAGES)` 清理 checkpoint messages，也不再把 ContextService 历史消息注入模型。

## 当前已完成

当前已经完成：

```text
干净的 AgentRunRequest
AgentService.run
AgentService.assemble_agent
ModelService
ToolService 基础注册
PromptService
RuntimeContextService
MiddlewareFactory
CareerAgentState
PostgreSQL Checkpointer
ContextService 展示会话记录
TemplateService 模板 CRUD
Checkpointer 恢复模型可见历史 messages
```

当前还没有完成：

```text
模板配置自动合并到 /agent/run
业务工具 Command(update=...) 写 state
业务中间件从 state 注入 prompt
岗位画像 Agent 编排
知识库检索工具
长期记忆真实实现
流式输出
执行轨迹查询
```

## 设计原则

```text
AgentService 负责编排，不写具体业务算法。
ModelService 负责模型实例创建。
ToolService 负责工具注册和筛选。
PromptService 负责 prompt 渲染。
RuntimeContextService 负责运行上下文。
MiddlewareFactory 负责中间件装配。
ContextService 负责跨轮会话历史。
CheckpointService 负责 LangGraph state 持久化。
TemplateService 负责 Agent 默认配置。
业务模块通过工具、state、middleware 扩展 Agent。
```

一句话总结：

```text
ContextService 管跨轮历史。
Checkpointer 管本轮执行状态。
agent_messages 不再注入模型，因此不会和 checkpoint 历史形成双历史。
/agent/run 只负责真实执行。
```
