# Agent A2A（Agent-to-Agent）方案设计

## 文档目标

本文档描述平台 Agent 的 A2A（Agent-to-Agent）调用机制的设计方案。

A2A 的核心思路：**Agent 调用 Agent，通过工具（Tool）的方式实现，由中间件（Middleware）注入到上下文**。

## 设计动机

### 为什么不把子 Agent 混在 `tools` 里

| | 常规工具（tools） | A2A 子 Agent |
|---|---|---|
| 调用载体 | HTTP API / 数据库查询 | 完整的 Agent 执行流程 |
| 生命周期 | 单次请求-响应 | 模型推理 → 工具调用 → 循环 |
| 上下文 | 无状态 | 有独立的 checkpointer |
| 管控方式 | 工具名白名单 | 独立的 `a2a` JSON 配置 |
| 注入方式 | 直接传给 `create_agent(tools=...)` | 中间件动态装配 |

把 A2A 工具和常规工具分离，职责边界更清晰，也为后续扩展（超时控制、调用链追踪、Token 统计）留出独立空间。

### 为什么用中间件而不是在 `assemble_agent` 里硬编码

Agent 组装流程（`AgentAssembler.assemble`）负责**基础能力**：模型、系统提示词、常规工具、checkpointer。A2A 属于**扩展能力**，应该通过中间件体系注入，做到：

- 基础组装不感知 A2A
- 装配过程通过 `AgentBuildConfig.a2a` 驱动
- 后续扩展（如记忆增强、调用保护）只改中间件，不改组装器

## 核心概念

### 1. 子 Agent 注册 — `is_sub_agent`

在 Agent 模板（`agent.agent_templates`）的 `config` 中新增字段：

```json
{
  "agent_id": "job_profile_agent",
  "agent_name": "岗位画像生成 Agent",
  "config": {
    "system_prompt": "...",
    "tools": ["create_job_skills"],
    "is_sub_agent": true,
    ...
  }
}
```

`is_sub_agent: true` 表示该 Agent 可以被其他 Agent 通过 A2A 调用。创建/更新模板时传入，存入 `config` JSONB 中，不单独建列。

### 2. A2A 调用配置 — `a2a`

在 `AgentRunRequest` 中新增可选字段：

```json
{
  "query": "帮我分析这个岗位并生成画像",
  "tools": ["search_jobs"],
  "a2a": {
    "sub_agent_list": ["job_profile_agent", "skill_eval_agent"]
  }
}
```

- `a2a` 为 `null` 或 `sub_agent_list` 为空 → 该 Agent 不具备 A2A 能力
- `sub_agent_list` 非空 → 装配 A2A 工具和中间件
- 子 Agent 被调用时，`a2a` 固定为 `null`（禁止嵌套 A2A）

### 3. 子 Agent 的调用模式

被调用的子 Agent 以**无状态任务**模式执行：

| 参数 | 固定值 | 原因 |
|------|--------|------|
| `conversation_id` | `None` | 不复用历史，每次独立执行 |
| `stream` | `false` | 同步返回结果给主 Agent |
| `a2a` | `None` | 禁止 A→B→C 递归 |

子 Agent 的 checkpointer 会创建临时 thread_id，调用结束即丢弃。

## 架构设计

### 整体数据流

```
AgentRunRequest
  ├── tools: ["search_jobs"]           ← 常规工具，走 tools 白名单
  ├── a2a: {sub_agent_list: [...]}     ← A2A 配置，走中间件体系
  │
  ▼
AgentAssembler.assemble()
  │
  ├── 基础组装（不变）
  │     ├── system_prompt 渲染
  │     ├── 常规工具加载（tools 白名单）
  │     ├── context_schema
  │     ├── 中间件（工具日志/异常/参数注入）
  │     ├── 模型
  │     └── checkpointer
  │
  ├── A2A 扩展（通过中间件体系）
  │     ├── 查 DB：sub_agent_list → agent 名称、描述
  │     ├── 创建 A2A Tool：agent 调用包装为 BaseTool
  │     └── 创建 A2A Middleware：before_agent 注入上下文
  │
  └── create_agent(
        tools=[常规工具, A2A工具],
        middleware=[...常规中间件, A2A中间件]
      )
```

### 组件关系图

```
┌─────────────────────────────────────────────┐
│                AgentRunRequest               │
│  tools: ["search_jobs"]                      │
│  a2a: {sub_agent_list: ["profile", "skill"]} │
└──────────────────┬──────────────────────────┘
                   │
┌──────────────────▼──────────────────────────┐
│            AgentAssembler                    │
│                                              │
│  assemble()                                  │
│    ├── 基础组装 ──────── 不变                │
│    ├── _load_sub_agent_metas()  ── 查 DB     │
│    ├── create_a2a_tool(metas)  ── 构建工具   │
│    └── middleware_factory.build_a2a(...)      │
└──────────────────┬──────────────────────────┘
                   │
     ┌─────────────┼─────────────┐
     ▼             ▼             ▼
┌─────────┐ ┌──────────┐ ┌──────────────┐
│ A2A     │ │ A2A      │ │ Middleware   │
│ Schema  │ │ Tool     │ │ Factory      │
│ (请求)  │ │ (工具)   │ │ (中间件装配) │
└─────────┘ └────┬─────┘ └──────┬───────┘
                 │              │
                 │    ┌─────────▼──────────┐
                 │    │ A2A Context        │
                 │    │ Middleware         │
                 │    │ (before_agent 注入) │
                 │    └────────────────────┘
                 │
      ┌──────────▼──────────┐
      │   子 Agent 调用      │
      │   AgentService.run() │
      │   conversation_id=None │
      │   stream=False       │
      │   a2a=None           │
      └─────────────────────┘
```

## 数据模型变更

### 1. `AgentRunRequest` — 新增 `a2a` 字段

```python
# schemas/request.py

class AgentA2AConfig(BaseModel):
    """A2A 调用配置。"""
    sub_agent_list: list[str] = Field(
        default_factory=list,
        description="可调用的子 Agent ID 列表；为空时该 Agent 不具备 A2A 能力"
    )

class AgentRunRequest(BaseModel):
    # ... 现有字段不变 ...
    a2a: AgentA2AConfig | None = Field(
        default=None,
        description="A2A 调用配置；为空时不启用 A2A"
    )
```

### 2. `AgentBuildConfig` — 新增 `a2a` 字段

```python
# schemas/config.py

class AgentBuildConfig(BaseModel):
    # ... 现有字段不变 ...
    a2a: AgentA2AConfig | None = Field(
        default=None,
        description="A2A 装配配置"
    )
```

### 3. `AgentTemplateConfig` — 新增 `is_sub_agent` 字段

```python
# templates/schemas.py

class AgentTemplateConfig(BaseModel):
    # ... 现有字段不变 ...
    is_sub_agent: bool = Field(
        default=False,
        description="是否为可被子 Agent 调用的 Agent"
    )
```

该字段存入 `agent.agent_templates.config` JSONB 中，不单独建列。

## 组件设计

### 1. A2A Tool — `tools/a2a_tool.py`

A2A 工具将子 Agent 调用包装为 LangChain BaseTool。

**工具描述（模型可见）**：

```
你可以调用以下子 Agent 来完成子任务：

可用子 Agent：
- job_profile_agent: 根据岗位信息生成候选人画像
- skill_eval_agent: 评估候选人技能匹配度

使用规则：
1. 按需调用，不要重复调用同一个子 Agent 做相同的事情
2. 传入的 query 应该清晰、具体，包含子 Agent 完成任务所需的所有信息
3. 子 Agent 返回的是文本结果，你需要整理后呈现给用户
```

**工具实现**：

```python
class A2ACallInput(BaseModel):
    agent_id: str = Field(description="要调用的子 Agent ID")
    query: str = Field(description="传给子 Agent 的任务指令")

def create_a2a_tool(sub_agent_metas: list[dict]) -> BaseTool:
    """
    创建 A2A 工具。

    Args:
        sub_agent_metas: [{agent_id, agent_name, description}, ...]

    Returns:
        可传给 create_agent(tools=...) 的 BaseTool 实例。
    """
```

`_run` 方法：
1. 根据 `agent_id` 从模板 DB 获取配置
2. 构造 `AgentRunRequest(query=query, conversation_id=None, stream=False, a2a=None)`
3. 创建临时 `AgentService` → `agent_service.run(request)`
4. 返回子 Agent 的 `answer`

### 2. A2A Middleware — `middlewares/a2a_context.py`

在模型调用前，将子 Agent 元信息注入到 runtime context 中，供后续调用追踪使用。

```python
class A2AAgentContextMiddleware(AgentMiddleware[CareerAgentState]):
    """A2A 上下文注入中间件。"""
    state_schema = CareerAgentState

    async def abefore_agent(self, request, handler):
        """Agent 执行开始时注入 A2A 上下文（仅触发一次）。"""
        # 第一版：确保 runtime.context 中有 a2a_agents 结构化数据
        # 后续可扩展：A2A 调用链追踪、Token 统计、超时控制
        return await handler(request)
```

### 3. MiddlewareFactory 扩展 — `middlewares/factory.py`

新增 A2A 中间件构建方法：

```python
def build_a2a_middleware(
    self,
    sub_agent_metas: list[dict] | None,
) -> object | None:
    """创建 A2A 上下文中间件。"""
    if not sub_agent_metas:
        return None
    from app.server.agent.src.middlewares.a2a_context import create_a2a_context_middleware
    return create_a2a_context_middleware(sub_agent_metas)
```

### 4. AgentAssembler 扩展 — `agent/assembler.py`

在 `assemble()` 方法中，常规工具加载之后、`create_agent` 之前插入 A2A 装配逻辑：

```python
# 第 X 步：A2A 扩展
a2a_tool = None
a2a_middleware = None
if build_config.a2a and build_config.a2a.sub_agent_list:
    sub_agent_metas = await self._load_sub_agent_metas(
        build_config.a2a.sub_agent_list
    )
    if sub_agent_metas:
        a2a_tool = create_a2a_tool(sub_agent_metas)
        a2a_middleware = self.middleware_factory.build_a2a_middleware(
            sub_agent_metas
        )

# create_agent 调用时：
agent = create_agent(
    model=model,
    tools=tools + ([a2a_tool] if a2a_tool else []),
    system_prompt=system_prompt,
    response_format=build_config.response_format,
    context_schema=context_schema,
    middleware=middlewares + ([a2a_middleware] if a2a_middleware else []),
    checkpointer=checkpointer,
)
```

新增辅助方法 `_load_sub_agent_metas`：

```python
async def _load_sub_agent_metas(
    self,
    agent_ids: list[str],
) -> list[dict]:
    """根据 agent_id 列表查询子 Agent 元信息。

    Args:
        agent_ids: 子 Agent ID 列表。

    Returns:
        [{agent_id, agent_name, description}, ...]
        遇到不存在的 agent_id 时跳过并 warn，不阻断组装流程。
    """
```

## 调用链示例

### 场景：用户让主 Agent 分析岗位并生成画像

**第一步：API 请求**

```json
{
  "query": "帮我分析 JD-001 这个岗位，然后生成候选人画像",
  "conversation_id": "conv_abc",
  "tools": ["search_jobs", "parse_jd"],
  "a2a": {
    "sub_agent_list": ["job_profile_agent"]
  },
  "stream": false
}
```

**第二步：组装 Agent**

`AgentAssembler.assemble()` 组装出：
- 常规工具：`search_jobs`、`parse_jd`
- A2A 工具：`a2a_call`（描述中包含 `job_profile_agent` 的名称和用途）
- A2A 中间件：`A2AAgentContextMiddleware`

**第三步：模型推理**

模型看到系统提示词 + 工具列表（含 `a2a_call`），决定：
1. 先调用 `search_jobs` 获取岗位信息
2. 再调用 `a2a_call(agent_id="job_profile_agent", query="基于以下JD生成画像...")` 

**第四步：A2A Tool 执行**

```
a2a_call._run(agent_id="job_profile_agent", query="基于以下JD生成画像...")
  ├── 查模板 DB: agent_id="job_profile_agent"
  │     → system_prompt, tools=["create_job_skills"], etc.
  ├── 构造 AgentRunRequest:
  │     query="基于以下JD生成画像..."
  │     conversation_id=None     ← 无状态
  │     stream=False
  │     a2a=None                 ← 禁止嵌套
  │     tools=["create_job_skills"]
  ├── 创建临时 AgentService
  ├── await agent_service.run(request)
  │     → AgentAssembler.assemble()  [不加载 A2A]
  │     → agent.ainvoke()
  │     → 返回 answer
  └── 返回子 Agent 的 answer 给主 Agent
```

**第五步：主 Agent 整理回复**

主 Agent 拿到子 Agent 的画像结果，结合自己的分析，返回最终回答给用户。

## 边界约束

### 明确不做

| 约束 | 说明 |
|------|------|
| 递归 A2A | 子 Agent 调用时 `a2a=None`，不加载 A2A 工具 |
| checkpointer 复用 | 子 Agent `conversation_id=None`，生成临时 thread_id |
| 流式 A2A | 子 Agent `stream=False`，同步返回完整结果 |
| A→A 自调用 | `sub_agent_list` 由调用方指定，调用方应避免把自己放进列表 |
| 子 Agent 参数透传 | 子 Agent 的 `tools`、`system_prompt` 使用模板配置，主 Agent 不覆盖 |

### 后续可扩展

| 扩展项 | 说明 |
|------|------|
| A2A 调用链追踪 | 在 `AgentRuntimeContext` 或 A2A Middleware 中追加 `call_chain` |
| 超时控制 | `AgentA2AConfig` 中加 `timeout_seconds` |
| Token 统计 | A2A Middleware 中统计子 Agent 消耗的 Token |
| 子 Agent 结果缓存 | 相同 query+agent_id 短时间内复用结果 |

## 文件变更清单

| 文件 | 操作 | 说明 |
|------|------|------|
| `schemas/request.py` | 修改 | 新增 `AgentA2AConfig`，`AgentRunRequest` 加 `a2a` 字段 |
| `schemas/config.py` | 修改 | `AgentBuildConfig` 加 `a2a` 字段 |
| `templates/schemas.py` | 修改 | `AgentTemplateConfig` 加 `is_sub_agent` 字段 |
| `tools/a2a_tool.py` | **新建** | A2A 工具实现 |
| `middlewares/a2a_context.py` | **新建** | A2A 上下文注入中间件 |
| `middlewares/factory.py` | 修改 | 新增 `build_a2a_middleware` 方法 |
| `agent/assembler.py` | 修改 | 新增 `_load_sub_agent_metas`，`assemble()` 加 A2A 装配步骤 |
| `agent/service.py` | 不改 | A2A 完全由中间件体系接管 |

## 与其他文档的关系

- Agent 组装基础流程：参见 `Agent构建模式说明.md`
- 中间件体系说明：参见 `Agent服务架构说明.md`
- A2A 工具的使用规则（给模型看的 prompt）：嵌入在 A2A Tool 的 `description` 中，由 `create_a2a_tool()` 动态生成
