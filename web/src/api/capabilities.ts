/**
 * 系统能力、健康检查与模型配置相关接口。
 * 对齐后端 AgentCapabilityResponse / ModelConfigResponse / AgentHealth。
 */
import { httpGet } from './http'

/** Agent 工具详情。 */
export interface AgentToolInfo {
  name: string
  description: string
  group: string
  invokable: boolean
  /** 是否允许在 Agent 模板 config.tools 中选择。 */
  template_selectable?: boolean
  /** 工具启用方式：template 表示模板选择，feature 表示能力开关自动挂载。 */
  activation_mode?: string
  invoke_note?: string | null
  args_schema: Record<string, any>
}

/** Agent 服务能力响应：/agent/capabilities。 */
export interface AgentCapabilityResponse {
  service_name: string
  modules: string[]
  enabled_features: string[]
  /** 后端返回的可选择工具编码列表，包含 MCP 工具编码。 */
  registered_tools: string[]
  /** 后端返回的工具详情，包含参数 Schema 和动态工具说明。 */
  tools?: AgentToolInfo[]
}

/** 获取 Agent 服务能力清单。 */
export function getCapabilities() {
  return httpGet<AgentCapabilityResponse>('/agent/capabilities')
}

/** 模型配置摘要响应：/agent/model/config。 */
export interface ModelConfigResponse {
  available_models: string[]
  chat_models: string[]
  embedding_models: string[]
  rerank_models: string[]
  langsmith_tracing: boolean
  langsmith_endpoint: string
  langsmith_project: string
  has_langsmith_api_key: boolean
}

/** 获取当前模型配置摘要。 */
export function getModelConfig() {
  return httpGet<ModelConfigResponse>('/agent/model/config')
}

/** Agent 健康检查响应：/agent/health。 */
export interface AgentHealthResponse {
  service: string
  status: string
}

/** Agent 健康检查。 */
export function getHealth() {
  return httpGet<AgentHealthResponse>('/agent/health')
}
