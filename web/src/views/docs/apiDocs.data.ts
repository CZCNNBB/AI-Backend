/**
 * Agent 平台接口文档数据
 * - 字段与路径对齐当前后端真实路由，path 包含完整模块前缀
 * - 后续 Agent 平台接口新增 / 调整时,同步更新本文件即可
 */
import type { Component } from 'vue'
import {
  ApiOutlined,
  ThunderboltOutlined,
  RobotOutlined,
  HistoryOutlined,
  MonitorOutlined,
  ToolOutlined,
  DatabaseOutlined,
  ApartmentOutlined,
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
  /** 接口路径，包含 /agent、/platform 或 /fastmcp 等完整模块前缀 */
  path: string
  /** 接口名 / 标题 */
  name: string
  /** 一句话说明 */
  summary: string
  /** HTTP 请求头；身份凭证必须与 JSON 请求体分开说明 */
  headers?: FieldDoc[]
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

/** 会话和运行查询接口共用的平台身份请求头。 */
const platformIdentityHeaders: FieldDoc[] = [
  { name: 'X-API-Key', type: 'string', required: true, description: '识别调用方业务平台的 API Key' },
  { name: 'Content-Type', type: 'string', required: true, description: '固定为 application/json' },
]

/** 接口分组顺序 */
export const apiDocs: ApiDoc[] = [
  // ================== 业务平台管理 ==================
  {
    group: '业务平台管理',
    groupIcon: ApartmentOutlined,
    method: 'POST',
    path: '/platform/platforms/upsert',
    name: '创建或更新业务平台',
    summary: '公司内网管理接口，用于登记接入 AI-backend 的业务系统。',
    requestFields: [
      { name: 'platform_code', type: 'string', required: true, description: '稳定且唯一的平台编码；更新时不能随意改变' },
      { name: 'platform_name', type: 'string', required: true, description: '业务平台展示名称' },
      { name: 'description', type: 'string', description: '平台用途说明' },
      { name: 'status', type: 'enabled | disabled', required: true, description: '平台状态' },
    ],
    responseFields: [
      { name: 'id', type: 'number', description: '业务平台数据库主键' },
      { name: 'platform_code', type: 'string', description: '平台编码' },
      { name: 'platform_name', type: 'string', description: '平台名称' },
      { name: 'status', type: 'string', description: '平台状态' },
    ],
    requestExample: `{
  "platform_code": "order_system",
  "platform_name": "订单业务系统",
  "description": "订单域 Agent 接入",
  "status": "enabled"
}`,
    notes: ['管理接口当前仅供公司内网管理端调用，不要求业务平台携带自己的 X-API-Key。'],
  },
  {
    group: '业务平台管理',
    groupIcon: ApartmentOutlined,
    method: 'POST',
    path: '/platform/platforms/search',
    name: '查询业务平台列表',
    summary: '分页查询已经登记的业务平台。',
    requestFields: [
      { name: 'keyword', type: 'string', description: '匹配平台编码、名称和说明' },
      { name: 'status', type: 'enabled | disabled', description: '状态过滤' },
      { name: 'page', type: 'number', description: '页码，默认 1' },
      { name: 'page_size', type: 'number', description: '每页数量，最大 100' },
    ],
    responseFields: [
      { name: 'total', type: 'number', description: '总数量' },
      { name: 'items', type: 'object[]', description: '业务平台列表' },
    ],
    requestExample: `{ "page": 1, "page_size": 100 }`,
  },
  {
    group: '业务平台管理',
    groupIcon: ApartmentOutlined,
    method: 'POST',
    path: '/platform/platforms/api-keys/create',
    name: '签发平台 API Key',
    summary: '为指定业务平台签发一个调用 AI-backend 的 API Key。',
    requestFields: [
      { name: 'platform_code', type: 'string', required: true, description: '业务平台编码' },
      { name: 'key_name', type: 'string', required: true, description: 'Key 用途名称，例如 production' },
      { name: 'expires_at', type: 'string', description: '可选 ISO8601 过期时间；不传表示长期有效' },
    ],
    responseFields: [
      { name: 'id', type: 'number', description: 'API Key 记录 ID' },
      { name: 'key_prefix', type: 'string', description: '用于辨识 Key 的安全前缀' },
      { name: 'api_key', type: 'string', description: '完整 API Key；请勿写入日志或放到业务前端' },
    ],
    requestExample: `{ "platform_code": "order_system", "key_name": "production" }`,
    notes: ['当前公司内网 MVP 会保存完整明文，管理页面可以再次查看和复制。鉴权时仍使用 SHA-256 Hash。'],
  },
  {
    group: '业务平台管理',
    groupIcon: ApartmentOutlined,
    method: 'POST',
    path: '/platform/platforms/api-keys/list',
    name: '查看平台 API Key',
    summary: '查询指定平台已经签发的 API Key，供公司内网管理页面查看、复制和停用。',
    requestFields: [
      { name: 'platform_code', type: 'string', required: true, description: '业务平台编码' },
    ],
    responseFields: [
      { name: 'id', type: 'number', description: 'API Key 记录 ID' },
      { name: 'key_name', type: 'string', description: 'Key 用途名称' },
      { name: 'api_key', type: 'string', description: '完整明文 API Key' },
      { name: 'status', type: 'enabled | disabled', description: 'Key 状态' },
      { name: 'expires_at', type: 'string', description: '可选过期时间' },
    ],
    requestExample: `{ "platform_code": "order_system" }`,
  },
  {
    group: '业务平台管理',
    groupIcon: ApartmentOutlined,
    method: 'POST',
    path: '/platform/platforms/api-keys/disable',
    name: '停用平台 API Key',
    summary: '立即停用指定 API Key；使用该 Key 的后续请求将无法通过平台认证。',
    requestFields: [
      { name: 'api_key_id', type: 'number', required: true, description: '待停用的 API Key 记录 ID' },
    ],
    responseFields: [
      { name: '(boolean)', type: 'boolean', description: '是否停用成功' },
    ],
    requestExample: `{ "api_key_id": 1 }`,
  },

  // ================== 平台基础 ==================
  {
    group: '平台基础',
    groupIcon: ApiOutlined,
    method: 'GET',
    path: '/agent/health',
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
    path: '/agent/model/config',
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
    path: '/agent/capabilities',
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
    path: '/agent/messages',
    name: '发送 Agent 消息',
    summary: '外部业务平台统一的 Agent 调用入口；stream=false 返回 JSON，stream=true 返回 SSE。',
    headers: [
      { name: 'X-API-Key', type: 'string', required: true, description: '识别调用方业务平台的 API Key' },
      { name: 'X-Business-Authorization', type: 'string', description: '可选，按 MCP Tool 的 business_token_header 配置原样透传给目标业务 API' },
      { name: 'Content-Type', type: 'string', required: true, description: '固定为 application/json' },
    ],
    requestFields: [
      { name: 'agent_id', type: 'string', required: true, description: 'Agent 模板的稳定业务 ID' },
      { name: 'external_user_id', type: 'string', required: true, description: '业务平台中的稳定用户 ID，用于隔离会话、消息和运行记录' },
      { name: 'conversation_id', type: 'string', description: '会话 ID；为空时会自动创建' },
      { name: 'message', type: 'string', required: true, description: '用户本次发送的文本' },
      { name: 'message_type', type: 'string', description: '消息类型，默认 text' },
      { name: 'stream', type: 'boolean', description: '是否走 SSE 流式输出，默认 true', example: true },
      { name: 'payload', type: 'object', description: '表单、按钮等结构化消息负载' },
      { name: 'inputs', type: 'object', description: '注入 Agent runtime 和 MCP runtime 参数的业务变量' },
      { name: 'file_ids', type: 'string[]', description: '通过 /file/upload 获得的附件 ID' },
      { name: 'runtime_options', type: 'object', description: '模型、温度、超时和重试配置' },
    ],
    responseFields: [
      { name: 'run_id', type: 'string', description: '本次运行 ID；流式模式在 run_start 事件中返回' },
      { name: 'conversation_id', type: 'string', description: '会话 ID；后续对话应继续携带' },
      { name: 'output / content', type: 'string | object', description: '非流式最终输出，或流式 model_delta 内容' },
    ],
    requestExample: `{
  "agent_id": "order-agent",
  "external_user_id": "user_10086",
  "conversation_id": null,
  "message": "帮我查询最近的订单",
  "message_type": "text",
  "stream": true,
  "payload": {},
  "inputs": {},
  "file_ids": [],
  "runtime_options": {
    "model_code": "chat_main",
    "temperature": 0.2,
    "timeout_seconds": 600,
    "max_retries": 2
  }
}`,
    responseExample: `data: {"type":"run_start","data":{"run_id":"run_xxx","conversation_id":"conv_xxx"}}

data: {"type":"model_delta","data":{"content":"查询结果"}}

data: {"type":"run_end","data":{"status":"succeeded"}}`,
    notes: [
      'stream=true 时响应为 text/event-stream；常见事件包括 run_start、reasoning_delta、model_delta、tool_call、run_end 和 error。',
      '相同 X-API-Key 下，external_user_id 必须使用业务系统中的稳定用户标识。',
      '首次请求 conversation_id 传 null；收到新会话 ID 后，继续对话时原样回传。',
    ],
  },

  // ================== Agent 模板 ==================
  {
    group: 'Agent 模板',
    groupIcon: RobotOutlined,
    method: 'POST',
    path: '/agent/templates/upsert',
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
    path: '/agent/templates/detail',
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
    path: '/agent/templates/search',
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
    path: '/agent/templates/delete',
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
    path: '/agent/runs/search',
    name: '查询 Agent 运行记录列表',
    summary: '在当前业务平台和指定外部用户范围内分页查询 Agent 运行记录。',
    headers: platformIdentityHeaders,
    requestFields: [
      { name: 'external_user_id', type: 'string', required: true, description: '外部业务用户 ID' },
      { name: 'run_id', type: 'string', description: '按运行 ID 精确匹配' },
      { name: 'run_type', type: 'main | sub', description: '主 Agent 或 A2A 子 Agent' },
      { name: 'parent_run_id', type: 'string', description: '按父运行 ID 查询子运行' },
      { name: 'agent_id', type: 'string', description: '按 Agent 模板 ID 过滤' },
      { name: 'conversation_id', type: 'string', description: '按会话 ID 过滤' },
      { name: 'status', type: 'string', description: '运行状态过滤' },
      { name: 'page', type: 'number', description: '页码', example: 1 },
      { name: 'page_size', type: 'number', description: '每页数量', example: 20 },
    ],
    responseFields: [
      { name: 'total', type: 'number', description: '总数量' },
      { name: 'items', type: 'object[]', description: '运行记录列表' },
    ],
    requestExample: `{ "external_user_id": "user_10086", "agent_id": "order-agent", "page": 1, "page_size": 20 }`,
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
    path: '/agent/runs/detail',
    name: '查询 Agent 运行记录详情',
    summary: '根据 run_id 查询单条运行记录详情。',
    headers: platformIdentityHeaders,
    requestFields: [
      { name: 'run_id', type: 'string', required: true, description: '运行记录 ID' },
      { name: 'external_user_id', type: 'string', required: true, description: '外部业务用户 ID' },
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
    requestExample: `{ "run_id": "run_20260626_0001", "external_user_id": "user_10086" }`,
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
    path: '/agent/runs/chain',
    name: '查询 Agent 主子运行链路',
    summary: '查询某次主 Agent 运行及其触发的子 Agent 运行链路。',
    headers: platformIdentityHeaders,
    requestFields: [
      { name: 'run_id', type: 'string', required: true, description: '主 Agent 运行 ID' },
      { name: 'external_user_id', type: 'string', required: true, description: '外部业务用户 ID' },
    ],
    responseFields: [
      { name: 'run_id', type: 'string', description: '主运行 ID' },
      { name: 'items', type: 'object[]', description: '主运行 + 全部子运行记录' },
    ],
    requestExample: `{ "run_id": "run_20260626_0001", "external_user_id": "user_10086" }`,
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
    path: '/agent/conversations/search',
    name: '查询 Agent 会话列表',
    summary: '在当前业务平台和指定外部用户范围内分页查询 Agent 会话。',
    headers: platformIdentityHeaders,
    requestFields: [
      { name: 'external_user_id', type: 'string', required: true, description: '外部业务用户 ID' },
      { name: 'agent_id', type: 'string', description: '可选 Agent ID；不传时返回该用户在当前平台的全部会话' },
      { name: 'conversation_id', type: 'string', description: '可选，会话 ID 精确匹配' },
      { name: 'page', type: 'number', description: '页码', example: 1 },
      { name: 'page_size', type: 'number', description: '每页数量', example: 20 },
    ],
    responseFields: [
      { name: 'total', type: 'number', description: '总数量' },
      { name: 'items', type: 'object[]', description: '会话列表；每项包含 conversation_id、agent_id、标题和更新时间' },
    ],
    requestExample: `{ "external_user_id": "user_10086", "agent_id": "order-agent", "page": 1, "page_size": 20 }`,
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
    path: '/agent/conversations/messages',
    name: '查询 Agent 会话消息',
    summary: '查询当前业务平台、指定外部用户的某个会话消息，最多返回 200 条。',
    headers: platformIdentityHeaders,
    requestFields: [
      { name: 'external_user_id', type: 'string', required: true, description: '外部业务用户 ID' },
      { name: 'conversation_id', type: 'string', required: true, description: '会话 ID' },
      { name: 'limit', type: 'number', description: '返回消息数量上限', example: 200 },
    ],
    responseFields: [
      { name: 'conversation_id', type: 'string', description: '会话 ID' },
      { name: 'messages', type: 'object[]', description: '消息列表' },
    ],
    requestExample: `{ "external_user_id": "user_10086", "conversation_id": "conv_20260626_0001", "limit": 200 }`,
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
    path: '/agent/models/upsert',
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
    path: '/agent/models/detail',
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
    path: '/agent/models/search',
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
    path: '/agent/models/delete',
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
    path: '/agent/tools/invoke',
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
