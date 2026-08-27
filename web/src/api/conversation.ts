/**
 * Agent 会话与消息接口
 * 路径与字段完全对齐后端 /agent/conversations/*
 */
import { httpPost } from './http'
import { readBusinessDebugContext } from '@/utils/businessDebugContext'

/** 会话视图（AgentConversationView） */
export interface Conversation {
  conversation_id: string
  external_user_id: string
  title?: string | null
  status: string
  created_at?: string
  updated_at?: string
  metadata?: Record<string, unknown>
}

/** 会话消息（AgentMessage） */
export interface ConversationMessage {
  message_id: string
  conversation_id: string
  /** 后端字段名是 message_type */
  message_type: string
  role: string
  content?: string | null
  structured_content?: Record<string, unknown> | null
  tool_name?: string | null
  tool_call_id?: string | null
  parent_message_id?: string | null
  status?: string
  created_at?: string
}

/** /agent/conversations/search 请求体 */
export interface ConversationSearchRequest {
  conversation_id?: string
  page?: number
  page_size?: number
}

/** /agent/conversations/search 响应 */
export interface ConversationSearchResponse {
  items: Conversation[]
  total: number
  page: number
  page_size: number
}

/** /agent/conversations/messages 响应 */
export interface ConversationMessagesResponse {
  conversation_id: string
  messages: ConversationMessage[]
}

/** 按 conversation_id 精确查询会话 */
export function searchConversations(payload: ConversationSearchRequest) {
  return httpPost<ConversationSearchResponse>('/agent/conversations/search', {
    ...payload,
    external_user_id: getExternalUserId(),
  })
}

/** 查询会话历史消息 */
export function getConversationMessages(conversation_id: string, limit = 50) {
  return httpPost<ConversationMessagesResponse>('/agent/conversations/messages', {
    external_user_id: getExternalUserId(),
    conversation_id,
    limit,
  })
}

/** 读取管理调用页保存的外部用户 ID。 */
function getExternalUserId() {
  return readBusinessDebugContext().externalUserId
}
