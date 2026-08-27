/**
 * 管理前端用于模拟外部业务系统调用身份的临时配置。
 *
 * 这些值只保存在当前浏览器标签页的 sessionStorage 中：
 * - 平台 API Key 用于识别业务平台；
 * - external_user_id 用于隔离平台内部用户；
 * - 业务 Token 只在 Agent 实际执行时透传给目标业务 API。
 */

export interface BusinessDebugContext {
  agentId: string
  platformId: number | null
  platformName: string
  platformApiKey: string
  externalUserId: string
  businessAuthorization: string
}

export const BUSINESS_DEBUG_CONTEXT_CHANGED = 'business-debug-context-changed'

const PLATFORM_API_KEY_STORAGE = 'agent_platform_api_key'
const EXTERNAL_USER_ID_STORAGE = 'agent_external_user_id'
const BUSINESS_AUTHORIZATION_STORAGE = 'agent_business_authorization'
const AGENT_ID_STORAGE = 'agent_debug_agent_id'
const PLATFORM_ID_STORAGE = 'agent_debug_platform_id'
const PLATFORM_NAME_STORAGE = 'agent_debug_platform_name'

/** 读取当前标签页保存的调试业务身份。 */
export function readBusinessDebugContext(): BusinessDebugContext {
  // 兼容读取改造前保存在 localStorage 的平台 Key 和用户 ID；
  // 用户下一次保存或清空后会统一迁移到 sessionStorage。
  const platformApiKey = sessionStorage.getItem(PLATFORM_API_KEY_STORAGE)
    || localStorage.getItem(PLATFORM_API_KEY_STORAGE)
    || ''
  const externalUserId = sessionStorage.getItem(EXTERNAL_USER_ID_STORAGE)
    || localStorage.getItem(EXTERNAL_USER_ID_STORAGE)
    || ''

  return {
    agentId: sessionStorage.getItem(AGENT_ID_STORAGE) || '',
    platformId: Number(sessionStorage.getItem(PLATFORM_ID_STORAGE)) || null,
    platformName: sessionStorage.getItem(PLATFORM_NAME_STORAGE) || '',
    platformApiKey,
    externalUserId,
    businessAuthorization: sessionStorage.getItem(BUSINESS_AUTHORIZATION_STORAGE) || '',
  }
}

/** 判断当前调试身份是否具备平台 API Key 和外部用户 ID。 */
export function hasCompleteBusinessDebugContext(): boolean {
  const context = readBusinessDebugContext()
  return Boolean(context.platformApiKey.trim() && context.externalUserId.trim())
}

/** 保存调试业务身份，并通知当前页面重新读取身份。 */
export function saveBusinessDebugContext(context: BusinessDebugContext): void {
  sessionStorage.setItem(AGENT_ID_STORAGE, context.agentId.trim())
  if (context.platformId === null) {
    sessionStorage.removeItem(PLATFORM_ID_STORAGE)
  } else {
    sessionStorage.setItem(PLATFORM_ID_STORAGE, String(context.platformId))
  }
  sessionStorage.setItem(PLATFORM_NAME_STORAGE, context.platformName.trim())
  sessionStorage.setItem(PLATFORM_API_KEY_STORAGE, context.platformApiKey.trim())
  sessionStorage.setItem(EXTERNAL_USER_ID_STORAGE, context.externalUserId.trim())
  sessionStorage.setItem(BUSINESS_AUTHORIZATION_STORAGE, context.businessAuthorization.trim())

  // 凭证改为标签页级存储后，删除旧版本遗留的长期存储，避免关闭浏览器后仍保留明文。
  localStorage.removeItem(PLATFORM_API_KEY_STORAGE)
  localStorage.removeItem(EXTERNAL_USER_ID_STORAGE)
  window.dispatchEvent(new CustomEvent(BUSINESS_DEBUG_CONTEXT_CHANGED))
}

/** 清空当前标签页及旧版本遗留的调试业务身份。 */
export function clearBusinessDebugContext(): void {
  sessionStorage.removeItem(AGENT_ID_STORAGE)
  sessionStorage.removeItem(PLATFORM_ID_STORAGE)
  sessionStorage.removeItem(PLATFORM_NAME_STORAGE)
  sessionStorage.removeItem(PLATFORM_API_KEY_STORAGE)
  sessionStorage.removeItem(EXTERNAL_USER_ID_STORAGE)
  sessionStorage.removeItem(BUSINESS_AUTHORIZATION_STORAGE)
  localStorage.removeItem(PLATFORM_API_KEY_STORAGE)
  localStorage.removeItem(EXTERNAL_USER_ID_STORAGE)
  window.dispatchEvent(new CustomEvent(BUSINESS_DEBUG_CONTEXT_CHANGED))
}

/**
 * 构造业务视角接口请求头。
 *
 * @param includeBusinessAuthorization 是否包含只能用于实际 Agent 执行的业务用户 Token。
 */
export function buildBusinessDebugHeaders(
  includeBusinessAuthorization = false,
): Record<string, string> {
  const context = readBusinessDebugContext()
  const headers: Record<string, string> = {}

  if (context.platformApiKey.trim()) {
    headers['X-API-Key'] = context.platformApiKey.trim()
  }
  if (includeBusinessAuthorization && context.businessAuthorization.trim()) {
    headers['X-Business-Authorization'] = context.businessAuthorization.trim()
  }
  return headers
}
