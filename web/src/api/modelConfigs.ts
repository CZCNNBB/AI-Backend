/**
 * 模型配置接口
 * 对齐后端 /agent/models/*，用于管理平台模型资源池。
 */
import { httpPost } from './http'
import type { PageResponse } from './types'

export type ModelType = 'chat' | 'embedding' | 'rerank'

/** 模型配置视图，本地部署场景下 api_key 作为普通配置返回。 */
export interface ModelConfigItem {
  id?: number | null
  model_code: string
  model_name: string
  model_type: ModelType
  base_url: string
  api_key?: string | null
  api_type: string
  support_stream: boolean
  support_tool_calling: boolean
  support_structured_output: boolean
  is_multimodal: boolean
  enabled: boolean
  extra_config?: Record<string, unknown> | null
  description?: string | null
  created_at?: string | null
  updated_at?: string | null
}

/** 新增或更新模型配置请求。 */
export interface ModelConfigUpsertPayload {
  original_model_code?: string | null
  model_code: string
  model_name: string
  model_type: ModelType
  base_url: string
  api_key?: string | null
  api_type?: string
  support_stream?: boolean
  support_tool_calling?: boolean
  support_structured_output?: boolean
  is_multimodal?: boolean
  enabled?: boolean
  extra_config?: Record<string, unknown> | null
  description?: string | null
}

/** 查询模型配置列表。 */
export function searchModelConfigs(params: {
  keyword?: string | null
  model_type?: ModelType | null
  enabled?: boolean | null
  page?: number
  page_size?: number
}) {
  return httpPost<PageResponse<ModelConfigItem>>('/agent/models/search', params)
}

/** 查询模型配置详情。 */
export function getModelConfigDetail(model_code: string) {
  return httpPost<ModelConfigItem | null>('/agent/models/detail', { model_code })
}

/** 新增或更新模型配置。 */
export function upsertModelConfig(payload: ModelConfigUpsertPayload) {
  return httpPost<ModelConfigItem>('/agent/models/upsert', payload)
}

/** 批量删除模型配置。 */
export function deleteModelConfigs(model_codes: string[]) {
  return httpPost<number>('/agent/models/delete', { model_codes })
}

/**
 * 拉取所有已启用的 Embedding 模型，供知识库创建表单使用。
 * - 复用 search 接口，便于复用分页/过滤
 * - 翻页拉完所有数据，返回扁平数组
 */
export async function listEnabledEmbeddingModels(): Promise<ModelConfigItem[]> {
  const PAGE_SIZE = 100
  const all: ModelConfigItem[] = []
  let page = 1
  // 最多翻 10 页（= 1000 条），超过则截断；embedding 模型一般 < 20 条
  while (page <= 10) {
    const resp = await searchModelConfigs({
      model_type: 'embedding',
      enabled: true,
      page,
      page_size: PAGE_SIZE,
    })
    all.push(...resp.items)
    if (all.length >= resp.total || resp.items.length < PAGE_SIZE) break
    page += 1
  }
  return all
}
