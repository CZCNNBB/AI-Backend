# Agent MCP接入最终方案

## 1. 目标

Agent 平台需要支持外部能力以 MCP 工具的形式热插拔接入。平台内置能力，例如 A2A、上下文注入、知识库检索中间件，可以继续由 Agent 内部实现；外部业务服务，例如岗位技能查询和创建，则通过 MCP 挂载为 Agent 可选择工具。

本方案采用单表设计：一条 MCP 记录就是一个可被 Agent 选择的 MCP 工具。

## 2. 核心原则

1. 前端和 Agent 只感知“工具”，不感知“MCP 服务”。
2. `mcp_code` 是平台内唯一工具编码，例如 `job.search_job_skills`。
3. `name` 是 MCP 服务中的真实工具名，例如 `search_job_skills`。
4. `base_url` 记录工具来源地址，同一个 MCP 服务下的多个工具可以共享相同地址。
5. 运行时内部可以按 `base_url + transport + auth_config` 临时分组加载工具，但这个分组不暴露给用户。

## 3. 数据表

表名：`agent.agent_mcp_tools`

核心字段：

| 字段 | 说明 |
| --- | --- |
| `id` | 主键 ID |
| `mcp_code` | 平台 MCP 工具唯一编码 |
| `name` | MCP 真实工具名 |
| `description` | 工具描述 |
| `base_url` | MCP 服务访问地址 |
| `transport` | MCP 传输协议，当前主要使用 `http` |
| `auth_type` | 认证类型，第一阶段可为空 |
| `auth_config` | 认证配置 JSON |
| `input_schema` | 工具入参 JSON Schema |
| `output_schema` | 工具出参 JSON Schema |
| `status` | 工具状态：`enabled` / `disabled` |
| `created_at` | 创建时间 |
| `updated_at` | 更新时间 |

## 4. API设计

统一挂载在 Agent 服务下：`/agent/mcp`

| 接口 | 作用 |
| --- | --- |
| `POST /agent/mcp/upsert` | 新增或更新 MCP 工具 |
| `POST /agent/mcp/detail` | 查询 MCP 工具详情 |
| `POST /agent/mcp/search` | 查询 MCP 工具列表 |
| `POST /agent/mcp/delete` | 删除 MCP 工具 |
| `POST /agent/mcp/test` | 测试已保存工具或临时 MCP 地址 |
| `POST /agent/mcp/sync` | 从某个 MCP 地址同步工具列表 |
| `POST /agent/mcp/invoke` | 直接测试调用某个 MCP 工具 |

## 5. 同步流程

1. 前端提交 `base_url`、`transport`、可选 `code_prefix`。
2. AI-backend 使用 `MultiServerMCPClient` 连接 MCP 服务。
3. 读取远端 MCP 工具列表。
4. 对每个工具生成平台工具编码：
   - 有 `code_prefix`：`{code_prefix}.{tool_name}`
   - 无 `code_prefix`：`{tool_name}`
5. 写入或更新 `agent.agent_mcp_tools`。
6. 前端工具管理页展示这些 MCP 工具。

## 6. Agent运行时加载流程

1. Agent 模板或运行请求中的 `tools` 只允许传入 MCP 工具编码。
2. `AgentToolService` 会拒绝 `a2a_call`、`set_task_plan`、`update_task_step` 等系统内置工具出现在 `tools` 中。
3. `MCPService.load_langchain_tools` 从 `agent_mcp_tools` 查询已启用工具。
4. 按 `base_url + transport + auth_config` 临时分组创建 MCP 客户端。
5. 通过 `langchain-mcp-adapters` 获取 LangChain Tool。
6. 只筛选本次请求指定的 MCP 工具，并传入 `create_agent`。
7. A2A、规划等内置能力工具不走 `tools` 字段，而是由 `a2a.sub_agent_list`、`optional_features.planning_enabled` 等能力参数自动挂载。

## 7. 为什么不用服务表

当前平台的管理对象是“Agent 可选工具”，不是“MCP 服务”。如果额外引入 MCP 服务表，会让前端配置、模板选择和运行时加载都多一层概念。单表方案更直观，也足够支持当前的热插拔需求。

后续如果真的需要按服务维度做健康检查、批量授权、服务分组或多租户管理，再拆出服务表也不迟。

## Runtime Context 自动注入

AI-backend 通过 langchain-mcp-adapters 的 ToolCallInterceptor 读取
`ToolRuntime.context.inputs`，不识别具体工具名，也不维护字段白名单，而是把完整
`inputs` 编码后写入统一的 `X-Agent-Runtime-Inputs` 请求头。嵌套对象、数组和中文
会使用紧凑 JSON 与 URL-safe Base64 传输。

MCP 服务负责解码完整 `inputs`，每个工具再自行读取和校验需要的字段。例如
`save_stage_result` 从中读取 `user_id`、`project_id`、`branch_id`、`node_id`
和 `stage_code`，模型侧公开 Schema 仍然只包含 `result` 和 `summary`。
脱离 Agent Runtime 的工具管理页测试不会强制注入该请求头。
