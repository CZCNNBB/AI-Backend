# MCP 接入 AI-backend 方案

## 1. 文档目的

本文用于沉淀 MCP 接入 AI-backend 的目标架构、模块职责、工具创建流程、Agent 绑定流程和运行时调用流程。

本文同时描述目标方案和当前实施状态。MCP 管理代码已经迁移到 `app/server/fastmcp`，Agent 内部只保留 MCP 运行时消费代码。

## 2. 核心设计

MCP Platform 不单独建设成另一个外部项目，而是作为与 Agent、Knowledge 平级的大模块集成在 AI-backend 中。

```text
AI-backend
├── Agent 模块
├── Knowledge 模块
├── MCP Platform 模块
└── 其他基础模块
```

第一阶段采用模块化单体：只部署一个后端服务，但保持代码和协议边界。后续并发量、权限隔离或团队协作要求提高时，可以把 MCP Platform 单独拆出。

## 3. 总体架构

```text
Java / Go / Python 等外部业务系统
                │ HTTP API
                ▼
┌─────────────────────────────────────┐
│ AI-backend / MCP Platform 模块      │
│                                     │
│ 配置和测试 HTTP API                 │
│ 把 HTTP API 转换成 MCP Tool         │
│ 发布、停用和维护 MCP Tool           │
│ 提供 tools/list 和 tools/call       │
└──────────────────┬──────────────────┘
                   │ MCP 协议
                   ▼
┌─────────────────────────────────────┐
│ Agent 内部 MCP Runtime              │
│                                     │
│ 发现并筛选 MCP Tool                 │
│ 转换为 LangChain Tool               │
│ 注入 Agent 运行时上下文             │
└──────────────────┬──────────────────┘
                   ▼
             LangChain Agent
```

## 4. 模块职责

### 4.1 Agent 内部 MCP Runtime

Agent 内部保留 `mcp` 文件夹，但它只负责消费 MCP Tool：

- 创建 MCP Client 并连接 MCP Platform。
- 通过 `tools/list` 发现实际可用工具。
- 根据 Agent 配置中的工具 `name` 筛选工具。
- 通过 LangChain MCP Adapter 转换为 LangChain Tool。
- 将 MCP Tool 与 AI-backend 内置工具合并后挂载到 Agent。
- 注入可信的 Agent 运行时上下文。
- 处理 MCP 连接、发现和调用错误。

Agent 内部 MCP Runtime 不负责：

- 创建、编辑和删除 MCP Tool。
- 配置和测试外部业务 HTTP API。
- 保存外部业务 API 密钥。
- 管理 MCP Tool 的发布、停用和版本。

### 4.2 MCP Platform 大模块

MCP Platform 负责生产和管理 MCP Tool：

- 配置外部 HTTP API 的 Method、URL、Path、Query、Header 和 JSON Body。
- 配置输入 Schema、参数映射和业务系统认证信息。
- 测试 API 连通性和带参数调用结果。
- 将测试通过的 HTTP API 发布为 MCP Tool。
- 管理工具草稿、发布、停用和删除。
- 实现 MCP `tools/list` 和 `tools/call`。
- 校验参数、调用目标 API 并转换返回结果。
- 记录调用日志、耗时和错误信息。

### 4.3 Agent 模块

Agent 模块继续负责：

- Agent 创建、编辑和删除。
- 提示词、模型和运行参数配置。
- Plan、A2A、Knowledge、文件等内部能力装配。
- 为 Agent 选择允许使用的 MCP Tool。
- Agent 会话、运行记录、流式输出和编排。

## 5. 工具分类

### 5.1 内置能力工具

例如 Plan 的 `set_task_plan`、A2A 的 `a2a_call`、Knowledge 的 `search_knowledge_base` 和文件读取工具。这些能力由开关或运行上下文自动挂载，不由 MCP Platform 管理。

### 5.2 MCP 外接工具

用于连接 Java、Go 或第三方业务系统，例如查询岗位、创建岗位画像、查询客户和创建订单。它们由 MCP Platform 创建并发布，Agent 只负责选择和使用。

## 6. 第一阶段工具标识

第一阶段不额外设计工具编码，直接使用 MCP 协议中的 `name` 作为全局唯一标识。

```json
{
  "name": "job_search",
  "description": "根据关键词和城市查询招聘岗位"
}
```

规则如下：

- `name` 在 MCP Platform 中全局唯一。
- Agent 配置直接保存 `name`。
- MCP `tools/list` 返回同一个 `name`。
- Agent Runtime 根据同一个 `name` 筛选工具。
- 工具发布后原则上不允许修改 `name`。
- 必须改名时，第一阶段采用创建新工具、调整 Agent、停用旧工具的方式。

推荐使用带业务域的名称：

```text
job_search
job_create_profile
resume_analyze
crm_query_customer
order_create
```

后续出现多 MCP Server 同名冲突、复杂版本管理或重命名需求时，再引入独立稳定编码。

## 7. 数据库归属

MCP 数据统一使用独立 PostgreSQL Schema：

```text
mcp
```

当前工具表为：

```text
mcp.mcp_tools
```

原来的空表 `agent.agent_mcp_tools` 不再使用，也不保留兼容逻辑。`mcp.mcp_tools.name` 是当前唯一工具标识。

建设 MCP Platform 时，HTTP API 配置、密钥引用、测试记录和调用审计等数据也应放入 `mcp` Schema，不能重新放回 `agent` Schema。

## 8. 新建 MCP Tool

“新建 MCP Tool”不是登记一个已经存在的远程工具，而是把普通 HTTP API 真正转换成 Agent 可以发现和调用的 MCP Tool。

```text
填写工具 name、描述和输入参数
→ 配置目标 HTTP API
→ 配置参数到 Path / Query / Header / Body 的映射
→ 填写测试参数并调用 API
→ 检查状态码和响应结构
→ 测试通过后发布
→ MCP tools/list 开始返回该工具
```

发布后的调用流程：

```text
接收 MCP tools/call
→ 校验工具状态和输入参数
→ 读取 HTTP API 配置与密钥引用
→ 构造并发送 HTTP 请求
→ 提取和限制响应内容
→ 转换为 MCP 调用结果
```

### 8.1 参数配置模型

前端不要求使用者手写 JSON Schema，而是维护参数列表，后端根据 `source=tool` 的参数自动生成 MCP 输入 Schema：

```json
{
  "name": "search_jobs",
  "description": "搜索职位",
  "api_url": "http://job-service/api/jobs/{category}",
  "http_method": "POST",
  "static_headers": {
    "X-App-Id": "ai-platform"
  },
  "parameters": [
    {
      "name": "category",
      "location": "path",
      "source": "tool",
      "data_type": "string",
      "required": true
    },
    {
      "name": "filters.keyword",
      "location": "body",
      "source": "tool",
      "data_type": "string"
    },
    {
      "name": "X-Tenant-Id",
      "location": "header",
      "source": "runtime",
      "runtime_path": "tenant_id"
    }
  ],
  "auth_type": "bearer",
  "auth_config": {
    "token": "由平台保存的 Token"
  },
  "timeout_seconds": 30,
  "status": "draft"
}
```

参数来源：

- `tool`：暴露给 Agent，由模型调用 Tool 时填写。
- `runtime`：从 Agent 可信 `inputs` 读取，不出现在 Tool Schema 中。
- `static`：使用平台配置的固定值，不出现在 Tool Schema 中。

`name` 直接填写目标 API 的参数字段名，同时作为 Agent 可见的 MCP Tool 参数名，不再维护额外字段别名。参数位置支持 `path`、`query`、`header` 和 `body`；body 参数名支持点分路径，例如 `filters.keyword` 会生成嵌套 JSON。

认证由平台独立注入，目前支持 `none`、`bearer`、`basic` 和 `api_key`。Token、密码和 API Key 不会成为模型参数。

## 9. 创建 Agent 时发现工具

创建或编辑 Agent 时，通过 MCP Platform 工具目录展示已经发布的工具：

```text
Agent 编辑页面
→ 查询已发布工具目录
→ 展示 name、description 和 input_schema
→ 用户勾选工具
→ 将 name 写入 Agent 配置
```

当前 Agent 模板继续通过 `config.tools` 保存 MCP 工具名：

```json
{
  "agent_id": "job-profile-agent",
  "config": {
    "system_prompt": "你负责生成岗位画像。",
    "tools": [
      "job_search",
      "job_create_profile"
    ],
    "optional_features": {
      "planning_enabled": true,
      "knowledge_enabled": false,
      "long_term_memory_enabled": false
    },
    "a2a": {
      "sub_agent_list": []
    }
  }
}
```

`config.tools` 只保存 MCP 外接工具名。Plan、A2A、Knowledge 和文件等内部工具仍由能力配置和运行上下文控制。

## 10. Agent 运行时发现工具

管理时目录查询和 Agent 运行时发现是两个阶段：

```text
管理时：查询已发布目录 → 用户选择 → 保存工具 name

运行时：读取 config.tools
      → 连接 MCP Platform MCP Endpoint
      → 调用 tools/list
      → 校验 name 是否仍然可用
      → 转换为 LangChain Tool
      → 挂载到 Agent
```

即使两个模块当前在同一个 AI-backend 中，运行时也保持标准 MCP 协议边界，不能让 Agent Runtime 直接查询 MCP Platform 数据表并绕过 MCP Server。

## 11. 运行时调用流程

```text
用户请求 Agent
→ 加载 Agent 模板
→ 根据能力配置装配内置工具
→ 根据 config.tools 加载 MCP 工具
→ MCP Tool 转换为 LangChain Tool
→ Agent 选择调用工具
→ Agent MCP Runtime 发起 tools/call
→ MCP Platform 调用目标 HTTP API
→ 返回 MCP Result / LangChain ToolMessage
→ Agent 继续推理并回复
```

## 12. 目标代码边界

项目已经使用 `fastmcp` 作为 MCP Platform 模块名。业务代码必须始终通过 `app.server.fastmcp` 绝对导入，避免和第三方 `fastmcp` Python 包混淆：

```text
app/server/fastmcp/
├── api/tool_api.py     # 配置、测试、发布、停用和删除接口
├── src/models.py       # mcp.mcp_tools ORM 模型
├── src/schemas.py      # 参数列表和管理接口 Schema
├── src/repository.py   # 只执行 SQL/flush 的数据访问层
├── src/executor.py     # 唯一的通用 HTTP API 执行器
├── src/registry.py     # 数据库配置到动态 FastMCP Tool 的注册中心
├── src/server.py       # FastMCP Server 和 Streamable HTTP ASGI 应用
├── src/config.py       # Agent 访问平台 MCP Endpoint 的地址配置
└── tests/              # 参数组装与动态注册测试
```

Agent 内部只保留运行时消费代码：

```text
app/server/agent/src/mcp/
├── client.py
├── runtime adapter/service
├── runtime_context_interceptor.py
└── runtime schemas
```

MCP 管理 API、数据库 Model、Repository、通用执行器和 FastMCP Registry 均位于该模块。调用审计和密钥托管属于后续增强项。

## 13. 当前接口迁移方向

原 `/agent/mcp/*` 路由已经移除，管理接口迁移为 `/fastmcp/tools/*`：

| 能力 | 目标归属 |
| --- | --- |
| 新增、更新和删除 MCP Tool | MCP Platform |
| 配置和测试 HTTP API | MCP Platform |
| 发布和停用工具 | MCP Platform |
| 查询已发布工具目录 | MCP Platform 提供，Agent 页面消费 |
| MCP Tool 转 LangChain Tool | Agent MCP Runtime |
| Agent 运行时调用 MCP Tool | Agent MCP Runtime |

前后端已经切换到新路由，不保留旧 `/agent/mcp/*` 兼容层。

当前实际接口：

| 接口 | 作用 |
| --- | --- |
| `POST /fastmcp/tools/upsert` | 保存 API、参数、请求头和认证配置 |
| `POST /fastmcp/tools/test` | 保存前或保存后测试目标 API |
| `POST /fastmcp/tools/publish` | 发布或停用动态 Tool |
| `POST /fastmcp/tools/search` | 查询全部状态的管理目录 |
| `POST /fastmcp/tools/detail` | 查询单个工具完整配置 |
| `POST /fastmcp/tools/invoke` | 管理接口直接调试已发布工具 |
| `POST /fastmcp/tools/delete` | 删除配置并热移除 Tool |
| `/mcp` | FastMCP 3.4 Streamable HTTP 协议入口 |

## 14. 多进程与热更新

动态工具不能只保存在单个 Python 进程内存中，否则多个 Worker 会看到不同工具列表。

```text
PostgreSQL mcp Schema 作为唯一数据源
→ 发布工具后刷新当前进程注册表
→ 每个 Worker 启动时加载已发布工具
```

第一阶段可以单 Worker 运行。后续启用多 Worker 时，再增加 Redis、PostgreSQL Notify 或版本轮询通知所有 Worker 刷新注册表。

## 15. 第一阶段范围

第一阶段支持：

- 手动创建和编辑 HTTP API 工具。
- HTTP GET、POST、PUT、PATCH、DELETE。
- Path、Query、Header 和 JSON Body 参数映射。
- JSON Schema 输入校验。
- API 连通性和带参数调用测试。
- 工具草稿、发布和停用。
- MCP `tools/list` 和 `tools/call`。
- 基础超时和非 2xx 错误处理。
- Agent 创建页面选择已发布 MCP Tool。
- Agent Runtime 转换并调用 MCP Tool。

第一阶段暂不包含：

- 自动导入整个 OpenAPI 文档。
- 多 HTTP API 工作流编排。
- 执行任意 Python 或 JavaScript。
- 复杂版本分支、审批流和多租户隔离。
- MCP Platform 中的 Agent 编排。
- 文件上传、表单请求和流式 HTTP 响应。
- 独立密钥托管、敏感字段掩码和调用审计日志。

## 16. 已确认事项

1. MCP Platform 作为 AI-backend 内与 Knowledge 平级的大模块建设。
2. Agent 内部 MCP 只负责发现、筛选、LangChain 转换和运行时调用。
3. MCP Platform 负责把普通 HTTP API 真正转换成 MCP Tool。
4. MCP Platform 负责工具创建、测试、发布、停用和维护。
5. 第一阶段直接使用 MCP 工具 `name` 作为全局唯一标识。
6. Agent 配置直接保存 MCP 工具 `name`。
7. MCP 数据统一放在 PostgreSQL `mcp` Schema。
8. 当前工具表为 `mcp.mcp_tools`，不再使用 `agent.agent_mcp_tools`。
9. 项目处于开发阶段，不为旧 MCP 管理接口和旧字段保留兼容逻辑。
10. 当前采用单体部署，但 Agent Runtime 与 MCP Platform 之间保留标准 MCP 协议边界。

## 17. 后续实施顺序

1. 已完成 `mcp.mcp_tools` 的 HTTP API 配置表设计。
2. 已创建 `app/server/fastmcp` 大模块并迁移 MCP 管理职责。
3. 已移除旧 `/agent/mcp/*` 路由并精简 Agent 内部 MCP Runtime。
4. 已完成 tool/runtime/static 参数来源及 path/query/header/body 映射。
5. 已完成固定请求头、Bearer、Basic、API Key 和 runtime inputs 注入。
6. 已完成 API 测试、通用 HTTP 执行器和 FastMCP 动态 Registry。
7. 已挂载 `/mcp` Streamable HTTP Endpoint，并让 Agent 统一从该地址发现 Tool。
8. 已调整工具管理页面，支持参数列表、认证配置、保存前测试和发布状态。
9. 下一步执行真实业务 API 的创建、发布、Agent 挂载和运行端到端联调。
10. 多 Worker 前增加跨进程 Registry 刷新机制；生产前增加密钥托管和调用审计。
