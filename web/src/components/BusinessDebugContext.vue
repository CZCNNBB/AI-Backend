<template>
  <div class="debug-context">
    <a-tag :color="configured ? 'green' : 'orange'">
      {{ configured ? `调试：${form.platformName || '业务平台'} / ${displayUserId}` : '未配置调试身份' }}
    </a-tag>
    <a-button size="small" @click="openEditor">配置调试身份</a-button>

    <a-modal
      v-model:open="editorOpen"
      title="配置调试业务身份"
      ok-text="保存"
      cancel-text="取消"
      :width="620"
      @ok="saveContext"
    >
      <a-alert
        type="info"
        show-icon
        class="context-tip"
        message="用于在管理平台中模拟外部业务系统调用"
        description="平台 API Key 和外部用户 ID 用于 Agent、运行记录和会话隔离；模拟业务 Token 只会在 Agent 调用目标业务 API 时透传。"
      />
      <a-form layout="vertical">
        <a-form-item label="Agent" required>
          <a-select
            v-model:value="form.agentId"
            :options="agentOptions"
            :loading="agentLoading"
            show-search
            option-filter-prop="label"
            placeholder="选择要模拟调用的 Agent"
            @change="onAgentChange"
          />
        </a-form-item>
        <a-form-item label="业务平台（自动识别）">
          <a-select
            v-model:value="form.platformId"
            :options="platformOptions"
            :loading="platformLoading"
            :disabled="!form.agentId || platformOptions.length <= 1"
            placeholder="单平台自动选择，多平台请手动选择"
            @change="onPlatformChange"
          />
          <div v-if="form.agentId && !platformLoading && platformOptions.length === 0" class="field-help warning-text">
            当前 Agent 尚未关联业务平台。可以手动填写 API Key 进行排查，但正式调用前仍需在 Agent 配置中绑定该 Key 所属平台。
          </div>
        </a-form-item>
        <a-form-item label="平台 API Key" required>
          <a-input-password
            v-model:value="form.platformApiKey"
            :placeholder="platformOptions.length ? '自动回填失败时，可手动粘贴 API Key' : '请输入或粘贴平台 API Key'"
          />
          <div class="field-help">
            选择平台后优先自动回填；没有可用 Key 时也可以手动输入。
          </div>
        </a-form-item>
        <a-form-item label="外部用户 ID" required>
          <a-input
            v-model:value="form.externalUserId"
            placeholder="模拟业务平台中的用户，例如 user_10086"
          />
        </a-form-item>
        <a-form-item label="模拟业务 Token（可选）">
          <a-input-password
            v-model:value="form.businessAuthorization"
            placeholder="例如 Bearer xxxxx；仅在 Agent 调用时透传"
          />
        </a-form-item>
      </a-form>
      <a-button danger @click="clearContext">清空调试身份</a-button>
    </a-modal>
  </div>
</template>

<script setup lang="ts">
/** 管理平台顶部的业务调用身份模拟器。 */
import { computed, onBeforeUnmount, onMounted, reactive, ref } from 'vue'
import { message } from 'ant-design-vue'
import { searchAgentTemplates } from '@/api/agentTemplate'
import {
  getAgentPlatformAccessOptions,
  type AgentPlatformAccessOption,
} from '@/api/platform'
import {
  BUSINESS_DEBUG_CONTEXT_CHANGED,
  clearBusinessDebugContext,
  hasCompleteBusinessDebugContext,
  readBusinessDebugContext,
  saveBusinessDebugContext,
} from '@/utils/businessDebugContext'

defineOptions({ name: 'BusinessDebugContext' })

const editorOpen = ref(false)
const configured = ref(hasCompleteBusinessDebugContext())
const form = reactive(readBusinessDebugContext())
const agentLoading = ref(false)
const platformLoading = ref(false)
const agentOptions = ref<{ label: string; value: string }[]>([])
const agentPlatformOptions = ref<AgentPlatformAccessOption[]>([])

const platformOptions = computed(() => agentPlatformOptions.value.map((platform) => ({
  label: `${platform.platform_name} (${platform.platform_code})`,
  value: platform.platform_id,
})))

const displayUserId = computed(() => {
  const userId = form.externalUserId
  return userId.length > 24 ? `${userId.slice(0, 24)}...` : userId
})

/** 打开配置弹窗，并加载其他页面可能刚刚保存的最新值。 */
async function openEditor(): Promise<void> {
  Object.assign(form, readBusinessDebugContext())
  editorOpen.value = true
  await loadAgentOptions()
  if (form.agentId) {
    await loadPlatformOptions(form.agentId)
  }
}

/** 加载管理平台中可用于调试的 Agent 列表。 */
async function loadAgentOptions(): Promise<void> {
  if (agentOptions.value.length) return
  agentLoading.value = true
  try {
    const response = await searchAgentTemplates({ page: 1, page_size: 100, status: 'active' })
    agentOptions.value = response.items.map((agent) => ({
      label: `${agent.agent_name} (${agent.agent_id})`,
      value: agent.agent_id,
    }))
  } finally {
    agentLoading.value = false
  }
}

/** 加载 Agent 关联平台，并在只有一个平台时自动选中。 */
async function loadPlatformOptions(agentId: string): Promise<void> {
  platformLoading.value = true
  try {
    const options = await getAgentPlatformAccessOptions(agentId)
    agentPlatformOptions.value = options
    const currentOption = options.find((option) => option.platform_id === form.platformId)
    if (currentOption) {
      applyPlatformOption(currentOption)
    } else if (options.length === 1) {
      applyPlatformOption(options[0])
    } else {
      form.platformId = null
      form.platformName = ''
      // 没有平台选项时保留 sessionStorage 中的手动 Key，避免重新打开弹窗后丢失。
      if (options.length > 1) {
        form.platformApiKey = ''
      }
    }
  } finally {
    platformLoading.value = false
  }
}

/** Agent 变化时清理旧平台信息并加载新平台绑定。 */
async function onAgentChange(agentId: string): Promise<void> {
  form.agentId = agentId
  form.platformId = null
  form.platformName = ''
  form.platformApiKey = ''
  await loadPlatformOptions(agentId)
}

/** 多平台 Agent 的平台下拉变化时自动回填明文 API Key。 */
function onPlatformChange(platformId: number): void {
  const platform = agentPlatformOptions.value.find((option) => option.platform_id === platformId)
  if (platform) {
    // 主动切换平台时不能沿用上一个平台的手动 Key，避免错用平台身份。
    form.platformApiKey = ''
    applyPlatformOption(platform)
  }
}

/** 将选中的平台信息和默认 API Key 写入调试表单。 */
function applyPlatformOption(platform: AgentPlatformAccessOption): void {
  form.platformId = platform.platform_id
  form.platformName = platform.platform_name
  if (platform.api_key) {
    form.platformApiKey = platform.api_key
  } else if (!form.platformApiKey) {
    message.warning(`业务平台“${platform.platform_name}”尚未签发可用 API Key`)
  }
}

/** 校验并保存当前调试业务身份。 */
function saveContext(): void {
  if (!form.agentId || !form.platformApiKey.trim() || !form.externalUserId.trim()) {
    message.warning('Agent、平台 API Key 和外部用户 ID 均为必填项')
    return
  }

  saveBusinessDebugContext(form)
  configured.value = true
  editorOpen.value = false
  message.success('调试业务身份已保存')
}

/** 清空当前标签页保存的调试身份。 */
function clearContext(): void {
  clearBusinessDebugContext()
  Object.assign(form, readBusinessDebugContext())
  configured.value = false
  editorOpen.value = false
  message.success('调试业务身份已清空')
}

/** 同步 Agent 调用页等其他页面保存的最新调试身份。 */
function syncContext(): void {
  Object.assign(form, readBusinessDebugContext())
  configured.value = hasCompleteBusinessDebugContext()
}

onMounted(() => window.addEventListener(BUSINESS_DEBUG_CONTEXT_CHANGED, syncContext))
onBeforeUnmount(() => window.removeEventListener(BUSINESS_DEBUG_CONTEXT_CHANGED, syncContext))
</script>

<style scoped>
.debug-context {
  display: flex;
  align-items: center;
  gap: 10px;
}
.context-tip {
  margin-bottom: 18px;
}
.field-help {
  margin-top: 6px;
  color: #8c8c8c;
  font-size: 12px;
  line-height: 1.5;
}
.warning-text {
  color: #d48806;
}
</style>
