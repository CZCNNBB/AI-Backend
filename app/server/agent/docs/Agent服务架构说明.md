# Agent 服务架构说明

## 定位

Agent 服务是平台里的通用智能体运行层。

它不直接绑定某一个具体业务，而是提供一套可复用的 Agent 基础设施：

- 模型调用
- 工具注册与筛选
- Prompt 渲染
- Runtime context 构建
- Middleware 装配
- LangGraph state 扩展
- Checkpointer 状态持久化
- 会话历史管理
- Agent 模板管理

后续岗位画像生成、知识库问答、定时分析任务，都应该基于这套 Agent 服务能力继续扩展。

## 目录结构

当前目录位于：

```text
backend/app/server/agent
```

主要结构如下：

```text
agent/
  api/
    agent_api.py
    conversation_api.py
    template_api.py
  docs/
    agent-state-pattern.md
    agent-service-architecture.md
  src/
    agent/
    checkpoint/
    context/
    graph/
    memory/
    middlewares/
    model/
    prompts/
    runtime/
    schemas/
    templates/
    tools/
```

## API 层

API 层只负责接收请求、调用 service、返回统一结果。

当前接口包括：

```text
GET  /agent/health
GET  /agent/model/config
GET  /agent/capabilities
POST /agent/run
POST /agent/conversations/search
POST /agent/conversations/messages
POST /agent/runs/search
POST /agent/runs/detail
POST /agent/runs/chain
POST /agent/templates/upsert
POST /agent/templates/detail
POST /agent/templates/search
```

流式模式：

```text
POST /agent/run
  stream=false -> 统一 JSON Result
  stream=true  -> SSE text/event-stream
```

SSE 事件由 `AgentService.stream()` 产出，API 层只负责序列化为 `event/data` 格式。
### agent_api.py

负责 Agent 运行相关接口。

核心接口是：

```text
POST /agent/run
```

它会调用 `AgentService.run()`，完成一次通用 Agent 调用。

### conversation_api.py

负责会话历史查询。

当前系统不做权限划分，也不接收 `user_id`，只通过 `conversation_id` 查询历史会话和消息。

### template_api.py

负责 Agent 模板管理。

模板通过 `agent_id` 区分，每个模板可以保存：

- `agent_name`
- `description`
- `config`
- `status`

其中 `config` 使用 JSON 存储，后续可以兼容不同 Agent 请求参数。

## src/agent

`src/agent` 是 Agent 服务的核心装配层。

主要文件：

```text
assembly.py
service.py
```

### AgentService

`AgentService` 负责把各个模块组装成一个可运行 Agent。

它的职责包括：

- 根据请求构建 Agent 装配配置
- 构建运行时上下文
- 渲染 system prompt
- 加载工具
- 加载 middleware
- 获取 checkpointer
- 调用 LangChain `create_agent`
- 执行 Agent
- 写入会话历史
- 调用记忆服务占位逻辑

一次 `/agent/run` 的主流程如下：

```text
1. build_context
   构建本次运行上下文；conversation_id 非空时作为持久 thread_id，空值时生成临时 thread_id。
2. ensure_conversation
   如果传入 conversation_id，则确保用户可见 conversation 存在。
3. prepare checkpoint memory
   模型可见历史由 checkpointer 根据 thread_id 恢复，不从 agent_messages 读取。
4. assemble_agent
   组装模型、工具、prompt、middleware、checkpointer。
5. build input messages
   只把本轮用户问题作为 LangChain 输入；历史 messages 由 checkpointer 恢复。
6. save user message
   如果传入 conversation_id，则写入用户消息。
7. agent.ainvoke
   真实运行 Agent。
8. extract answer
   从返回消息里提取最终回答。
9. save assistant message
   如果传入 conversation_id，则写入 Agent 回复。
```
## src/model

模型层负责统一创建模型实例。

当前主要通过 OpenAI-compatible 的 `ChatOpenAI` 调用模型。

这样做的好处是：

- OpenAI 官方模型可以使用
- 兼容 OpenAI API 格式的国产模型也可以接入
- 业务层不需要关心不同厂商的 SDK 差异

模型参数由请求里的 `runtime_options` 控制，例如：

- `model`
- `temperature`
- `timeout_seconds`
- `max_retries`

## src/tools

工具层负责工具注册、工具筛选和工具注入配置。

当前还处于基础阶段，主要提供通用工具注册能力。

后续业务工具应该放到工具层管理，例如：

- 查询岗位列表工具
- 查询岗位 JD 工具
- 保存岗位画像工具
- 知识库检索工具
- 数据库查询工具

工具本身应该尽量保持业务函数属性，不要和 Agent 运行时强绑定。

如果工具需要把结果写入 LangGraph state，推荐返回 `Command(update=...)`，或者由 middleware 拦截工具结果后写入 state。

## src/prompts

Prompt 层负责基础 prompt 和模块 prompt 渲染。

当前 `AgentPromptService` 负责把模板中的变量替换为本次运行的 `context.inputs`。

后续可以扩展：

- Agent 基础 prompt
- 岗位画像 prompt
- 知识库问答 prompt
- 工具使用约束 prompt
- 输出格式 prompt

Prompt 层只负责生成文本，不负责调用模型。

## src/runtime

Runtime 层负责构建本次 Agent 调用的外部运行上下文。

这里的 context 不是聊天消息，也不是 system prompt。

它是给工具、中间件、LangChain runtime 使用的结构化上下文。

典型字段包括：

- `thread_id`
- `allowed_tools`
- `inputs`
- `optional_features`

例如知识库检索工具需要 `knowledge_base_id`，这个值应该从 `context.inputs` 中读取，而不是让模型自己提供。

## src/middlewares

Middleware 层负责横切 Agent 执行过程。

中间件可以拦截：

- 模型调用前
- 模型调用后
- 工具调用前
- 工具调用后
- Agent 执行前后

当前已有基础中间件：

- `ToolErrorHandlerMiddleware`
- `ToolArgsInjectMiddleware`
- `ToolLoggingMiddleware`
- `MemoryPlaceholderMiddleware`

这些中间件都会声明：

```python
state_schema = CareerAgentState
```

这表示它们会参与 LangGraph state 扩展。

后续可以继续增加业务中间件，例如：

- `KnowledgePromptMiddleware`
- `JobProfilePromptMiddleware`
- `LongTermMemoryMiddleware`
- `OutputStructuringMiddleware`

## src/graph

Graph 层负责 LangGraph 相关抽象。

当前不是手写完整 `StateGraph`，而是通过 LangChain `create_agent` 使用其底层 LangGraph。

当前已经定义：

```python
class CareerAgentState(AgentState, total=False):
    tool_trace: NotRequired[list[dict[str, Any]]]
    structured_output: NotRequired[dict[str, Any]]
    profile_draft: NotRequired[dict[str, Any]]
    metadata: NotRequired[dict[str, Any]]
```

这表示平台通用 Agent state 支持：

- 工具调用轨迹
- 结构化输出
- 岗位画像草稿
- 运行元信息

后续具体业务可以继续扩展：

```python
class JobProfileState(CareerAgentState, total=False):
    job_postings_context: NotRequired[str]
    source_job_ids: NotRequired[list[int]]
    extracted_requirements: NotRequired[list[dict[str, Any]]]
```

## src/checkpoint

Checkpoint 层负责 LangGraph 状态持久化。

当前使用 PostgreSQL，不使用 Redis。

它的职责是：

- 创建 LangGraph checkpointer
- 指定 PostgreSQL 连接
- 指定 schema，例如 `agent`
- 给 `create_agent` 提供 checkpointer

需要注意：

```text
checkpointer 保存的是 LangGraph state
context_service 保存的是业务会话历史
```

两者不是一回事。

## src/context

Context 层负责业务会话历史管理。

当前通过 PostgreSQL 表保存：

- `agent.agent_conversations`
- `agent.agent_messages`

它负责：

- 创建会话
- 查询会话
- 写入用户消息
- 写入 Agent 回复
- 查询消息列表
- 把数据库消息转换成 LangChain messages

当前系统不接收 `user_id`，只通过 `conversation_id` 管理历史。

## src/templates

Templates 层负责 Agent 模板管理。

模板表使用 `agent_id` 作为稳定业务标识。

模板适合保存：

- Agent 名称
- Agent 描述
- 默认模型配置
- 默认 MCP 外接工具列表
- 默认 prompt
- 默认 optional features
- 业务自定义配置

模板配置使用 JSONB 存储，并通过 `AgentTemplateConfig` 校验 `system_prompt`、`tools`、`optional_features` 和 `runtime_options`。其中 `tools` 只允许保存 MCP 外接工具编码；规划、A2A 等内置工具通过能力参数自动挂载。同时允许额外字段，便于后续扩展。

模板服务只负责配置管理。调用方如果要基于模板运行，应先通过模板接口查询配置，再把配置展开后调用 `/agent/run`。

## src/memory

Memory 层是长期记忆能力的预留层。

当前只是占位实现。

后续可以拆成：

- 会话内上下文
- 长期用户偏好
- 长期任务记忆
- 画像类记忆

目前模型可见会话记忆由 LangGraph checkpointer 管理；`ContextService` 只负责用户可见会话记录。

## src/schemas

Schemas 层定义请求、响应和内部配置对象。

其中：

- `AgentRunRequest` 是 `/agent/run` 请求体
- `response_format` 是可选结构化输出 JSON Schema
- `AgentOptionalFeatures` 是本次运行的可选能力
- `ModelRuntimeOptions` 是模型运行参数
- `AgentBuildConfig` 是 Agent 内部装配配置
- `AgentRunResponse` 是 Agent 运行响应

`conversation_id` 非空表示持久会话：复用 checkpointer thread，并写入用户可见会话记录；`conversation_id` 为空表示临时任务调用。

## run 接口调用链路

一次 `/agent/run` 请求进入后，大致链路如下：

```text
agent_api.py
  -> AgentService.run()
    -> RuntimeContextService.build_context()
    -> ContextService.ensure_conversation()
    -> Checkpointer 根据 thread_id 恢复模型可见历史
    -> AgentService.assemble_agent()
      -> build_agent_assembly_config()
      -> PromptService.render_system_prompt()
      -> ToolService.get_tools()
      -> RuntimeContextService.get_context_schema()
      -> MiddlewareFactory.build_langchain_middlewares()
      -> CheckpointService.get_checkpointer()
      -> create_agent(response_format=...)
    -> agent.ainvoke(...)
    -> ContextService.add_user_message()
    -> ContextService.add_assistant_message()
```

## 三类上下文的区别

### messages

给模型看的对话消息。

包括：

- 用户消息
- AI 消息
- 工具消息

### runtime context

给工具和中间件看的外部业务上下文。

比如：

- 当前 Agent 是谁
- 当前 thread_id 是什么
- 本次允许哪些工具
- 本次业务输入参数是什么

### LangGraph state

给图内部流转和 checkpoint 使用的执行状态。

比如：

- 检索结果
- 岗位画像草稿
- 工具轨迹
- 结构化结果

## 当前已完成能力

当前 Agent 服务已经具备：

- 基础 API
- 模型配置读取
- OpenAI-compatible 模型创建
- 通用 Agent 装配
- 工具注册框架
- 基础 middleware 框架
- Runtime context schema
- LangGraph state schema
- PostgreSQL checkpointer
- PostgreSQL 会话历史
- Agent 模板 CRUD

## 当前未完成能力

当前还没有完成：

- 模板配置和 `/agent/run` 请求参数的调用方侧合并规范
- 业务工具返回 `Command(update=...)`
- 业务 middleware 读取 state 并注入 prompt
- 岗位画像专用 Agent
- 知识库检索工具
- 长期记忆真实实现
- 流式输出
- Agent 执行轨迹查询

## 推荐演进路线

建议后续按这个顺序推进：

1. 明确模板接口和 `/agent/run` 的边界：模板负责配置管理，run 只负责执行。
2. 实现岗位数据查询工具。
3. 定义 `JobProfileState`。
4. 实现岗位数据工具 `Command(update=...)` 写入 state。
5. 实现 `JobProfilePromptMiddleware` 注入岗位数据。
6. 实现岗位画像生成接口或编排流程。
7. 增加 Agent 执行轨迹查询能力，方便排查模型和工具行为。
8. 增加 Agent 执行轨迹查询能力，方便排查模型和工具行为。

## 设计原则

- API 层只负责接入和返回，不写业务逻辑。
- AgentService 负责编排，不直接写具体业务工具逻辑。
- Model 层统一处理模型供应商差异。
- Tool 层负责业务能力注册和筛选。
- Middleware 层负责横切模型和工具调用链路。
- Runtime context 传递外部业务参数。
- LangGraph state 保存执行中间结果。
- Checkpointer 负责图状态持久化。
- ContextService 负责用户可见会话记录。
- Templates 负责 Agent 默认配置。
