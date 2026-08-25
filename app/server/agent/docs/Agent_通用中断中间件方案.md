# Agent 通用中断中间件方案

## 1. 背景

Agent 在执行复杂任务时，经常需要暂停等待用户参与，例如：

1. 任务计划确认。
2. 用户补充信息。
3. 工具调用审批。
4. 内容草稿审阅。
5. 多方案选择。

这些场景的业务含义不同，但底层中断机制是一致的：

```text
某个工具或业务中间件决定需要中断
  ↓
写入中断状态
  ↓
通用中断中间件触发 interrupt
  ↓
前端展示交互卡片
  ↓
用户继续调用 /agent/messages 返回内容
  ↓
通用中断中间件把用户返回写回 state
  ↓
对应业务中间件根据 type 处理 data
```

因此我们需要一个通用的 `InterruptMiddleware`，但它不能承载具体业务逻辑。

## 2. 核心原则

### 2.1 通用中断中间件不理解业务

`InterruptMiddleware` 不关心：

1. 什么是任务计划。
2. 什么是审批。
3. 什么是补充信息。
4. 用户点了确认、取消还是修改。

它只关心两个字段：

```json
{
  "interrupt_enabled": true,
  "interrupt_payload": {}
}
```

### 2.2 type 用于路由，data 用于业务

中断请求和恢复结果都统一使用：

```json
{
  "type": "xxx",
  "data": {}
}
```

其中：

| 字段 | 说明 |
|------|------|
| `type` | 中断类型，用于前端选择渲染方式，也用于后端业务中间件认领处理 |
| `data` | 业务自定义数据，具体结构由对应业务中间件约定 |

外层协议保持稳定，业务自由度全部放在 `data` 中。

## 3. State 字段设计

通用中断能力只需要三个 state 字段：

```json
{
  "interrupt_enabled": false,
  "interrupt_payload": null,
  "resume_value": null
}
```

字段说明：

| 字段 | 类型 | 说明 |
|------|------|------|
| `interrupt_enabled` | bool | 是否触发中断 |
| `interrupt_payload` | dict/null | 中断时返回给前端的数据，固定为 `{type, data}` |
| `resume_value` | dict/null | 用户恢复运行时传回的数据，固定为 `{type, data}` |

## 4. interrupt_payload 协议

触发中断时写入：

```json
{
  "interrupt_enabled": true,
  "interrupt_payload": {
    "type": "plan_confirmation",
    "data": {
      "title": "请确认任务计划",
      "task_plan": {}
    }
  }
}
```

`interrupt_payload` 外层只固定：

```json
{
  "type": "中断类型",
  "data": {}
}
```

`data` 内部可以按业务自由设计。

例如任务计划确认：

```json
{
  "type": "plan_confirmation",
  "data": {
    "title": "请确认任务计划",
    "message": "我将按下面步骤执行，确认后继续。",
    "task_plan": {
      "status": "draft",
      "steps": []
    }
  }
}
```

例如补充信息：

```json
{
  "type": "need_user_input",
  "data": {
    "title": "需要补充信息",
    "question": "你的 Python 基础是什么水平？"
  }
}
```

例如工具审批：

```json
{
  "type": "tool_approval",
  "data": {
    "title": "请确认工具操作",
    "tool_name": "create_job_skills",
    "args": {}
  }
}
```

## 5. resume_value 协议

用户通过 `/agent/messages` 返回结构化 payload，后端内部转换为 `resume_value`：

```json
{
  "resume_value": {
    "type": "plan_confirmation",
    "data": {
      "action": "approve",
      "feedback": "确认，继续执行"
    }
  }
}
```

`resume_value` 外层同样只固定：

```json
{
  "type": "中断类型",
  "data": {}
}
```

`data` 内部由业务中间件自己解释。

例如任务计划确认返回：

```json
{
  "type": "plan_confirmation",
  "data": {
    "action": "approve",
    "feedback": "确认，继续执行",
    "task_plan": {}
  }
}
```

例如要求修改任务计划：

```json
{
  "type": "plan_confirmation",
  "data": {
    "action": "revise",
    "feedback": "第二步需要增加学习路径建议"
  }
}
```

例如取消任务计划：

```json
{
  "type": "plan_confirmation",
  "data": {
    "action": "cancel",
    "feedback": "先不执行了"
  }
}
```

## 6. 中间件职责

### 6.1 InterruptMiddleware

通用中断中间件只做这些事：

1. 检查 `interrupt_enabled`。
2. 读取 `interrupt_payload`。
3. 调用 LangGraph `interrupt(interrupt_payload)`。
4. 等待 `/agent/messages` 命中中断运行后传回用户内容。
5. 把用户内容写入 `resume_value`。
6. 清理 `interrupt_enabled` 和 `interrupt_payload`。

它不处理任何业务动作。

伪代码：

```python
if state.get("interrupt_enabled"):
    payload = state.get("interrupt_payload") or {}
    raw_resume_value = interrupt(payload)

    return {
        "interrupt_enabled": False,
        "interrupt_payload": None,
        "resume_value": normalize_resume_value(payload, raw_resume_value),
    }
```

`normalize_resume_value` 只保证外层格式统一：

```python
def normalize_resume_value(payload, raw_resume_value):
    return {
        "type": payload.get("type") or raw_resume_value.get("type"),
        "data": raw_resume_value.get("data") or {},
    }
```

注意：`InterruptMiddleware` 不关心 `data.action` 是什么。

### 6.2 PlanningMiddleware

任务计划中间件只处理：

```json
{
  "resume_value": {
    "type": "plan_confirmation",
    "data": {}
  }
}
```

如果 `resume_value.type != plan_confirmation`，它直接跳过。

处理规则：

| data.action | 行为 |
|-------------|------|
| `approve` | 把 `task_plan.status` 从 `draft` 改成 `running` |
| `revise` | 保持 `task_plan.status = draft`，把 `feedback` 注入给 Agent，让 Agent 调用 `set_task_plan` 重写计划 |
| `cancel` | 把 `task_plan.status` 改成 `cancelled` |

处理完成后，清理 `resume_value`，避免后续重复处理。

### 6.3 其他业务中间件

未来可以继续增加：

| 中间件 | 处理 type |
|--------|-----------|
| `ToolApprovalMiddleware` | `tool_approval` |
| `HumanInputMiddleware` | `need_user_input` |
| `DraftReviewMiddleware` | `draft_review` |

每个业务中间件只处理自己认领的 `type`。

## 7. 工具如何触发中断

工具不直接调用 `interrupt()`。

工具只负责写 state。会触发中断的工具返回 `Command(update=...)` 即可，不建议再设置 `goto="model"`：

```python
return Command(
    update={
        "interrupt_enabled": True,
        "interrupt_payload": {
            "type": "plan_confirmation",
            "data": {
                "title": "请确认任务计划",
                "task_plan": task_plan
            }
        }
    }
)
```

`InterruptMiddleware.before_model` 会在下一次模型调用前检查 `interrupt_enabled` 并触发中断。

不使用 `goto="model"` 的原因是：强制跳回模型节点会额外制造模型轮次，容易让任务步骤更新、A2A 调用等链路出现意外的交错执行。工具不需要关心 LangGraph 的中断恢复细节，也不应该主动控制图跳转。

## 8. 前端 SSE 事件格式

后端向前端返回：

```json
{
  "type": "interrupt",
  "data": {
    "run_id": "run_xxx",
    "thread_id": "thread_xxx",
    "payload": {
      "type": "plan_confirmation",
      "data": {
        "title": "请确认任务计划",
        "task_plan": {}
      }
    }
  }
}
```

前端根据：

```text
payload.type
```

选择渲染方式。

例如：

| payload.type | 前端渲染 |
|--------------|----------|
| `plan_confirmation` | 任务计划确认卡片 |
| `need_user_input` | 用户补充信息输入框 |
| `tool_approval` | 工具审批卡片 |
| `draft_review` | 内容审阅卡片 |

## 9. /agent/messages 中断恢复请求格式

```json
{
  "agent_id": "orchestrator-agent",
  "conversation_id": "conv_xxx",
  "message": "用户已确认任务计划",
  "message_type": "action_click",
  "payload": {
    "type": "plan_confirmation",
    "data": {
      "action": "approve",
      "feedback": "确认，继续执行"
    }
  },
  "stream": true
}
```

后端发现该 `conversation_id` 存在 interrupted 运行后，会把 `payload` 转换为 `Command(resume=...)` 所需的 `resume_value`。
恢复后，`InterruptMiddleware` 会把这个值写入 state 的 `resume_value`。

业务中间件随后按 `resume_value.type` 处理。

## 10. 任务计划场景完整流程

```text
Agent 调用 set_task_plan
  ↓
set_task_plan 创建 task_plan.status=draft
  ↓
set_task_plan 写 interrupt_enabled=true
  ↓
set_task_plan 写 interrupt_payload.type=plan_confirmation
  ↓
InterruptMiddleware 触发 interrupt
  ↓
前端展示任务计划确认卡片
  ↓
用户选择 approve/revise/cancel
  ↓
前端调用 /agent/messages
  ↓
InterruptMiddleware 写 resume_value.type=plan_confirmation
  ↓
PlanningMiddleware 读取 resume_value
  ↓
根据 data.action 更新 task_plan 状态或注入修改意见
  ↓
Agent 继续执行
```

## 11. 为什么采用 type + data

这种协议的好处是：

1. 外层稳定，前后端容易对齐。
2. 业务自由度高，所有细节放在 `data`。
3. 通用中断中间件保持极简。
4. 不同业务中间件通过 `type` 认领自己的数据。
5. 后续新增中断类型不需要改通用中断中间件。

## 12. 注意事项

### 12.1 同一时刻只处理一个中断

第一版默认同一条 Agent Run 同一时刻只存在一个中断。

因此暂时不设计 `interrupt_id`。

如果未来要支持并发中断或复杂嵌套中断，再增加 `interrupt_id`。

### 12.2 业务中间件处理后必须清理 resume_value

否则同一个 `resume_value` 可能被下一轮重复处理。

### 12.3 type 必须稳定

`type` 是前后端和业务中间件的路由字段，不建议频繁改名。

### 12.4 data 必须 JSON 可序列化

`interrupt_payload.data` 和 `resume_value.data` 都必须是 JSON 可序列化结构。

## 13. 最终结论

通用中断中间件采用最小协议：

```json
{
  "interrupt_enabled": true,
  "interrupt_payload": {
    "type": "xxx",
    "data": {}
  },
  "resume_value": {
    "type": "xxx",
    "data": {}
  }
}
```

`InterruptMiddleware` 只负责中断和恢复，不理解业务。

业务中间件根据 `resume_value.type` 认领处理，具体业务字段全部放在 `data` 中。
