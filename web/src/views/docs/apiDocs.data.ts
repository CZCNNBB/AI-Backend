/**
 * Agent 平台接口文档数据
 * - 字段与路径完全对齐后端 /agent/* 接口
 * - 后续 Agent 平台接口新增 / 调整时,同步更新本文件即可
 */
import type { Component } from 'vue'
import {
  ApiOutlined,
  ThunderboltOutlined,
  AppstoreOutlined,
  RobotOutlined,
  HistoryOutlined,
  MonitorOutlined,
  ToolOutlined,
  DatabaseOutlined,
  ApartmentOutlined,
  PlayCircleOutlined,
} from '@ant-design/icons-vue'

/** 单个请求/响应字段描述 */
export interface FieldDoc {
  name: string
  type: string
  required?: boolean
  description: string
  /** 示例值（用于 JSON 示例展示） */
  example?: string | number | boolean | null | Record<string, unknown> | unknown[]
}

/** 单个接口文档 */
export interface ApiDoc {
  /** 分组标题 */
  group: string
  /** 分组图标 */
  groupIcon: Component
  /** 接口方法 */
  method: 'GET' | 'POST' | 'PUT' | 'DELETE' | 'PATCH'
  /** 接口路径（不包含 /agent 前缀） */
  path: string
  /** 接口名 / 标题 */
  name: string
  /** 一句话说明 */
  summary: string
  /** 请求体字段列表；GET 或无请求体时为空数组 */
  requestFields: FieldDoc[]
  /** 响应体字段列表（data 内部） */
  responseFields: FieldDoc[]
  /** 请求 JSON 示例 */
  requestExample?: string
  /** 响应 JSON 示例 */
  responseExample?: string
  /** 备注 / 补充说明 */
  notes?: string[]
}

/** 接口分组顺序 */
export const apiDocs: ApiDoc[] = [
  // ================== 平台基础 ==================
  {
    group: '平台基础',
    groupIcon: ApiOutlined,
    method: 'GET',
    path: '/health',
    name: 'Agent 服务健康检查',
    summary: '检查 Agent 服务是否已经挂载，常用于监控探活。',
    requestFields: [],
    responseFields: [
      { name: 'service', type: 'string', description: '服务标识，固定为 agent' },
      { name: 'status', type: 'string', description: '状态，ok 表示正常' },
    ],
    responseExample: `{
  "code": 0,
  "msg": "success",
  "data": { "service": "agent", "status": "ok" }
}`,
  },
  {
    group: '平台基础',
    groupIcon: ApiOutlined,
    method: 'GET',
    path: '/model/config',
    name: '查询模型资源池摘要',
    summary: '返回当前平台已配置的可用模型 / Chat / Embedding / Rerank 模型列表。',
    requestFields: [],
    responseFields: [
      { name: 'available_models', type: 'string[]', description: '全部可用模型 code 列表' },
      { name: 'chat_models', type: 'string[]', description: '聊天类模型 code 列表' },
      { name: 'embedding_models', type: 'string[]', description: '向量类模型 code 列表' },
      { name: 'rerank_models', type: 'string[]', description: '重排类模型 code 列表' },
    ],
    responseExample: `{
  "code": 0,
  "msg": "success",
  "data": {
    "available_models": ["gpt-4o-mini", "text-embedding-3-small"],
    "chat_models": ["gpt-4o-mini"],
    "embedding_models": ["text-embedding-3-small"],
    "rerank_models": []
  }
}`,
  },
  {
    group: '平台基础',
    groupIcon: ApiOutlined,
    method: 'GET',
    path: '/capabilities',
    name: '查询 Agent 服务能力',
    summary: '返回 Agent 服务当前已挂载的模块、特性与已注册工具。',
    requestFields: [],
    responseFields: [
      { name: 'service_name', type: 'string', description: '服务名' },
      { name: 'modules', type: 'string[]', description: '已挂载的子模块' },
      { name: 'enabled_features', type: 'string[]', description: '已启用的能力标识' },
      { name: 'registered_tools', type: 'string[]', description: '已注册工具名列表' },
      { name: 'tools', type: 'object[]', description: '已注册工具的详细信息' },
    ],
    responseExample: `{
  "code": 0,
  "msg": "success",
  "data": {
    "service_name": "agent",
    "modules": ["agent", "model", "tools", "templates", "runtime"],
    "enabled_features": ["openai_compatible_chat_model", "agent_template_management"],
    "registered_tools": ["http_get", "http_post"]
  }
}`,
  },

  // ================== Agent 运行 ==================
  {
    group: 'Agent 运行',
    groupIcon: ThunderboltOutlined,
    method: 'POST',
    path: '/run',
    name: '运行通用 Agent',
    summary: '根据 agent_id 运行一次 Agent；stream=false 返回 JSON，stream=true 返回 SSE。',
    requestFields: [
      { name: 'agent_id', type: 'string', required: true, description: 'Agent 模板的稳定业务 ID' },
      { name: 'input', type: 'string | object', required: true, description: '用户输入，可以是字符串或多模态对象' },
      { name: 'conversation_id', type: 'string', description: '会话 ID；为空时会自动创建' },
      { name: 'stream', type: 'boolean', description: '是否走 SSE 流式输出', example: false },
      { name: 'override_config', type: 'object', description: '运行级别覆盖配置（tools、system_prompt 等）' },
    ],
    responseFields: [
      { name: 'run_id', type: 'string', description: '本次运行的唯一 ID' },
      { name: 'conversation_id', type: 'string', description: '关联的会话 ID' },
      { name: 'agent_id', type: 'string', description: '运行的 Agent 模板 ID' },
      { name: 'output', type: 'string | object', description: 'Agent 最终输出' },
      { name: 'messages', type: 'object[]', description: '本轮新增的消息列表' },
      { name: 'elapsed_ms', type: 'number', description: '总耗时（毫秒）' },
    ],
    requestExample: `{
  "agent_id": "demo_agent",
  "input": "你好,帮我介绍一下自己",
  "conversation_id": null,
  "stream": false
}`,
    responseExample: `{
  "code": 0,
  "msg": "success",
  "data": {
    "run_id": "run_20260626_0001",
    "conversation_id": "conv_20260626_0001",
    "agent_id": "demo_agent",
    "output": "你好!我是 demo_agent ...",
    "messages": [],
    "elapsed_ms": 1234
  }
}`,
    notes: [
      '当 stream=true 时，HTTP 响应为 text/event-stream，每个 SSE 事件包含 type 与 payload。',
    ],
  },

  // ================== Agent 模板 ==================
  {
    group: 'Agent 模板',
    groupIcon: RobotOutlined,
    method: 'POST',
    path: '/templates/upsert',
    name: '创建或更新 Agent 模板',
    summary: '按 agent_id 创建或更新一个 Agent 模板。',
    requestFields: [
      { name: 'agent_id', type: 'string', required: true, description: 'Agent 稳定业务 ID（1~100 字符）' },
      { name: 'agent_name', type: 'string', required: true, description: 'Agent 展示名称（1~255 字符）' },
      { name: 'description', type: 'string', description: '模板描述' },
      { name: 'status', type: 'string', description: '状态：active / disabled', example: 'active' },
      { name: 'config.system_prompt', type: 'string', description: '默认系统提示词' },
      { name: 'config.tools', type: 'string[]', description: '默认可用工具名列表' },
      { name: 'config.is_sub_agent', type: 'boolean', description: '是否可被其他 Agent A2A 调用' },
      { name: 'config.runtime_options', type: 'object', description: '模型运行参数（temperature、max_tokens 等）' },
    ],
    responseFields: [
      { name: 'agent_id', type: 'string', description: 'Agent 稳定业务 ID' },
      { name: 'agent_name', type: 'string', description: 'Agent 展示名称' },
      { name: 'description', type: 'string', description: '模板描述' },
      { name: 'config', type: 'object', description: '模板配置' },
      { name: 'status', type: 'string', description: '模板状态' },
      { name: 'created_at', type: 'string', description: '创建时间（ISO8601）' },
      { name: 'updated_at', type: 'string', description: '更新时间（ISO8601）' },
    ],
    requestExample: `{
  "agent_id": "demo_agent",
  "agent_name": "演示 Agent",
  "description": "用于演示的 Agent 模板",
  "status": "active",
  "config": {
    "system_prompt": "你是一个乐于助人的助手",
    "tools": ["http_get"],
    "is_sub_agent": false
  }
}`,
    responseExample: `{
  "code": 0,
  "msg": "success",
  "data": {
    "agent_id": "demo_agent",
    "agent_name": "演示 Agent",
    "status": "active",
    "created_at": "2026-06-26T10:00:00",
    "updated_at": "2026-06-26T10:00:00"
  }
}`,
  },
  {
    group: 'Agent 模板',
    groupIcon: RobotOutlined,
    method: 'POST',
    path: '/templates/detail',
    name: '查询 Agent 模板详情',
    summary: '根据 agent_id 查询单个 Agent 模板详情，不存在时 data 为 null。',
    requestFields: [
      { name: 'agent_id', type: 'string', required: true, description: 'Agent 稳定业务 ID' },
    ],
    responseFields: [
      { name: 'agent_id', type: 'string', description: 'Agent 稳定业务 ID' },
      { name: 'agent_name', type: 'string', description: 'Agent 展示名称' },
      { name: 'config', type: 'object', description: '模板配置' },
      { name: 'status', type: 'string', description: '模板状态' },
    ],
    requestExample: `{ "agent_id": "demo_agent" }`,
    responseExample: `{
  "code": 0,
  "msg": "success",
  "data": {
    "agent_id": "demo_agent",
    "agent_name": "演示 Agent",
    "status": "active"
  }
}`,
  },
  {
    group: 'Agent 模板',
    groupIcon: RobotOutlined,
    method: 'POST',
    path: '/templates/search',
    name: '查询 Agent 模板列表',
    summary: '分页查询 Agent 模板列表，支持关键字与状态筛选。',
    requestFields: [
      { name: 'keyword', type: 'string', description: '关键字，匹配 agent_id / agent_name / description' },
      { name: 'status', type: 'string', description: '状态：active / disabled' },
      { name: 'page', type: 'number', description: '页码，从 1 开始', example: 1 },
      { name: 'page_size', type: 'number', description: '每页数量，1~100', example: 20 },
    ],
    responseFields: [
      { name: 'total', type: 'number', description: '总数量' },
      { name: 'page', type: 'number', description: '当前页码' },
      { name: 'page_size', type: 'number', description: '每页数量' },
      { name: 'items', type: 'object[]', description: '模板列表' },
    ],
    requestExample: `{ "keyword": "demo", "page": 1, "page_size": 20 }`,
    responseExample: `{
  "code": 0,
  "msg": "success",
  "data": {
    "total": 1,
    "page": 1,
    "page_size": 20,
    "items": [{ "agent_id": "demo_agent", "agent_name": "演示 Agent" }]
  }
}`,
  },
  {
    group: 'Agent 模板',
    groupIcon: RobotOutlined,
    method: 'POST',
    path: '/templates/delete',
    name: '批量删除 Agent 模板',
    summary: '根据 agent_ids 列表批量删除 Agent 模板。',
    requestFields: [
      { name: 'agent_ids', type: 'string[]', required: true, description: '待删除的 agent_id 列表，至少 1 个' },
    ],
    responseFields: [
      { name: '(int)', type: 'number', description: '实际删除的条数' },
    ],
    requestExample: `{ "agent_ids": ["demo_agent", "test_agent"] }`,
    responseExample: `{
  "code": 0,
  "msg": "success",
  "data": 2
}`,
    notes: ['遵循项目硬约束：批量删除使用 POST + 请求体 ID 列表。'],
  },

  // ================== 运行记录 ==================
  {
    group: '运行记录',
    groupIcon: MonitorOutlined,
    method: 'POST',
    path: '/runs/search',
    name: '查询 Agent 运行记录列表',
    summary: '分页查询 Agent 运行记录，支持按 agent_id / 状态 / 时间筛选。',
    requestFields: [
      { name: 'agent_id', type: 'string', description: '按 Agent 模板 ID 过滤' },
      { name: 'status', type: 'string', description: '运行状态过滤' },
      { name: 'keyword', type: 'string', description: '关键字过滤' },
      { name: 'start_time', type: 'string', description: '起始时间（ISO8601）' },
      { name: 'end_time', type: 'string', description: '结束时间（ISO8601）' },
      { name: 'page', type: 'number', description: '页码', example: 1 },
      { name: 'page_size', type: 'number', description: '每页数量', example: 20 },
    ],
    responseFields: [
      { name: 'total', type: 'number', description: '总数量' },
      { name: 'items', type: 'object[]', description: '运行记录列表' },
    ],
    requestExample: `{ "agent_id": "demo_agent", "page": 1, "page_size": 20 }`,
    responseExample: `{
  "code": 0,
  "msg": "success",
  "data": { "total": 0, "items": [] }
}`,
  },
  {
    group: '运行记录',
    groupIcon: MonitorOutlined,
    method: 'POST',
    path: '/runs/detail',
    name: '查询 Agent 运行记录详情',
    summary: '根据 run_id 查询单条运行记录详情。',
    requestFields: [
      { name: 'run_id', type: 'string', required: true, description: '运行记录 ID' },
    ],
    responseFields: [
      { name: 'run_id', type: 'string', description: '运行记录 ID' },
      { name: 'agent_id', type: 'string', description: '关联 Agent ID' },
      { name: 'status', type: 'string', description: '运行状态' },
      { name: 'input', type: 'string', description: '用户输入' },
      { name: 'output', type: 'string', description: 'Agent 输出' },
      { name: 'elapsed_ms', type: 'number', description: '耗时（毫秒）' },
      { name: 'started_at', type: 'string', description: '开始时间' },
      { name: 'ended_at', type: 'string', description: '结束时间' },
    ],
    requestExample: `{ "run_id": "run_20260626_0001" }`,
    responseExample: `{
  "code": 0,
  "msg": "success",
  "data": {
    "run_id": "run_20260626_0001",
    "agent_id": "demo_agent",
    "status": "success",
    "elapsed_ms": 1234
  }
}`,
  },
  {
    group: '运行记录',
    groupIcon: ApartmentOutlined,
    method: 'POST',
    path: '/runs/chain',
    name: '查询 Agent 主子运行链路',
    summary: '查询某次主 Agent 运行及其触发的子 Agent 运行链路。',
    requestFields: [
      { name: 'run_id', type: 'string', required: true, description: '主 Agent 运行 ID' },
    ],
    responseFields: [
      { name: 'run_id', type: 'string', description: '主运行 ID' },
      { name: 'items', type: 'object[]', description: '主运行 + 全部子运行记录' },
    ],
    requestExample: `{ "run_id": "run_20260626_0001" }`,
    responseExample: `{
  "code": 0,
  "msg": "success",
  "data": {
    "run_id": "run_20260626_0001",
    "items": []
  }
}`,
  },

  // ================== 会话 ==================
  {
    group: '会话',
    groupIcon: HistoryOutlined,
    method: 'POST',
    path: '/conversations/search',
    name: '查询 Agent 会话列表',
    summary: '分页查询 Agent 会话列表。',
    requestFields: [
      { name: 'agent_id', type: 'string', description: '按 Agent 模板 ID 过滤' },
      { name: 'keyword', type: 'string', description: '关键字过滤' },
      { name: 'page', type: 'number', description: '页码', example: 1 },
      { name: 'page_size', type: 'number', description: '每页数量', example: 20 },
    ],
    responseFields: [
      { name: 'total', type: 'number', description: '总数量' },
      { name: 'items', type: 'object[]', description: '会话列表' },
    ],
    requestExample: `{ "page": 1, "page_size": 20 }`,
    responseExample: `{
  "code": 0,
  "msg": "success",
  "data": { "total": 0, "items": [] }
}`,
  },
  {
    group: '会话',
    groupIcon: HistoryOutlined,
    method: 'POST',
    path: '/conversations/messages',
    name: '查询 Agent 会话消息',
    summary: '查询某个会话的消息列表，最多返回 200 条。',
    requestFields: [
      { name: 'conversation_id', type: 'string', required: true, description: '会话 ID' },
      { name: 'limit', type: 'number', description: '返回消息数量上限', example: 200 },
    ],
    responseFields: [
      { name: 'conversation_id', type: 'string', description: '会话 ID' },
      { name: 'messages', type: 'object[]', description: '消息列表' },
    ],
    requestExample: `{ "conversation_id": "conv_20260626_0001", "limit": 200 }`,
    responseExample: `{
  "code": 0,
  "msg": "success",
  "data": { "conversation_id": "conv_20260626_0001", "messages": [] }
}`,
    notes: ['会话历史检索上限为 200 条。'],
  },

  // ================== 模型配置 ==================
  {
    group: '模型配置',
    groupIcon: DatabaseOutlined,
    method: 'POST',
    path: '/models/upsert',
    name: '新增或更新模型配置',
    summary: '按 model_code 新增或更新一个模型配置。',
    requestFields: [
      { name: 'model_code', type: 'string', required: true, description: '模型唯一编码' },
      { name: 'model_name', type: 'string', required: true, description: '模型展示名' },
      { name: 'model_type', type: 'string', required: true, description: '模型类型：chat / embedding / rerank' },
      { name: 'provider', type: 'string', description: '模型提供方' },
      { name: 'enabled', type: 'boolean', description: '是否启用', example: true },
    ],
    responseFields: [
      { name: 'model_code', type: 'string', description: '模型编码' },
      { name: 'model_name', type: 'string', description: '模型名称' },
      { name: 'model_type', type: 'string', description: '模型类型' },
    ],
    requestExample: `{
  "model_code": "gpt-4o-mini",
  "model_name": "GPT-4o mini",
  "model_type": "chat",
  "enabled": true
}`,
    responseExample: `{
  "code": 0,
  "msg": "success",
  "data": { "model_code": "gpt-4o-mini", "model_name": "GPT-4o mini" }
}`,
  },
  {
    group: '模型配置',
    groupIcon: DatabaseOutlined,
    method: 'POST',
    path: '/models/detail',
    name: '查询模型配置详情',
    summary: '根据 model_code 查询模型配置详情。',
    requestFields: [
      { name: 'model_code', type: 'string', required: true, description: '模型编码' },
    ],
    responseFields: [
      { name: 'model_code', type: 'string', description: '模型编码' },
      { name: 'model_name', type: 'string', description: '模型名称' },
    ],
    requestExample: `{ "model_code": "gpt-4o-mini" }`,
    responseExample: `{
  "code": 0,
  "msg": "success",
  "data": { "model_code": "gpt-4o-mini" }
}`,
  },
  {
    group: '模型配置',
    groupIcon: DatabaseOutlined,
    method: 'POST',
    path: '/models/search',
    name: '查询模型配置列表',
    summary: '分页查询模型配置列表。',
    requestFields: [
      { name: 'keyword', type: 'string', description: '关键字过滤' },
      { name: 'model_type', type: 'string', description: '按类型过滤' },
      { name: 'enabled', type: 'boolean', description: '按启用状态过滤' },
      { name: 'page', type: 'number', description: '页码', example: 1 },
      { name: 'page_size', type: 'number', description: '每页数量', example: 20 },
    ],
    responseFields: [
      { name: 'total', type: 'number', description: '总数量' },
      { name: 'items', type: 'object[]', description: '模型配置列表' },
    ],
    requestExample: `{ "page": 1, "page_size": 20 }`,
    responseExample: `{
  "code": 0,
  "msg": "success",
  "data": { "total": 0, "items": [] }
}`,
  },
  {
    group: '模型配置',
    groupIcon: DatabaseOutlined,
    method: 'POST',
    path: '/models/delete',
    name: '批量删除模型配置',
    summary: '根据 model_codes 列表批量删除模型配置。',
    requestFields: [
      { name: 'model_codes', type: 'string[]', required: true, description: '待删除的 model_code 列表' },
    ],
    responseFields: [
      { name: '(int)', type: 'number', description: '实际删除条数' },
    ],
    requestExample: `{ "model_codes": ["gpt-4o-mini"] }`,
    responseExample: `{
  "code": 0,
  "msg": "success",
  "data": 1
}`,
  },

  // ================== 工具 ==================
  {
    group: '工具',
    groupIcon: ToolOutlined,
    method: 'POST',
    path: '/tools/invoke',
    name: '调试调用 Agent 工具',
    summary: '调试调用一个已注册的常规 Agent 工具，常用于工具自测。',
    requestFields: [
      { name: 'tool_name', type: 'string', required: true, description: '工具名（已注册）' },
      { name: 'args', type: 'object', description: '工具调用参数', example: { url: 'https://example.com' } },
    ],
    responseFields: [
      { name: 'tool_name', type: 'string', description: '工具名' },
      { name: 'args', type: 'object', description: '入参（已 JSON 化）' },
      { name: 'result', type: 'object', description: '工具执行结果' },
    ],
    requestExample: `{
  "tool_name": "http_get",
  "args": { "url": "https://example.com" }
}`,
    responseExample: `{
  "code": 0,
  "msg": "success",
  "data": {
    "tool_name": "http_get",
    "args": { "url": "https://example.com" },
    "result": { "status": 200, "body": "ok" }
  }
}`,
  },

  // ================== Playground ==================
  {
    group: 'Playground',
    groupIcon: PlayCircleOutlined,
    method: 'GET',
    path: '/agents/:agent_id/playground',
    name: 'Agent Playground 试跑台',
    summary: '前端页面：在线选择模板、输入问题、查看运行结果与会话上下文。',
    requestFields: [],
    responseFields: [
      { name: '(页面)', type: '-', description: '前端路由，无后端接口' },
    ],
    notes: ['该入口为前端页面，不是后端 HTTP 接口。'],
  },
  {
    group: 'Playground',
    groupIcon: AppstoreOutlined,
    method: 'GET',
    path: '/agents',
    name: 'Agent 模板管理列表',
    summary: '前端页面：分页、关键字、状态筛选；支持编辑 / 试跑 / 克隆 / 删除。',
    requestFields: [],
    responseFields: [
      { name: '(页面)', type: '-', description: '前端路由，无后端接口' },
    ],
    notes: ['该入口为前端页面，不是后端 HTTP 接口。'],
  },
]

/** 把接口按 group 分组,便于页面渲染 */
export function groupApiDocs(docs: ApiDoc[] = apiDocs): { group: string; icon: Component; items: ApiDoc[] }[] {
  const map = new Map<string, { group: string; icon: Component; items: ApiDoc[] }>()
  for (const doc of docs) {
    if (!map.has(doc.group)) {
      map.set(doc.group, { group: doc.group, icon: doc.groupIcon, items: [] })
    }
    map.get(doc.group)!.items.push(doc)
  }
  return Array.from(map.values())
}

/** HTTP method 到 ant design Tag 颜色的映射 */
export const methodColorMap: Record<ApiDoc['method'], string> = {
  GET: 'green',
  POST: 'blue',
  PUT: 'orange',
  DELETE: 'red',
  PATCH: 'purple',
}

/** 后端 baseURL（用于组装完整 URL 提示） */
export const apiBaseUrl = (import.meta.env.VITE_API_BASE as string) || '/api'
