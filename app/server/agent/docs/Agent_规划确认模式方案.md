# Agent 规划确认模式方案

## 1. 背景

当前 Agent 已经具备普通对话、工具调用、A2A 子 Agent 调用、MCP 工具接入和流式输出能力。下一步需要增强复杂任务的可控性：当用户提出一个复杂需求时，Agent 不应该直接开始执行，而应该先生成任务计划，让用户确认后再继续执行。

这个能力不是长期任务队列，也不是业务层工作流，而是一次 Agent Run 内部的可控执行模式。

## 2. 核心目标

1. Agent 在复杂任务执行前先生成任务计划。
2. 任务计划需要展示给用户确认。
3. 用户可以确认、要求修改或取消计划。
4. 用户确认后，Agent 从中断点继续执行，而不是重新发起一次普通对话。
5. 执行过程中如果缺少必要信息，Agent 可以再次中断并向用户追问。
6. 任务计划只属于本次 Agent Run 生命周期，不作为长期会话记忆，也不单独写入 PostgreSQL 业务表。

## 3. 设计原则

### 3.1 Agent 管计划内容，系统管计划生命周期

规划确认模式最重要的边界是：

```text
Agent 负责：
  创建任务计划内容
  根据用户反馈重写 draft 计划
  执行 running 计划中的步骤
  更新单个步骤状态

系统负责：
  控制任务计划整体状态
  控制是否中断
  控制用户确认后是否进入 running
  控制用户取消后是否进入 cancelled
```

Agent 不能绕过用户确认，不能自己把任务计划整体状态改成 `running`。

### 3.2 只保留两个工具

第一版只保留两个规划工具：

1. `set_task_plan`
2. `update_task_step`

不单独设计 `revise_task_plan`。如果用户要求修改计划，Agent 继续调用 `set_task_plan` 重写 draft 计划。

### 3.3 中断协议保持最小

通用中断状态只保留两个字段：

```json
{
  "interrupt_enabled": true,
  "interrupt_payload": {}
}
```

用户回复通过统一消息入口 `/agent/messages` 传回 LangGraph，并在通用中断中间件中统一写入 `resume_value`。

## 4. 任务计划整体状态

任务计划整体状态只保留四个：

| 状态 | 说明 | 谁能设置 |
|------|------|----------|
| `draft` | 草稿/未开始，等待用户确认 | `set_task_plan` 创建或重写 |
| `running` | 用户已确认，Agent 可以开始执行步骤 | 中间件根据用户 approve 设置 |
| `completed` | 所有步骤完成 | 中间件或系统根据步骤状态设置 |
| `cancelled` | 用户取消本次计划 | 中间件根据用户 cancel 设置 |

注意：

1. Agent 不能直接设置整体状态为 `running`。
2. Agent 不能直接设置整体状态为 `cancelled`。
3. Agent 可以通过工具更新步骤状态，但不能越权修改整体生命周期。

## 5. task_plan 结构

`task_plan` 存在 LangGraph state 中。

建议结构：

```json
{
  "status": "draft",
  "title": "生成岗位画像并给出学习建议",
  "steps": [
    {
      "step_id": "step_1",
      "title": "分析用户提供的岗位描述",
      "description": "识别岗位名称、职责和能力要求",
      "status": "waiting",
      "result": null
    },
    {
      "step_id": "step_2",
      "title": "提炼核心技能",
      "description": "抽取必备技能和加分技能",
      "status": "waiting",
      "result": null
    }
  ]
}
```

步骤状态建议：

| 状态 | 说明 |
|------|------|
| `waiting` | 待执行 |
| `running` | 执行中 |
| `done` | 已完成 |
| `failed` | 执行失败，失败后应停止后续步骤并向用户说明原因 |

## 6. optional_features.planning_enabled

在 Agent 调用参数的 `optional_features` 中增加规划开关：

```json
{
  "optional_features": {
    "planning_enabled": true
  }
}
```

当 `optional_features.planning_enabled = true` 时，Agent 组装阶段会启用规划能力：

1. 注入规划模式系统提示词。
2. 自动注入 `set_task_plan` 和 `update_task_step` 工具。
3. 扩展 LangGraph state。
4. 允许中断和恢复。

## 7. 工具设计

### 7.1 set_task_plan

用于创建或重写任务计划。

规则：

```text
如果没有计划：创建 draft 计划
如果已有 draft：重写 draft 计划
如果已有 running：拒绝修改整体计划
如果已有 completed：拒绝修改整体计划
如果已有 cancelled：拒绝修改整体计划
```

入参：

```json
{
  "title": "生成岗位画像并给出学习建议",
  "steps": [
    {
      "step_id": "step_1",
      "title": "分析岗位描述",
      "description": "识别岗位名称、职责和能力要求"
    }
  ]
}
```

工具行为：

1. 创建或重写 `task_plan`。
2. 强制设置 `task_plan.status = draft`。
3. 初始化步骤状态为 `waiting`。
4. 设置 `interrupt_enabled = true`。
5. 设置 `interrupt_payload.type = plan_confirmation`。
6. 返回 `Command(update=...)` 写入状态和工具消息，不再强制 `goto="model"`。
7. 后续是否进入模型节点由 LangGraph 正常工具链路决定，`InterruptMiddleware` 会在下一次模型调用前触发中断。

示例工具返回：

```python
return Command(
    update={
        "task_plan": task_plan,
        "interrupt_enabled": True,
        "interrupt_payload": {
            "type": "plan_confirmation",
            "data": {
                "task_plan": task_plan
            }
        },
        "messages": [ToolMessage(content="任务计划已创建成功，具体状态和下一步动作请以 <planning_mode> 中的系统提示为准。")]
    }
)
```

注意：任务计划工具不再设置 `goto="model"`。

原因是 `goto="model"` 会额外制造一次模型轮次，在 A2A、任务步骤更新等场景下容易让主 Agent 提前继续推理，造成“工具尚未完全结束但模型已经进入下一步”的错觉或并发问题。现在工具只负责写入 state 和 ToolMessage，控制流交给 LangGraph 默认工具链路。

### 7.2 update_task_step

用于更新任务步骤状态、结果和备注。

规则：

```text
仅当 task_plan.status = running 时允许更新步骤
如果 task_plan.status = draft：拒绝更新步骤，提示需要用户先确认计划
如果 task_plan.status = completed：拒绝更新步骤
如果 task_plan.status = cancelled：拒绝更新步骤
```

入参：

```json
{
  "step_id": "step_1",
  "status": "done",
  "result": "已识别岗位为 AI 应用开发工程师"
}
```

工具行为：

1. 从 `task_plan.steps` 中找到对应步骤。
2. 更新步骤状态、结果和备注。
3. 如果所有步骤都已完成，系统可以把 `task_plan.status` 设置为 `completed`。
4. 返回更新后的任务计划摘要。

#### update_task_step 使用要求

Agent 执行已确认计划时，必须按以下方式使用 `update_task_step`：

1. 开始执行某个步骤前，先调用 `update_task_step`，把该步骤状态设置为 `running`。
2. 步骤执行成功后，调用 `update_task_step`，把该步骤状态设置为 `done`，并在 `result` 中写入执行结果。
3. 步骤执行失败后，调用 `update_task_step`，把该步骤状态设置为 `failed`，并在 `note` 或 `result` 中写入失败原因。
4. 步骤失败后，不继续执行剩余步骤，直接回复用户：`任务执行失败，原因：具体原因`。

## 8. 中间件设计

规划确认模式建议拆成两个中间件协作。

### 8.1 PlanningMiddleware

职责：

1. 注入规划模式提示词。
2. 注入当前 `task_plan` 摘要。
3. 在用户要求修改计划后，提示 Agent 继续调用 `set_task_plan` 重写 draft 计划。
4. 在计划进入 `running` 后，提示 Agent 按步骤执行并调用 `update_task_step` 更新进度。

PlanningMiddleware 不直接负责通用中断触发。

### 8.2 InterruptMiddleware

职责：

1. 检查 `interrupt_enabled`。
2. 如果为 true，则调用 `interrupt(interrupt_payload)`。
3. 用户 resume 后，把用户返回内容写入 `resume_value`。
4. 清理 `interrupt_enabled` 和 `interrupt_payload`。
5. 不解释 `resume_value.data` 的业务含义。

伪代码：

```python
if state.get("interrupt_enabled"):
    payload = state.get("interrupt_payload") or {}
    raw_resume_value = interrupt(payload)

    return {
        "interrupt_enabled": False,
        "interrupt_payload": None,
        "resume_value": {
            "type": payload.get("type") or raw_resume_value.get("type"),
            "data": raw_resume_value.get("data") or {},
        },
    }
```

## 9. PlanningMiddleware 处理 resume_value

`/agent/messages` 在命中中断运行后会转换出的内容会进入统一的 `resume_value`：

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

PlanningMiddleware 只处理 `resume_value.type = plan_confirmation` 的数据。

`resume_value.data.action` 建议只保留三个：

| action | 说明 |
|--------|------|
| `approve` | 用户确认计划，系统将计划整体状态改成 `running` |
| `revise` | 用户要求修改计划，计划仍保持 `draft` |
| `cancel` | 用户取消本次计划，系统将计划整体状态改成 `cancelled` |

### 9.1 approve

用户确认无误。

系统行为：

1. `task_plan.status = running`。
2. 清理或消费 `resume_value`。
3. 注入提示：用户已确认任务计划，请开始按步骤执行。

### 9.2 revise

用户要求修改计划。

系统行为：

1. `task_plan.status` 保持 `draft`。
2. 清理或消费 `resume_value`。
3. 注入用户修改意见。
4. Agent 根据意见调用 `set_task_plan` 重写 draft 计划。
5. `set_task_plan` 再次触发中断确认。

### 9.3 cancel

用户取消本次任务。

系统行为：

1. `task_plan.status = cancelled`。
2. 清理或消费 `resume_value`。
3. 当前 run 结束，状态可记为 `cancelled`。

## 10. 完整流程

```text
POST /agent/messages
  optional_features.planning_enabled = true
        ↓
PlanningMiddleware 注入规划规则和规划工具
        ↓
Agent 判断任务复杂，需要规划
        ↓
Agent 调用 set_task_plan
        ↓
set_task_plan 创建 draft 计划
        ↓
set_task_plan 设置 interrupt_enabled=true + interrupt_payload
        ↓
InterruptMiddleware 触发 interrupt
        ↓
前端展示任务计划确认卡片
        ↓
用户选择 revise
        ↓
POST /agent/messages
        ↓
PlanningMiddleware 读取 resume_value，保持 task_plan.status=draft，并注入修改意见
        ↓
Agent 调用 set_task_plan 重写 draft 计划
        ↓
再次 interrupt 给用户确认
        ↓
用户选择 approve
        ↓
POST /agent/messages
        ↓
PlanningMiddleware 读取 resume_value，将 task_plan.status 设置为 running
        ↓
Agent 按步骤执行
        ↓
Agent 调用 update_task_step 更新步骤状态
        ↓
所有步骤完成
        ↓
系统设置 task_plan.status=completed
        ↓
Agent 输出最终结果
```

## 11. SSE 事件设计

### 11.1 task_plan 事件

只要 LangGraph `updates` 流中出现 `task_plan` state 更新，后端就向前端推送完整任务计划。

前端不需要解析 `set_task_plan` 或 `update_task_step` 的工具返回结果，只需要监听 `type = task_plan` 并整体替换当前任务计划面板。

```json
{
  "type": "task_plan",
  "data": {
    "run_id": "run_xxx",
    "thread_id": "thread_xxx",
    "task_plan": {
      "title": "生成岗位画像并给出学习建议",
      "status": "draft",
      "steps": [
        {
          "step_id": "step_1",
          "title": "分析岗位描述",
          "description": "识别岗位名称、职责和能力要求",
          "status": "waiting",
          "result": null,
          "note": null
        }
      ]
    }
  }
}
```

推荐前端处理方式：

```text
收到 type=task_plan
  ↓
整体替换任务计划面板数据
```

### 11.2 interrupt 事件

```json
{
  "type": "interrupt",
  "data": {
    "run_id": "run_xxx",
    "thread_id": "thread_xxx",
    "payload": {
      "type": "plan_confirmation",
      "title": "请确认任务计划",
      "data": {
        "task_plan": {
          "status": "draft",
          "title": "生成岗位画像并给出学习建议",
          "steps": []
        }
      }
    }
  }
}
```

### 11.3 run_end interrupted 事件

```json
{
  "type": "run_end",
  "data": {
    "run_id": "run_xxx",
    "thread_id": "thread_xxx",
    "status": "interrupted",
    "interrupt_type": "plan_confirmation"
  }
}
```

## 12. Resume 接口设计

```http
POST /agent/messages
```

请求体：

```json
{
  "run_id": "run_xxx",
  "thread_id": "thread_xxx",
  "resume_value": {
    "type": "plan_confirmation",
    "data": {
      "action": "approve",
      "feedback": "确认，继续执行"
    }
  },
  "stream": true
}
```

如果用户修改计划，可以传：

```json
{
  "run_id": "run_xxx",
  "thread_id": "thread_xxx",
  "resume_value": {
    "type": "plan_confirmation",
    "data": {
      "action": "revise",
      "feedback": "第二步需要增加学习路径建议"
    }
  },
  "stream": true
}
```

## 13. 前端交互设计

前端 Agent 调用页需要支持：

1. 接收 `interrupt` SSE 事件。
2. 根据 `interrupt.payload.type` 选择渲染方式。
3. `plan_confirmation` 渲染任务计划确认卡片。
4. 用户可以确认、要求修改或取消。
5. 用户操作后继续调用 `/agent/messages`。
6. resume 后继续在同一条 Agent 消息时间线中追加事件。

推荐展示结构：

```text
Agent 思考
  ↓
任务计划确认卡片
  标题：生成岗位画像并给出学习建议
  状态：draft
  步骤：
    1. 分析岗位描述
    2. 提炼核心技能
    3. 生成学习建议
  [确认执行] [要求修改] [取消]
  ↓
用户确认后
  ↓
Agent 继续执行
  ↓
工具调用 / 子 Agent 调用 / 回复
```

## 14. 和现有能力的关系

### 14.1 和 conversation_id 的关系

`conversation_id` 主要用于用户聊天展示和会话管理。

规划确认模式中的 `task_plan` 不建议绑定 `conversation_id`，因为它只属于本次 run。

### 14.2 和 run_id / thread_id 的关系

`run_id` 用于业务侧追踪本次 Agent 运行。

`thread_id` 用于 LangGraph checkpoint 恢复。

规划确认模式应该主要依赖 `thread_id` 恢复状态，并用 `run_id` 关联前端展示和运行记录。

### 14.3 和 checkpoint 的关系

`task_plan` 存在 LangGraph state 中，checkpoint 负责保存中断时的完整状态。

用户 resume 时，后端根据 `thread_id` 从 checkpoint 恢复执行。

## 15. 第一版落地步骤

### 阶段一：协议和 Schema

1. 在 `AgentOptionalFeatures` 中增加 `planning_enabled` 参数。
2. 通过 `AgentFeatureConfig.enable_planning` 转换为内部装配开关。
3. 定义 `AgentResumeRequest` schema。
4. 定义 interrupt SSE 事件格式。

### 阶段二：State 和工具

1. 增加 `task_plan`、`interrupt_enabled`、`interrupt_payload` state 字段。
2. 实现 `set_task_plan` 工具。
3. 实现 `update_task_step` 工具。
4. 工具通过 `ToolRuntime` 写入 state。

### 阶段三：中间件

1. 实现 `InterruptMiddleware`。
2. 实现 `PlanningMiddleware`。
3. 在 PlanningMiddleware 中注入规划提示词和当前计划摘要。
4. 在 InterruptMiddleware 中处理中断和 resume action。

### 阶段四：Agent 组装

1. `optional_features.planning_enabled = true` 时自动装配 PlanningMiddleware。
2. 始终装配 InterruptMiddleware，或在存在中断能力时装配。
3. 自动注入规划工具。
4. 日志打印规划模式启用状态。

### 阶段五：统一消息入口恢复

1. 前端继续调用 `/agent/messages`。
2. 后端根据 `conversation_id` 找到 interrupted 运行。
3. 后端内部根据原 `thread_id` 恢复 checkpoint。
4. 后端内部使用 `Command(resume=...)` 继续执行 Agent。
5. 支持流式和非流式返回。

### 阶段六：前端

1. Agent 调用页支持 `interrupt` 事件。
2. 展示任务计划确认卡片。
3. 支持确认、要求修改、取消。
4. 用户操作后继续调用 `/agent/messages` 并接收流式事件。

## 16. 风险点

### 16.1 interrupt 所在节点可能重新执行

LangGraph 恢复时可能重新进入中断所在节点，所以中断前不要做不可重复的副作用。

### 16.2 running 计划不能被 Agent 重写

`set_task_plan` 必须校验当前计划状态，防止 Agent 在执行中重写整体计划。

### 16.3 revise 可能产生多轮确认

用户多次要求修改时，计划会多次保持 `draft` 并重复中断确认。这是符合预期的。

### 16.4 thread_id 必须返回前端

前端调用 `/agent/messages` 必须带回同一个 `conversation_id`；后端会用它找到原运行的 `thread_id`。

## 17. MVP 建议

第一版只实现最小闭环：

1. `optional_features.planning_enabled = true`。
2. Agent 调用 `set_task_plan`。
3. `set_task_plan` 创建 `draft` 计划并触发中断。
4. 前端展示计划。
5. 用户 approve。
6. 前端继续调用 `/agent/messages`，后端内部恢复执行。
7. 系统设置 `task_plan.status = running`。
8. Agent 调用 `update_task_step` 更新步骤。
9. Agent 最终回复。

暂时不做：

1. 任务步骤可视化执行进度条。
2. 任务计划长期保存。
3. 独立任务队列管理页面。
4. 任务并发。
5. 多人审批。

## 18. 总结

Agent 规划确认模式的本质是：

> 把复杂任务的计划内容交给 Agent，把计划生命周期控制权交给系统，把关键确认权交给用户。

第一版只需要两个工具：`set_task_plan` 和 `update_task_step`。

计划整体状态只保留四个：`draft`、`running`、`completed`、`cancelled`。

这样可以让 Agent 保持自主规划能力，同时避免它绕过用户确认直接开始执行。
