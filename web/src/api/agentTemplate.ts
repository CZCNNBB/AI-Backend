/**
 * Agent 模板相关接口
 * 字段与路径对齐后端 /agent/templates/*。
 */
import { httpPost } from './http'
import type { PageRequest, PageResponse } from './types'

/** 模型运行参数（ModelRuntimeOptions） */
export interface ModelRuntimeOptions {
  model_code?: string | null
  temperature?: number
  max_tokens?: number
  timeout_seconds?: number
  max_retries?: number
}

/** 可选能力（AgentOptionalFeatures） */
export interface AgentOptionalFeatures {
  long_term_memory_enabled?: boolean
  planning_enabled?: boolean
  knowledge_enabled?: boolean
}

/** 模板会话上下文总结配置；对象存在即启用该能力。 */
export interface ContextSummarizationConfig {
  model_code: string
  trigger_tokens?: number
  keep_messages?: number
  trim_tokens_to_summarize?: number
}

/** Agent 模板运行配置（AgentTemplateConfig） */
export interface AgentTemplateConfig {
  system_prompt?: string | null
  tools?: string[]
  optional_features?: AgentOptionalFeatures
  is_sub_agent?: boolean
  a2a?: { sub_agent_list?: string[] } | null
  context_summarization?: ContextSummarizationConfig | null
  runtime_options?: ModelRuntimeOptions
  /** 模板 config 是 JSONB，后端 ConfigDict(extra='allow') 允许其他扩展字段。 */
  [key: string]: unknown
}

/** Agent 模板视图（AgentTemplateView） */
export interface AgentTemplate {
  agent_id: string
  agent_name: string
  description?: string | null
  platform_ids: number[]
  config: AgentTemplateConfig
  status: string
  created_at?: string | null
  updated_at?: string | null
}

/** 分页搜索模板 */
export function searchAgentTemplates(params: PageRequest & { keyword?: string; status?: string }) {
  return httpPost<PageResponse<AgentTemplate>>('/agent/templates/search', params)
}

/** 查询模板详情 */
export function getAgentTemplateDetail(agent_id: string) {
  return httpPost<AgentTemplate>('/agent/templates/detail', { agent_id })
}

/** 创建或更新模板 */
export function upsertAgentTemplate(payload: {
  agent_id: string
  agent_name: string
  description?: string | null
  platform_ids: number[]
  config: AgentTemplateConfig
  status?: string
}) {
  return httpPost<AgentTemplate>('/agent/templates/upsert', payload)
}

/** 批量删除模板（与后端 /agent/templates/delete 接口对齐，请求体携带 ID 列表）。 */
export function deleteAgentTemplate(agent_ids: string[]) {
  return httpPost<number>('/agent/templates/delete', { agent_ids })
}
