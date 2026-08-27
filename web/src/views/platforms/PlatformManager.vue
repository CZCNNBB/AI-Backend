<!-- 业务平台注册、状态管理和 API Key 签发页面。 -->
<template>
  <div>
    <div class="page-header">
      <h2 class="page-title">业务平台管理</h2>
      <a-button type="primary" @click="openCreateModal">新增业务平台</a-button>
    </div>

    <a-card class="mb-4">
      <a-space>
        <a-input v-model:value="keyword" allow-clear placeholder="平台编码、名称或说明" @press-enter="loadPlatforms" />
        <a-select v-model:value="status" allow-clear placeholder="全部状态" style="width: 140px" :options="statusOptions" />
        <a-button type="primary" @click="loadPlatforms">查询</a-button>
      </a-space>
    </a-card>

    <a-card>
      <a-table :columns="columns" :data-source="platforms" :loading="loading" row-key="id" :pagination="false">
        <template #bodyCell="{ column, record }">
          <template v-if="column.key === 'status'">
            <a-tag :color="record.status === 'enabled' ? 'green' : 'red'">
              {{ record.status === 'enabled' ? '启用' : '停用' }}
            </a-tag>
          </template>
          <template v-else-if="column.key === 'action'">
            <a-space>
              <a-button type="link" @click="openEditModal(record)">编辑</a-button>
              <a-button type="link" @click="openKeyList(record)">查看 API Key</a-button>
              <a-button type="link" @click="openKeyModal(record)">签发 API Key</a-button>
            </a-space>
          </template>
        </template>
      </a-table>
    </a-card>

    <a-modal v-model:open="platformModalOpen" :title="editingPlatform ? '编辑业务平台' : '新增业务平台'" @ok="savePlatform">
      <a-form layout="vertical">
        <a-form-item label="平台编码" required>
          <a-input v-model:value="platformForm.platform_code" :disabled="!!editingPlatform" placeholder="例如 order_system" />
        </a-form-item>
        <a-form-item label="平台名称" required>
          <a-input v-model:value="platformForm.platform_name" placeholder="例如订单业务系统" />
        </a-form-item>
        <a-form-item label="说明">
          <a-textarea v-model:value="platformForm.description" :rows="3" />
        </a-form-item>
        <a-form-item label="状态">
          <a-radio-group v-model:value="platformForm.status">
            <a-radio value="enabled">启用</a-radio>
            <a-radio value="disabled">停用</a-radio>
          </a-radio-group>
        </a-form-item>
      </a-form>
    </a-modal>

    <a-modal v-model:open="keyModalOpen" title="签发平台 API Key" @ok="createApiKey">
      <a-alert
        type="warning"
        show-icon
        class="mb-4"
        message="API Key 会在内网平台保存明文，供 Agent 调试页自动回填；仍建议复制后安全交给业务平台后端。"
      />
      <a-form layout="vertical">
        <a-form-item label="业务平台">
          <a-input :value="keyPlatform?.platform_name" disabled />
        </a-form-item>
        <a-form-item label="Key 名称" required>
          <a-input v-model:value="keyName" placeholder="例如 production" />
        </a-form-item>
      </a-form>
    </a-modal>

    <a-modal v-model:open="keyResultOpen" title="API Key 签发成功" :footer="null">
      <a-alert type="success" show-icon class="mb-4" message="完整密钥已保存，可在 Agent 调试时自动读取；也可以立即复制给业务平台后端。" />
      <a-input-search :value="createdApiKey" readonly enter-button="复制" @search="copyApiKey" />
    </a-modal>

    <a-modal
      v-model:open="keyListOpen"
      :title="`API Key - ${keyListPlatform?.platform_name || ''}`"
      :footer="null"
      width="1100px"
    >
      <a-alert
        type="info"
        show-icon
        class="mb-4"
        message="这里展示公司内网模式保存的完整 API Key，可复制给业务平台后端。停用后该 Key 会立即无法调用业务接口。"
      />
      <a-table
        :columns="keyColumns"
        :data-source="apiKeys"
        :loading="keyListLoading"
        row-key="id"
        :pagination="false"
        :scroll="{ x: 980 }"
      >
        <template #bodyCell="{ column, record }">
          <template v-if="column.key === 'api_key'">
            <a-space>
              <a-input-password :value="record.api_key" readonly style="width: 340px" />
              <a-button @click="copyStoredApiKey(record.api_key)">复制</a-button>
            </a-space>
          </template>
          <template v-else-if="column.key === 'status'">
            <a-tag :color="record.status === 'enabled' ? 'green' : 'red'">
              {{ record.status === 'enabled' ? '启用' : '停用' }}
            </a-tag>
          </template>
          <template v-else-if="column.key === 'expires_at'">
            {{ formatDateTime(record.expires_at) || '永不过期' }}
          </template>
          <template v-else-if="column.key === 'created_at'">
            {{ formatDateTime(record.created_at) || '-' }}
          </template>
          <template v-else-if="column.key === 'action'">
            <a-popconfirm
              v-if="record.status === 'enabled'"
              title="确认停用这个 API Key？停用后业务系统将无法继续使用它。"
              ok-text="确认停用"
              cancel-text="取消"
              @confirm="disableApiKey(record)"
            >
              <a-button type="link" danger>停用</a-button>
            </a-popconfirm>
            <span v-else class="muted-text">已停用</span>
          </template>
        </template>
      </a-table>
    </a-modal>
  </div>
</template>

<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { message } from 'ant-design-vue'
import {
  createBusinessPlatformApiKey,
  disableBusinessPlatformApiKey,
  listBusinessPlatformApiKeys,
  searchBusinessPlatforms,
  type BusinessPlatform,
  type BusinessPlatformAPIKey,
  upsertBusinessPlatform,
} from '@/api/platform'

defineOptions({ name: 'PlatformManagerView' })

const loading = ref(false)
const keyword = ref('')
const status = ref<string>()
const platforms = ref<BusinessPlatform[]>([])
const platformModalOpen = ref(false)
const editingPlatform = ref<BusinessPlatform | null>(null)
const keyModalOpen = ref(false)
const keyResultOpen = ref(false)
const keyPlatform = ref<BusinessPlatform | null>(null)
const keyName = ref('default')
const createdApiKey = ref('')
const keyListOpen = ref(false)
const keyListLoading = ref(false)
const keyListPlatform = ref<BusinessPlatform | null>(null)
const apiKeys = ref<BusinessPlatformAPIKey[]>([])

const statusOptions = [
  { label: '启用', value: 'enabled' },
  { label: '停用', value: 'disabled' },
]
const columns = [
  { title: '平台编码', dataIndex: 'platform_code', key: 'platform_code' },
  { title: '平台名称', dataIndex: 'platform_name', key: 'platform_name' },
  { title: '说明', dataIndex: 'description', key: 'description', ellipsis: true },
  { title: '状态', dataIndex: 'status', key: 'status', width: 100 },
  { title: '操作', key: 'action', width: 320 },
]
const keyColumns = [
  { title: 'Key 名称', dataIndex: 'key_name', key: 'key_name', width: 130 },
  { title: '完整 API Key', dataIndex: 'api_key', key: 'api_key', width: 460 },
  { title: '状态', dataIndex: 'status', key: 'status', width: 90 },
  { title: '过期时间', dataIndex: 'expires_at', key: 'expires_at', width: 180 },
  { title: '签发时间', dataIndex: 'created_at', key: 'created_at', width: 180 },
  { title: '操作', key: 'action', width: 90 },
]
const platformForm = reactive({
  platform_code: '',
  platform_name: '',
  description: '',
  status: 'enabled' as 'enabled' | 'disabled',
})

/** 加载业务平台列表。 */
async function loadPlatforms() {
  loading.value = true
  try {
    const response = await searchBusinessPlatforms({
      page: 1,
      page_size: 100,
      keyword: keyword.value || undefined,
      status: status.value || undefined,
    })
    platforms.value = response.items || []
  } finally {
    loading.value = false
  }
}

/** 打开新增平台窗口。 */
function openCreateModal() {
  editingPlatform.value = null
  Object.assign(platformForm, { platform_code: '', platform_name: '', description: '', status: 'enabled' })
  platformModalOpen.value = true
}

/** 打开编辑平台窗口。 */
function openEditModal(platform: BusinessPlatform) {
  editingPlatform.value = platform
  Object.assign(platformForm, {
    platform_code: platform.platform_code,
    platform_name: platform.platform_name,
    description: platform.description || '',
    status: platform.status,
  })
  platformModalOpen.value = true
}

/** 保存业务平台基础信息。 */
async function savePlatform() {
  if (!platformForm.platform_code.trim() || !platformForm.platform_name.trim()) {
    message.warning('请填写平台编码和平台名称')
    return
  }
  await upsertBusinessPlatform({
    platform_code: platformForm.platform_code.trim(),
    platform_name: platformForm.platform_name.trim(),
    description: platformForm.description.trim() || null,
    status: platformForm.status,
  })
  message.success('业务平台已保存')
  platformModalOpen.value = false
  await loadPlatforms()
}

/** 打开 API Key 签发窗口。 */
function openKeyModal(platform: BusinessPlatform) {
  keyPlatform.value = platform
  keyName.value = 'default'
  keyModalOpen.value = true
}

/** 打开指定业务平台的 API Key 列表，并从后端读取完整明文。 */
async function openKeyList(platform: BusinessPlatform) {
  keyListPlatform.value = platform
  keyListOpen.value = true
  await loadApiKeys()
}

/** 加载当前选中业务平台的 API Key 列表。 */
async function loadApiKeys() {
  if (!keyListPlatform.value) return
  keyListLoading.value = true
  try {
    apiKeys.value = await listBusinessPlatformApiKeys(keyListPlatform.value.platform_code)
  } finally {
    keyListLoading.value = false
  }
}

/** 签发并展示已经在内网平台中保存的完整 API Key。 */
async function createApiKey() {
  if (!keyPlatform.value || !keyName.value.trim()) return
  const result = await createBusinessPlatformApiKey({
    platform_code: keyPlatform.value.platform_code,
    key_name: keyName.value.trim(),
  })
  createdApiKey.value = result.api_key
  keyModalOpen.value = false
  keyResultOpen.value = true
  if (keyListOpen.value && keyListPlatform.value?.id === keyPlatform.value.id) {
    await loadApiKeys()
  }
}

/** 把本次签发的完整 API Key 复制到剪贴板。 */
async function copyApiKey() {
  await navigator.clipboard.writeText(createdApiKey.value)
  message.success('API Key 已复制')
}

/** 复制列表中已经保存的完整 API Key。 */
async function copyStoredApiKey(apiKey: string) {
  await navigator.clipboard.writeText(apiKey)
  message.success('API Key 已复制')
}

/** 停用指定 API Key，并刷新当前平台的 Key 列表。 */
async function disableApiKey(apiKey: BusinessPlatformAPIKey) {
  await disableBusinessPlatformApiKey(apiKey.id)
  message.success(`API Key「${apiKey.key_name}」已停用`)
  await loadApiKeys()
}

/** 把后端时间字符串转换为适合管理端阅读的本地时间。 */
function formatDateTime(value?: string | null) {
  if (!value) return ''
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  return date.toLocaleString()
}

onMounted(loadPlatforms)
</script>

<style scoped>
.page-header { display: flex; align-items: center; justify-content: space-between; margin-bottom: 16px; }
.page-title { margin: 0; font-size: 20px; font-weight: 600; }
.mb-4 { margin-bottom: 16px; }
.muted-text { color: #9ca3af; }
</style>
