# Agent Checkpointer 异步连接池改造方案

> 文档状态：已实施并通过验证  
> 适用项目：AI-backend  
> 改造范围：LangGraph PostgreSQL Checkpointer 的连接管理、应用生命周期、初始化并发控制与测试  
> 参考资料：`异步+线程池checkpoint实现思路，参考deer-flow.md`

---

## 1. 背景

当前项目使用 LangGraph 官方的 `AsyncPostgresSaver` 持久化 Agent State，使同一个
`conversation_id` 对应的 Agent 可以跨请求恢复消息、工具结果和图执行状态。

当前实现位于：

- `app/server/agent/src/checkpoint/config.py`
- `app/server/agent/src/checkpoint/service.py`

当前 PostgreSQL Checkpointer 通过下面的方式创建：

```python
AsyncPostgresSaver.from_conn_string(postgres_url)
```

该方式虽然使用异步 PostgreSQL 驱动，不会像同步数据库调用一样直接阻塞 asyncio
事件循环，但底层只持有一条 PostgreSQL 连接。进程内的所有持久化 Agent 会话会共享
这一条连接。

随着持久会话并发量上升，当前实现可能出现：

- Checkpoint 读写在单连接上排队，延迟逐步升高。
- 底层连接不允许同时执行多个命令时产生并发异常。
- 单连接失效时，同一进程内的所有持久会话同时受影响。
- 第一个请求承担连接建立和 `setup()` 表结构检查延迟。
- 多个首次请求同时进入时，可能重复初始化并互相覆盖实例。
- Checkpointer 没有接入 FastAPI lifespan，应用退出时不能保证优雅关闭。

本次改造只解决上述连接与生命周期问题，不引入 DeerFlow 的完整 Checkpoint 高级体系。

---

## 2. 改造目标

本次改造必须实现以下目标：

1. PostgreSQL Checkpointer 使用 `psycopg_pool.AsyncConnectionPool`。
2. 整个 FastAPI Worker 只创建一个应用级 Checkpointer 连接池。
3. 在 FastAPI lifespan 启动阶段完成连接池初始化和 LangGraph 表结构检查。
4. 在应用退出阶段优雅关闭 Checkpointer 连接池。
5. 使用进程内 `asyncio.Lock` 防止同一进程重复初始化。
6. 使用 PostgreSQL advisory lock 防止多个 Worker 同时执行 Checkpoint 迁移。
7. 连接池大小和超时参数可通过环境变量配置。
8. 初始化失败时阻止应用启动，不静默降级到内存存储。
9. 保持现有 Checkpoint 表结构、历史数据和 Agent API 不变。
10. 提供中文生命周期日志、单元测试和 PostgreSQL 集成测试。

---

## 3. 非目标

以下内容不纳入本次改造：

- Full/Delta 双 Checkpoint 模式。
- Redis Checkpoint 历史缓存。
- DeerFlow `CachedHistorySaver`。
- Checkpoint 状态物化访问器。
- Checkpoint 回滚、重放、分支管理。
- Checkpoint 历史数据清理和归档。
- 同一个 `conversation_id` 的跨进程执行互斥。
- 用户断开 SSE 后主动取消后台 Agent。

这些能力可以在连接池改造稳定后按独立方案逐项评估。

---

## 4. 最终技术选型

本次确定采用：

```text
AsyncPostgresSaver
  + psycopg_pool.AsyncConnectionPool
  + FastAPI lifespan
  + 应用级 AgentCheckpointService 单例
  + 进程内 asyncio.Lock
  + PostgreSQL advisory lock
```

这不是“把 Checkpoint SQL 放进普通线程池”。PostgreSQL Checkpoint 读写继续使用
psycopg3 原生异步接口，`AsyncConnectionPool` 负责并发连接复用。

当前本地依赖已经支持该方案：

```text
langgraph                         1.2.7
langgraph-checkpoint-postgres     3.1.0
psycopg                           3.3.4
psycopg-pool                      3.3.1
```

本地安装的 `AsyncPostgresSaver` 构造函数可以直接接收 `AsyncConnectionPool`。

---

## 5. 改造后的整体架构

```text
FastAPI Worker 启动
  │
  ├─ 创建应用级 AgentCheckpointService
  │
  ├─ 打开 AsyncConnectionPool
  │    ├─ 建立最小连接数
  │    ├─ 检查连接健康
  │    └─ 启动失败时立即关闭已创建资源
  │
  ├─ 获取 PostgreSQL advisory lock
  │    ├─ 创建绑定当前锁连接的临时 AsyncPostgresSaver
  │    ├─ 执行 saver.setup()
  │    └─ 释放 advisory lock
  │
  ├─ 创建 AsyncPostgresSaver(conn=pool)
  └─ 开始接收请求

Agent 请求
  │
  ├─ conversation_id 为空
  │    └─ 不挂载 Checkpointer
  │
  └─ conversation_id 非空
       ├─ 获取应用级 AsyncPostgresSaver
       ├─ Checkpoint 操作从池中借用连接
       ├─ 执行读取或写入
       └─ 操作完成后立即归还连接

FastAPI Worker 退出
  │
  ├─ 停止接收新请求
  ├─ 等待生命周期内任务结束
  └─ 关闭 AsyncConnectionPool
```

---

## 6. 配置设计

### 6.1 环境变量

在 `.env.example` 中新增并统一以下配置：

```env
# Checkpointer 类型：postgres / memory / none
CHECKPOINTER_TYPE="postgres"

# PostgreSQL Checkpoint 表所在 Schema
CHECKPOINTER_POSTGRES_SCHEMA="agent"

# Checkpointer 异步连接池最小连接数
CHECKPOINTER_POOL_MIN_SIZE=1

# Checkpointer 异步连接池最大连接数
CHECKPOINTER_POOL_MAX_SIZE=5

# 等待池中可用连接的最长时间，单位为秒
CHECKPOINTER_POOL_TIMEOUT=10

# 启动阶段建立最小连接的最长时间，单位为秒
CHECKPOINTER_POOL_STARTUP_TIMEOUT=15

# 空闲连接保留时间，单位为秒
CHECKPOINTER_POOL_MAX_IDLE=300

# 单条连接的最长生命周期，单位为秒
CHECKPOINTER_POOL_MAX_LIFETIME=1800
```

PostgreSQL 地址、端口、库名、用户和密码继续复用现有配置：

```env
POSTGRES_HOST="127.0.0.1"
POSTGRES_PORT=5433
POSTGRES_DATABASE="ai"
POSTGRES_USER="postgres"
POSTGRES_PASSWORD=""
```

### 6.2 默认值决策

第一版连接池默认使用：

```text
min_size = 1
max_size = 5
```

Checkpoint SQL 通常执行时间较短。50 个正在运行的 Agent 不会在每个时刻同时写入
Checkpoint，因此第一版不盲目把连接池开到 10 或更高。上线前根据连接等待耗时和
PostgreSQL 活跃连接数决定是否增加。

### 6.3 配置校验

`AgentCheckpointConfig` 必须校验：

- `min_size >= 0`
- `max_size >= 1`
- `min_size <= max_size`
- 所有 timeout、idle 和 lifetime 参数必须大于 0
- `CHECKPOINTER_POSTGRES_SCHEMA` 必须是合法 PostgreSQL 标识符
- `CHECKPOINTER_TYPE` 只允许 `postgres`、`memory`、`none`

配置错误必须在启动阶段抛出明确异常，不允许使用错误配置继续运行。

---

## 7. AgentCheckpointService 设计

### 7.1 服务状态

`AgentCheckpointService` 维护清晰的生命周期状态：

```text
NEW → STARTING → READY → CLOSING → CLOSED
```

需要维护的核心成员：

```python
self._initialization_lock: asyncio.Lock
self._pool: AsyncConnectionPool | None
self._instance: Any | None
self._state: CheckpointServiceState
```

### 7.2 `startup()`

`startup()` 负责：

1. 校验配置。
2. 在初始化锁内再次检查是否已经 READY。
3. 根据 `CHECKPOINTER_TYPE` 创建对应 Saver。
4. PostgreSQL 模式下创建并打开连接池。
5. 使用 advisory lock 串行执行 `setup()`。
6. 创建绑定连接池的正式 Saver。
7. 将状态切换为 READY。
8. 任意步骤失败时关闭已经创建的资源并重新抛出异常。

`startup()` 必须幂等，多次调用不能重复创建连接池。

### 7.3 `get_checkpointer()`

改造后 `get_checkpointer()` 只返回 lifespan 已经初始化完成的 Saver，不再执行懒加载。

| Checkpointer 类型 | 返回值 |
|---|---|
| `postgres` | 应用级 `AsyncPostgresSaver(conn=pool)` |
| `memory` | 应用级 `InMemorySaver` |
| `none` | `None` |
| 服务未启动 | 抛出明确的初始化错误 |
| 服务启动失败 | 应用整体启动失败，不接受请求 |

### 7.4 `close()`

`close()` 负责：

1. 在锁内将状态切换为 CLOSING。
2. 清除对外 Saver 引用，阻止新任务继续获取实例。
3. 等待连接池完成关闭。
4. 清空连接池引用。
5. 将状态切换为 CLOSED。

`close()` 必须幂等，多次调用不能重复关闭或抛出无意义异常。

---

## 8. PostgreSQL 异步连接池设计

连接池使用以下关键参数：

```python
pool = AsyncConnectionPool(
    conninfo=postgres_url,
    min_size=config.pool_min_size,
    max_size=config.pool_max_size,
    timeout=config.pool_timeout,
    max_idle=config.pool_max_idle,
    max_lifetime=config.pool_max_lifetime,
    open=False,
    kwargs={
        "autocommit": True,
        "prepare_threshold": 0,
        "row_factory": dict_row,
        "connect_timeout": config.connect_timeout,
    },
    check=AsyncConnectionPool.check_connection,
)
```

设计说明：

- `autocommit=True`：满足 LangGraph PostgreSQL Saver 的迁移与写入要求。
- `row_factory=dict_row`：满足 Saver 对字典行结果的要求。
- `prepare_threshold=0`：保持当前 Checkpointer 推荐的 prepared statement 行为。
- `open=False`：避免在构造函数中隐式打开异步资源。
- `check_connection`：借出连接前检查连接健康。
- `wait=True`：应用启动时等待最小连接数真正建立完成。

正式 Saver 创建方式：

```python
saver = AsyncPostgresSaver(conn=pool)
```

不再使用：

```python
AsyncPostgresSaver.from_conn_string(...)
```

---

## 9. 多 Worker 迁移锁

### 9.1 为什么需要 advisory lock

每个 Uvicorn Worker 都是独立进程，会创建自己的 Checkpointer 连接池并执行
`saver.setup()`。

当前版本的 `setup()` 会读取 `checkpoint_migrations` 的最高版本，然后逐条执行迁移并
写入版本号。如果多个 Worker 同时启动，可能同时执行相同迁移。

### 9.2 执行方式

启动时从池中获取一条连接，在同一连接上：

```text
SELECT pg_advisory_lock(固定锁编号)
→ AsyncPostgresSaver(conn=当前连接).setup()
→ SELECT pg_advisory_unlock(固定锁编号)
```

必须让临时 Saver 使用持有 advisory lock 的同一条连接。不能在持锁后再让 `setup()`
重新从池中借连接，否则 `max_size=1` 时可能形成自我等待。

advisory lock 只在应用启动迁移时使用，不参与正常 Checkpoint 读写。

---

## 10. 应用级单例与依赖注入

在 Checkpoint 模块提供唯一实例：

```python
agent_checkpoint_service = AgentCheckpointService()
```

该实例同时提供给：

- FastAPI lifespan：负责 `startup()` 和 `close()`。
- `AgentService`：传递给主 `AgentAssembler`。
- `AgentResumeService`：通过共用 `AgentAssembler` 自然复用。

API 层创建主服务时显式注入：

```python
agent_service = AgentService(
    checkpoint_service=agent_checkpoint_service,
)
```

构造函数仍保留依赖注入参数，方便单元测试传入 Fake 或 Mock，但生产入口只能使用应用级
单例。

A2A 子 Agent 当前不传 `conversation_id`，不会挂载 Checkpointer，因此临时创建的
`AgentService` 不应初始化新的连接池。

---

## 11. FastAPI lifespan 编排

修改 `app/common/core/lifespan.py`，启动顺序确定为：

```text
1. 启动 Agent Checkpointer
2. 检查知识库 PostgreSQL、Milvus 和本地切片能力
3. 启动知识库入库 Worker
4. 加载 FastMCP 动态工具
5. 进入 FastMCP lifespan
6. 开始接收请求
```

退出顺序反向执行：

```text
1. 退出 FastMCP lifespan
2. 停止知识库 Worker
3. 关闭知识库 HTTP/Milvus 客户端
4. 关闭 Agent Checkpointer 连接池
```

如果知识库或 FastMCP 启动失败，已经打开的 Checkpointer 池必须被关闭，不能遗留半初始化
资源。

---

## 12. 失败策略

### 12.1 启动失败

当 `CHECKPOINTER_TYPE=postgres` 时，出现以下问题必须阻止应用启动：

- PostgreSQL 无法连接。
- Checkpoint Schema 不可访问。
- 连接池最小连接无法建立。
- `saver.setup()` 执行失败。
- Checkpoint 表迁移失败。

禁止自动切换成 `InMemorySaver`。静默降级会造成服务看似可用，但重启后会话状态全部
丢失。

### 12.2 运行期间连接池耗尽

```text
等待 CHECKPOINTER_POOL_TIMEOUT
→ 获得连接后继续
→ 等待超时则抛出 Checkpointer 依赖异常
→ 当前 Agent run 进入 failed
→ SSE 返回明确错误事件
```

不允许无限等待，也不能在 Checkpoint 写入失败后将 Agent 标记为成功。

### 12.3 数据库短暂断连

- 借出连接前执行健康检查。
- 失效连接由连接池重新建立。
- 当前已经失败的 Checkpoint 操作正常返回错误。
- 不自动切换到内存 Checkpointer。

---

## 13. 中文日志与安全要求

增加以下日志：

```text
Checkpointer 初始化开始: type=postgres host=127.0.0.1 port=5433 database=ai schema=agent
Checkpointer 异步连接池已打开: min_size=1 max_size=5
Checkpointer 数据表检查开始
Checkpointer 数据表检查完成
Checkpointer 初始化完成
Checkpointer 连接池关闭开始
Checkpointer 连接池关闭完成
```

异常日志必须包含阶段：

```text
Checkpointer 初始化失败: stage=open_pool error=...
Checkpointer 初始化失败: stage=setup error=...
```

禁止输出：

- PostgreSQL 密码。
- 完整 PostgreSQL DSN。
- Checkpoint 消息正文。
- Tool 调用中的敏感参数。

可以输出 `pool.get_stats()` 中不包含敏感信息的连接池统计数据。

---

## 14. PostgreSQL 连接预算

当前业务 SQLAlchemy 连接池为：

```text
pool_size = 10
max_overflow = 20
```

即单 Worker 最多使用 30 条业务数据库连接。

第一版 Checkpointer 使用 `max_size=5` 后：

```text
单 Worker 理论最大连接数
= 业务连接池 30
+ Checkpointer 连接池 5
= 35
```

两个 Worker：

```text
35 × 2 = 70
```

该数字还没有包含数据库管理连接和其他外部程序。因此第一阶段建议：

```text
Uvicorn Worker = 1
CHECKPOINTER_POOL_MAX_SIZE = 5
```

启动两个 Worker 前，应将业务数据库池也改为环境变量，并建议使用：

```env
POSTGRES_POOL_SIZE=10
POSTGRES_MAX_OVERFLOW=5
CHECKPOINTER_POOL_MAX_SIZE=5
```

此时两个 Worker 的理论最大值为：

```text
(10 + 5 + 5) × 2 = 40
```

连接池不能代替 PostgreSQL 容量规划，不应仅通过增大 `max_size` 处理压力问题。

---

## 15. 文件改动清单

### 15.1 必须修改

| 文件 | 改动 |
|---|---|
| `app/server/agent/src/checkpoint/config.py` | 增加连接池配置、类型校验、Schema 校验 |
| `app/server/agent/src/checkpoint/service.py` | 实现连接池、startup/close、初始化锁、迁移锁 |
| `app/server/agent/src/checkpoint/__init__.py` | 导出应用级 Checkpointer 单例 |
| `app/server/agent/api/agent_api.py` | 向主 AgentService 注入应用级单例 |
| `app/common/core/lifespan.py` | 启动和关闭 Checkpointer |
| `app/bootstrap.py` | Windows 下统一使用 psycopg 异步连接兼容的 SelectorEventLoop |
| `app/main.py` | Uvicorn 显式使用项目 Selector loop factory |
| `.env.example` | 增加连接池环境变量和中文说明 |

### 15.2 建议新增

| 文件 | 作用 |
|---|---|
| `app/server/agent/tests/test_checkpoint_config.py` | 配置解析与校验测试 |
| `app/server/agent/tests/test_checkpoint_service.py` | 生命周期、并发初始化与资源关闭测试 |

### 15.3 暂不修改

- Agent 请求和响应 Schema。
- `/agent/messages` API。
- `/agent/resume` API。
- LangGraph Checkpoint 官方表结构。
- 已存在的 Checkpoint 历史数据。
- `agent_conversations`、`agent_messages`、`agent_runs` 表。

---

## 16. 实施阶段

### 阶段一：配置和连接池

1. 扩展 `AgentCheckpointConfig`。
2. 实现 `AsyncConnectionPool` 构建函数。
3. 实现 `startup()`、`get_checkpointer()` 和 `close()`。
4. 增加初始化锁和资源清理。

### 阶段二：应用生命周期

1. 创建应用级单例。
2. 注入主 `AgentService`。
3. 接入 FastAPI lifespan。
4. 增加多 Worker advisory lock。

### 阶段三：测试与验证

1. 完成单元测试。
2. 执行 PostgreSQL 集成测试。
3. 验证普通、流式、恢复和多会话 Agent。
4. 观察 PostgreSQL 连接数和 Checkpoint 延迟。

本次改造应作为一个完整提交完成，不能只改连接池而不接入 lifespan，也不能只接入
lifespan 而保留首次请求懒初始化。

---

## 17. 测试方案

### 17.1 单元测试

- 环境变量可以正确解析。
- `min_size > max_size` 时拒绝启动。
- 非法 Schema 名称拒绝启动。
- `none` 模式返回 `None`。
- `memory` 模式复用同一个 `InMemorySaver`。
- 并发调用 `startup()` 只创建一个连接池。
- 多次调用 `startup()` 不重复初始化。
- 多次调用 `close()` 不报错。
- 初始化失败会关闭已经打开的连接池。
- `get_checkpointer()` 不再执行懒初始化。
- advisory lock 正确包裹 `setup()`。
- 正式 Saver 持有连接池，而不是单连接。

### 17.2 PostgreSQL 集成测试

- 启动阶段可以检查或创建官方 Checkpoint 表。
- 原有 Checkpoint 数据可以继续读取。
- 同一个 `thread_id` 可以跨请求恢复消息。
- 20 个不同 `thread_id` 并发写入成功。
- 写入完成后连接可以归还连接池。
- 应用关闭后没有残留 Checkpointer 连接。
- 两个并发初始化任务不会重复执行迁移。

### 17.3 Agent 回归测试

- 普通非流式 Agent 调用。
- SSE 流式 Agent 调用。
- 同会话连续发送两轮消息。
- 多个不同会话并发调用。
- Planning 中断与 Resume。
- `conversation_id=""` 时不启用 Checkpointer。
- A2A 子 Agent 不创建 Checkpoint 连接。

---

## 18. 验收标准

改造完成后必须同时满足：

1. FastAPI 启动阶段完成 Checkpointer 初始化。
2. 第一个 Agent 请求不再建立连接或执行 `setup()`。
3. Saver 底层对象为 `AsyncConnectionPool`。
4. 20 个不同会话并发时不出现单连接并发异常。
5. PostgreSQL Checkpointer 连接数不超过配置上限。
6. 原有会话 Checkpoint 可以继续恢复。
7. 应用退出时连接池正确关闭。
8. 初始化失败时应用启动失败且无资源泄漏。
9. 现有单元测试全部通过。
10. 新增 Checkpointer 测试全部通过。
11. Python 语法检查和项目导入检查通过。
12. 中文文件执行乱码检查后不存在异常的连续问号文本。

---

## 19. 回滚方案

本次改造不修改数据库表结构和历史数据格式，出现问题时可以只回滚代码和环境变量。

回滚步骤：

1. 停止新版本应用。
2. 回滚 Checkpointer 相关代码。
3. 移除新增的连接池环境变量。
4. 恢复原来的 `AsyncPostgresSaver.from_conn_string()` 创建方式。
5. 重新启动应用并验证历史会话。

由于 LangGraph 官方 Checkpoint 表没有改变，回滚不需要执行 SQL 数据迁移。

---

## 20. 后续优化方向

本次改造稳定后，可以按优先级继续评估：

1. 为同一个 `conversation_id` 增加运行互斥或幂等控制。
2. 实现用户主动取消与后台 Agent 任务终止。
3. 增加 Checkpoint 表容量和写入耗时监控。
4. 设计历史 Checkpoint 清理和保留策略。
5. 对长会话评估 Full/Delta 存储模式。
6. 多 Worker 场景下增加跨进程会话锁。

---

## 21. 最终决策

本次确定实施的最终范围为：

```text
单连接 AsyncPostgresSaver
→ 应用级 AsyncConnectionPool
→ FastAPI lifespan 初始化与关闭
→ 进程内初始化锁
→ 多 Worker PostgreSQL advisory lock
→ 连接池环境变量配置
→ 中文生命周期日志
→ 单元测试与 PostgreSQL 集成验证
```

不迁移数据、不修改 Agent API、不引入 Redis、不实现 Delta Checkpoint，也不保留首次请求
懒初始化模式。

---

## 22. 实施与验证结果

本方案已经完成实现，并通过以下验证：

- Checkpointer 配置与服务专项测试通过。
- FastAPI lifespan 启停顺序和失败清理测试通过。
- 全项目 66 个单元测试通过。
- FastAPI 应用成功导入，共注册 56 条路由。
- 完整 lifespan 成功启动并关闭 Checkpointer、Knowledge Worker 和 FastMCP。
- 真实 PostgreSQL 连接池初始化成功，实际类型为 `AsyncConnectionPool`。
- 真实 LangGraph 临时线程完成 Checkpoint 写入、读取和官方接口清理。
- 连接池实际配置为 `min_size=1`、`max_size=5`，关闭后服务状态为 `closed`。

Windows 环境的真实连接验证发现，psycopg3 异步连接不支持
`WindowsProactorEventLoopPolicy`。项目后端当前没有 Playwright 或 asyncio 子进程调用，
因此已在 `app/bootstrap.py` 中统一切换为 `WindowsSelectorEventLoopPolicy`，确保本地脚本、
FastAPI 和 Uvicorn 使用兼容的事件循环模型。`app/main.py` 同时显式配置项目 loop
factory，避免 Uvicorn 在加载字符串形式的应用之前先创建 ProactorEventLoop。
