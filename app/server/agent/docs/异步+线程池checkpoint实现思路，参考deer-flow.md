# DeerFlow Checkpoint 系统实现解析

> 基于 `deer-flow` 仓库（v2.1.0, commit cc6a265）代码逐行分析。
> 核心代码位置：`backend/packages/harness/deerflow/runtime/checkpointer/` 及 `runtime/checkpoint_*.py`

---

## 目录

1. [概述：Checkpoint 是什么](#1-概述checkpoint-是什么)
2. [架构总览](#2-架构总览)
3. [配置层：两种配置入口](#3-配置层两种配置入口)
4. [Provider 工厂层：三种后端装配](#4-provider-工厂层三种后端装配)
5. [连接模型：Postgres 是异步连接池](#5-连接模型postgres-是异步连接池)
6. [双通道模式：full vs delta](#6-双通道模式full-vs-delta)
7. [缓存包装：CachedHistorySaver](#7-缓存包装cachedhistorysaver)
8. [状态访问器：CheckpointStateAccessor](#8-状态访问器checkpointstateaccessor)
9. [写入生命周期：谁在什么时候写](#9-写入生命周期谁在什么时候写)
10. [高并发与多 Worker 考量](#10-高并发与多-worker-考量)
11. [关键设计决策总结](#11-关键设计决策总结)
12. [文件索引](#12-文件索引)

---

## 1. 概述：Checkpoint 是什么

Checkpoint（检查点）是 LangGraph 的**状态持久化机制**：agent 图每执行完一个节点，就把当前状态（消息列表、工具结果、中间变量）**快照**到存储里。它的三个核心用途：

| 用途 | 场景 |
|---|---|
| **断点续聊** | 对话历史跨请求/跨重启存活 |
| **分支与重放** | 从历史 checkpoint 重新生成 / 编辑重发 |
| **打断恢复** | 用户打断 run 后，新 run 从最后 checkpoint 无缝续接（前面聊过的"路径 2"） |

DeerFlow 没有自己实现 checkpoint 存储，而是**直接使用 LangGraph 官方的 `BaseCheckpointSaver` 家族**（`InMemorySaver` / `AsyncSqliteSaver` / `AsyncPostgresSaver`），在它之上做了三层增强：

```
┌─────────────────────────────────────────────────────┐
│  ① 配置层    checkpointer_config.py / database_config.py │
├─────────────────────────────────────────────────────┤
│  ② Provider 工厂  async_provider.py（选后端+建连接池）     │
├─────────────────────────────────────────────────────┤
│  ③ 缓存包装    CachedHistorySaver（delta 历史缓存）       │
├─────────────────────────────────────────────────────┤
│  ④ 访问器      CheckpointStateAccessor（唯一读写入口）    │
├─────────────────────────────────────────────────────┤
│  ⑤ 底层 Saver  LangGraph 官方（memory/sqlite/postgres）  │
└─────────────────────────────────────────────────────┘
```

---

## 2. 架构总览

```
                    ┌──────────────────────────────┐
                    │      make_checkpointer()      │  ← 唯一工厂入口
                    │   (async_provider.py:216)     │
                    └──────────────┬───────────────┘
                                   │
                    ┌──────────────▼───────────────┐
                    │   _select_inner_checkpointer  │  ← 选择优先级：
                    │   (async_provider.py:188)     │     legacy checkpointer 配置
                    └──────────────┬───────────────┘     > database 配置
                                   │                      > 默认 InMemorySaver
                 ┌─────────────────┼─────────────────┐
                 ▼                 ▼                 ▼
          type=memory        type=sqlite        type=postgres
                 │                 │                 │
        InMemorySaver    AsyncSqliteSaver   AsyncPostgresSaver
        (进程内存，重启丢)  (本地文件, aio)      (Postgres, aio)
                                              conn = AsyncConnectionPool
                                   │
                    ┌──────────────▼───────────────┐
                    │   delta 模式？                 │
                    │   frozen_checkpoint_channel_mode()│
                    └──────────────┬───────────────┘
                 ┌─────────────────┴─────────────────┐
                 ▼                                   ▼
        CachedHistorySaver(saver,   裸 saver（full 模式）
          cache, key_prefix)         直接 yield
```

---

## 3. 配置层：两种配置入口

### 3.1 Legacy 独立配置（`checkpointer_config.py`）

```python
CheckpointerType = Literal["memory", "sqlite", "postgres"]

class CheckpointerConfig(BaseModel):
    type: CheckpointerType = Field(description="...")
    connection_string: str | None = Field(
        default=None,
        description="sqlite 用文件路径；postgres 用 DSN",
    )
    postgres_schema: str = Field(
        default="",
        description="PostgreSQL schema，空 = 服务器默认 search_path（通常 public）",
    )

    @field_validator("postgres_schema")
    @classmethod
    def _validate_postgres_schema(cls, value: str) -> str:
        return validate_postgres_schema(value)   # 只允许纯标识符，防注入
```

### 3.2 统一配置（`database_config.py`，推荐）

```python
backend: Literal["memory", "sqlite", "postgres"] = Field(...)
postgres_url: str | None = Field(...)
pool_size: int = Field(default=5, ...)        # ← App ORM 层的 asyncpg 连接池大小
postgres_schema: str = Field(default="", ...)
checkpoint_channel_mode: Literal["full", "delta"] = Field(default="full", ...)
checkpoint_delta.snapshot_frequency: int = Field(default=10, ...)
```

### 3.3 config.yaml 实际写法

```yaml
# 方式一：统一 database 配置（推荐）
database:
  backend: postgres
  postgres_url: $DATABASE_URL          # .env: DATABASE_URL=postgresql://user:pass@host:5432/db
  pool_size: 5                         # App ORM 层连接池（默认 5）
  postgres_schema: deerflow            # 可选：专用 schema
  checkpoint_channel_mode: full        # full | delta（默认 full，进程冻结）
  checkpoint_delta:
    snapshot_frequency: 10             # delta 模式的快照节奏

# 方式二：legacy checkpointer 配置（向后兼容，优先级更高）
# checkpointer:
#   type: postgres
#   connection_string: $DATABASE_URL
#   postgres_schema: deerflow
```

**优先级**：legacy `checkpointer:` 段 > 统一 `database:` 段 > 默认 `InMemorySaver`（`async_provider.py:196-212`）。

---

## 4. Provider 工厂层：三种后端装配

### 4.1 统一入口（`async_provider.py:216`）

```python
@contextlib.asynccontextmanager
async def make_checkpointer(app_config: AppConfig | None = None) -> AsyncIterator[Checkpointer]:
    """Async context manager that yields a checkpointer for the caller's lifetime.
    Resources are opened on enter and closed on exit -- no global state."""
    async with _select_inner_checkpointer(app_config) as saver:
        mode = frozen_checkpoint_channel_mode() or (db_config.checkpoint_channel_mode if db_config else "full")
        if mode == "delta":
            # delta 模式包一层 CachedHistorySaver（见第 7 节）
            async with make_checkpoint_cache(app_config, serde=saver.serde) as cache:
                yield CachedHistorySaver(saver, cache, key_prefix=checkpoint_cache_key_prefix(app_config))
        else:
            yield saver                  # full 模式：裸 saver
```

设计要点：**`make_checkpointer` 是 async context manager，资源在 enter 打开、exit 关闭，没有全局单例**。调用方（Gateway lifespan）持有它的生命周期。

### 4.2 三种后端分支（`async_provider.py:108-142`）

```python
async def _async_checkpointer(config):
    if config.type == "memory":
        from langgraph.checkpoint.memory import InMemorySaver
        yield InMemorySaver()                        # 进程内存，重启即失
        return

    if config.type == "sqlite":
        from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
        conn_str = await asyncio.to_thread(_prepare_sqlite_checkpointer_path, ...)
        async with AsyncSqliteSaver.from_conn_string(conn_str) as saver:
            await saver.setup()                      # 建表
            yield saver
        return

    if config.type == "postgres":
        if not config.connection_string:
            raise ValueError(POSTGRES_CONN_REQUIRED)
        AsyncPostgresSaver, _ = _ensure_postgres_imports()
        pool = _build_postgres_pool(config.connection_string, config.postgres_schema)
        async with pool:
            await _ensure_postgres_schema_with_pool(pool, config.postgres_schema)  # CREATE SCHEMA IF NOT EXISTS
            saver = AsyncPostgresSaver(conn=pool)    # ★ 传连接池，不是单连接
            await saver.setup()
            yield saver
        return
```

注意 **sqlite 路径**：`conn_str` 的准备工作通过 `asyncio.to_thread` 扔到线程池——文件 IO 不阻塞事件循环。这是全项目"async 不阻塞"原则的体现。

---

## 5. 连接模型：Postgres 是异步连接池

### 5.1 连接池构建（`async_provider.py:51-76`）

```python
def _build_postgres_pool(conn_string: str, schema: str = ""):
    """Build an AsyncConnectionPool with TCP keepalive and connection checking."""
    from psycopg.rows import dict_row
    from psycopg_pool import AsyncConnectionPool

    kwargs = {
        "autocommit": True,          # LangGraph saver 自己管理事务
        "prepare_threshold": 0,      # 总是使用 prepared statements
        "row_factory": dict_row,
        "keepalives": 1,             # TCP keepalive，长连接存活
        "keepalives_idle": 60,
        "keepalives_interval": 10,
        "keepalives_count": 6,
    }
    dsn = dsn_with_search_path(normalize_libpq_dsn(conn_string), schema)

    return AsyncConnectionPool(
        dsn,
        kwargs=kwargs,
        check=AsyncConnectionPool.check_connection,   # 借出前检查连接健康
    )
```

### 5.2 为什么是"连接池"而不是"单连接"（关键对比）

| | LangGraph 官方默认 | DeerFlow 的做法 |
|---|---|---|
| 创建方式 | `AsyncPostgresSaver.from_conn_string(dsn)` | `AsyncPostgresSaver(conn=AsyncConnectionPool)` |
| 连接模型 | **单连接**（一个 DSN 一个连接） | **连接池**（psycopg_pool 默认 min_size=4，按需增长） |
| 并发写入 | 所有线程的 checkpoint 写**串行**排队 | 并发 run 各拿各的连接，**互不阻塞** |

```python
# ❌ LangGraph 官方示例（单连接）：
async with AsyncPostgresSaver.from_conn_string(dsn) as saver:
    ...

# ✅ DeerFlow 的做法（连接池）：
pool = _build_postgres_pool(dsn, schema)
async with pool:
    saver = AsyncPostgresSaver(conn=pool)   # 传入的是池对象
    await saver.setup()
```

### 5.3 项目里其实是"两层独立的连接池"

| 层 | 驱动 | 连接池 | 大小 |
|---|---|---|---|
| **Checkpoint（LangGraph saver）** | psycopg3 + psycopg_pool | `AsyncConnectionPool` | 默认 min_size=4，**无显式配置项** |
| **App ORM（DeerFlow 自己的表）** | asyncpg + SQLAlchemy | `create_async_engine(pool_size=...)` | `pool_size=5`（`database_config.py:185`，可配） |

```python
# persistence/engine.py:17, 142
from sqlalchemy.ext.asyncio import create_async_engine
_engine = create_async_engine(url, echo=echo, json_serializer=_json_serializer, pool_size=pool_size)
```

### 5.4 URL 驱动后缀自动补（`database_config.py:289`）

```python
# 用户写 postgresql:// 或 postgres://
# App ORM 自动转成 postgresql+asyncpg://（asyncpg 方言）
url = url.replace("postgresql://", "postgresql+asyncpg://", 1)
```

### 5.5 双驱动的 search_path 注入（`persistence/postgres_schema.py`）

```python
# asyncpg（App ORM）：通过 server_settings / connect_args 注入
def build_asyncpg_connect_args(schema): ...

# psycopg（Checkpointer）：通过 libpq options 注入
def build_psycopg_options(schema): ...

# 所以配置了 postgres_schema: deerflow 时，
# 两条路径各自用自己的方式把连接钉到正确 schema
```

### 5.6 一个已知的小空白

checkpoint 连接池**没有暴露 min_size/max_size 配置**（用 psycopg_pool 默认值）。高并发场景需要的话，要在 `_build_postgres_pool` 上包一层配置——改动很小，是项目目前的小留白。

---

## 6. 双通道模式：full vs delta

### 6.1 两种存储模式（`checkpoint_mode.py`）

| 模式 | 存储方式 | 存储增长 | 适用 |
|---|---|---|---|
| `full`（默认） | 每次 checkpoint 存**完整** channel_values | O(N²) 随轮次增长 | 默认、简单 |
| `delta` | 存 sentinel 标记 + **每步增量写入**（LangGraph `DeltaChannel`） | **O(N)** 线性增长 | 长对话、存储敏感 |

```python
# checkpoint_mode.py:1-10
"""Checkpointer storage runs in ``full`` mode (whole-snapshot channel values) or
``delta`` mode (LangGraph ``DeltaChannel``: sentinel blobs + per-step writes)."""
```

### 6.2 模式是"进程冻结 + 重启生效"

```python
def freeze_checkpoint_channel_mode(mode):
    global _frozen_checkpoint_channel_mode
    if _frozen_checkpoint_channel_mode is None:
        _frozen_checkpoint_channel_mode = mode
    elif _frozen_checkpoint_channel_mode != mode:
        raise CheckpointModeReconfigurationError(
            "checkpoint_channel_mode is restart-required and cannot change in a running process")
    return _frozen_checkpoint_channel_mode
```

- 模式在 **agent 构建时冻结**，运行时改配置 → 直接报错（防静默漂移）
- delta 的 `snapshot_frequency`（默认 10）同样冻结，且**必须与共享同一 checkpoint 库的所有进程一致**——因为快照节奏编译进每个图的 channel 表

### 6.3 兼容性是"非对称 + fail-closed"

```python
# 元数据标记：delta 写的 checkpoint 带 deerflow_checkpoint_channel_mode: "delta"
# 缺失标记 = full（旧 checkpoint 无需迁移）

# 读取前检查：
#   full 模式进程打开 delta 线程 → CheckpointModeMismatchError（HTTP 409）
#   delta 模式进程读 full checkpoint → 透明兼容（full → delta 是平滑迁移路径）
#   delta → full 需要先物化/转换数据
```

---

## 7. 缓存包装：CachedHistorySaver

### 7.1 为什么需要缓存（只有 delta 模式需要）

delta 模式下，`aget_delta_channel_history()` 需要**沿祖先链收集每步写入**（`pending_writes`），这是读放大最严重的热路径。DeerFlow 用 `CachedHistorySaver` 包住底层 saver，做**读穿透缓存**。

### 7.2 正确性论证（`cached_saver.py:1-17`，这是它的灵魂）

```python
"""Read-through delta-history cache wrapper for any BaseCheckpointSaver.

Correctness argument (spec §3): a checkpoint's delta history is a pure
function of its sealed ancestor chain — the LangGraph contract excludes the
target's own pending writes, parent links are fixed at creation, and an
ancestor's writes are sealed once its child exists. Entries keyed by
(thread, ns, checkpoint_id, channel) are therefore immutable: no
invalidation, and shared backends are coherent across processes.

The wrapper never caches the "latest checkpoint" resolution; only histories
keyed by resolved immutable checkpoint_ids.
"""
```

**核心论点**：delta 历史是"密封祖先链"的纯函数——
- 父链接在创建时固定（不可变）
- 祖先的写入在子 checkpoint 存在后就"封口"（不会再变）
- 所以缓存条目**天然不可变 → 无需失效 → 跨进程一致**

这解决了一般缓存系统最头疼的问题（缓存失效），因为**这个数据模型里根本没有"失效"这个概念**。

### 7.3 缓存策略：compose 优于 walk

```python
_COMPOSE_MAX_DEPTH = 8   # 递归组装深度预算

async def aget_delta_channel_history(self, *, config, channels):
    target = await self._inner.aget_tuple(config)
    keys = {ch: self._key(target, ch) for ch in channels}
    hits = await self._cache.aget_many(list(keys.values()))   # 查缓存
    missing = [ch for ch in channels if hits.get(keys[ch]) is None]
    if missing:
        computed = await self._compose_or_walk(config, target, missing)  # 组装 or 全量走
    if new_entries:
        await self._cache.aset_many(new_entries)              # 回填
    return {ch: found.get(ch) or computed.get(ch) or {"writes": []} for ch in channels}
```

- **compose（组装）**：从最近的"温暖祖先"递归拼历史（~2 层命中，实测 500 步 sqlite run 稳态下）
- **walk（全量走）**：深度预算耗尽时，委托一次底层快速路径（2 条 SQL），不逐个祖先爬

### 7.4 缓存后端可插拔（`checkpoint_cache/provider.py`）

```python
# database.checkpoint_cache.type: memory | redis
# memory  = 进程内 LRU（默认）
# redis   = 多 worker 共享缓存（entries 不可变 → 跨进程天然一致）
```

Redis 后端挂了**只损失命中率，不损失可用性**（fail-open，条目可重建）。

---

## 8. 状态访问器：CheckpointStateAccessor

### 8.1 为什么所有读取必须走它（`checkpoint_state.py:1-15`）

```python
"""Materialized checkpoint-state access and state-only mutation graphs.

:class:`CheckpointStateAccessor` is the single choke point for thread
checkpoint-state reads and writes. It binds a compiled graph (which carries
the mode-matched channel schema), a checkpointer, and the frozen channel mode:
every operation injects the mode marker into the config and passes the
compatibility gate before touching state. Delta checkpoints store no full
``channel_values`` — raw saver reads see sentinels — so consumers must go
through this accessor instead of calling the checkpointer directly.
```

**原因**：delta 模式的 checkpoint 没有完整 `channel_values`（原始 saver 读出来是 sentinel 标记），只有通过 accessor（绑定图 + channel schema）才能**物化**出真实状态。直接读 saver = 读到空数据。

### 8.2 状态突变图（`build_state_mutation_graph`）

```python
def build_state_mutation_graph(as_node, mode, state_schema=None, *, snapshot_frequency=None):
    """Compile a state-only graph whose single writer node finishes immediately."""
    builder = StateGraph(state_schema or get_thread_state_schema(mode, snapshot_frequency))
    builder.add_node(as_node, _finish_state_mutation)   # 空节点
    builder.set_entry_point(as_node)
    builder.set_finish_point(as_node)
    return builder.compile()
```

用途：**整体替换状态**（rollback 恢复、上下文压缩）必须用 `Overwrite` 而不是普通 update（因为 reducer 会 merge）。这个"单节点图"复用 agent 图的 checkpoint 机制，但**不调度任何 agent 节点**——写完后 head 保持空闲，不会重新触发 agent。

---

## 9. 写入生命周期：谁在什么时候写

### 9.1 写入时机（LangGraph 机制）

```
agent 图执行
  │
  ├─ 节点 A 完成 → checkpoint（完整快照 / delta 写入）
  ├─ 节点 B 完成 → checkpoint
  ├─ ...（每节点一次）
  │
  └─ run 结束 → 最终 checkpoint（含 run 元数据：title、durations 等）
```

- **消息级**：每轮模型调用后写 checkpoint（`thread_state` 的 messages 通道）
- **pending_writes**：节点内的小步写入（`put_writes`），不落完整快照
- **run 级**：worker 在 run 结束时补写 `run_metadata` checkpoint（标题、时长等）

### 9.2 打断与 rollback 的写入（衔接前面聊的"路径 2"）

```python
# runtime/runs/worker.py
# 1) run 开始前：_capture_rollback_point 捕获完整 pre-run 状态
rollback_point = await _capture_rollback_point(accessor, checkpointer, checkpoint_config)

# 2) 取消时（action=rollback）：
#    _rollback_to_pre_run_checkpoint 用状态突变图把 pre-run 状态整体写回
mutation_graph = build_state_mutation_graph("rollback_restore", accessor.mode, ...)
replacement_values = {"messages": Overwrite(list(rollback_point.messages))}
```

- `interrupt`：保留当前 checkpoint（新 run 从断点继续）
- `rollback`：用状态突变图把 pre-run 快照**整体覆写**回 head

### 9.3 写入的并发保护

```python
# worker.py: 持有 _checkpoint_thread_lock 跨 rollback 捕获和 resume 重写
async with _checkpoint_thread_lock(thread_id):
    rollback_point = await _capture_rollback_point(...)   # 读取
    ...                                                    # 重写
# 快照捕获与重写是"一次不被中断的读-写序列"，与图流式串行化
```

---

## 10. 高并发与多 Worker 考量

| 机制 | 作用 |
|---|---|
| **异步连接池**（本节 5） | 并发 run 的 checkpoint 写入不串行 |
| **`CachedHistorySaver`** | 减少 delta 历史的重复读放大（SQL 次数骤降） |
| **Redis 缓存后端** | 多 worker 共享历史缓存（条目不可变 → 天然一致） |
| **`pg_advisory_xact_lock`** | 多实例迁移/事件写入串行化（`bootstrap.py:402`） |
| **checkpoint 模式一致性** | 共享同一 checkpoint 库的所有进程必须同模式同节奏 |
| **每线程操作唯一性** | `runs.operation_kind`（run / checkpoint_write / artifact_write）共享活动线程唯一约束——**同一线程同一时刻只有一个 checkpoint 写者** |

### 多 worker 的硬性约束（再次强调）

```
GATEWAY_WORKERS > 1 时必须：
  database.backend = postgres        （SQLite 文件锁扛不住多进程）
  run_events.backend = db
  run_ownership.heartbeat_enabled = true
否则启动直接 SystemExit（deps.py:_enforce_postgres_for_multi_worker）
```

---

## 11. 关键设计决策总结

| # | 决策 | 理由 |
|---|---|---|
| 1 | **直接复用 LangGraph 官方 saver** | 不自造轮子；checkpoint 语义（密封链、pending_writes）由官方保证 |
| 2 | **Postgres 用连接池而非单连接** | 绕开官方 `from_conn_string` 单连接默认值，并发写不串行 |
| 3 | **异步驱动**（AsyncPostgresSaver + asyncpg + AsyncConnectionPool） | 不阻塞 Gateway 的 asyncio 事件循环 |
| 4 | **full/delta 双模式 + 进程冻结** | delta 省存储（O(N) vs O(N²)），但模式漂移会静默读错 → 冻结 + fail-closed |
| 5 | **delta 历史缓存 + 不可变条目论证** | 缓存失效问题被数据模型消灭——密封链纯函数 |
| 6 | **CheckpointStateAccessor 单一入口** | delta 物化需要图上下文；杜绝绕过 |
| 7 | **状态突变图做整体替换** | 绕过 reducer merge 语义，用 Overwrite 精确恢复 |
| 8 | **async context manager 生命周期** | 无全局单例；Gateway 优雅关停时统一释放连接池 |

---

## 12. 文件索引

| 文件 | 职责 |
|---|---|
| `runtime/checkpointer/async_provider.py` | 异步 checkpointer 工厂（三种后端 + 连接池） |
| `runtime/checkpointer/provider.py` | 同步 checkpointer 工厂（TUI/内嵌客户端用） |
| `runtime/checkpointer/cached_saver.py` | delta 历史缓存包装 |
| `runtime/checkpoint_mode.py` | full/delta 模式冻结、标记、兼容门 |
| `runtime/checkpoint_state.py` | CheckpointStateAccessor + 状态突变图 |
| `runtime/checkpoint_cache/` | 缓存后端（memory / redis） |
| `config/checkpointer_config.py` | legacy checkpointer 配置 |
| `config/database_config.py` | 统一 database 配置（backend/pool/channel mode） |
| `persistence/engine.py` | SQLAlchemy async 引擎（App ORM 层，asyncpg） |
| `persistence/postgres_schema.py` | 双驱动 search_path 注入 |
| `persistence/bootstrap.py` | 建表 + pg_advisory_lock 多实例迁移锁 |
| `runtime/runs/worker.py` | run 执行中 checkpoint/rollback 的写入方 |

---

*文档生成时间：基于 deer-flow @ cc6a265（v2.1.0）代码分析。*
