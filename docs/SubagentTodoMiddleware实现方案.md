# SubagentTodoMiddleware 任务规划中间件实现方案

## 📋 概述

`SubagentTodoMiddleware` 是项目自研的**主智能体任务规划与调度中间件**，用于在多智能体协作（A2A）场景下，让主智能体能够：

1. 将复杂用户需求拆解为多个子任务（Todo 列表）
2. 智能分配任务给合适的子智能体（A2A Agent）
3. 自动跟踪任务执行状态
4. 在需要时主动向用户提问补充信息
5. 最终汇总所有任务结果

---

## 🎯 核心定位

| 项目 | 说明 |
|------|------|
| **使用者** | 主智能体（规划者） |
| **作用** | 任务拆解 + 任务调度 + 状态跟踪 |
| **依赖** | `plan_mode_enabled = True` 时才启用 |
| **搭档** | `ResultReviewMiddleware`（结果审核） |

---

## 🏗️ 整体架构

```
┌────────────────────────────────────────────────────────────┐
│                      主智能体（规划者）                       │
│                                                            │
│  ┌──────────────────────────────────────────────────────┐  │
│  │           SubagentTodoMiddleware                     │  │
│  │                                                      │  │
│  │  abefore_model → 初始任务规划                          │  │
│  │        ↓                                             │  │
│  │  [状态: todos 已生成，第一个任务 in_progress]         │  │
│  │        ↓                                             │  │
│  │  Agent 执行当前任务                                   │  │
│  │        ↓                                             │  │
│  │  aafter_agent → 更新任务状态                          │  │
│  │        ↓                                             │  │
│  │  Command(goto="model") 跳转回 model 执行下一个任务    │  │
│  │        ↓                                             │  │
│  │  循环执行直到 all_completed = True                    │  │
│  └──────────────────────────────────────────────────────┘  │
│                                                            │
└──────────────────────┬─────────────────────────────────────┘
                       │
                       │ send_message (A2A 协议)
                       ↓
        ┌──────────────┴──────────────┐
        ↓              ↓              ↓
   ┌─────────┐   ┌─────────┐   ┌─────────┐
   │ 子Agent1 │   │ 子Agent2 │   │ 子Agent3 │
   │ (执行者) │   │ (执行者) │   │ (执行者) │
   └─────────┘   └─────────┘   └─────────┘
```

---

## 📦 核心组件

### 1. State Schema（状态定义）

```python
class SubagentTodoState(AgentState):
    """子智能体任务规划状态"""
    todos: Optional[List[dict]] = None     # 任务列表
    all_completed: bool = False             # 是否全部完成
    task_results: List[str] = []            # 各任务结果累积
    final_output: bool = False              # 是否最终输出
    plan_disable_only_one: bool = False     # 单任务时关闭规划
```

### 2. TodoItem 数据结构

```python
class TodoItem(BaseModel):
    id: str                              # 任务ID，如 "1", "2"
    content: str                         # 任务描述
    status: Literal["pending",           # 状态
                    "in_progress", 
                    "completed"]
    agent: Optional[str]                 # 负责的子智能体名称
    need_human_input: bool = False       # 是否需要人工介入
```

---

## 🔄 核心流程

### 阶段一：初始任务规划（`abefore_model`）

```
用户输入："帮我分析下销售数据，生成一份报告"
                ↓
┌─────────────────────────────────────────────────────────┐
│ abefore_model 钩子触发                                  │
├─────────────────────────────────────────────────────────┤
│ 1. 检查 state["todos"] 是否为 None                       │
│ 2. 为 None → 调用 plan_todos() 调用 LLM 生成任务列表      │
│ 3. 调用 LLM（with_structured_output 强制 JSON 输出）      │
│ 4. 解析返回的 TodoUpdateResult                           │
│ 5. 判断特殊情况：                                        │
│    - 只有一个任务 → 关闭规划模式，return                  │
│    - 第一个任务需要人工输入 → 触发 ask_clarification 中断 │
│ 6. 自动将第一个 pending 任务标记为 in_progress           │
│ 7. 替换原始用户输入为第一个任务的 content                 │
│ 8. return {todos, all_completed, messages}              │
└─────────────────────────────────────────────────────────┘
                ↓
返回的 todos 状态示例：
[
  {"id": "1", "content": "收集本季度销售数据", "status": "in_progress", "agent": "data_agent"},
  {"id": "2", "content": "进行数据清洗和分析", "status": "pending", "agent": "analysis_agent"},
  {"id": "3", "content": "生成可视化报告", "status": "pending", "agent": None}
]
```

### 阶段二：任务执行（Agent 主循环）

```
Agent 接收规划后的任务 1
                ↓
        模型判断执行方式
                ↓
    ┌───────────┴───────────┐
    ↓                       ↓
独立完成              调用 send_message
（如调工具）          调度子智能体
    ↓                       ↓
    └───────────┬───────────┘
                ↓
        AIMessage 响应
                ↓
        aafter_agent 钩子触发
```

### 阶段三：任务状态更新（`aafter_agent`）

```
┌─────────────────────────────────────────────────────────┐
│ aafter_agent 钩子触发                                   │
├─────────────────────────────────────────────────────────┤
│ 1. 检查最后一条消息是否为 AIMessage（无 tool_calls）      │
│ 2. 记录 task_result = last_msg.content                 │
│ 3. 调用 update_todos() 调用 LLM 更新任务状态            │
│ 4. LLM 返回更新后的 todos 列表                          │
│ 5. 自动修复：全部 completed → 强制 all_completed=True   │
│ 6. 判断下一个任务：                                      │
│    - 全部完成 → goto="model" 做最终总结                  │
│    - 有 in_progress → 继续执行当前任务                   │
│    - 有 pending → 标记为 in_progress，继续执行           │
│    - 下一个任务需要人工输入 → 触发 ask_clarification     │
│ 7. return Command(update, goto="model")                 │
└─────────────────────────────────────────────────────────┘
                ↓
        Command(goto="model") 跳回模型
                ↓
        循环执行直到所有任务完成
```

---

## 🎬 具体场景示例

### 场景 1：标准多任务规划

**用户输入**：`"查询上海天气，并搜索北京旅游攻略"`

**初始规划**：
```python
todos = [
  {"id": "1", "content": "查询上海天气", "status": "in_progress", "agent": "weather_agent"},
  {"id": "2", "content": "搜索北京旅游攻略", "status": "pending", "agent": "search_agent"}
]
```

**执行流程**：
```
模型调用 send_message(weather_agent, "查询上海天气")
    ↓
weather_agent 返回结果
    ↓
aafter_agent 触发 → LLM 更新 todos
    ↓
todos 变为：
[
  {"id": "1", "status": "completed", ...},
  {"id": "2", "status": "in_progress", ...}
]
    ↓
Command(goto="model") 跳回
    ↓
模型调用 send_message(search_agent, "搜索北京旅游攻略")
    ↓
search_agent 返回结果
    ↓
aafter_agent 触发 → LLM 更新 todos
    ↓
todos 变为：
[
  {"id": "1", "status": "completed"},
  {"id": "2", "status": "completed"}
]
    ↓
all_completed = True
    ↓
goto="model" → 模型做最终总结
```

### 场景 2：需要人工介入

**用户输入**：`"帮我分析现场照片"`（但还没上传）

**初始规划**：
```python
todos = [
  {"id": "1", "content": "请您上传现场照片以便分析", "status": "in_progress", "need_human_input": True}
]
```

**执行流程**：
```
abefore_model 检测到 need_human_input
    ↓
触发 ask_clarification 工具
    ↓
中断执行，等待用户上传
    ↓
用户上传照片后恢复
```

### 场景 3：单任务自动跳过

**用户输入**：`"你好"`（简单问候）

**处理**：
```python
# plan_todos 返回空或单元素
if len(result.todos) == 1:
    self.enable = False  # 关闭规划
    return {"plan_disable_only_one": True}
```

→ 直接进入正常 ReAct 模式，不做任务规划

---

## 🔑 关键设计点

### 1. 双 LLM 协作

中间件**自己调用 LLM**（不是通过主 Agent 的模型），用于任务规划：

```python
async def get_model(self):
    model_config = ModelConfig(
        **self.llm_service.config.model_dump(),
    )
    model_config.enable_thinking = False      # 关闭思考
    model_config.stream = False                # 非流式
    model_config.max_tokens_for_node = 1024   # 限制 token
    return await self.llm_service.create_model(model_config)
```

**为什么自己调 LLM？**
- 主 Agent 正在执行当前任务
- 任务规划需要独立、稳定、不被干扰
- 使用 `with_structured_output` 强制返回 JSON

### 2. Command 跳转控制

通过 LangGraph 的 `Command` 对象控制流程：

```python
return Command(
    update={"todos": ..., "messages": [HumanMessage(...)]},
    goto="model"  # 跳回模型节点
)
```

**为什么用 goto？**
- 默认流程会到 `end`
- 任务未完成时需要回到 `model` 继续执行
- 比循环重试更精确

### 3. 状态自动修复

```python
# LLM 可能漏判
if response.todos and all(t.status == "completed" for t in response.todos):
    response.all_completed = True  # 强制修正
```

**为什么需要？**
- LLM 输出不稳定
- 状态一致性保障
- 避免陷入死循环

### 4. 消息注入技巧

```python
# 把原始用户输入替换为第一个任务描述
original_user_msg.content = task_prompt
```

**作用**：
- 模型看到的是"任务 1 的内容"，而不是原始用户输入
- 引导模型专注于当前任务

### 5. 子智能体结果跳过模型

```python
# 如果是 send_message 工具的结果，直接返回，不让模型再处理
if message.name == "send_message":
    return {
        "messages": [AIMessage(content=content)],
        "jump_to": "end"
    }
```

**原因**：
- 子智能体已经处理过结果
- 避免主模型重复加工
- 提升效率

---

## 🛠️ Hook 钩子使用

| 钩子 | 用途 |
|------|------|
| `abefore_model` | 初始任务规划（仅在 todos 为 None 时） |
| `aafter_agent` | 任务状态更新 + 跳转控制 |
| `state_schema` | 自定义状态结构（todos、all_completed 等） |
| `hook_config(can_jump_to=["tools", "end"])` | 声明可跳转的节点 |

---

## 📊 状态转换图

```
            abefore_model
                 ↓
    ┌──────────────────────────┐
    │ todos = None             │
    │ → plan_todos()           │
    │ → 设置第一个为 in_progress│
    └────────────┬─────────────┘
                 ↓
         [todos 已规划]
                 ↓
         Agent 执行
                 ↓
    ┌──────────────────────────┐
    │ aafter_agent             │
    │ → update_todos()         │
    └────────────┬─────────────┘
                 ↓
        ┌────────┴────────┐
        ↓                 ↓
  有 pending         all_completed
        ↓                 ↓
  标记 in_progress    goto="model"
        ↓                 ↓
  goto="model"        最终总结
        ↓
    Agent 继续
        ↓
    (循环)
```

---

## ⚙️ 启用配置

```python
# agent_config.py
plan_mode_enabled: bool = Field(
    default_factory=lambda: str(os.getenv("PLAN_MODE_ENABLED_DEFAULT", "false")).lower() == "true",
    description="是否启用计划模式"
)
```

**环境变量**：`PLAN_MODE_ENABLED_DEFAULT = true/false`

---

## 🎯 实际效果

### 启用前（普通 ReAct）
```
用户：分析销售数据，生成报告
模型：直接调用工具 → 一次性输出
```

### 启用后（任务规划）
```
用户：分析销售数据，生成报告
中间件：规划 3 个任务（数据收集 → 数据分析 → 报告生成）
模型：执行任务 1 → 执行任务 2 → 执行任务 3 → 总结输出
```

### 核心价值

| 价值 | 说明 |
|------|------|
| **任务可追踪** | 复杂任务拆解为可视化步骤 |
| **智能调度** | 自动分配给合适的子智能体 |
| **状态管理** | 自动维护任务执行状态 |
| **人工介入** | 信息不全时主动询问用户 |
| **结果汇总** | 自动合并各任务结果 |

---

## ⚠️ 注意事项

### 1. 性能开销

- 每次任务结束后调用 LLM 做状态更新
- 多次 LLM 调用会增加延迟
- 适合复杂任务，简单任务不适用

### 2. LLM 依赖

- 任务规划依赖 LLM 的能力
- 模型能力不足时规划可能失败
- 已有容错机制（try/except）

### 3. 默认关闭

- 默认 `plan_mode_enabled = False`
- 需要主动开启
- 避免对简单任务造成额外开销

### 4. 特殊场景处理

- 单任务自动关闭规划
- 子智能体结果跳过模型
- 全部完成后强制修正状态

---

## 🔗 相关文件

- 中间件实现：[`subagent_todo_middleware.py`](file:///d:/work/HaiKong/AI/agent-engine/agent_engine/src/services/services_platform/langchain/middlewares/subagent_todo_middleware.py)
- 中间件编排：[`agent_service.py:241`](file:///d:/work/HaiKong/AI/agent-engine/agent_engine/src/services/services_platform/langchain/agent_service.py#L241)
- 配置定义：[`agent_config.py:124`](file:///d:/work/HaiKong/AI/agent-engine/agent_engine/src/models/agent_config.py#L124)
- 结果审核：[`agent_service.py:260`](file:///d:/work/HaiKong/AI/agent-engine/agent_engine/src/services/services_platform/langchain/agent_service.py#L260)

---

## 📝 总结

`SubagentTodoMiddleware` 是项目为 **A2A 多智能体场景**专门设计的任务规划中间件，它通过：

1. **LLM 驱动的任务规划**：将用户需求拆解为可执行任务
2. **智能任务调度**：自动分配给合适的子智能体
3. **状态机管理**：自动维护任务执行状态
4. **Command 跳转控制**：精确控制执行流程
5. **人工介入机制**：信息不全时主动询问

实现了**主智能体作为规划者，子智能体作为执行者**的协作模式，是项目 A2A 模块的重要组成部分。
