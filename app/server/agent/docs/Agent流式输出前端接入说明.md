# Agent 流式输出前端接入说明

本文档说明前端如何接入 Agent 的统一消息入口。

当前正式对外只推荐使用：

```http
POST /agent/messages
```

前端不需要区分“启动新 Agent 运行”还是“恢复一次中断运行”。后端会根据 `conversation_id` 自动判断：

- 当前会话没有 `interrupted` 运行：创建新的 Agent 运行。
- 当前会话存在 `interrupted` 运行：把本次消息转换为恢复数据，继续原来的 Agent 运行。

底层的 `run` / `resume` 仍然是后端内部能力，但不作为前端主接入接口。

## 一、接口说明

### 请求地址

```http
POST /agent/messages
```

### 请求方式

流式接口使用 `POST + text/event-stream`。

由于请求体需要传入 JSON 参数，前端不建议使用原生 `EventSource`，而应使用 `fetch + ReadableStream` 读取 SSE。

### 普通文本消息请求示例

```json
{
  "agent_id": "orchestrator-agent",
  "conversation_id": "conv_001",
  "message": "帮我根据这段 JD 生成岗位画像...",
  "message_type": "text",
  "payload": {},
  "stream": true,
  "inputs": {},
  "file_ids": [],
  "optional_features": {
    "long_term_memory_enabled": false,
    "planning_enabled": false
  }
}
```

### 开启规划模式请求示例

```json
{
  "agent_id": "orchestrator-agent",
  "conversation_id": "conv_001",
  "message": "帮我规划一个 30 天 FastAPI 学习计划",
  "message_type": "text",
  "payload": {},
  "stream": true,
  "optional_features": {
    "long_term_memory_enabled": false,
    "planning_enabled": true
  }
}
```

### 表单提交 / 按钮确认请求示例

如果前端收到 `interrupt` 事件，例如任务计划确认卡片，用户点击“确认执行”后，仍然调用同一个接口：

```json
{
  "agent_id": "orchestrator-agent",
  "conversation_id": "conv_001",
  "message": "用户已确认任务计划",
  "message_type": "action_click",
  "payload": {
    "type": "plan_confirmation",
    "data": {
      "action": "approve"
    }
  },
  "stream": true
}
```

如果用户要求修改计划：

```json
{
  "agent_id": "orchestrator-agent",
  "conversation_id": "conv_001",
  "message": "用户要求修改任务计划",
  "message_type": "form_submit",
  "payload": {
    "type": "plan_confirmation",
    "data": {
      "action": "revise",
      "feedback": "把学习计划改得更适合零基础，每天控制在 1 小时内"
    }
  },
  "stream": true
}
```

如果用户取消计划：

```json
{
  "agent_id": "orchestrator-agent",
  "conversation_id": "conv_001",
  "message": "用户取消任务计划",
  "message_type": "action_click",
  "payload": {
    "type": "plan_confirmation",
    "data": {
      "action": "cancel"
    }
  },
  "stream": true
}
```

前端关键规则：只要是同一个会话，继续传同一个 `conversation_id`。后端会自动判断这次是新消息还是恢复中断。

## 二、请求字段说明

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `agent_id` | string | 否 | Agent 模板 ID。新任务时用于加载模板配置；中断恢复时以后端原运行记录为准。 |
| `conversation_id` | string | 建议必填 | 会话 ID。用于会话记忆、checkpoint 和中断恢复判断。 |
| `message` | string | 否 | 用户本次输入文本。普通聊天建议必填；表单提交可传摘要文本。 |
| `message_type` | string | 否 | 消息类型，默认 `text`。可用 `text`、`form_submit`、`action_click`、`file_submit` 等。 |
| `payload` | object | 否 | 结构化负载。中断恢复时建议使用 `{type, data}`。 |
| `stream` | boolean | 否 | 是否 SSE 流式返回，默认建议传 `true`。 |
| `inputs` | object | 否 | 业务变量。新任务时会进入 Agent runtime context。 |
| `file_ids` | array | 否 | 附件上下文预留字段。 |
| `tools` | array | 否 | 新任务运行时允许加载的 MCP 外接工具编码。内置工具不能放在这里，多数场景交给模板控制。 |
| `optional_features` | object | 否 | 可选能力，例如 `planning_enabled`。 |
| `a2a` | object | 否 | A2A 子 Agent 配置。多数场景交给模板控制。 |
| `runtime_options` | object | 否 | 模型运行参数。多数场景交给模板控制。 |

如果使用 `agent_id`，前端尽量不要传空的 `system_prompt`、`tools`、`runtime_options`，让后端按模板运行。

## 三、SSE 返回格式

后端每条 SSE 事件格式如下：

```text
event: model_delta
data: {"type":"model_delta","data":{"content":"你好"}}

```

前端应以空行 `\n\n` 拆分事件块，再解析其中的 `event:` 和 `data:`。

`data` 内部始终是 JSON，格式统一为：

```ts
interface AgentSseEvent<T = unknown> {
  type: string
  data: T
}
```

其中 `type` 与 SSE 的 `event:` 一致。

## 四、事件类型

### 1. run_start

表示本次 Agent 运行开始。

```json
{
  "type": "run_start",
  "data": {
    "run_id": "3bef498aafdb403fb2b3692562d06018",
    "thread_id": "conv_001",
    "persistent_conversation": true,
    "stream": true
  }
}
```

前端建议：

- 创建一条新的运行记录。
- 开启 loading 状态。
- 保存 `run_id`，后续可用于查询运行链路。

### 2. resume_start

表示本次消息命中了当前会话的中断恢复，后端开始恢复原运行。

```json
{
  "type": "resume_start",
  "data": {
    "run_id": "3bef498aafdb403fb2b3692562d06018",
    "thread_id": "conv_001",
    "stream": true
  }
}
```

前端建议：

- 复用原来的 Agent 消息时间线继续追加事件。
- 不需要新建一条独立 assistant 消息，除非产品设计要求单独展示用户确认动作。

### 3. agent_assembled

表示 Agent 已完成组装，模型、工具、中间件等已经就绪。

```json
{
  "type": "agent_assembled",
  "data": {
    "run_id": "xxx",
    "model_code": "chat_main",
    "tool_count": 2,
    "tools": ["job.search_job_skills", "job.create_job_skills"],
    "middlewares": ["ToolLoggingMiddleware"],
    "checkpointer_enabled": true
  }
}
```

前端建议：

- 可在调试面板展示。
- 普通聊天界面可以忽略。

### 4. reasoning_delta

模型思考过程增量输出。

```json
{
  "type": "reasoning_delta",
  "data": {
    "content": "我需要先识别岗位职责和技能关键词..."
  }
}
```

前端建议：

- 追加到“思考过程”区域。
- 可以默认折叠，也可以用灰色文本展示。
- 不要把它合并到最终回答正文里。

### 5. model_delta

Agent 正式回复正文增量输出。

```json
{
  "type": "model_delta",
  "data": {
    "content": "岗位画像已生成..."
  }
}
```

前端建议：

- 追加到当前 assistant 消息正文。
- 这是用户最终可见回答的主要来源。
- 流式模式下后端不额外发送 `final` 事件，最终正文由前端累计 `model_delta` 得到。

### 6. context_summary_started / context_summary_completed

Agent 在模型调用前发现会话上下文过长时，会先压缩早期工作记忆。这两个事件只表示内部总结状态，不包含摘要正文。

```json
{
  "type": "context_summary_started",
  "data": {
    "run_id": "run_xxx"
  }
}
```

```json
{
  "type": "context_summary_completed",
  "data": {
    "run_id": "run_xxx"
  }
}
```

总结失败时会收到：

```json
{
  "type": "context_summary_failed",
  "data": {
    "run_id": "run_xxx",
    "message": "上下文总结失败，本轮将继续使用原始上下文。"
  }
}
```

前端建议：

- `context_summary_started`：展示轻量状态“正在总结会话上下文”。
- `context_summary_completed`：更新为“会话上下文总结完成”，随后继续展示 Agent 正常输出。
- `context_summary_failed`：展示轻量提示，但不能终止当前 Agent 的 loading；主 Agent 会继续执行。
- 不展示摘要正文、Token 或思考过程。

### 7. tool_call

模型准备调用工具。

```json
{
  "type": "tool_call",
  "data": {
    "tool_name": "search_job_skills",
    "args": {
      "keywords": ["Python", "FastAPI"]
    },
    "id": "call_xxx",
    "metadata": {
      "langgraph_node": "model",
      "langgraph_step": 2
    }
  }
}
```

前端建议：

- 可展示为“正在调用工具：search_job_skills”。
- 普通聊天正文不要展示工具参数。
- 调试面板可以展示 `args` 和 `metadata`。

### 8. tool_result

工具执行完成后的返回结果。

```json
{
  "type": "tool_result",
  "data": {
    "tool_name": "search_job_skills",
    "tool_call_id": "call_xxx",
    "output": {},
    "metadata": {
      "langgraph_node": "tools",
      "langgraph_step": 3
    }
  }
}
```

前端建议：

- 不要把 `tool_result.output` 拼进 assistant 正文。
- 可以展示在工具调用记录面板中。
- 如果是普通用户聊天界面，可以只展示“工具调用完成”。

### 9. task_plan

任务计划发生变化。规划模式开启后，Agent 调用 `set_task_plan` 或 `update_task_step` 时会推送该事件。

```json
{
  "type": "task_plan",
  "data": {
    "run_id": "run_xxx",
    "thread_id": "conv_001",
    "task_plan": {
      "title": "FastAPI 30 天学习计划",
      "status": "draft",
      "steps": [
        {
          "step_id": "step_1",
          "title": "学习 Python Web 基础",
          "description": "理解 HTTP、路由、请求响应模型",
          "status": "waiting"
        }
      ]
    }
  }
}
```

前端建议：

- 使用 `data.task_plan` 整体替换当前任务计划面板。
- 不要尝试根据工具调用参数自行拼任务列表。
- `status=draft` 时等待用户确认。
- `status=running` 时展示执行进度。
- `status=completed` 时展示完成态。
- `status=cancelled` 时展示取消态。

### 10. interrupt

Agent 主动暂停，等待用户操作。

```json
{
  "type": "interrupt",
  "data": {
    "run_id": "run_xxx",
    "thread_id": "conv_001",
    "payload": {
      "type": "plan_confirmation",
      "data": {
        "task_plan": {}
      }
    }
  }
}
```

前端建议：

- 不要把它当成错误。
- 根据 `payload.type` 渲染不同交互卡片。
- `plan_confirmation` 渲染任务计划确认卡片。
- 用户操作后继续调用 `POST /agent/messages`，不要调用底层恢复接口。

### 11. run_end

表示本次流式运行结束。

成功结束：

```json
{
  "type": "run_end",
  "data": {
    "run_id": "xxx",
    "thread_id": "conv_001",
    "status": "success",
    "elapsed_ms": 12345.67,
    "answer_length": 320
  }
}
```

中断结束：

```json
{
  "type": "run_end",
  "data": {
    "run_id": "xxx",
    "thread_id": "conv_001",
    "status": "interrupted",
    "interrupt_type": "plan_confirmation",
    "elapsed_ms": 12345.67,
    "answer_length": 0
  }
}
```

前端建议：

- `status=success`：关闭 loading，标记 assistant 消息完成。
- `status=interrupted`：关闭普通 loading，但保留“等待用户操作”的 UI 状态。
- `answer_length` 可用于判断本次是否产生了正文。

### 12. error

运行失败。

```json
{
  "type": "error",
  "data": {
    "run_id": "xxx",
    "message": "模型服务出错：...",
    "error_type": "BadRequestError"
  }
}
```

前端建议：

- 关闭 loading。
- 展示错误提示。
- 可保留已收到的 `model_delta` 内容。

## 五、前端 TypeScript 类型建议

```ts
export type AgentStreamEventType =
  | 'run_start'
  | 'resume_start'
  | 'agent_assembled'
  | 'reasoning_delta'
  | 'model_delta'
  | 'context_summary_started'
  | 'context_summary_completed'
  | 'context_summary_failed'
  | 'tool_call'
  | 'tool_result'
  | 'task_plan'
  | 'interrupt'
  | 'run_end'
  | 'error'

export interface AgentStreamEvent<T = unknown> {
  type: AgentStreamEventType | string
  data: T
}

export interface AgentMessageRequest {
  agent_id?: string
  conversation_id?: string
  message?: string
  message_type?: string
  payload?: Record<string, unknown>
  stream?: boolean
  inputs?: Record<string, unknown>
  file_ids?: string[]
  tools?: string[]
  optional_features?: {
    long_term_memory_enabled?: boolean
    planning_enabled?: boolean
  }
  a2a?: {
    sub_agent_list?: string[]
  }
  runtime_options?: Record<string, unknown>
}

export interface RunStartData {
  run_id: string
  thread_id: string
  persistent_conversation: boolean
  stream: boolean
}

export interface ReasoningDeltaData {
  content: string
}

export interface ModelDeltaData {
  content: string
}

export interface ToolCallData {
  tool_name: string
  args: Record<string, unknown>
  id?: string | null
  metadata?: Record<string, unknown>
}

export interface ToolResultData {
  tool_name: string
  tool_call_id?: string | null
  output: unknown
  metadata?: Record<string, unknown>
}

export interface TaskPlanData {
  run_id: string
  thread_id: string
  task_plan: Record<string, unknown>
}

export interface InterruptData {
  run_id: string
  thread_id: string
  payload: {
    type: string
    data: Record<string, unknown>
  }
}

export interface RunEndData {
  run_id: string
  thread_id: string
  status?: 'success' | 'interrupted' | 'failed' | string
  interrupt_type?: string
  elapsed_ms: number
  answer_length: number
}

export interface ErrorData {
  run_id?: string
  message: string
  error_type?: string
}
```

## 六、前端解析示例

```ts
function parseSseBlock(block: string) {
  let eventType = 'message'
  const dataLines: string[] = []

  for (const rawLine of block.split('\n')) {
    const line = rawLine.replace(/\r$/, '')
    if (line.startsWith('event:')) {
      eventType = line.slice(6).trim() || 'message'
    }
    if (line.startsWith('data:')) {
      dataLines.push(line.slice(5).trim())
    }
  }

  const data = dataLines.join('\n')
  if (!data) return null

  const parsed = JSON.parse(data)
  return {
    ...parsed,
    type: parsed.type || eventType,
  }
}

export async function sendAgentMessageStream(
  payload: AgentMessageRequest,
  onEvent: (event: AgentStreamEvent) => void,
) {
  const response = await fetch('/api/agent/messages', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({
      ...payload,
      stream: true,
    }),
  })

  if (!response.ok || !response.body) {
    throw new Error(`Agent stream failed: ${response.status}`)
  }

  const reader = response.body.getReader()
  const decoder = new TextDecoder('utf-8')
  let buffer = ''

  while (true) {
    const { value, done } = await reader.read()
    if (done) break

    buffer += decoder.decode(value, { stream: true })
    const normalized = buffer.replace(/\r\n/g, '\n')
    const blocks = normalized.split('\n\n')
    buffer = blocks.pop() || ''

    for (const block of blocks) {
      const event = parseSseBlock(block)
      if (event) onEvent(event)
    }
  }

  const tail = buffer.trim()
  if (tail) {
    const event = parseSseBlock(tail)
    if (event) onEvent(event)
  }
}
```

## 七、推荐渲染逻辑

```ts
let answer = ''
let reasoning = ''
let currentTaskPlan: Record<string, unknown> | null = null
let pendingInterrupt: InterruptData | null = null
const toolLogs: Array<AgentStreamEvent> = []

function handleAgentEvent(event: AgentStreamEvent) {
  switch (event.type) {
    case 'run_start':
    case 'resume_start':
      // 初始化或恢复运行状态。
      break

    case 'reasoning_delta':
      reasoning += (event.data as ReasoningDeltaData).content
      break

    case 'model_delta':
      answer += (event.data as ModelDeltaData).content
      break

    case 'tool_call':
    case 'tool_result':
      toolLogs.push(event)
      break

    case 'task_plan':
      currentTaskPlan = (event.data as TaskPlanData).task_plan
      break

    case 'interrupt':
      pendingInterrupt = event.data as InterruptData
      break

    case 'run_end': {
      const data = event.data as RunEndData
      if (data.status === 'interrupted') {
        // 等待用户在 interrupt 卡片上操作。
      } else {
        // 标记完成，answer 就是最终回复。
      }
      break
    }

    case 'error':
      // 展示错误提示。
      break
  }
}
```

## 八、中断确认提交示例

前端收到 `interrupt.payload.type = plan_confirmation` 后，可以渲染三个操作：确认、修改、取消。

确认：

```ts
await sendAgentMessageStream(
  {
    agent_id: 'orchestrator-agent',
    conversation_id: 'conv_001',
    message: '用户已确认任务计划',
    message_type: 'action_click',
    payload: {
      type: 'plan_confirmation',
      data: {
        action: 'approve',
      },
    },
  },
  handleAgentEvent,
)
```

修改：

```ts
await sendAgentMessageStream(
  {
    agent_id: 'orchestrator-agent',
    conversation_id: 'conv_001',
    message: '用户要求修改任务计划',
    message_type: 'form_submit',
    payload: {
      type: 'plan_confirmation',
      data: {
        action: 'revise',
        feedback: '请把计划改得更适合零基础，并减少每天学习时长',
      },
    },
  },
  handleAgentEvent,
)
```

取消：

```ts
await sendAgentMessageStream(
  {
    agent_id: 'orchestrator-agent',
    conversation_id: 'conv_001',
    message: '用户取消任务计划',
    message_type: 'action_click',
    payload: {
      type: 'plan_confirmation',
      data: {
        action: 'cancel',
      },
    },
  },
  handleAgentEvent,
)
```

## 九、注意事项

1. 前端主入口只接 `POST /agent/messages`。
2. `model_delta` 才是 assistant 正文，前端最终回答只累计该事件。
3. `reasoning_delta` 是思考过程，不要拼进最终回答。
4. `tool_result` 是工具返回结果，不要拼进最终回答。
5. `tool_call` 和 `tool_result` 可以放入“执行过程”或“调试面板”。
6. `task_plan` 事件用于整体替换任务计划面板。
7. `interrupt` 事件用于渲染用户交互卡片。
8. 用户处理中断后，仍然调用 `POST /agent/messages`，不要调用底层恢复接口。
9. 流式模式不返回统一 `Result` 包装，也不返回 `final` 事件。
10. 流式结束以 `run_end` 为准。
11. 如果后端返回 `error`，前端仍可以保留已经收到的正文和思考内容。
12. 如果使用 `agent_id`，前端尽量不要传空的 `system_prompt`、`tools`、`runtime_options`，让后端按模板运行。

## 十、页面展示建议

普通用户聊天页建议展示：

- assistant 正文：只展示 `model_delta` 累计结果。
- 思考过程：展示 `reasoning_delta`，默认可折叠。
- 执行过程：展示工具名称和状态，默认可折叠。
- 任务计划：监听 `task_plan`，以独立任务面板展示。
- 中断确认：监听 `interrupt`，根据 `payload.type` 渲染交互卡片。

Agent 调试页建议展示：

- 所有事件列表。
- `tool_call.args`。
- `tool_result.output`。
- `task_plan` state 快照。
- `interrupt.payload`。
- `agent_assembled` 中的模型、工具、中间件信息。
- `run_end.elapsed_ms` 和 `answer_length`。
