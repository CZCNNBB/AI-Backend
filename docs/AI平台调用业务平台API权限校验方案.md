# AI 平台调用业务平台 API 权限校验方案

> 方案状态：已实施  
> 确定日期：2026-08-28  
> 适用范围：AI-backend、FastMCP、外部业务平台接入  
> 代码和空数据库初始化 SQL 已按本文档完成改造；已有开发数据库需要执行一次性结构调整。

## 1. 背景

Agent 接入外部业务平台后，会通过 MCP Tool 调用业务平台提供的 HTTP API。业务
API 通常需要使用当前登录用户的 Token 判断用户身份和业务权限。

不同业务平台使用的 Token 请求头并不统一，例如：

```http
Authorization: Bearer eyJ...
X-Token: eyJ...
X-Access-Token: eyJ...
token: eyJ...
```

AI 平台无法提前枚举所有业务系统的认证协议，也不应该复制业务平台的用户、角色、
菜单和数据权限体系。因此，本方案不再预设 Bearer、Basic、API Key 等认证类型，
而是把业务用户凭证视为一段不透明文本，由 MCP Tool 配置决定它最终进入目标 API
的哪个请求头。

## 2. 方案目标

本方案需要实现以下目标：

1. 外部业务平台使用统一入口请求头向 AI 平台传递当前用户凭证。
2. AI 平台不解析、不验证、不保存业务用户凭证。
3. 每个 MCP Tool 可以配置目标业务 API 实际接收 Token 的请求头名称。
4. FastMCP 调用目标 API 时，将本次 Agent 请求携带的凭证原样写入目标请求头。
5. 目标业务 API 继续负责最终的身份认证和权限判断。
6. 业务 API 返回 `401`、`403` 或业务权限错误时，Agent 能得到安全、明确的工具错误。
7. Token 不进入模型参数、Tool Schema、会话消息、Checkpoint 和普通日志。

## 3. 不在本方案中实现的能力

第一阶段明确不实现以下能力：

- 不同步业务平台用户表、角色表和权限表。
- 不在 AI 平台判断用户是否有某个业务操作权限。
- 不维护“用户—工具”级权限关系。
- 不预设 Bearer、Basic、API Key 等业务 Token 类型。
- 不自动给 Token 增加 `Bearer `、`Token ` 等前缀。
- 不自动刷新、续期或交换业务 Token。
- 不把 Token 写入数据库供后续运行复用。
- 不支持 Cookie、Query 参数等其他凭证位置；第一阶段只支持 HTTP Header。

固定的系统级请求头或平台级密钥仍可通过 MCP Tool 已有的 `static_headers` 配置。

## 4. 两层权限边界

AI 平台调用业务 API 时存在两层不同的权限校验，二者不能混淆。

### 4.1 AI 平台入口身份校验

外部业务平台调用 AI-backend 时携带：

```http
X-API-Key: AI平台签发给业务平台的Key
```

AI-backend 使用 `X-API-Key` 识别调用来自哪个业务平台，并校验：

- API Key 是否存在、启用和有效。
- 当前 Agent 是否绑定该业务平台。
- 当前会话和外部用户是否属于该业务平台调用上下文。

这一层解决“哪个业务平台可以调用哪个 Agent”的问题。

### 4.2 业务用户权限校验

外部业务平台同时可以携带：

```http
X-Business-Authorization: 当前登录用户的业务凭证
```

AI 平台不校验该值是否有效，只在本次 Agent 运行期间保存于内存运行上下文中。当
Agent 调用需要业务用户身份的 MCP Tool 时，FastMCP 根据 Tool 配置把它原样放入
目标 API 请求头。

目标业务 API 使用自身已有的认证与权限体系完成最终判断。这一层解决“当前业务
用户能否执行具体业务操作”的问题。

## 5. 最终调用链路

```text
业务前端中的已登录用户
  → 业务后端取得当前用户 Token
  → POST /agent/messages
      X-API-Key: platform-key
      X-Business-Authorization: opaque-credential
  → AI-backend 校验业务平台身份和 Agent 绑定关系
  → Token 进入本次 Agent Runtime Credentials
  → Agent 决定调用某个 MCP Tool
  → AI-backend 使用内部运行上下文把 Token 交给 FastMCP
  → FastMCP 读取 Tool.business_token_header
  → 组装目标请求头：
      <business_token_header>: <X-Business-Authorization 原始值>
  → 调用目标业务 API
  → 目标业务 API 完成用户认证和业务权限校验
  → 结果返回 MCP Tool，再由 Agent 组织回答
```

## 6. MCP Tool 配置模型

### 6.1 新增字段

MCP Tool 新增一个可选字段：

```text
business_token_header
```

字段语义：

| 配置值 | 执行行为 |
| --- | --- |
| `NULL` 或空字符串 | 该 Tool 不使用业务用户 Token |
| `Authorization` | 原样写入目标 API 的 `Authorization` 请求头 |
| `X-Token` | 原样写入目标 API 的 `X-Token` 请求头 |
| 其他合法 Header 名 | 原样写入对应目标请求头 |

前端字段名称统一使用：

```text
业务 Token 目标请求头（可选）
```

不使用“校验请求头”这个名称，因为 AI 平台不负责校验 Token，只负责映射和透传。

### 6.2 配置示例一：X-Token

MCP Tool 配置：

```json
{
  "name": "query_business_order",
  "api_url": "http://business-service/api/orders/query",
  "business_token_header": "X-Token"
}
```

调用 Agent：

```http
X-Business-Authorization: abc123
```

FastMCP 调用目标业务 API：

```http
X-Token: abc123
```

### 6.3 配置示例二：Authorization Bearer

MCP Tool 配置：

```json
{
  "name": "query_user_profile",
  "api_url": "http://business-service/api/users/me",
  "business_token_header": "Authorization"
}
```

业务平台传递完整的目标请求头值：

```http
X-Business-Authorization: Bearer eyJhbGciOi...
```

FastMCP 原样调用：

```http
Authorization: Bearer eyJhbGciOi...
```

AI 平台不会自动增加或删除 `Bearer ` 前缀。

### 6.4 固定请求头

与当前用户无关的固定请求头继续使用 `static_headers`：

```json
{
  "Content-Type": "application/json",
  "X-App-Id": "ai-platform"
}
```

固定 Token 也可以使用 `static_headers`，但不得把用户动态 Token 保存为固定请求头。

## 7. 数据库调整方案

当前 `mcp.mcp_tools` 中的以下字段将不再使用：

```text
auth_type
auth_config
```

改造后使用单一字段：

```sql
business_token_header VARCHAR(150)
```

已有开发数据库执行以下一次性结构调整：

```sql
BEGIN;

ALTER TABLE mcp.mcp_tools
    DROP CONSTRAINT IF EXISTS ck_mcp_tools_auth_type,
    DROP COLUMN IF EXISTS auth_type,
    DROP COLUMN IF EXISTS auth_config,
    ADD COLUMN IF NOT EXISTS business_token_header VARCHAR(150);

COMMENT ON COLUMN mcp.mcp_tools.business_token_header IS
'可选的目标业务 Token 请求头；值来自本次 X-Business-Authorization 并原样透传。';

COMMIT;
```

项目仍处于开发阶段，本次改造不保留旧 `runtime_bearer` 兼容逻辑。正式实施时应把
该调整直接合并到空数据库初始化 SQL，而不是继续增加长期迁移兼容代码。

## 8. 请求组装规则

FastMCP 执行目标 API 时，按以下规则组装请求头：

1. 加载 `static_headers`。
2. 加载参数映射中 `location=header` 的普通请求头。
3. 如果 `business_token_header` 为空，结束 Token 处理。
4. 如果配置了 `business_token_header`，读取本次 Runtime Credentials。
5. 如果本次请求没有 `X-Business-Authorization`，禁止调用目标 API，并返回缺少凭证错误。
6. 如果存在凭证，将其原样写入 `business_token_header` 指定的请求头。

配置保存时必须检查请求头名称冲突。比较时忽略大小写；以下配置应直接拒绝保存：

- `business_token_header` 与 `static_headers` 中的请求头同名。
- `business_token_header` 与参数映射中 `location=header` 的字段同名。

这样可以避免固定配置、模型参数或运行时凭证互相覆盖。

## 9. 输入安全校验

### 9.1 目标请求头名称

`business_token_header` 必须满足合法 HTTP Header Name 规则：

- 长度为 1 到 150 个字符。
- 不允许空格、冒号、中文、换行符和控制字符。
- 只允许 HTTP Token 字符。
- 保存时清理首尾空白，空字符串统一保存为 `NULL`。

### 9.2 Token 值

`X-Business-Authorization` 的值作为不透明凭证处理：

- 不解析 JWT。
- 不判断前缀。
- 不修改字符内容。
- 拒绝包含 `\r`、`\n` 或其他非法控制字符的值。
- 不写入日志和异常详情。

## 10. 异常处理规则

### 10.1 Tool 需要 Token，但请求未提供

FastMCP 不调用目标 API，直接返回结构化工具错误：

```json
{
  "code": "BUSINESS_CREDENTIAL_MISSING",
  "message": "当前操作需要业务用户凭证，请重新登录或重新发起请求"
}
```

### 10.2 目标 API 返回 401

统一转换为：

```json
{
  "code": "BUSINESS_CREDENTIAL_INVALID",
  "status_code": 401,
  "message": "业务用户凭证无效或已过期"
}
```

AI 平台不自动刷新 Token，也不使用相同 Token 自动重试。

### 10.3 目标 API 返回 403

统一转换为：

```json
{
  "code": "BUSINESS_PERMISSION_DENIED",
  "status_code": 403,
  "message": "当前业务用户没有执行该操作的权限"
}
```

Agent 可以据此向用户解释权限不足，但不能自行绕过权限或改用平台固定 Token 重试。

### 10.4 业务系统使用 200 表示权限失败

部分业务 API 会返回 HTTP 200，但响应 JSON 中包含业务错误码。这类规则无法由 AI
平台统一推断，第一阶段将原始业务结果作为 Tool 结果返回，由 Tool 描述和 Agent
提示词帮助模型识别。后续如有明确需求，再增加工具级响应错误映射配置。

## 11. Token 生命周期和保密要求

业务 Token 只允许存在于以下链路：

```text
当前 HTTP 请求
→ 当前 Agent Runtime Context
→ 当前 MCP 调用内部传递
→ 当前目标业务 API 请求
```

明确禁止：

- 写入 Agent 请求 JSON。
- 写入会话消息表和运行记录表。
- 写入 LangGraph State 或 PostgreSQL Checkpoint。
- 写入 MCP Tool 配置表。
- 写入普通日志、异常堆栈、SSE 事件和监控标签。
- 返回给模型作为可见参数或 Tool 结果。

内部运行凭证请求头只能由 AI-backend 生成。FastMCP 的内部凭证传递入口不应直接
暴露给外部调用方，外部请求携带的同名内部请求头必须被忽略或拒绝。

## 12. 前端管理页面方案

MCP Tool 新建和编辑页面调整为：

```text
固定请求头 JSON
业务 Token 目标请求头（可选）
```

移除：

```text
认证类型
认证配置 JSON
Bearer Token
Basic Auth
API Key
运行时 Bearer
```

“业务 Token 目标请求头”提供以下提示：

```text
为空时不透传业务用户 Token；例如目标 API 接收 X-Token，就填写 X-Token。
Token 值来自调用 /agent/messages 时携带的 X-Business-Authorization，并原样转发。
```

工具调试页面在配置了 `business_token_header` 时显示：

```text
本次测试业务用户凭证（仅用于本次调用，不保存）
```

测试完成后前端清空该值，不将其写入 Tool 保存请求。

## 13. 多业务平台场景约束

第一阶段一次 `/agent/messages` 请求只携带一个 `X-Business-Authorization`，代表当前
业务平台中的当前登录用户。Agent 可以调用多个 MCP Tool，每个 Tool 可以配置不同
的目标请求头名称，但它们收到的是同一段凭证值。

如果未来一次 Agent 运行确实需要同时访问多个业务平台，并且每个平台使用不同
Token，再扩展为按 `platform_id` 保存的运行时凭证集合。第一阶段不提前实现该复杂度。

## 14. 计划改造范围

正式实施时需要调整以下部分：

1. 空数据库初始化 SQL：删除 `auth_type`、`auth_config`，增加 `business_token_header`。
2. FastMCP ORM 模型和 Repository：改为读写新字段。
3. MCP Tool 请求/响应 Schema：移除认证枚举和认证 JSON。
4. FastMCP 执行器：按新字段原样注入运行时业务凭证。
5. Tool 配置校验：增加 Header 名称合法性和冲突校验。
6. MCP Tool 管理前端：替换认证类型与认证配置控件。
7. Tool 测试接口：继续允许临时传入 `X-Business-Authorization`，但不保存。
8. 外部接入文档：删除 `runtime_bearer` 和固定 `Authorization` 描述。
9. 原有业务平台接入与会话隔离方案：更新为本文确定的新规则。
10. 自动化测试：覆盖无 Token、不同 Header、非法 Header、401、403 和敏感信息泄漏。

## 15. 验收标准

改造完成后必须满足：

- Tool 不配置 `business_token_header` 时，不向目标 API 发送业务 Token。
- 配置 `X-Token` 后，目标 API 能收到 `X-Token: <原始凭证>`。
- 配置 `Authorization` 后，目标 API 能收到原始的完整 Authorization 值。
- 平台不会自动增加 `Bearer ` 或其他前缀。
- 缺少凭证时不会实际请求目标 API。
- 目标 API 返回 `401`、`403` 时，Agent 获得明确且不泄漏 Token 的错误。
- Header 名称冲突和非法 Header 名称无法保存。
- Token 不出现在数据库、Checkpoint、日志、SSE 和模型上下文中。
- Tool 调试输入的 Token 不会保存到 Tool 配置。
- 新建、编辑、发布和 Agent 实际调用使用同一套请求头映射规则。

## 16. 最终结论

本方案将权限职责划分为：

```text
AI-backend：校验业务平台身份、Agent 绑定关系和会话隔离
FastMCP：按照 Tool 配置原样转发本次业务用户凭证
目标业务 API：校验用户身份并执行最终业务权限判断
```

AI 平台不理解 Token 类型，也不复制业务权限体系。MCP Tool 只配置一个可选的
`business_token_header`，以最小配置适配不同业务平台的用户鉴权请求头。
