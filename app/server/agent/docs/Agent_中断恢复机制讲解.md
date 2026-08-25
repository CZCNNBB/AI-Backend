# Agent 中断恢复机制讲解

## 1. 这是什么

Agent 中断恢复机制，也可以叫 Human-in-the-loop 机制。

它解决的问题是：Agent 在一次运行过程中，不一定要从头执行到尾。如果执行到某个关键点时需要用户确认、审批、补充信息，Agent 可以主动暂停，把需要用户处理的内容返回给前端。用户处理完之后，后端再从暂停点附近恢复执行。

这个机制的核心不是“重新发起一次对话”，而是“继续同一次 Agent Run”。

可以简单理解为：

```text
Agent 正在运行
  ↓
遇到需要用户参与的点
  ↓
中断，等待用户输入
  ↓
用户确认 / 修改 / 补充
  ↓
恢复运行
  ↓
Agent 继续执行后续步骤
```

## 2. 为什么需要它

普通 Agent 对话是这样的：

```text
用户提问
  ↓
Agent 执行
  ↓
Agent 回复
  ↓
本轮结束
```

这种模式适合简单问答，但不适合复杂任务。

复杂任务经常需要这些能力：

1. 执行前让用户确认计划。
2. 执行中发现信息不足，向用户追问。
3. 调用高风险工具前让用户审批。
4. 生成内容后让用户修改，再继续后续流程。
5. 多步骤任务执行过程中保留中间状态。

如果没有中断恢复机制，这些场景只能变成多轮普通对话：

```text
Agent：我生成了计划，你确认吗？
用户：确认
Agent：好的，我重新根据上下文继续
```

这种方式的问题是：

1. Agent 不一定能准确恢复之前的内部状态。
2. 工具调用状态、任务计划、临时变量容易丢失。
3. 多步骤任务会越来越依赖提示词记忆。
4. 前端很难区分“普通回复”和“等待用户确认”。

中断恢复机制可以把这些问题变成可控流程。

## 3. 核心概念

### 3.1 interrupt

`interrupt` 表示 Agent 主动暂停当前执行。

它会把一段 JSON 数据返回给调用方，例如：

```json
{
  "reason": "plan_confirmation",
  "message": "请确认下面的任务计划",
  "task_plan": {
    "title": "生成岗位画像",
    "steps": [
      {"id": "step_1", "title": "分析岗位 JD"},
      {"id": "step_2", "title": "提炼技能要求"}
    ]
  }
}
```

前端收到后，不应该把它当成普通 Agent 回复，而应该展示成一个交互卡片。

### 3.2 resume

`resume` 表示用户已经处理完中断请求，后端可以继续执行。

例如用户确认任务计划后，前端调用：

```json
{
  "run_id": "run_xxx",
  "thread_id": "thread_xxx",
  "action": "approve",
  "feedback": "计划可以，继续执行"
}
```

后端把用户输入交回 LangGraph，Agent 从之前中断的流程继续跑。

### 3.3 checkpoint

checkpoint 是中断恢复的基础。

Agent 中断时，当前图状态必须保存下来，包括：

1. 当前执行到哪个节点。
2. 当前 state 里有什么数据。
3. 当前消息历史是什么。
4. 工具调用和中间变量是什么。

如果没有 checkpoint，后端就不知道从哪里恢复，只能重新开始。

### 3.4 thread_id

`thread_id` 是 checkpoint 的恢复标识。

同一个 `thread_id` 表示同一条可恢复的执行线程。

恢复时必须使用中断时的 `thread_id`。如果换了新的 `thread_id`，就是新的执行状态，不是恢复。

### 3.5 run_id

`run_id` 是我们平台层面的运行记录 ID。

它主要用于：

1. 前端展示本次 Agent 运行。
2. `agent_runs` 表记录运行状态。
3. 排查问题和关联日志。
4. 和 LangSmith 或本地运行记录关联。

可以这样区分：

| 字段 | 归属 | 作用 |
|------|------|------|
| `run_id` | 我们平台 | 追踪一次 Agent 运行 |
| `thread_id` | LangGraph | 恢复 checkpoint 状态 |
| `conversation_id` | 会话展示 | 管理用户聊天上下文 |

## 4. 生命周期

### 4.1 普通运行

```text
POST /agent/messages
  ↓
创建 run_id
  ↓
创建或复用 thread_id
  ↓
Agent 执行
  ↓
返回 model_delta / tool_call / tool_result
  ↓
返回 run_end(status=success)
```

### 4.2 中断运行

```text
POST /agent/messages
  ↓
创建 run_id
  ↓
创建 thread_id
  ↓
Agent 执行
  ↓
触发 interrupt
  ↓
checkpoint 保存当前状态
  ↓
SSE 返回 interrupt 事件
  ↓
run 状态更新为 interrupted
  ↓
前端等待用户操作
```

### 4.3 恢复运行

```text
POST /agent/messages
  ↓
传入 run_id + thread_id + 用户反馈
  ↓
根据 thread_id 找到 checkpoint
  ↓
Command(resume=用户反馈)
  ↓
Agent 从中断流程继续执行
  ↓
继续返回流式事件
  ↓
返回 run_end(status=success)
```

## 5. 官方机制的关键点

LangGraph 的中断恢复机制有几个非常重要的规则。

### 5.1 中断不是失败

中断只表示 Agent 暂停等待用户输入。

所以运行状态不应该是 `failed`，而应该是：

```text
interrupted
```

### 5.2 恢复依赖同一个 thread_id

通过 `/agent/messages` 恢复时必须继续使用同一个 `conversation_id`，后端会映射到中断时的 `thread_id`。

如果没有 `thread_id`，就无法恢复。

### 5.3 中断点所在节点可能会重新执行

LangGraph 恢复时，不是从 `interrupt()` 那一行之后继续执行，而是重新进入当前节点，然后把 resume 值返回给 `interrupt()`。

因此要注意：

1. 不要在 `interrupt()` 前做不可重复的副作用。
2. 不要在 `interrupt()` 前直接写数据库、发消息、扣费、调用外部不可逆接口。
3. 如果必须做副作用，需要保证幂等。

### 5.4 interrupt 的 payload 必须可序列化

中断返回给前端的数据应该是 JSON 可序列化对象。

推荐只传：

1. 字符串。
2. 数字。
3. 布尔值。
4. list。
5. dict。
6. null。

不要传 Python 对象、函数、数据库连接、LangChain 消息对象。

### 5.5 不要随便捕获 interrupt 异常

LangGraph 的 interrupt 底层依赖特殊控制流。

如果我们用宽泛的 `try/except Exception` 把它吞掉，可能会导致中断失效。

所以在中间件或节点中要谨慎处理异常。

## 6. 适合我们的场景

### 6.1 任务计划确认

用户说：

```text
帮我根据这个岗位 JD 生成岗位画像，并给学习建议。
```

Agent 不直接执行，而是先中断：

```text
我准备按以下步骤执行：
1. 分析岗位 JD
2. 提炼岗位技能
3. 生成岗位画像
4. 给出学习建议
是否继续？
```

用户确认后，Agent 再继续执行。

### 6.2 缺少信息追问

Agent 执行学习路径生成时发现缺少用户基础信息：

```text
你当前 Python 基础是什么水平？
```

用户补充后，Agent 继续生成学习路径。

### 6.3 高风险工具审批

未来如果有工具会写数据库、发送通知、生成正式报告，可以先中断审批。

例如：

```text
即将创建新的平台技能词条：日志监控。是否确认？
```

### 6.4 内容审阅修改

Agent 生成一版岗位画像草稿后，可以中断给用户修改。

用户修改后，Agent 用修改后的内容继续生成最终结果。

## 7. 我们项目里的推荐事件格式

### 7.1 interrupt SSE 事件

```json
{
  "type": "interrupt",
  "data": {
    "run_id": "run_xxx",
    "thread_id": "thread_xxx",
    "reason": "plan_confirmation",
    "title": "请确认任务计划",
    "message": "我将按下面的步骤执行，确认后继续。",
    "payload": {
      "task_plan": {
        "title": "生成岗位画像",
        "steps": []
      }
    }
  }
}
```

### 7.2 run_end interrupted 事件

```json
{
  "type": "run_end",
  "data": {
    "run_id": "run_xxx",
    "thread_id": "thread_xxx",
    "status": "interrupted",
    "interrupt_reason": "plan_confirmation"
  }
}
```

### 7.3 resume 请求

```json
{
  "run_id": "run_xxx",
  "thread_id": "thread_xxx",
  "action": "approve",
  "feedback": "确认，继续执行",
  "payload": {
    "task_plan": {
      "title": "生成岗位画像",
      "steps": []
    }
  },
  "stream": true
}
```

## 8. 我们项目里的状态建议

`agent_runs.status` 建议支持：

| 状态 | 说明 |
|------|------|
| `running` | 正在运行 |
| `interrupted` | 已中断，等待用户输入 |
| `success` | 运行成功 |
| `failed` | 运行失败 |
| `cancelled` | 用户取消 |

中断时：

1. `agent_runs.status = interrupted`。
2. 记录 `thread_id`。
3. 记录 `interrupt_reason` 到 metadata。
4. 不写 assistant 最终回复。

恢复后：

1. 可以继续使用原 `run_id`，也可以创建新的 resume run。
2. 第一版建议继续使用原 `run_id`，简单直观。
3. 最终完成后更新 `agent_runs.status = success`。

## 9. 和规划确认模式的关系

中断恢复机制是底层能力。

规划确认模式是它的一个业务用法。

关系如下：

```text
中断恢复机制
  ├─ 任务计划确认
  ├─ 用户补充信息
  ├─ 工具调用审批
  └─ 内容审阅修改
```

所以实现顺序应该是：

1. 先做通用 interrupt/resume。
2. 再做 PlanningMiddleware。
3. 再做任务计划工具。
4. 最后接前端任务计划确认卡片。

## 10. 前端应该怎么理解

前端收到 `interrupt` 时，不要当成错误，也不要当成最终回答。

它应该进入“等待用户操作”状态：

```text
Agent 暂停执行
原因：请确认任务计划
[确认继续] [修改后继续] [取消]
```

用户操作后，前端继续调用 `/agent/messages`。

resume 之后，前端继续接收同一条 Agent 消息的后续流式事件。

## 11. 最小落地版本

第一版可以只做最小闭环。

### 后端

1. 增加统一消息入口 `/agent/messages` 的中断恢复路由能力。
2. 流式输出支持 `interrupt`。
3. `agent_runs` 支持 `interrupted`。
4. 统一消息入口命中中断后，内部使用 `Command(resume=...)`。
5. 保证中断时返回 `thread_id`。

### 前端

1. 支持展示 interrupt 卡片。
2. 支持确认继续。
3. 支持用户输入 feedback 后继续。
4. 支持取消。

### 暂时不做

1. 复杂多次中断。
2. 长期任务计划保存。
3. 独立任务队列页面。
4. 多人审批。
5. 中断超时回收。

## 12. 总结

中断恢复机制的价值是：

> Agent 可以继续保持自己的执行状态，但关键节点可以交给用户参与决策。

它让 Agent 从“自动回复机器”变成“可控执行流程”。

对我们的就业指导 AI 平台来说，它非常适合岗位画像生成、学习计划生成、简历优化、面试准备等复杂流程。第一版建议只围绕 `interrupt`、`resume`、`checkpoint`、`thread_id` 做最小闭环，后续再逐步扩展任务计划、审批和前端可视化能力。

## 13. 参考资料

- LangGraph Interrupts: https://docs.langchain.com/oss/python/langgraph/interrupts
- LangGraph Persistence: https://docs.langchain.com/oss/python/langgraph/persistence
