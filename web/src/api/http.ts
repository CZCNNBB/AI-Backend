/**
 * Axios 实例与统一拦截器配置
 * 负责：baseURL 注入、统一错误处理、response.data 自动解包
 */
import axios, { type AxiosInstance, type AxiosRequestConfig, type AxiosResponse, type InternalAxiosRequestConfig } from 'axios'
import { message } from 'ant-design-vue'
import { buildBusinessDebugHeaders } from '@/utils/businessDebugContext'

/** 创建 Axios 实例，默认指向本地后端 */
const http: AxiosInstance = axios.create({
  baseURL: import.meta.env.VITE_API_BASE || '/api',
  timeout: 60000,
  headers: { 'Content-Type': 'application/json' },
})

/** 判断请求是否需要模拟外部业务平台身份。 */
function isBusinessIdentityRequest(url: string): boolean {
  return url.startsWith('/agent/messages')
    || url.startsWith('/agent/runs/')
    || url.startsWith('/agent/conversations/')
}

/** 请求拦截器：只给业务身份视角接口注入平台凭证。 */
http.interceptors.request.use((config: InternalAxiosRequestConfig) => {
  const requestUrl = config.url || ''
  if (!isBusinessIdentityRequest(requestUrl)) {
    return config
  }

  // 业务 Token 只允许发送给真正执行 Agent 的消息接口，运行和会话查询不需要它。
  const headers = buildBusinessDebugHeaders(requestUrl.startsWith('/agent/messages'))
  for (const [headerName, headerValue] of Object.entries(headers)) {
    if (!config.headers.has(headerName)) {
      config.headers.set(headerName, headerValue)
    }
  }
  return config
})

/** 统一解包后的响应数据 */
export interface ApiResult<T = unknown> {
  data: T
  message: string
  code: number
}

/**
 * 响应拦截器：解包 + 错误提示
 * - 后端统一格式：{ code, msg, data }，成功 code === 0
 * - 兼容旧字段：若后端用 message 替代 msg，也能正确读取
 * - 若响应不包含 code 字段，直接返回 res.data
 */
http.interceptors.response.use(
  (response: AxiosResponse) => {
    const res = response.data
    if (res && typeof res === 'object' && 'code' in res) {
      // 后端错误消息字段是 msg，但部分接口可能用 message，做兼容
      const errMsg = (res as { msg?: string; message?: string }).msg
        || (res as { msg?: string; message?: string }).message
        || '请求失败'
      if (res.code !== 0 && res.code !== 200) {
        message.error(errMsg)
        return Promise.reject(new Error(errMsg))
      }
      return res.data
    }
    return res
  },
  (error) => {
    // 网络层错误（404、500、ECONNREFUSED 等）
    const data = error?.response?.data
    const errMsg = (data && typeof data === 'object' && (data.msg || data.message))
      || error?.response?.statusText
      || error.message
      || '网络异常'
    message.error(errMsg)
    return Promise.reject(error)
  },
)

/**
 * 自定义请求方法：直接返回解包后的 data 类型 T
 * 这样在业务层调用时，TS 就能正确识别 Promise<T> 而不是 Promise<AxiosResponse<T>>
 */
function request<T = unknown>(config: AxiosRequestConfig): Promise<T> {
  return http.request<unknown, T>(config)
}

/** 快捷方法：GET */
export function httpGet<T = unknown>(url: string, config?: AxiosRequestConfig): Promise<T> {
  return request<T>({ ...config, url, method: 'GET' })
}

/** 快捷方法：POST */
export function httpPost<T = unknown>(url: string, data?: unknown, config?: AxiosRequestConfig): Promise<T> {
  return request<T>({ ...config, url, method: 'POST', data })
}

/** 快捷方法：DELETE */
export function httpDelete<T = unknown>(url: string, config?: AxiosRequestConfig): Promise<T> {
  return request<T>({ ...config, url, method: 'DELETE' })
}

export default http
