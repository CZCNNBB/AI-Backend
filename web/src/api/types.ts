/**
 * API 通用类型定义
 */

// 后端统一响应结构
export interface ApiResponse<T = unknown> {
  code: number
  message: string
  data: T
}

// 分页请求参数
export interface PageRequest {
  page?: number
  page_size?: number
}

// 分页响应结构
export interface PageResponse<T> {
  total: number
  items: T[]
}
