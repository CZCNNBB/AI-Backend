# A2A（Agent-to-Agent）实现方案

> 本文档描述智能体间调用（A2A）的整体设计思路与架构方案，聚焦于"如何做"，不涉及具体代码实现。
> 目标：让一个 Agent 能够以标准化方式发现、调用、协作其他 Agent。

---

## 一、目标与定位

### 1.1 解决什么问题

在多 Agent 系统中，需要解决三个核心问题：

| 问题 | 描述 |
|------|------|
| **发现** | 当前 Agent 怎么知道"世界上还有哪些 Agent 可用"？ |
| **调用** | 找到目标 Agent 后，怎么把任务交给它并拿到结果？ |
| **协作** | 调用过程中怎么支持流式、中断、上下文共享？ |

A2A 协议提供了一套**标准化的解决方案**，让 Agent 之间像调用本地函数一样互相协作，而无需关心对方的位置、实现语言、运行平台。

### 1.2 设计目标

- **协议标准化**：调用方与被调用方遵循统一的协议规范
- **能力可发现**：每个 Agent 暴露"我能做什么"的元信息
- **流式可中断**：支持任务执行过程中的实时反馈与中途打断
- **上下文隔离**：每次跨 Agent 调用都有独立的会话上下文
- **传输无关**：底层可用 HTTP、SSE、WebSocket、gRPC 等多种传输

---

## 二、整体架构

### 2.1 三层模型

```
┌──────────────────────────────────────────────────────┐
│  应用层 (Application Layer)                           │
│  - Agent 业务逻辑（LLM 推理、工具调用、Prompt 拼接）     │
│  - 把"调其他 Agent"封装为本地工具                        │
└──────────────────────────────────────────────────────┘
           ↓ 协议层
┌──────────────────────────────────────────────────────┐
│  协议层 (Protocol Layer) - A2A                         │
│  - AgentCard：智能体名片                                │
│  - Message / Part：消息结构                            │
│  - Task / TaskState：任务状态机                        │
│  - JSON-RPC 2.0：底层传输协议                          │
└──────────────────────────────────────────────────────┘
           ↓ 传输层
┌──────────────────────────────────────────────────────┐
│  传输层 (Transport Layer)                             │
│  - HTTP + SSE（流式）                                  │
│  - 服务发现                                           │
│  - 安全 / 鉴权                                        │
└──────────────────────────────────────────────────────┘
```

### 2.2 角色划分

系统中存在两类角色，**同一个进程可以同时承担**：

| 角色 | 职责 | 对外暴露 |
|------|------|---------|
| **Server（被调用方）** | 接收请求、执行任务、推送状态 | `/a2a/{agent_id}` |
| **Client（调用方）** | 发现 Agent、构造请求、订阅流 | 内部工具 / SDK |

---

## 三、核心概念设计

### 3.1 AgentCard —— 智能体"名片"

> 每个 Agent 必须对外发布一张"名片"，描述自己的身份与能力。

**关键字段**：

| 字段 | 说明 |
|------|------|
| `name` | 智能体唯一名称（全局可寻址） |
| `description` | 智能体简介（其他 Agent 用来判断"我该不该调它"） |
| `url` | 访问入口 |
| `version` | 版本号 |
| `capabilities` | 能力开关（streaming / push_notifications / interruptible） |
| `skills` | 技能列表（可被发现的"我能干的事"） |
| `default_input_modes` | 默认输入类型（text / file / data） |
| `default_output_modes` | 默认输出类型 |

**发布方式**：标准路径 `GET /a2a/{agent_id}/.well-known/agent-card.json`

### 3.2 Message —— 消息结构

A2A 的消息是**多模态**的，由若干个 `Part` 组成：

```
Message
├── role: "user" | "agent"
├── parts: [
│   ├── TextPart      文本
│   ├── FilePart      文件（图片、PDF 等）
│   └── DataPart      结构化数据（变量、配置）
│ ]
├── contextId         所属会话上下文
├── messageId         消息唯一ID
└── metadata          透传元数据（如 user_id、trace_id）
```

> **设计亮点**：一个消息可以同时携带"问题 + 图片 + 变量"，调用方无需拆成多次请求。

### 3.3 Task 与状态机

> 一次"调用其他 Agent"被建模为一个 Task，有完整的生命周期。

```
┌──────────┐
│ submitted│  (Task 被创建)
└─────┬────┘
      ↓
┌──────────┐
│ working  │ ←──── 持续推送中间状态（流式输出、进度更新）
└─────┬────┘
      ↓
      ├──→ ┌─────────────┐
      │    │input_required│ (需要用户补充信息，可恢复)
      │    └──────┬──────┘
      │           ↓ (用户提供输入后)
      │           └──→ 回到 working
      ↓
┌────────────┐
│ completed  │  (任务完成，附带 artifact)
└────────────┘

异常分支：canceled / failed
```

**事件类型**：

| 事件 | 含义 |
|------|------|
| `TaskStatusUpdateEvent` | 状态变化（如 `working` → `input_required`） |
| `TaskArtifactUpdateEvent` | 增量产物（如流式文本片段） |
| `Task` | 完整任务对象（首次创建或最终交付） |

### 3.4 AgentSkill —— 技能描述

> Agent 把自己"能干的事"声明为 Skill，便于 LLM 在决策时匹配。

**示例**：

```yaml
skills:
  - id: quarterly-report
    name: 季度财报分析
    description: 根据上传的财报 PDF 回答营收、利润、增长率等问题
    examples:
      - "Q3 营收多少？"
      - "对比 Q2 和 Q3 的净利润"
    inputModes: [text, file]
    outputModes: [text]
```

> **设计亮点**：这些 Skill 信息会被拼到主 Agent 的系统提示词里，**LLM 自己会决定何时调用哪个 Skill**。

---

## 四、协议流程设计

### 4.1 一次性调用（Request/Response）

```
Client                                    Server
  │                                          │
  │  1. POST /a2a/{agent_id}                 │
  │     { jsonrpc: "2.0",                    │
  │       method: "message/send",            │
  │       params: { message: {...} } }       │
  │─────────────────────────────────────────→│
  │                                          │
  │                                   2. 创建 Task
  │                                   3. 执行业务逻辑
  │                                          │
  │  4. Response:                            │
  │     { result: {                          │
  │         id,                              │
  │         status: { state: "completed" },  │
  │         artifacts: [{...}]               │
  │     } }                                  │
  │←─────────────────────────────────────────│
```

### 4.2 流式调用（Streaming）

```
Client                                    Server
  │                                          │
  │  1. POST /a2a/{agent_id}                 │
  │     { method: "message/stream", ... }    │
  │─────────────────────────────────────────→│
  │                                          │
  │  2. SSE: TaskStatusUpdateEvent(working)  │
  │←─────────────────────────────────────────│
  │                                          │
  │  3. SSE: TaskArtifactUpdateEvent(chunk1) │
  │←─────────────────────────────────────────│
  │                                          │
  │  4. SSE: TaskArtifactUpdateEvent(chunk2) │
  │←─────────────────────────────────────────│
  │                                          │
  │  5. SSE: TaskStatusUpdateEvent(completed)│
  │←─────────────────────────────────────────│
```

### 4.3 中断-恢复流程

```
Client                Server              User
  │                      │                  │
  │  send message        │                  │
  │─────────────────────→│                  │
  │                      │ LLM 思考         │
  │  input_required      │ 想问用户         │
  │  (metadata: 问题)    │                  │
  │←─────────────────────│                  │
  │                      │                  │
  │ 展示问题给用户 ──────────────────────→  │
  │                      │                  │
  │                      │   用户回复       │
  │←────────────────────────────────────────│
  │                      │                  │
  │  send message        │                  │
  │  (contextId, 用户回复)│                  │
  │─────────────────────→│                  │
  │                      │ 继续执行          │
  │  working ...         │                  │
  │←─────────────────────│                  │
  │  completed           │                  │
  │←─────────────────────│                  │
```

---

## 五、模块划分

### 5.1 服务端（被调用方）模块

| 模块 | 职责 |
|------|------|
| **AgentRegistry** | 维护 Agent 列表，构造 AgentCard |
| **AgentExecutor** | 任务执行入口（开发者主要实现这里） |
| **RequestHandler** | JSON-RPC 协议解析与分发 |
| **TaskStore** | 任务状态存储（内存 / 持久化） |
| **PushNotificationSender** | 异步通知（WebHook） |
| **ProtocolAdapter** | 把业务事件 → A2A 协议事件 |

### 5.2 客户端（调用方）模块

| 模块 | 职责 |
|------|------|
| **AgentCardResolver** | 解析 Agent 名 → 拿到 AgentCard 与 URL |
| **MessageBuilder** | 构造符合协议的 Message |
| **A2AClient** | 发送请求（一次性 / 流式） |
| **EventProcessor** | 处理响应事件（状态、产物、中断） |
| **ToolAdapter** | 把 A2A 客户端能力封装为本地工具 |

### 5.3 公共模块

| 模块 | 职责 |
|------|------|
| **Type Definitions** | Pydantic 模型（Message、Task、Event 等） |
| **Utils** | MIME 推断、ID 生成、文本提取等 |

---

## 六、关键设计决策

### 6.1 服务端："惰性注册" vs "启动注册"

**方案 A：启动时注册一次**（简单）
```
进程启动 → 加载所有 Agent → 挂载到路由
```

**方案 B：每次请求时注册**（灵活，本项目采用）
```
请求到达 → 加载该 Agent 最新配置 → 构造 App → 处理请求
```

**优劣对比**：

| 维度 | 启动注册 | 惰性注册 |
|------|---------|---------|
| 性能 | 高（一次） | 略低（每次） |
| 配置变更 | 需重启 | 立即生效 |
| 内存 | 常驻 | 一次性 |
| 实现复杂度 | 低 | 中 |

> **选型建议**：Agent 配置变更频繁时用"惰性注册"；Agent 数量少且稳定时用"启动注册"。

### 6.2 客户端："精确匹配" vs "模糊匹配"

Agent 路由时存在名称解析问题：

```
LLM 调用：send_message("财务助手", "...")
实际注册名：finance_agent
```

**方案 A：精确匹配**（简单）
- 名称必须完全一致
- 失败率高

**方案 B：Embedding 模糊匹配**（本项目采用）
- 名称不匹配时，用 Embedding 算相似度
- 阈值（如 0.6）以上视为匹配
- 容错性强

**降级链设计**：
```
精确匹配
   ↓ 失败
Embedding 相似度匹配（≥ 0.6）
   ↓ 失败
返回明确错误
```

### 6.3 上下文隔离：单 ID vs 多 ID

**方案 A：单 ID（共享）**
- 所有子 Agent 调用共享主 Agent 的 conversation_id
- 实现简单，但子 Agent 之间会"串台"

**方案 B：多 ID（隔离）**（本项目采用）
- 主会话：`conversation_id`（thread_id）
- 子会话：`context_id`（A2A contextId）
- 维护 `context_id ↔ conversation_id` 的映射

**为何要隔离**：
- 同一主对话里多次调同一个子 Agent，需要独立会话状态
- 不同子 Agent 之间互不干扰
- 子 Agent 重启后能从 context 恢复

### 6.4 中断透传：本地 vs 跨 Agent

**关键问题**：子 Agent 想问用户澄清问题，怎么传到主 Agent、再传到前端？

**方案**：把中断信息作为 ToolMessage 的 artifact 透传

```
子 Agent 内部：
   LLM 想问用户 → yield {require_user_input: True, metadata: {question, options}}
   ↓ 映射
   A2A TaskStatusUpdateEvent(input_required, metadata=...)
   ↓ 透传
主 Agent 工具 send_message 收到：
   interrupt_data = result.metadata
   ↓ 包装
   ToolMessage(content={is_interrupt: True, interrupt_data: {...}})
   ↓ 业务流
   前端：弹窗让用户选
   ↓ 用户回复
   下次 send_message 把用户回复带过去
```

---

## 七、数据流图

### 7.1 端到端时序

```
┌────┐    ┌──────┐    ┌────┐    ┌────┐    ┌──────┐    ┌────┐
│用户│    │主引擎│    │LLM │    │Tool│    │客户端│    │远端│
└─┬──┘    └──┬───┘    └──┬─┘    └──┬─┘    └──┬───┘    └─┬──┘
  │ 提问     │            │         │         │          │
  │─────────→│            │         │         │          │
  │          │ 调用 LLM   │         │         │          │
  │          │───────────→│         │         │          │
  │          │            │ 决定调  │         │          │
  │          │            │ send_msg│         │          │
  │          │            │────────→│         │          │
  │          │            │         │ 找 Agent│          │
  │          │            │         │────────→│          │
  │          │            │         │         │ 发送请求 │
  │          │            │         │         │─────────→│
  │          │            │         │         │          │ 执行业务
  │          │            │         │         │ 流式回包 │
  │          │            │         │         │←─────────│
  │          │            │         │ 接收响应│          │
  │          │            │         │←────────│          │
  │          │            │ 返回结果│         │          │
  │          │            │←────────│         │          │
  │          │ 再次调 LLM  │         │         │          │
  │          │───────────→│         │         │          │
  │          │  最终回答   │         │         │          │
  │←─────────│            │         │         │          │
  │          │            │         │         │          │
```

### 7.2 内部数据转换

```
┌─────────────────────────────────────────────────────┐
│ LangGraph 事件 (values / messages / custom)         │
└──────────────────────┬──────────────────────────────┘
                       ↓ [服务端] 状态机映射
┌─────────────────────────────────────────────────────┐
│ A2A 事件 (TaskStatusUpdate / TaskArtifactUpdate)    │
└──────────────────────┬──────────────────────────────┘
                       ↓ [传输] SSE
┌─────────────────────────────────────────────────────┐
│ JSON-RPC 2.0 响应流                                  │
└──────────────────────┬──────────────────────────────┘
                       ↓ [客户端] 事件解析
┌─────────────────────────────────────────────────────┐
│ ToolMessage (LangChain 工具结果)                     │
└──────────────────────┬──────────────────────────────┘
                       ↓ [业务流] LLM 二次推理
┌─────────────────────────────────────────────────────┐
│ 最终给用户的回答                                     │
└─────────────────────────────────────────────────────┘
```

---

## 八、与 LLM 框架的集成

### 8.1 核心思路："协议即工具"

> 把 A2A 客户端能力**伪装成一个 LangChain / LangGraph 工具**，让 LLM 自己决定何时调用。

**工具签名**：

```
send_message(agent_name: str, message: str) -> ToolMessage
```

**工具内部完成**：
1. 解析 `agent_name`（精确 / 模糊匹配）
2. 构造 A2A Message
3. 发送请求（流式）
4. 处理响应事件
5. 实时进度反馈（通过 `stream_writer`）
6. 中断信息透传
7. 返回最终结果

**对 LLM 的提示词注入**：

```
# 协作指令
- 你是 host_agent，可调用的协作者有：
  • finance_agent: 处理财务相关问题
  • kb_agent: 知识库问答
- 当用户问题超出你的能力时，调用 send_message
- 调用 send_message 后必须把结果转述给用户
- 不要征求用户许可才能与远程 agent 交互
- 多 agent 协作时直接串联，不要分多轮
```

### 8.2 服务端集成："执行器即业务入口"

> 把"接收到 A2A 请求"映射为"调用本引擎的 LangGraph Agent"。

**执行器职责**：

```
A2AAgentExecutor.execute(context, event_queue):
    1. 解析入参 (query / files / variables / metadata)
    2. 加载本 Agent 配置
    3. 调用 LangGraph Agent（流式）
    4. 把 LangGraph 事件映射为 A2A 状态机:
         - LLM 思考中       → TaskState.working
         - 工具调用中       → TaskState.working + message
         - 需要用户澄清     → TaskState.input_required + metadata
         - 任务完成         → TaskState.completed + artifact
    5. 异常处理 (failed / canceled)
```

---

## 九、能力扩展点

### 9.1 短期（MVP）

- [ ] HTTP + SSE 流式传输
- [ ] AgentCard 发布与发现
- [ ] Task 状态机基本实现（working / completed / failed）
- [ ] 精确匹配 + Embedding 模糊匹配
- [ ] 上下文隔离（context_id）
- [ ] 简单中断透传

### 9.2 中期

- [ ] Push Notification（WebHook 异步通知）
- [ ] 任务持久化（PostgreSQL / Redis）
- [ ] 鉴权与限流
- [ ] 多模态 Part（FilePart / DataPart）
- [ ] 流式断点续传
- [ ] 监控埋点（Trace / Metric）

### 9.3 长期

- [ ] 联邦发现（跨集群 Agent 发现）
- [ ] 安全沙箱（隔离执行）
- [ ] 智能路由（基于任务画像自动选 Agent）
- [ ] 协商协议（Agent 之间讨价还价）
- [ ] 成本控制（按调用次数 / Token 计费）

---

## 十、风险与应对

| 风险 | 影响 | 应对 |
|------|------|------|
| **循环调用** | A → B → A 死循环 | 加调用深度限制 / 调用链追踪 |
| **超时** | 远端 Agent 长时间不响应 | 客户端超时 + 服务端心跳 |
| **状态不一致** | Task 状态与服务端实际不符 | 定期同步 + 强制刷新接口 |
| **配置漂移** | 多个 Agent 版本不一致 | 强制版本号 + 灰度发布 |
| **资源耗尽** | 大量并发任务 | Task 队列 + 限流 |

---

## 十一、落地建议

### 11.1 技术选型参考

| 组件 | 推荐 | 备选 |
|------|------|------|
| 协议实现 | Google `a2a-sdk` | 自研（参考规范） |
| 传输 | HTTP + SSE | gRPC / WebSocket |
| 序列化 | JSON（JSON-RPC 2.0） | Protobuf |
| 任务存储 | PostgreSQL | Redis / 内存 |
| 服务发现 | Nacos | Consul / etcd |
| LLM 框架 | LangChain + LangGraph | LlamaIndex / 自研 |

### 11.2 演进路径

```
Phase 1 - 单机版
   ├── 一个进程同时跑 Server + Client
   ├── 内存 TaskStore
   └── 同步调用（先跑通）

Phase 2 - 分布式
   ├── 多实例部署
   ├── 持久化 TaskStore
   └── 流式 + Push Notification

Phase 3 - 规模化
   ├── 联邦发现
   ├── 限流 / 鉴权
   └── 监控 / 告警

Phase 4 - 智能化
   ├── 智能路由
   ├── 自适应负载均衡
   └── 成本优化
```

---

## 十二、总结

A2A 的本质是**把"Agent 调用"这件事标准化**：

| 抽象层 | 解决的问题 |
|--------|-----------|
| **AgentCard** | "你是谁，能干啥" |
| **Message / Part** | "我们怎么说话" |
| **Task / TaskState** | "任务生命周期怎么管" |
| **JSON-RPC 2.0** | "底层怎么传" |
| **Tool Adapter** | "LLM 怎么用" |

设计原则：
- **协议与传输解耦**：未来可以换 gRPC
- **状态显式化**：所有变化都通过事件表达
- **可降级**：每一步失败都有兜底
- **可观测**：全链路日志、Trace、Metric

> **一句话**：A2A 让 Agent 之间像调用本地函数一样简单，但又不失工业级的可靠性、可观测性、可扩展性。
