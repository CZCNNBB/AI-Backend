# 外部业务平台接入 AI-backend 说明

## 1. 文档目标

本文面向需要把 AI Agent 接入现有 Java、Go、Python 或其他业务系统的开发人员，说明：

- 业务平台如何取得 AI-backend 的调用凭证。
- 如何调用 Agent 并建立多轮会话。
- 如何隔离不同平台和不同业务用户的数据。
- 如何把业务用户 Token 透传给 MCP Tool 调用的目标业务 API。
- 如何查询会话、历史消息和运行记录。

当前方案定位为公司内网 MVP。业务操作权限仍由目标业务 API 校验，AI-backend 不重复维护业务用户的角色和权限。

## 2. 整体调用关系

```text
业务系统前端
  → 业务系统后端
      → 携带 X-API-Key、external_user_id、业务用户 Token
      → AI-backend /agent/messages
          → Agent 组装已配置的内部工具与 MCP Tool
          → MCP Tool 携带业务用户 Token 调用目标业务 API
          → 目标业务 API 执行最终权限校验
```

正式接入时，浏览器或移动端不应直接持有平台 API Key。推荐始终由业务系统后端调用 AI-backend。

## 3. 接入前的管理端配置

### 3.1 创建业务平台

在 AI 管理平台的“业务平台”页面创建一条平台记录，例如：

```json
{
  "platform_code": "order_system",
  "platform_name": "订单业务系统",
  "description": "订单域 Agent 接入",
  "status": "enabled"
}
```

`platform_code` 是稳定编码，创建后不建议修改。

### 3.2 签发 API Key

在业务平台列表中点击“签发 API Key”，可以按环境或用途签发多个 Key，例如：

- `development`
- `test`
- `production`

管理页面的“查看 API Key”可以查看、复制或停用已经签发的 Key。

当前内网模式会同时保存完整明文和 SHA-256 Hash：

- 完整明文只用于公司内网管理和联调。
- 实际请求认证使用 Hash 比对。
- API Key 不应写入应用日志、Git、公开配置或业务前端代码。

### 3.3 绑定 Agent 与 MCP Tool

创建或编辑 Agent 时，需要把 Agent 绑定到允许使用它的业务平台。

配置 Agent 的 MCP Tool 时，管理端只展示能够覆盖该 Agent 业务平台范围的工具。完成配置后，运行时不再重复做复杂的工具归属计算。

## 4. 服务地址

直接访问本地后端时：

```text
http://127.0.0.1:8090
```

Agent 消息接口完整地址：

```text
http://127.0.0.1:8090/agent/messages
```

本地 Vite 管理端使用 `/api` 代理时，浏览器请求地址可能表现为：

```text
http://127.0.0.1:5173/api/agent/messages
```

Vite 会把 `/api` 去掉后转发到后端。外部业务系统直接访问 8090 时不要额外增加 `/api`，除非部署网关明确配置了该前缀。

## 5. 身份与隔离字段

### 5.1 X-API-Key

`X-API-Key` 用于识别当前调用来自哪个业务平台。

```http
X-API-Key: aik_xxxxxxxxxxxxxxxxx
```

AI-backend 会根据 API Key 得到可信的 `platform_id`。业务方不能在 JSON 请求体中自行指定 `platform_id`。

### 5.2 external_user_id

`external_user_id` 是用户在业务系统中的稳定标识，例如用户主键、员工编号或不可变账号 ID：

```json
{
  "external_user_id": "user_10086"
}
```

不要使用昵称、手机号等可能变化或可能重复的字段。

当前数据隔离边界为：

```text
platform_id + external_user_id + conversation_id
```

因此：

- 两个不同业务平台可以使用相同的 `external_user_id`，数据仍然互相隔离。
- 同一平台的两个不同用户不能读取彼此的会话和运行记录。
- 查询会话、消息和运行记录时必须继续传入同一个 `external_user_id`。

### 5.3 X-Business-Authorization

如果 Agent 需要调用当前业务用户才有权访问的 API，业务后端把用户 Token 放在以下请求头：

```http
X-Business-Authorization: Bearer eyJhbGciOi...
```

该值的处理规则是：

- AI-backend 不使用它认证调用方平台。
- AI-backend 不解析其中的用户角色和业务权限。
- 它只保存在本次运行的内存上下文中。
- 配置为 `runtime_bearer` 的 MCP Tool 会把它作为目标业务 API 的 `Authorization` 请求头。
- 目标业务 API 返回无权限时，Agent 会收到该工具调用失败结果。

业务 Token 不应持久化到 Agent 会话、Checkpoint、运行记录或日志。

## 6. 调用 Agent

### 6.1 请求头

```http
Content-Type: application/json
X-API-Key: aik_xxxxxxxxxxxxxxxxx
X-Business-Authorization: Bearer eyJhbGciOi...
```

如果本次 Agent 不需要调用用户鉴权 API，可以不传 `X-Business-Authorization`。

### 6.2 最小非流式请求

```bash
curl --request POST "http://127.0.0.1:8090/agent/messages" \
  --header "Content-Type: application/json" \
  --header "X-API-Key: aik_xxxxxxxxxxxxxxxxx" \
  --data-raw '{
    "agent_id": "order-agent",
    "external_user_id": "user_10086",
    "conversation_id": null,
    "message": "你好，请介绍一下你能做什么",
    "message_type": "text",
    "stream": false
  }'
```

成功响应：

```json
{
  "code": 0,
  "msg": "success",
  "data": {
    "run_id": "4a9f...",
    "conversation_id": "conv_8d5f...",
    "answer": "你好，我可以……",
    "tool_results": []
  }
}
```

业务系统需要保存或回传 `conversation_id`，用于下一轮对话。

### 6.3 完整请求示例

```json
{
  "agent_id": "order-agent",
  "external_user_id": "user_10086",
  "conversation_id": null,
  "message": "查询我最近三笔订单",
  "message_type": "text",
  "stream": true,
  "payload": {},
  "inputs": {
    "tenant_code": "tenant_001"
  },
  "file_ids": [],
  "tools": [],
  "optional_features": {
    "long_term_memory_enabled": false,
    "planning_enabled": false,
    "knowledge_enabled": false
  },
  "knowledge": null,
  "a2a": null,
  "runtime_options": {
    "model_code": "chat_main",
    "temperature": 0.2,
    "timeout_seconds": 600,
    "max_retries": 2
  }
}
```

主要字段说明：

| 字段 | 必填 | 说明 |
| --- | --- | --- |
| `agent_id` | 是 | 管理端配置的 Agent ID，且必须已绑定当前业务平台 |
| `external_user_id` | 是 | 当前业务平台中的稳定用户 ID |
| `conversation_id` | 否 | 首次请求传 `null`；继续对话时传上一轮返回值 |
| `message` | 条件必填 | 用户文本；与 `payload` 不能同时为空 |
| `message_type` | 否 | 默认 `text`，也可以是 `form_submit`、`action_click` 等 |
| `payload` | 否 | 表单或按钮等结构化数据 |
| `stream` | 否 | 默认 `true`；`true` 返回 SSE |
| `inputs` | 否 | 注入 Runtime 参数，可被 MCP Tool 的 runtime 参数映射读取 |
| `file_ids` | 否 | `/file/upload` 返回的文件 ID 列表 |
| `runtime_options` | 否 | 本次模型运行参数 |

### 6.4 流式 SSE 调用

```bash
curl --no-buffer --request POST "http://127.0.0.1:8090/agent/messages" \
  --header "Content-Type: application/json" \
  --header "Accept: text/event-stream" \
  --header "X-API-Key: aik_xxxxxxxxxxxxxxxxx" \
  --header "X-Business-Authorization: Bearer eyJhbGciOi..." \
  --data-raw '{
    "agent_id": "order-agent",
    "external_user_id": "user_10086",
    "conversation_id": null,
    "message": "查询我最近三笔订单",
    "stream": true
  }'
```

流式事件格式：

```text
event: run_start
data: {"type":"run_start","data":{"run_id":"...","conversation_id":"conv_...","thread_id":"conv_...","stream":true}}

event: model_delta
data: {"type":"model_delta","data":{"content":"正在"}}

event: model_delta
data: {"type":"model_delta","data":{"content":"查询订单"}}

event: run_end
data: {"type":"run_end","data":{"run_id":"...","status":"success","elapsed_ms":1234}}
```

常见事件：

| 事件 | 说明 |
| --- | --- |
| `run_start` | 新运行开始，包含 `run_id` 和 `conversation_id` |
| `resume_start` | 恢复中断运行，继续沿用原 `run_id` 和 `conversation_id` |
| `agent_assembled` | Agent 已完成组装 |
| `reasoning_delta` | 模型思考内容增量，前端可选择是否展示 |
| `model_delta` | 回答正文增量 |
| `tool_call` | 工具调用事件 |
| `interrupt` | LangGraph 中断事件 |
| `run_end` | 运行结束，`status` 可能为 `success` 或 `interrupted` |
| `error` | 执行失败，包含错误消息 |

业务方至少需要处理 `run_start`、`resume_start`、`model_delta`、`run_end` 和 `error`。

## 7. 多轮会话

### 7.1 首次对话

首次请求可以传：

```json
{
  "conversation_id": null
}
```

AI-backend 自动生成 `conv_...`。非流式响应通过 `data.conversation_id` 返回；流式响应通过 `run_start.data.conversation_id` 返回。

### 7.2 继续对话

下一轮请求继续使用相同的：

- `X-API-Key`
- `external_user_id`
- `conversation_id`

```json
{
  "agent_id": "order-agent",
  "external_user_id": "user_10086",
  "conversation_id": "conv_8d5f...",
  "message": "再帮我看看第一笔订单的物流",
  "stream": true
}
```

LangGraph Checkpointer 会根据平台、用户和会话组成的内部命名空间恢复上下文：

```text
platform:{platform_id}:user:{external_user_id}:conversation:{conversation_id}
```

同一个会话不建议同时发起多次 Agent 运行，以免两个运行同时写入同一 Checkpoint。业务后端或前端应在本轮结束前禁用重复发送，或对同一会话串行排队。

## 8. 查询会话与运行记录

以下接口都需要请求头 `X-API-Key`，并且请求体必须携带 `external_user_id`。

### 8.1 查询用户会话

```http
POST /agent/conversations/search
```

```json
{
  "external_user_id": "user_10086",
  "page": 1,
  "page_size": 20
}
```

业务方不必自己保存完整的用户与会话关系，也可以按 `external_user_id` 从 AI-backend 查询该用户的会话列表。

### 8.2 查询会话消息

```http
POST /agent/conversations/messages
```

```json
{
  "external_user_id": "user_10086",
  "conversation_id": "conv_8d5f...",
  "limit": 100
}
```

### 8.3 查询运行记录

```http
POST /agent/runs/search
```

```json
{
  "external_user_id": "user_10086",
  "agent_id": "order-agent",
  "page": 1,
  "page_size": 20
}
```

运行详情与 A2A 主子链路接口：

```text
POST /agent/runs/detail
POST /agent/runs/chain
```

两个接口都需要同时传 `run_id` 和 `external_user_id`。

## 9. Java、Go 与 Python 示例

### 9.1 Java 11 HttpClient

```java
import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;

public class AiBackendClient {
    /** 调用 AI-backend 的非流式 Agent 消息接口。 */
    public static String sendMessage(String apiKey, String businessToken) throws Exception {
        String requestBody = """
            {
              "agent_id": "order-agent",
              "external_user_id": "user_10086",
              "conversation_id": null,
              "message": "查询最近订单",
              "stream": false
            }
            """;

        HttpRequest.Builder requestBuilder = HttpRequest.newBuilder()
            .uri(URI.create("http://127.0.0.1:8090/agent/messages"))
            .header("Content-Type", "application/json")
            .header("X-API-Key", apiKey)
            .POST(HttpRequest.BodyPublishers.ofString(requestBody));

        // 业务用户 Token 是可选项，只有需要调用用户鉴权 API 时才透传。
        if (businessToken != null && !businessToken.isBlank()) {
            requestBuilder.header("X-Business-Authorization", businessToken);
        }

        HttpClient client = HttpClient.newHttpClient();
        HttpResponse<String> response = client.send(
            requestBuilder.build(),
            HttpResponse.BodyHandlers.ofString()
        );
        return response.body();
    }
}
```

### 9.2 Go net/http

```go
package aibackend

import (
	"bytes"
	"io"
	"net/http"
)

// SendMessage 调用 AI-backend 的非流式 Agent 消息接口。
func SendMessage(apiKey string, businessToken string) ([]byte, error) {
	body := []byte(`{
        "agent_id":"order-agent",
        "external_user_id":"user_10086",
        "conversation_id":null,
        "message":"查询最近订单",
        "stream":false
    }`)

	request, err := http.NewRequest(
		http.MethodPost,
		"http://127.0.0.1:8090/agent/messages",
		bytes.NewReader(body),
	)
	if err != nil {
		return nil, err
	}
	request.Header.Set("Content-Type", "application/json")
	request.Header.Set("X-API-Key", apiKey)
	if businessToken != "" {
		request.Header.Set("X-Business-Authorization", businessToken)
	}

	response, err := http.DefaultClient.Do(request)
	if err != nil {
		return nil, err
	}
	defer response.Body.Close()
	return io.ReadAll(response.Body)
}
```

### 9.3 Python httpx

```python
import httpx


def send_message(api_key: str, business_token: str | None = None) -> dict:
    """调用 AI-backend 的非流式 Agent 消息接口。"""
    headers = {
        "Content-Type": "application/json",
        "X-API-Key": api_key,
    }
    if business_token:
        # 业务 Token 保持原格式透传，例如 Bearer eyJ...。
        headers["X-Business-Authorization"] = business_token

    payload = {
        "agent_id": "order-agent",
        "external_user_id": "user_10086",
        "conversation_id": None,
        "message": "查询最近订单",
        "stream": False,
    }
    response = httpx.post(
        "http://127.0.0.1:8090/agent/messages",
        headers=headers,
        json=payload,
        timeout=600,
    )
    response.raise_for_status()
    return response.json()
```

## 10. 错误处理建议

业务调用方应同时处理：

1. HTTP 网络错误，例如连接失败、超时、网关 502。
2. HTTP 认证错误，例如缺少或使用了无效的 `X-API-Key`。
3. 统一响应中的非零 `code`。
4. SSE 中的 `error` 事件。
5. MCP Tool 返回的目标业务 API 无权限、参数错误或服务异常。

不要把完整 API Key、业务用户 Token、固定认证头或 MCP `auth_config` 写入错误日志。日志中只记录平台编码、Key 前缀、`external_user_id`、`conversation_id` 和 `run_id` 即可。

## 11. 联调检查清单

- [ ] 业务平台已创建且状态为 `enabled`。
- [ ] 已签发状态为 `enabled` 的 API Key。
- [ ] Agent 已绑定该业务平台。
- [ ] Agent 配置中已选择需要的 MCP Tool。
- [ ] 业务后端能够安全读取 API Key，业务前端无法看到它。
- [ ] 每个请求都提供稳定的 `external_user_id`。
- [ ] 需要业务权限的场景已经传入 `X-Business-Authorization`。
- [ ] 首次调用可以取得并保存 `conversation_id`。
- [ ] 后续调用复用相同的 `conversation_id`。
- [ ] SSE 客户端能够处理 `run_end` 和 `error`。
- [ ] 同一会话不会被无控制地并发调用。

## 12. 当前阶段边界

当前版本暂不实现：

- 业务平台级的复杂角色和工具权限策略。
- OAuth2、JWT 换票或动态 Token 刷新。
- API Key 只显示一次和加密托管。
- 按平台配置独立限流、配额和计费。

后续可以逐步增强这些能力，但不改变当前核心协议：

```text
X-API-Key 识别业务平台
+ external_user_id 隔离业务用户
+ conversation_id 标识多轮会话
+ X-Business-Authorization 透传业务权限
```
