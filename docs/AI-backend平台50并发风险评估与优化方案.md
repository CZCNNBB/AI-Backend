# AI-backend 平台 50 并发风险评估与优化方案

## 1. 文档目的

本文基于 AI-backend 当前代码实现，对约 50 个并发 Agent 运行时的容量、稳定性和潜在故障进行评估，并给出上线前的优化顺序与压测方案。

本文所说的“50 并发”特指 50 个 Agent 在同一时间持续运行，而不是 50 个用户登录平台或偶尔发送请求。一个 Agent 运行可能持续几十秒到数分钟，并可能包含多轮模型推理、MCP 工具调用、知识库检索、Checkpointer 写入或 A2A 子 Agent 调度，因此其资源消耗远高于普通 HTTP 接口。

## 2. 评估结论

当前版本能够接收 50 个 HTTP/SSE 连接，但不能可靠保证 50 个 Agent 同时运行完成。

如果 50 个请求同时进行持续流式推理，尤其同时启用持久化会话、MCP、知识库或 A2A，当前实现存在以下高概率风险：

- PostgreSQL 连接池耗尽。
- LangGraph Checkpointer 单连接排队或并发异常。
- MCP 平台收到大量重复的 `tools/list` 请求。
- 模型服务触发并发、RPM 或 TPM 限制，返回 429 或超时。
- 重试进一步放大模型和外部服务压力。
- 同一个会话并发运行时出现消息乱序或状态冲突。
- 知识库检索在线程池中排队，首 Token 时间明显增加。

当前阶段可以先把约 10 个同时运行的普通 Agent 作为试运行目标。达到可靠的 50 个活跃 Agent 并发前，至少需要完成本文 P0 级别的改造，并通过包含真实 Agent 链路的压力测试。

## 3. 并发场景定义

不同场景的压力并不相同：

| 场景 | 当前判断 | 主要风险 |
| --- | --- | --- |
| 50 个用户在线，但只有 5～10 个 Agent 同时运行 | 大概率可用 | 模型服务稳定性 |
| 50 个无会话、无工具的短 Agent 同时运行 | 可能完成 | 模型并发和限流 |
| 50 个持久化会话同时进行 SSE 流式运行 | 高风险 | 数据库连接池、Checkpointer |
| 50 个 Agent 同时使用 MCP 工具 | 高风险 | 重复工具发现、MCP 并发、模型重试 |
| 50 个 Agent 同时使用知识库 | 高风险 | 线程池、Milvus、Embedding、Reranker |
| 50 个主 Agent 同时执行 A2A | 极高风险 | 子 Agent 放大实际模型调用量 |
| 同一个 `conversation_id` 同时发送多个请求 | 数据一致性风险 | Checkpoint 冲突、消息乱序 |

## 4. 当前架构中的主要瓶颈

### 4.1 PostgreSQL 连接池上限

当前 SQLAlchemy 引擎配置为：

```python
pool_size=10
max_overflow=20
```

因此单个 Web 进程最多同时使用 30 条 SQLAlchemy 数据库连接。

当前 `/agent/messages` 接口通过 FastAPI 依赖注入创建同步 SQLModel Session，并将其传入流式事件生成器。Session 的生命周期会覆盖整个 SSE 响应过程。

Session 在执行 `commit()` 后可能暂时归还连接，但 Agent 组装阶段仍然会读取 Agent 模板、模型配置、MCP 工具和子 Agent 信息。最后一次只读查询会开启新的数据库事务；如果没有及时 `commit()`、`rollback()` 或关闭 Session，数据库连接可能一直保留到流式响应结束。

50 个长时间运行的 Agent 可能出现以下过程：

```text
前 30 个请求获得数据库连接
        │
        ▼
后 20 个请求等待连接池
        │
        ▼
等待超过 pool_timeout
        │
        ▼
抛出 QueuePool Timeout
```

可能出现的典型错误包括：

```text
QueuePool limit of size 10 overflow 20 reached
connection timed out
```

#### 建议改造

流式执行过程不应长期持有业务数据库 Session，应拆成短事务：

```text
运行开始
  → 打开 Session
  → 读取 Agent 配置并创建运行记录
  → commit/rollback
  → 关闭 Session

LLM/MCP/SSE 流式执行
  → 不持有业务数据库连接

运行结束或失败
  → 重新打开 Session
  → 写入消息并更新运行状态
  → commit/rollback
  → 关闭 Session
```

不能只通过增大 `pool_size` 解决问题。连接池盲目扩大可能将故障转移到 PostgreSQL 的 `max_connections`、内存和锁竞争。

### 4.2 Checkpointer 使用进程级单连接

当前 PostgreSQL Checkpointer 使用：

```python
AsyncPostgresSaver.from_conn_string(...)
```

并将返回的 Saver 保存为进程级单实例。所有持久化会话会共享该实例及其底层连接。

50 个持久化 Agent 同时读写 Checkpoint 时可能出现：

- Checkpoint 操作在单连接上串行排队。
- Checkpoint 读写延迟不断升高。
- 底层连接不支持同一时刻的多个命令时产生并发异常。
- 单连接中断导致大量活跃会话同时失败。

第一次调用 `get_checkpointer()` 时当前也没有异步初始化锁。多个请求同时首次进入时，可能重复创建连接、重复执行 `setup()`，并覆盖进程内保存的上下文对象。

#### 建议改造

- 使用 PostgreSQL 异步连接池承载 Checkpointer。
- 在 FastAPI lifespan 启动阶段完成 Checkpointer 初始化和表结构检查。
- 初始化过程增加 `asyncio.Lock`，避免重复初始化。
- 应用退出时优雅关闭 Checkpointer 连接池。
- 设置独立的 Checkpointer 最小和最大连接数。
- 监控 Checkpoint 获取连接、读取和写入耗时。

### 4.3 MCP 工具定义在每次运行时重新发现

Agent 每次装配 MCP 工具时都会创建 `MultiServerMCPClient`，并执行：

```python
await client.get_tools()
```

如果 50 个 Agent 使用同一个 MCP 服务，将产生约 50 次重复工具发现请求，然后才进行实际的工具调用。

这会导致：

- Agent 首 Token 时间增加。
- MCP 平台承受大量没有业务价值的 `tools/list` 请求。
- MCP 客户端和 HTTP 连接反复创建。
- MCP 平台短暂不可用时，所有 Agent 装配同时失败。

#### 建议改造

缓存 MCP 工具定义和转换后的 LangChain Tool：

```text
缓存键：base_url + transport + auth摘要 + 工具版本
缓存值：MCP Tool Schema 或 LangChain Tool 定义
```

缓存失效条件：

- 管理员手动同步 MCP 工具。
- MCP 平台发布或停用工具。
- 工具配置发生变更。
- 缓存 TTL 到期。

Agent 运行时应优先从缓存装配工具，不应每次都调用远端 `tools/list`。

### 4.4 缺少并发限制和背压

当前没有看到全局、模型级、MCP 服务级或用户级并发闸门。请求进入后会直接调用模型、MCP、Milvus、Embedding、Reranker 或 A2A 子 Agent。

如果外部模型只允许 20 个并发，而平台同时放入 50 个请求，可能发生：

```text
模型返回 429
    │
    ▼
LangChain 自动重试
    │
    ▼
实际请求数量进一步增加
    │
    ▼
更多 429、超时和连接占用
```

A2A 会放大这一问题。50 个主 Agent 并不等于 50 个模型调用；主 Agent 调用子 Agent 后，实际活跃模型调用可能达到 100 个或更多。

#### 建议改造

增加以下限流器或 Semaphore：

- 全局活跃 Agent 上限。
- 单模型并发上限。
- 单 MCP 服务并发上限。
- 单用户或单租户并发上限。
- 单会话同时运行上限。
- 等待队列长度上限。

队列已满时应快速返回 `429` 或 `503`，并携带 `Retry-After`，不能无限等待。

第一阶段可以从保守值开始，例如：

```text
全局活跃 Agent：20
单模型并发：10～15
单 MCP 服务并发：20
单用户并发：2
同一会话并发：1
```

最终数值必须根据模型服务配额、服务器资源和压力测试结果调整。

### 4.5 当前 Uvicorn 启动方式属于开发模式

当前直接启动方式使用：

```python
workers=1
reload=True
```

该配置适合本地开发，不适合生产环境。

生产环境应至少满足：

- `reload=False`。
- 优先部署在 Linux。
- 使用多个 Uvicorn Worker 或多个容器实例。
- 通过 Nginx 或 API Gateway 代理 SSE。
- 配置足够长的上游响应超时。
- 关闭 SSE 响应缓冲。
- 支持优雅停机和连接排空。

不能直接把 Worker 数量增加到 4 而不调整数据库连接池。每个 Worker 都会创建自己的 SQLAlchemy 连接池、Checkpointer、MCP 缓存和知识入库 Worker。

数据库连接预算应满足：

```text
Web Worker 数量
× 每进程 SQLAlchemy 最大连接数
+ Checkpointer 连接池总数
+ 知识入库 Worker 连接
+ 运维和管理连接预留
< PostgreSQL max_connections 安全值
```

例如 4 个进程继续使用每进程最多 30 条连接，理论上仅 SQLAlchemy 就可能消耗 120 条连接。

知识入库 Worker 后续应考虑从 Web 进程拆分为独立进程，避免每个 Web Worker 都启动一组后台任务。

### 4.6 同一会话缺少并发互斥

`conversation_id` 当前也是 LangGraph Checkpointer 使用的 `thread_id`。如果同一会话同时收到两个请求，两次运行可能读取同一份旧状态并并发写入新状态。

可能出现：

- 消息顺序错乱。
- Checkpoint 分支或版本冲突。
- 一个运行覆盖另一个运行的状态。
- 中断恢复找到错误的运行记录。
- 同一个新会话并发创建时触发唯一键错误。
- 前端同时显示两条交叉输出的回答。

#### 建议改造

同一个 `conversation_id` 同一时刻只允许一个活跃运行：

```text
conversation_id 已存在 running/interrupted 处理任务
        │
        ▼
新请求返回 409 或进入受控队列
```

单进程内存锁只能作为开发阶段方案。多 Worker 或多实例部署应使用：

- PostgreSQL advisory lock。
- Redis 分布式锁。
- 数据库运行状态唯一约束。

### 4.7 模型客户端和外部模型容量

当前每次 Agent 装配都会根据数据库模型配置重新创建 ChatModel。这样做逻辑简单，但会降低底层 HTTP 连接复用效率，并增加连接建立和对象创建开销。

模型服务通常是整个平台最终的吞吐瓶颈，容量受以下因素影响：

- 模型接口最大并发连接数。
- RPM 和 TPM 配额。
- 输入上下文长度。
- 输出 Token 数量。
- 推理模型的 reasoning 输出长度。
- 每次 Agent 的模型调用轮数。
- 工具调用与重新推理次数。
- A2A 子 Agent 数量。

#### 建议改造

- 按模型配置复用异步 HTTP Client。
- 明确配置每个模型的并发、RPM 和 TPM 限额。
- 对 429 使用带抖动的指数退避。
- 限制最大重试次数，避免重试风暴。
- 记录每个模型的首 Token、总耗时、Token 用量和错误率。

### 4.8 知识库调用依赖线程池

Milvus 当前使用同步 `MilvusClient`，通过 `asyncio.to_thread()` 放入线程池执行。这可以避免直接阻塞事件循环，但线程池容量有限。

大量知识库 Agent 同时运行时可能出现：

- Milvus 检索在线程池中排队。
- 首 Token 时间明显增加。
- Embedding 或 Reranker 服务触发限流。
- 同步客户端的并发安全性和连接复用成为瓶颈。
- CPU 花费在结果解析和线程切换上。

#### 建议改造

- 为知识库检索设置独立并发上限。
- 监控线程池排队和 Milvus 查询耗时。
- 评估客户端并发安全性及连接池配置。
- 对 Embedding 和 Reranker 分别设置并发限制、超时和熔断。
- 避免将大规模知识入库任务和在线检索运行在同一资源池中。

### 4.9 客户端断开与运行取消

SSE 客户端可能因为刷新页面、网络中断或网关超时而断开。如果服务端没有及时检测断开并取消模型调用，Agent 仍可能继续消耗模型、数据库和 MCP 资源。

#### 建议改造

- 在流式生成器中检测客户端断开。
- 将取消信号传递到 Agent、模型和工具调用。
- 在取消后把 `agent_runs` 标记为 `cancelled`。
- 对无法真正取消的外部调用设置明确超时。
- 记录取消原因和已消耗时间。

## 5. 生产部署建议

建议生产环境最终拆分为：

```text
Nginx / API Gateway
        │
        ▼
AI-backend Web 实例 × N
        │
        ├── PostgreSQL 业务连接池
        ├── PostgreSQL Checkpointer 连接池
        ├── 模型服务
        ├── MCP 平台
        └── Milvus / Reranker

独立知识入库 Worker × N
        │
        ├── PostgreSQL 队列
        ├── 文件存储
        ├── Embedding 服务
        └── Milvus
```

Web 服务和知识入库 Worker 分离后，可以独立调整实例数和资源配额，避免后台入库任务影响在线 Agent 的首 Token 时间。

## 6. 优化优先级

### 6.1 P0：支持 50 并发前必须完成

1. 重构 SSE 数据库 Session 生命周期，流式期间不长期持有连接。
2. Checkpointer 改为异步连接池并在应用启动阶段初始化。
3. 增加同一 `conversation_id` 的并发互斥。
4. 增加全局、模型级和用户级并发限制与等待队列上限。
5. 缓存 MCP `tools/list` 结果和 LangChain Tool 定义。
6. 生产环境关闭 Uvicorn `reload`。
7. 将数据库连接池参数改为环境可配置。
8. 增加 PostgreSQL 连接池等待、占用和超时监控。
9. 增加客户端断开检测和 Agent 取消逻辑。

### 6.2 P1：稳定生产运行

1. 复用模型异步 HTTP Client。
2. 将知识入库 Worker 从 Web 进程拆分。
3. 为模型、MCP、Milvus、Embedding、Reranker 增加熔断。
4. 增加统一 `trace_id` 和跨服务调用链追踪。
5. 配置 Nginx SSE 超时和关闭响应缓冲。
6. 增加 Agent 运行超时和最大工具调用轮数。
7. 增加多实例下的分布式限流和会话锁。

### 6.3 P2：容量和成本优化

1. 缓存 Agent 模板和模型配置。
2. 对超长会话提前总结，控制上下文 Token。
3. 按模型和 Agent 类型拆分容量池。
4. 根据业务优先级实现任务队列和优先级调度。
5. 建立 Token、模型费用和工具调用成本统计。

## 7. 压力测试方案

### 7.1 测试原则

只压测 `/health` 或普通 CRUD 接口不能反映 Agent 容量。压测必须覆盖真实 SSE、模型调用、Checkpointer、MCP 和知识库链路。

应先使用可控的 Mock LLM、Mock MCP 和 Mock Reranker 测试 AI-backend 自身容量，再逐步接入真实外部服务，区分内部瓶颈和外部限流。

### 7.2 必测场景

#### 场景一：无状态流式 Agent

- 50 个并发请求。
- 不传 `conversation_id`。
- 不挂载 MCP、知识库和 A2A。
- Mock LLM 持续流式返回 30～60 秒。

目的：测试 FastAPI、SSE、事件循环和基础模型调用链。

#### 场景二：持久化会话

- 50 个不同 `conversation_id`。
- 开启 PostgreSQL Checkpointer。
- 每个 Agent 持续 30～120 秒。

目的：测试业务连接池和 Checkpointer 连接池。

#### 场景三：MCP 工具

- 50 个 Agent 使用同一个 MCP 服务。
- 每个 Agent 至少执行一次工具调用。

目的：确认工具定义缓存、MCP 连接复用和 MCP 限流是否有效。

#### 场景四：知识库 Agent

- 20、30、50 并发逐级增加。
- 同时执行 Milvus 检索和可选 Reranker。

目的：测试线程池、Milvus 和模型服务的组合容量。

#### 场景五：同会话并发

- 对同一个 `conversation_id` 同时发送两条消息。

目的：验证会话互斥、409/排队策略和状态一致性。

#### 场景六：异常与降级

- 模型返回 429。
- 模型超时或流式中断。
- MCP 服务超时。
- Milvus 不可用。
- PostgreSQL 连接池耗尽。
- 客户端在流式过程中断开。

目的：验证重试、熔断、取消和错误状态落库。

#### 场景七：A2A 放大

- 主 Agent 调用一个或多个子 Agent。
- 逐步增加主 Agent 并发。

目的：统计单个用户请求对应的实际模型调用量，并验证全局并发预算。

## 8. 监控指标

### 8.1 Agent 指标

- 活跃 Agent 数。
- 排队 Agent 数。
- 成功、失败、取消和中断数量。
- 首 Token 时间。
- 总执行时间 P50/P95/P99。
- 单次运行模型调用轮数。
- 单次运行工具调用次数。
- A2A 子 Agent 调用次数。

### 8.2 PostgreSQL 指标

- SQLAlchemy 连接池大小。
- 已借出连接数。
- 溢出连接数。
- 连接等待时间。
- Pool Timeout 数量。
- 活跃事务数量和持续时间。
- Checkpointer 连接池占用。
- Checkpoint 读写耗时。

### 8.3 外部依赖指标

- 模型请求并发、429、超时和重试次数。
- 模型首 Token 和总耗时。
- MCP `tools/list` 次数。
- MCP `tools/call` 次数与耗时。
- Milvus 查询耗时和错误率。
- Embedding、Reranker 并发和错误率。

### 8.4 进程指标

- CPU 和内存。
- 事件循环延迟。
- 活跃线程数和线程池排队。
- 活跃 SSE 连接数。
- 文件描述符或网络连接数。

## 9. 建议验收标准

最终指标需要结合模型服务能力确定，但 AI-backend 自身至少应满足：

- 目标并发下无数据库连接池超时。
- 同一会话不会出现并发状态覆盖。
- 客户端断开后能停止或尽快终止后台运行。
- MCP 工具定义不会随 Agent 请求数量线性重复拉取。
- 内部错误率低于 1%。
- 模型服务 429 时不会形成无限重试或重试风暴。
- 服务实例重启时能够停止接收新任务，并给活跃任务留出排空时间。
- 压测结束后数据库连接、线程和任务数量能够恢复到基线。

首 Token 和总耗时会明显受到模型服务影响，应分别记录 AI-backend 内部耗时与外部模型耗时，不能只观察用户侧总耗时。

## 10. 推荐落地顺序

```text
短 Session 重构
    ↓
Checkpointer 连接池与启动初始化
    ↓
同会话互斥
    ↓
全局/模型并发闸门
    ↓
MCP 工具定义缓存
    ↓
Mock 外部依赖完成 50 并发压测
    ↓
接入真实模型、MCP 和知识库逐级压测
    ↓
确定生产 Worker 数量和连接池预算
    ↓
上线监控、限流和告警
```

## 11. 最终结论

当前 AI-backend 的异步 Agent 和 SSE 设计具备承载并发的基础，但数据库 Session 生命周期、Checkpointer 单连接、MCP 重复发现和并发控制仍属于明确瓶颈。

在这些问题解决前，不能仅根据 FastAPI 能建立 50 个连接，就认为平台能够可靠承载 50 个同时运行的 Agent。建议先完成 P0 改造，再通过真实 Agent 链路压测确定最终容量。
