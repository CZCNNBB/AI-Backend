/**
 * 知识库管理接口。
 * 覆盖知识库、文档、入库任务和调试能力。
 */
import { httpGet, httpPost } from './http'

/** 知识库记录。 */
export interface KnowledgeBaseItem {
  knowledge_id: string
  name: string
  description?: string | null
  collection_name: string
  embedding_model_code: string
  embedding_dimension: number
  split_config: Record<string, unknown>
  status: 'active' | 'disabled' | 'deleted'
  metadata: Record<string, unknown>
  created_at: string
  updated_at: string
}

/** 创建知识库参数。 */
export interface KnowledgeBaseCreatePayload {
  name: string
  description?: string | null
  embedding_model_code: string
  split_config?: Record<string, unknown>
  metadata?: Record<string, unknown>
}

/** 修改知识库参数。 */
export interface KnowledgeBaseUpdatePayload {
  knowledge_id: string
  name?: string
  description?: string | null
  split_config?: Record<string, unknown> | null
  status?: 'active' | 'disabled'
  metadata?: Record<string, unknown> | null
}

/** 查询知识库列表。 */
export function searchKnowledgeBases(params: { keyword?: string; status?: string } = {}) {
  return httpPost<KnowledgeBaseItem[]>('/knowledge/bases/search', params)
}

/** 查询知识库详情。 */
export function getKnowledgeBase(knowledgeId: string) {
  return httpPost<KnowledgeBaseItem>('/knowledge/bases/detail', { knowledge_id: knowledgeId })
}

/** 创建知识库并初始化 Milvus Collection。 */
export function createKnowledgeBase(payload: KnowledgeBaseCreatePayload) {
  return httpPost<KnowledgeBaseItem>('/knowledge/bases/create', payload)
}

/** 修改知识库基础配置。 */
export function updateKnowledgeBase(payload: KnowledgeBaseUpdatePayload) {
  return httpPost<KnowledgeBaseItem>('/knowledge/bases/update', payload)
}

/** 删除知识库并回收 Collection。 */
export function deleteKnowledgeBase(knowledgeId: string) {
  return httpPost<KnowledgeBaseItem>('/knowledge/bases/delete', { knowledge_id: knowledgeId })
}

/** 单一文档切片方式配置。 */
export interface KnowledgeSplitMethodConfig {
  type: 'markdown' | 'markdown_header' | 'recursive_character' | 'character' | 'qa_separator'
  chunk_size?: number
  chunk_overlap?: number
  separator?: string
  headers?: string[]
}

/** Markdown 标题切块后递归细切策略。 */
export interface KnowledgeSplitStrategyConfig {
  type: 'markdown_document_header_then_recursive'
  chunk_size?: number
  chunk_overlap?: number
  headers?: string[]
}

/** 提交入库请求。 */
export interface KnowledgeDocumentSubmitPayload {
  knowledge_id: string
  file_id: string
  force_reindex?: boolean
  priority?: number
  split_method?: KnowledgeSplitMethodConfig
  split_strategy?: KnowledgeSplitStrategyConfig
}

/** 文档关系及文件元数据。 */
export interface KnowledgeDocumentRecord {
  id: number
  knowledge_id: string
  file_id: string
  file_name?: string | null
  mime_type?: string | null
  size_bytes?: number | null
  status: 'pending' | 'indexing' | 'indexed' | 'deleting' | 'failed' | 'deleted'
  index_version: number
  chunk_count: number
  error_message?: string | null
  indexed_at?: string | null
  created_at: string
  updated_at: string
}

/** 入库任务运行记录。 */
export interface IngestionRunRecord {
  run_id: string
  document_id: number
  knowledge_id: string
  file_id: string
  operation: 'ingest' | 'reindex' | 'delete'
  status: 'pending' | 'running' | 'completed' | 'failed' | 'cancelled'
  priority: number
  worker_id?: string | null
  retry_count: number
  max_retries: number
  error_message?: string | null
  available_at: string
  created_at: string
  updated_at: string
  started_at?: string | null
  completed_at?: string | null
}

/** 分页任务列表。 */
export interface IngestionRunListResponse {
  total: number
  page: number
  page_size: number
  items: IngestionRunRecord[]
}

/** 提交任务后的文档和任务信息。 */
export interface KnowledgeDocumentSubmitResponse {
  document: KnowledgeDocumentRecord
  run: IngestionRunRecord | null
  reused_active_run: boolean
}

/** 查询知识库文档。 */
export function searchKnowledgeDocuments(params: {
  knowledge_id: string
  status?: string
  file_name?: string
}) {
  return httpPost<KnowledgeDocumentRecord[]>('/knowledge/documents/search', params)
}

/** 查询单个知识库文档。 */
export function getKnowledgeDocument(knowledgeId: string, fileId: string) {
  return httpPost<KnowledgeDocumentRecord>('/knowledge/documents/detail', {
    knowledge_id: knowledgeId,
    file_id: fileId,
  })
}

/** 上传文件关系并提交首次入库。 */
export function submitKnowledgeDocument(payload: KnowledgeDocumentSubmitPayload) {
  return httpPost<KnowledgeDocumentSubmitResponse>('/knowledge/documents/submit', payload)
}

/** 重新构建文档索引。 */
export function reindexKnowledgeDocument(payload: Omit<KnowledgeDocumentSubmitPayload, 'force_reindex'>) {
  return httpPost<KnowledgeDocumentSubmitResponse>('/knowledge/documents/reindex', payload)
}

/** 异步删除文档索引。 */
export function deleteKnowledgeDocument(knowledgeId: string, fileId: string, priority = 0) {
  return httpPost<KnowledgeDocumentSubmitResponse>('/knowledge/documents/delete', {
    knowledge_id: knowledgeId,
    file_id: fileId,
    priority,
  })
}

/** 查询单个任务状态。 */
export function getIngestionRunStatus(runId: string) {
  return httpPost<IngestionRunRecord>('/knowledge/ingestion/status', { run_id: runId })
}

/** 分页查询任务。 */
export function searchIngestionRuns(params: {
  knowledge_id?: string
  file_id?: string
  operation?: string
  status?: string
  page?: number
  page_size?: number
}) {
  return httpPost<IngestionRunListResponse>('/knowledge/ingestion/search', params)
}

/** 取消尚未被 Worker 抢占的任务。 */
export function cancelIngestionRun(runId: string) {
  return httpPost<IngestionRunRecord>('/knowledge/ingestion/cancel', { run_id: runId })
}

/** 重新提交失败任务。 */
export function retryIngestionRun(runId: string) {
  return httpPost<IngestionRunRecord>('/knowledge/ingestion/retry', { run_id: runId })
}

/** 切片预览输入。 */
export interface SplitPreviewInput {
  text: string
  chunk_size: number
  chunk_overlap: number
  separator?: string
}

/** 切片结果片段。 */
export interface SplitPreviewChunk {
  index: number
  text: string
  token_count?: number
}

/** 切片预览输出。 */
export interface SplitPreviewOutput {
  chunks: SplitPreviewChunk[]
  total_chunks: number
}

/** 预览文本切片效果，不写入知识库。 */
export function previewSplit(payload: SplitPreviewInput) {
  return httpPost<SplitPreviewOutput>('/knowledge/split/preview', payload)
}

/** 预览 Embedding 向量，不写入 Milvus。 */
export function previewEmbedding(modelCode: string, text: string) {
  return httpPost<{ model_code: string; dimension: number; embedding: number[] }>(
    '/knowledge/embedding/preview',
    { model_code: modelCode, text },
  )
}


/** 知识库检索模式。 */
export type KnowledgeRetrievalMode = 'vector' | 'keyword' | 'hybrid'

/** 单次知识库检索参数。 */
export interface KnowledgeRetrievalPayload {
  collection_list: string[]
  query: string
  retrieval_config: {
    mode: KnowledgeRetrievalMode
    top_k: number
    fetch_k: number
    similarity_threshold: number
    metric_type: 'COSINE'
    rrf_k: number
    hybrid_weights?: { vector: number; keyword: number }
    per_collection_min_keep: number
  }
  rerank_config?: {
    enable: true
    model_code: string
    max_candidates: number
    max_chars: number
  }
  enhance_config?: { metadata_headers: boolean }
  filter_config?: { file_ids: string[] }
}

/** 检索命中的单个切片。 */
export interface KnowledgeRetrievalResult {
  collection_name: string
  chunk_id: string
  file_id: string
  source: string
  chunk_index: number
  content: string
  score: number
}

/** 知识库检索响应。 */
export interface KnowledgeRetrievalOutput {
  mode: KnowledgeRetrievalMode | 'document'
  result_count: number
  rerank_used: boolean
  results: KnowledgeRetrievalResult[]
  document?: Record<string, unknown> | null
}

/** 执行知识库底层检索，供管理端调试召回质量。 */
export function testKnowledgeRetrieval(payload: KnowledgeRetrievalPayload) {
  return httpPost<KnowledgeRetrievalOutput>('/knowledge/retrieval/search', payload)
}

/** 服务存活检查。 */
export function checkKnowledgeHealth() {
  return httpGet<{ service: string; status: string }>('/knowledge/health')
}
