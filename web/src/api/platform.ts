/**
 * 业务平台、平台 API Key 和资源归属相关接口。
 */
import { httpPost } from './http'
import type { PageRequest, PageResponse } from './types'

/** 业务平台管理视图。 */
export interface BusinessPlatform {
  id: number
  platform_code: string
  platform_name: string
  description?: string | null
  status: 'enabled' | 'disabled'
  created_at?: string | null
  updated_at?: string | null
}

/** Agent 调用页使用的平台与默认 API Key 选项。 */
export interface AgentPlatformAccessOption {
  platform_id: number
  platform_code: string
  platform_name: string
  api_key_id?: number | null
  api_key_name?: string | null
  api_key?: string | null
}

/** 管理端查看的业务平台 API Key，包含公司内网模式保存的完整明文。 */
export interface BusinessPlatformAPIKey {
  id: number
  platform_id: number
  key_name: string
  key_prefix: string
  api_key: string
  status: 'enabled' | 'disabled'
  expires_at?: string | null
  created_at?: string | null
  updated_at?: string | null
}

/** 创建或更新业务平台。 */
export function upsertBusinessPlatform(payload: {
  platform_code: string
  platform_name: string
  description?: string | null
  status: 'enabled' | 'disabled'
}) {
  return httpPost<BusinessPlatform>('/platform/platforms/upsert', payload)
}

/** 分页查询业务平台。 */
export function searchBusinessPlatforms(params: PageRequest & { keyword?: string; status?: string }) {
  return httpPost<PageResponse<BusinessPlatform>>('/platform/platforms/search', params)
}

/** 按 Agent 查询已经绑定的平台以及各平台默认可用的调试 API Key。 */
export function getAgentPlatformAccessOptions(agent_id: string) {
  return httpPost<AgentPlatformAccessOption[]>('/platform/platforms/agent-access-options', {
    agent_id,
  })
}

/** 为业务平台签发一个 API Key；公司内网模式会同时保存完整明文。 */
export function createBusinessPlatformApiKey(payload: {
  platform_code: string
  key_name: string
  expires_at?: string | null
}) {
  return httpPost<{
    id: number
    platform_id: number
    key_name: string
    key_prefix: string
    api_key: string
    expires_at?: string | null
  }>('/platform/platforms/api-keys/create', payload)
}

/** 查询指定业务平台已经签发的全部 API Key。 */
export function listBusinessPlatformApiKeys(platform_code: string) {
  return httpPost<BusinessPlatformAPIKey[]>('/platform/platforms/api-keys/list', {
    platform_code,
  })
}

/** 停用一个已经签发的平台 API Key。 */
export function disableBusinessPlatformApiKey(api_key_id: number) {
  return httpPost<boolean>('/platform/platforms/api-keys/disable', { api_key_id })
}
