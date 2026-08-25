# Agent 知识库检索接入说明

## 1. 能力定位

知识库检索属于 AI-backend 内部基础能力，不是 MCP 外部工具。

模板的 `tools` 字段继续只保存 MCP 工具编码。模板只通过
`optional_features.knowledge_enabled` 声明 Agent 是否具备知识库检索能力，
具体允许访问哪些知识库由每次调用的 `knowledge.knowledge_base_ids` 决定。

## 2. 模板配置

```json
{
  "optional_features": {
    "knowledge_enabled": true
  }
}
```

模板不保存知识库 ID。历史模板中的 `optional_features.knowledge_base_ids`
会在读取或再次保存时被清理。

## 3. 运行配置

调用 `/agent/messages` 时传入本次运行的访问白名单：

```json
{
  "agent_id": "orchestrator-agent",
  "conversation_id": "conv_xxx",
  "message": "查询知识库中的岗位信息",
  "knowledge": {
    "knowledge_base_ids": ["kb_job", "kb_skill"]
  }
}
```

装配规则：

1. 模板未开启 `knowledge_enabled`：即使请求传入知识库 ID，也不装配检索工具。
2. 模板已开启，但本次没有知识库 ID：不装配检索工具。
3. 模板已开启且本次提供知识库 ID：装配 `search_knowledge_base`。
4. 知识库 ID 最多 20 个，后端会清理空值并按顺序去重。

## 4. 执行链路

```text
Agent 模板 knowledge_enabled
  + 本次调用 knowledge.knowledge_base_ids
  -> AgentRunLifecycleService 解析模板，保留运行时访问范围
  -> AgentRuntimeContext 保存知识库白名单
  -> AgentAssembler 执行双重条件检查
  -> 自动挂载 search_knowledge_base
  -> 模型只传 query 和 top_k
  -> 工具从 ToolRuntime 读取 knowledge_base_ids
  -> 映射为 Milvus Collection 并执行 Hybrid 检索和可选 Rerank
  -> Command 写入 retrieval_context
  -> InjectRetrievalContextMiddleware 按 run_id 注入检索证据
```

## 5. 工具参数

模型能看到的参数只有：

```json
{
  "query": "用户要查询的问题",
  "top_k": 5
}
```

`ToolRuntime`、`knowledge_base_ids`、`run_id` 都由 LangGraph 和平台自动注入，
模型无法修改访问白名单。

## 6. 中断与 A2A

- Agent 中断时，运行记录会保存 `knowledge` 配置；恢复后继续使用原来的白名单。
- A2A 子 Agent 只能继承父运行已经授权的知识库 ID，不能扩大访问范围。
- 子 Agent 模板同样必须开启 `knowledge_enabled`，否则不会装配检索工具。

## 7. 前端职责

1. Agent 模板编辑页只展示“挂载知识库”能力开关。
2. Agent 调用页和 Playground 在模板开启能力时展示知识库多选框。
3. 前端把选择结果放入 `knowledge.knowledge_base_ids`，不写入 `optional_features`。
4. 内部检索工具不出现在工具管理页或模板 MCP 工具列表中。
