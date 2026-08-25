/**
 * Agent 工具管理与调试接口
 */
import { httpPost } from './http'

/** 工具调试调用请求 */
export interface ToolInvokeRequest {
  tool_name: string
  args: Record<string, unknown>
}

/** 工具调试调用响应 */
export interface ToolInvokeResponse {
  tool_name: string
  args: Record<string, unknown>
  result: unknown
}

/** 调试调用一个已注册工具 */
export function invokeAgentTool(payload: ToolInvokeRequest) {
  return httpPost<ToolInvokeResponse>('/agent/tools/invoke', payload)
}
