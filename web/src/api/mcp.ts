/**
 * HTTP API 转 MCP Tool 的平台管理接口。
 */
import { httpPost } from './http'
import type { AgentToolInfo } from './capabilities'

export type McpParameterLocation = 'path' | 'query' | 'header' | 'body'
export type McpParameterSource = 'tool' | 'runtime' | 'static'
export type McpParameterType = 'string' | 'integer' | 'number' | 'boolean' | 'object' | 'array'

/** 单个 API 参数映射。 */
export interface McpToolParameter {
  name: string
  target?: string | null
  location: McpParameterLocation
  source: McpParameterSource
  data_type: McpParameterType
  required: boolean
  description?: string | null
  default?: any
  value?: any
  runtime_path?: string | null
  item_schema?: Record<string, any> | null
}

/** 新增或更新 HTTP API 转换型 MCP Tool 的请求。 */
export interface McpToolUpsertRequest {
  name: string
  description?: string | null
  api_url: string
  http_method: 'GET' | 'POST' | 'PUT' | 'PATCH' | 'DELETE'
  static_headers: Record<string, unknown>
  parameters: McpToolParameter[]
  auth_type: 'none' | 'bearer' | 'basic' | 'api_key'
  auth_config: Record<string, unknown>
  output_schema?: Record<string, any> | null
  timeout_seconds: number
  status: 'draft' | 'enabled' | 'disabled'
}

/** MCP Tool 管理视图。 */
export interface McpToolView extends McpToolUpsertRequest {
  id?: number | null
  input_schema: Record<string, any>
  created_at?: string | null
  updated_at?: string | null
}

/** MCP Tool 分页搜索响应。 */
export interface McpToolSearchResponse {
  total: number
  page: number
  page_size: number
  items: McpToolView[]
}

/** 目标 API 测试响应。 */
export interface McpToolTestResponse {
  ok: boolean
  status_code?: number | null
  elapsed_ms?: number | null
  data: unknown
}

/** 新增或更新一个 API 转换型 MCP Tool。 */
export function upsertMcpTool(payload: McpToolUpsertRequest) {
  return httpPost<McpToolView>('/fastmcp/tools/upsert', payload)
}

/** 查询平台管理的 MCP Tool 列表。 */
export function searchMcpTools() {
  return httpPost<McpToolSearchResponse>('/fastmcp/tools/search', { page: 1, page_size: 100 })
}

/** 保存前或保存后测试目标 HTTP API。 */
export function testMcpTool(payload: {
  name?: string
  tool?: McpToolUpsertRequest
  args?: Record<string, unknown>
  runtime_inputs?: Record<string, unknown>
}) {
  return httpPost<McpToolTestResponse>('/fastmcp/tools/test', payload)
}

/** 发布或停用一个 MCP Tool。 */
export function publishMcpTool(name: string, enabled: boolean) {
  return httpPost<McpToolView>('/fastmcp/tools/publish', { name, enabled })
}

/** 把平台工具视图转换成工具管理页统一展示结构。 */
export function toAgentToolInfo(item: McpToolView): AgentToolInfo {
  return {
    name: item.name,
    description: item.description || '',
    group: 'mcp',
    invokable: item.status === 'enabled',
    template_selectable: item.status === 'enabled',
    activation_mode: 'template',
    invoke_note: item.status === 'enabled'
      ? `${item.http_method} ${item.api_url}`
      : `当前状态为 ${item.status}，发布后 Agent 才能发现。`,
    args_schema: item.input_schema || {},
  }
}
