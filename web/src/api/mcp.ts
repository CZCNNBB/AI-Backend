/**
 * Agent MCP 工具管理接口。
 */
import { httpPost } from './http'
import type { AgentToolInfo } from './capabilities'

/** MCP 工具返回视图。 */
export interface AgentMcpToolView {
  id?: number | null
  mcp_code: string
  name: string
  description?: string | null
  base_url: string
  transport: string
  auth_type?: string | null
  auth_config?: Record<string, any> | null
  input_schema?: Record<string, any> | null
  output_schema?: Record<string, any> | null
  status: string
  created_at?: string | null
  updated_at?: string | null
}

/** 同步 MCP 工具请求。 */
export interface McpToolSyncRequest {
  base_url: string
  transport: string
  code_prefix?: string | null
  auth_type?: string | null
  auth_config?: Record<string, any> | null
  overwrite: boolean
}

/** 同步 MCP 工具响应。 */
export interface McpToolSyncResponse {
  base_url: string
  synced: number
  items: AgentMcpToolView[]
}

/** 新增或更新 MCP 工具请求。 */
export interface McpToolUpsertRequest {
  original_mcp_code?: string | null
  mcp_code: string
  name: string
  description?: string | null
  base_url: string
  transport: string
  auth_type?: string | null
  auth_config?: Record<string, any> | null
  input_schema?: Record<string, any> | null
  output_schema?: Record<string, any> | null
  status: string
}

/** 从 MCP 服务地址同步工具。 */
export function syncMcpTools(payload: McpToolSyncRequest) {
  return httpPost<McpToolSyncResponse>('/agent/mcp/sync', payload)
}

/** 新增或更新单个 MCP 工具。 */
export function upsertMcpTool(payload: McpToolUpsertRequest) {
  return httpPost<AgentMcpToolView>('/agent/mcp/upsert', payload)
}

/** 把 MCP 工具视图转换成工具管理页统一工具结构。 */
export function toAgentToolInfo(item: AgentMcpToolView): AgentToolInfo {
  return {
    name: item.mcp_code,
    description: item.description || '',
    group: 'mcp',
    invokable: item.status === 'enabled',
    invoke_note: `MCP 外部工具，真实工具名：${item.name}`,
    args_schema: item.input_schema || {},
  }
}
