/**
 * Agent 运行相关接口
 * 前端调用统一消息入口 /agent/messages；历史运行记录仍使用 /agent/runs/*。
 */
import { httpPost } from './http'
import type { PageRequest, PageResponse } from './types'

/** Agent 运行记录视图（AgentRunView） */
export interface AgentRun {
  run_id: string
  run_type: 'main' | 'sub' | string
  parent_run_id?: string | null
  agent_id?: string | null
  conversation_id?: string | null
  user_message_id?: string | null
  assistant_message_id?: string | null
  query?: string | null
  answer?: string | null
  status: 'running' | 'success' | 'failed' | string
  error_message?: string | null
  elapsed_ms?: number | null
  metadata?: Record<string, unknown>
  started_at?: string | null
  finished_at?: string | null
}

/** Agent 主子运行链路（AgentRunChainResponse） */
export interface AgentRunChain {
  run_id: string
  items: AgentRun[]
}

/** 搜索运行记录请求（AgentRunSearchRequest） */
export interface SearchAgentRunsParams extends PageRequest {
  run_id?: string
  run_type?: 'main' | 'sub'
  parent_run_id?: string
  agent_id?: string
  conversation_id?: string
  status?: 'running' | 'success' | 'failed'
}

/** 搜索运行记录 */
export function searchAgentRuns(params: SearchAgentRunsParams) {
  return httpPost<PageResponse<AgentRun>>('/agent/runs/search', params)
}

/** 查询单条运行详情 */
export function getAgentRunDetail(run_id: string) {
  return httpPost<AgentRun>('/agent/runs/detail', { run_id })
}

/** 查询主子运行链路 */
export function getAgentRunChain(run_id: string) {
  return httpPost<AgentRunChain>('/agent/runs/chain', { run_id })
}

/** Agent 消息请求兼容载荷；页面仍可传 query，这里会映射为后端 message。 */
export interface AgentRunRequestPayload {
  agent_id?: string | null
  query: string
  conversation_id?: string
  stream?: boolean
  message_type?: string
  payload?: Record<string, unknown>
  system_prompt?: string
  inputs?: Record<string, unknown>
  file_ids?: string[]
  tools?: string[]
  optional_features?: {
    long_term_memory_enabled?: boolean
    planning_enabled?: boolean
    knowledge_enabled?: boolean
  }
  knowledge?: { knowledge_base_ids?: string[] } | null
  a2a?: { sub_agent_list?: string[] } | null
  runtime_options?: {
    model_code?: string | null
    temperature?: number
    max_tokens?: number
    timeout_seconds?: number
    max_retries?: number
  }
}


/** 将旧的 query 载荷转换为后端统一消息入口需要的 message 载荷。 */
function toAgentMessagePayload(payload: AgentRunRequestPayload, stream: boolean) {
  const { query, message_type, payload: structuredPayload, ...rest } = payload
  return {
    ...rest,
    message: query,
    message_type: message_type || 'text',
    payload: structuredPayload || {},
    stream,
  }
}

/** Agent 运行响应（AgentRunResponse） */
export interface AgentRunResponse {
  run_id: string
  answer: string
}

/** 同步运行 Agent（stream=false） */
export function runAgent(payload: AgentRunRequestPayload) {
  return httpPost<AgentRunResponse>('/agent/messages', toAgentMessagePayload(payload, false))
}

/** SSE 事件类型 */
export interface AgentStreamEvent {
  type: string
  content?: string
  answer?: string
  run_id?: string
  message_id?: string
  delta?: string
  [key: string]: unknown
}

/**
 * 流式运行 Agent（SSE）
 * 后端返回 text/event-stream 格式，event 行 + data 行
 * 事件类型：message / start / end / error 等
 */
/** 解析单个 SSE 事件块，并把 data JSON 转成前端统一事件对象。 */
function emitSseBlock(block: string, onEvent: (event: AgentStreamEvent) => void) {
  let eventType = 'message'
  const dataLines: string[] = []

  for (const raw of block.split('\n')) {
    const line = raw.replace(/\r$/, '')
    if (line.startsWith('event:')) {
      eventType = line.slice(6).trim() || 'message'
    } else if (line.startsWith('data:')) {
      dataLines.push(line.slice(5).trim())
    }
  }

  const data = dataLines.join('\n')
  if (!data) return
  try {
    const json = JSON.parse(data) as AgentStreamEvent
    onEvent({ ...json, type: json.type || eventType })
  } catch {
    onEvent({ type: eventType, content: data })
  }
}

export async function runAgentStream(
  payload: AgentRunRequestPayload,
  onEvent: (event: AgentStreamEvent) => void,
  onError?: (err: Error) => void,
  onDone?: () => void,
) {
  const baseURL = (import.meta.env.VITE_API_BASE as string) || '/api'
  try {
    const response = await fetch(`${baseURL}/agent/messages`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(toAgentMessagePayload(payload, true)),
    })
    if (!response.ok || !response.body) {
      throw new Error(`HTTP ${response.status}`)
    }
    const reader = response.body.getReader()
    const decoder = new TextDecoder('utf-8')
    let buffer = ''
    // 持续读取 SSE 流，按空行分隔的事件块解析；这样 event/data 被网络拆包时也不会丢事件名。
    while (true) {
      const { value, done } = await reader.read()
      if (done) break
      buffer += decoder.decode(value, { stream: true })
      const normalizedBuffer = buffer.replace(/\r\n/g, '\n')
      const blocks = normalizedBuffer.split('\n\n')
      buffer = blocks.pop() || ''
      for (const block of blocks) {
        emitSseBlock(block, onEvent)
      }
    }
    // 兜底处理最后一个没有以空行结束的 SSE 事件块。
    const tail = buffer.trim()
    if (tail) emitSseBlock(tail, onEvent)
    onDone?.()
  } catch (err) {
    onError?.(err as Error)
  }
}
