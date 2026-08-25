# Agent A2A 优化方案

## 1. 背景

当前项目已经实现了一个轻量版 A2A 能力：主 Agent 可以通过 `a2a_call` 工具调用子 Agent，子 Agent 的模板由 `agent_templates` 管理，并通过 `is_sub_agent=true` 声明自己允许被其他 Agent 调用。

这套实现不使用 `a2a-sdk`，也暂时不实现完整 A2A 协议。我们的目标是保留 A2A 的核心价值：让一个主 Agent 在必要时调用其他专用 Agent 完成子任务，同时保证执行链路可控、可追踪、不会污染主会话。

参考 `agent_engine` 后，当前方案需要重点优化两件事：

1. 子 Agent 必须和主 Agent 的会话状态隔离。
2. 子 Agent 调用过程需要有轻量映射记录，方便排查和后续可视化。

## 2. agent_engine 中值得参考的点

`agent_engine` 的 A2A 实现比较完整，包含 A2A 协议服务、AgentCard、远程连接、流式回传、中断恢复等能力。我们当前不照搬完整实现，只参考它的关键设计思想。

### 2.1 主会话和子会话隔离

`agent_engine` 不让子 Agent 的内部执行直接复用主 Agent 的 `conversation_id`。

它的思路是：

```text
主 Agent conversation_id
  -> 主 Agent 自己的 thread_id

子 Agent context_id
  -> 子 Agent 自己的 thread_id
```

这样主 Agent 和子 Agent 的状态不会串在一起。我们当前项目进一步要求：A2A 子 Agent 不落 PostgreSQL checkpointer。

### 2.2 子 Agent 默认关闭长期记忆

`agent_engine` 的 A2A 子 Agent 运行时会使用 `RuntimeContextConfig(memory_enabled=False)`。

这说明 A2A 子 Agent 默认不应该读取或写入用户长期记忆。子 Agent 只应该基于本次传入的任务上下文执行，不应该把主 Agent 用户的长期偏好、历史习惯带进去。

### 2.3 维护 context 映射

`agent_engine` 会维护类似：

```text
context_id -> conversation_id -> agent_name
```

这个映射不是为了让子 Agent 共享主会话，而是为了追踪、中断恢复和问题排查。

我们当前虽然暂时不做中断恢复，但仍然需要保留一份轻量映射，记录主 Agent 本轮调用了哪些子 Agent、输入是什么、输出是什么、是否成功。

### 2.4 中间件负责注入上下文，工具负责执行调用

`agent_engine` 中 A2A 相关能力不是全塞到工具里：

- 中间件负责筛选可用子 Agent，并把可用子 Agent 信息注入提示词。
- 工具负责真正发送消息、接收结果、把结果写回 Agent 状态。

我们当前项目的分层和这个方向一致：

- `A2AAgentContextMiddleware`：注入可调用子 Agent 信息。
- `a2a_call`：执行子 Agent 调用。

## 3. 我们当前 A2A 的目标边界

第一版 A2A 不做完整协议，只做平台内部轻量调用。

### 3.1 要做的

- 主 Agent 可以调用指定子 Agent。
- 子 Agent 必须通过 `is_sub_agent=true` 才能被调用。
- 子 Agent 调用必须在本次 `a2a.sub_agent_list` 白名单内。
- 子 Agent 的运行记录归属主 Agent 的 `conversation_id`，但内部执行使用独立 `sub_thread_id`。
- 子 Agent 不启用长期记忆。
- 子 Agent 不允许继续调用其他子 Agent。
- 每次子 Agent 调用生成独立 `sub_thread_id`。
- 每次调用写入映射表，用于追踪和排查。

### 3.2 暂时不做的

- 不使用 `a2a-sdk`。
- 不发布 AgentCard 标准协议。
- 不做远程 Agent 发现。
- 不做子 Agent 流式回传。
- 不做中断恢复。
- 不做子 Agent 递归调用子 Agent。
- 不复用子 Agent 上一次的 `sub_thread_id`。

## 4. 推荐运行模型

推荐把一次 A2A 调用理解成主 Agent 本轮执行中的一个子任务。主 Agent 和子 Agent 都属于“Agent 运行”，因此统一写入 `agent_runs`。

```text
/agent/run
  conversation_id = 用户会话 ID
  run_id = 本次主 Agent 运行 ID
  agent_runs.run_type = main

主 Agent 执行
  -> 模型决定调用 a2a_call
  -> a2a_call 创建 sub_run_id 和 sub_thread_id
  -> 写入 agent_runs(run_type=sub, parent_run_id=主 Agent run_id, status=running)
  -> 子 Agent 使用 sub_thread_id 执行，但不挂 PostgreSQL checkpointer
  -> 子 Agent 返回结果
  -> 回写 agent_runs(status=success/failed, answer/error_message)
  -> 主 Agent 整合子 Agent 结果
```

关键点：

`sub_thread_id` 只用于本次子 Agent 内部执行，不作为下一次调用的会话 ID 复用，也不写入 LangGraph checkpoint。

`sub_run_id` 是子 Agent 在 `agent_runs` 中的运行 ID，用于追踪子任务本身。

## 5. 数据库设计建议

运行记录统一使用一张表：`agent_runs`。

### 5.1 表职责

`agent_runs` 用于记录主 Agent 和子 Agent 的完整运行链路。

它不是用户可见聊天记录表。用户可见聊天记录仍然由 `agent_conversations` 和 `agent_messages` 负责。

它主要服务于：

- 调试问题。
- 查看 Agent 执行链路。
- 后续做 Agent 运行过程可视化。
- 后续分析主 Agent / 子 Agent 的成功率、耗时、错误率。

### 5.2 核心字段

```sql
run_id          -- 本次运行 ID
run_type        -- main=主 Agent，sub=A2A 子 Agent
parent_run_id   -- 父级 Agent run_id，子 Agent 用它关联主 Agent
agent_id        -- 当前运行的 Agent 模板 ID
conversation_id -- 用户会话 ID，子 Agent 记录父级会话 ID
query           -- 本次运行输入
answer          -- 本次运行最终输出
status          -- running/success/failed
error_message   -- 失败原因
elapsed_ms      -- 运行耗时
metadata        -- 扩展元数据
```

### 5.3 查询链路

查询一次主 Agent 运行和它触发的子 Agent 运行：

```sql
SELECT *
FROM agent.agent_runs
WHERE run_id = :run_id
   OR parent_run_id = :run_id
ORDER BY started_at;
```

## 6. 代码层优化建议

### 6.1 统一使用 AgentRunService

不再新增独立的子运行服务。主 Agent 和子 Agent 都通过 `AgentRunService` 写入 `agent_runs`。

职责：

- 创建主 Agent 运行记录。
- 创建 A2A 子 Agent 运行记录。
- 更新 Agent 输出。
- 标记成功或失败。
- 后续提供运行链路查询接口。

### 6.2 A2A 工具调用流程

`a2a_call` 建议调整成下面流程：

```text
1. 从 runtime.context 读取 parent_run_id 和 conversation_id
2. 校验 agent_id 是否在 a2a_sub_agent_list 中
3. 查询 agent_templates，确认 is_sub_agent=true
4. 生成 sub_run_id 和 sub_thread_id
5. 写入 agent_runs(run_type=sub, status=running)
6. 构造 AgentRunRequest
   - conversation_id=sub_thread_id，仅用于构造子 Agent 内部 thread_id
   - long_term_memory_enabled=False
   - a2a=None
   - stream=False
   - stateless=True
7. 调用子 Agent：AgentService().run(sub_request, db=None)
8. 成功则回写 agent_runs.answer/status=success
9. 失败则回写 agent_runs.error_message/status=failed
10. 返回子 Agent 输出给主 Agent
```

这里有一个关键取舍：

- 子 Agent 不写用户可见会话记录，所以调用 `AgentService.run(sub_request, db=None)`。
- 子 Agent 不落 PostgreSQL checkpointer，所以设置 `runtime_options.stateless=True`。
- 子 Agent 的执行追踪写入 `agent_runs(run_type=sub)`，不依赖 LangGraph checkpoint。

第一版推荐：

```python
sub_request = AgentRunRequest(
    query=query,
    conversation_id=sub_thread_id,  # 仅作为子 Agent 内部 thread_id，不落 checkpoint
    stream=False,
    system_prompt=config.system_prompt,
    response_format=config.response_format,
    tools=list(config.tools or []),
    optional_features=AgentOptionalFeatures(long_term_memory_enabled=False),
    runtime_options=config.runtime_options.model_copy(update={"stateless": True}),
    a2a=None,
)

response = await AgentService().run(sub_request, db=None)
```
## 7. 中间件优化建议

当前 `A2AAgentContextMiddleware` 已经可以把 `a2a_sub_agent_list` 对应的子 Agent 信息注入 system prompt。

后续可以参考 `agent_engine` 的 `SubagentFilterMiddleware`，增加一个可选能力：先让轻量模型判断当前问题是否真的需要调用子 Agent。

第一版不建议做自动筛选，因为会增加一次模型调用成本。

可以先保持：

```text
前端/编排层传入 a2a.sub_agent_list
  -> 中间件全部注入
  -> 主 Agent 自己决定是否调用
```

第二阶段再加：

```text
sub_agent_filter_enabled=true
  -> 轻量模型判断是否需要子 Agent
  -> 过滤 a2a_sub_agent_list
  -> 再注入 system prompt
```

## 8. API 层建议

`/agent/run` 请求可以保持当前形态：

```json
{
  "query": "请分析这个岗位画像，并让技能分析 Agent 帮我检查技能结构是否合理",
  "conversation_id": "conv_001",
  "tools": [],
  "a2a": {
    "sub_agent_list": ["skill_analysis_agent"]
  }
}
```

调用方不需要显式传 `a2a_call` 工具。只要 `a2a.sub_agent_list` 非空，AgentAssembler 自动装配 A2A 工具。

## 9. 查询接口建议

后续可以提供统一运行记录查询接口：

```text
POST /agent/runs/search
POST /agent/runs/detail
POST /agent/runs/chain
```

查询条件：

- run_id
- run_type
- parent_run_id
- agent_id
- status

其中 `/agent/runs/chain` 可以按主 Agent 的 `run_id` 查询完整执行链路：主 Agent 运行记录 + 它触发的所有子 Agent 运行记录。

## 10. 分阶段落地

### 第一阶段：统一运行表和隔离执行

- 使用 `agent_runs` 同时记录主 Agent 和子 Agent。
- 新增 `run_type` 区分 `main` 和 `sub`。
- 新增 `parent_run_id` 串联主子 Agent 执行链路。
- A2A 工具生成 `sub_run_id` 和 `sub_thread_id`。
- A2A 工具写入 running/success/failed。
- 子 Agent 强制关闭长期记忆。
- 子 Agent 禁止递归 A2A。
- 子 Agent 不写用户可见会话记录。

### 第二阶段：排查接口

- 增加运行记录查询接口。
- 支持按主 run、子 Agent、状态查询。
- 返回 Agent 输入、输出、错误、耗时。

### 第三阶段：运行事件明细

- 当前第一版已经启用 `stateless=True`。
- 后续如需查看子 Agent 内部工具调用细节，可扩展 `agent_run_events`。
- `agent_run_events` 可记录模型开始、工具调用、工具返回、模型结束等事件。

### 第四阶段：智能子 Agent 筛选

- 参考 `agent_engine` 的 `SubagentFilterMiddleware`。
- 增加可选的子 Agent 意图识别。
- 自动过滤无关子 Agent，降低误调用概率。

## 11. 当前推荐结论

当前项目最适合采用轻量 A2A：

```text
不用 a2a-sdk
保留 a2a.sub_agent_list
保留 A2A 中间件注入
保留 a2a_call 工具
统一使用 agent_runs 记录主 Agent 和子 Agent
每次子 Agent 调用生成新的 sub_run_id 和 sub_thread_id
子 Agent 运行记录归属主 conversation_id，但内部执行不复用主 conversation_id
子 Agent 强制关闭长期记忆
子 Agent 不允许递归调用
子 Agent 不落 PostgreSQL checkpointer
```

这样既能保持实现简单，又能保留后续排查和可视化所需的执行链路。