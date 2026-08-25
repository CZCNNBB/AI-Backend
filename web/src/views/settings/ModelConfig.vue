<!--
  模型配置管理页
  - 管理平台模型资源池 model_configs
  - API Key 只允许写入，不从后端读取明文
-->
<template>
  <div>
    <div class="page-header">
      <h2 class="page-title">模型配置</h2>
      <a-button type="primary" @click="openCreate">新增模型</a-button>
    </div>

    <a-card class="mb-4">
      <a-space wrap>
        <a-input v-model:value="filters.keyword" placeholder="搜索 model_code / model_name" allow-clear style="width: 260px" />
        <a-select v-model:value="filters.model_type" placeholder="模型类型" allow-clear style="width: 160px">
          <a-select-option value="chat">chat</a-select-option>
          <a-select-option value="embedding">embedding</a-select-option>
          <a-select-option value="rerank">rerank</a-select-option>
        </a-select>
        <a-select v-model:value="filters.enabled" placeholder="启用状态" allow-clear style="width: 140px">
          <a-select-option :value="true">启用</a-select-option>
          <a-select-option :value="false">禁用</a-select-option>
        </a-select>
        <a-button @click="loadModels">查询</a-button>
      </a-space>
    </a-card>

    <a-card>
      <a-table
        row-key="model_code"
        :loading="loading"
        :columns="columns"
        :data-source="items"
        :pagination="pagination"
        @change="onTableChange"
      >
        <template #bodyCell="{ column, record }">
          <template v-if="column.key === 'model_code'">
            <code>{{ record.model_code }}</code>
          </template>
          <template v-else-if="column.key === 'capabilities'">
            <a-space wrap>
              <a-tag v-if="record.support_stream" color="blue">stream</a-tag>
              <a-tag v-if="record.support_tool_calling" color="purple">tool</a-tag>
              <a-tag v-if="record.support_structured_output" color="green">json</a-tag>
              <a-tag v-if="record.is_multimodal" color="orange">multimodal</a-tag>
            </a-space>
          </template>
          <template v-else-if="column.key === 'api_key'">
            <code>{{ record.api_key || '-' }}</code>
          </template>
          <template v-else-if="column.key === 'enabled'">
            <a-tag :color="record.enabled ? 'green' : 'default'">
              {{ record.enabled ? '启用' : '禁用' }}
            </a-tag>
          </template>
          <template v-else-if="column.key === 'action'">
            <a-space>
              <a-button size="small" @click="openEdit(record)">编辑</a-button>
              <a-popconfirm title="确认删除这个模型配置？" @confirm="deleteOne(record.model_code)">
                <a-button size="small" danger>删除</a-button>
              </a-popconfirm>
            </a-space>
          </template>
        </template>
      </a-table>
    </a-card>

    <a-modal v-model:open="modalOpen" :title="editing ? '编辑模型' : '新增模型'" width="760px" @ok="submitForm">
      <a-form layout="vertical">
        <a-row :gutter="16">
          <a-col :span="12">
            <a-form-item label="model_code" required>
              <a-input v-model:value="form.model_code" placeholder="chat-deepseek-pro" />
            </a-form-item>
          </a-col>
          <a-col :span="12">
            <a-form-item label="model_type" required>
              <a-select v-model:value="form.model_type">
                <a-select-option value="chat">chat</a-select-option>
                <a-select-option value="embedding">embedding</a-select-option>
                <a-select-option value="rerank">rerank</a-select-option>
              </a-select>
            </a-form-item>
          </a-col>
        </a-row>
        <a-row :gutter="16">
          <a-col :span="form.model_type === 'embedding' ? 8 : 12">
            <a-form-item label="model_name" required>
              <a-input v-model:value="form.model_name" placeholder="deepseek-chat" />
            </a-form-item>
          </a-col>
          <a-col v-if="form.model_type === 'embedding'" :span="8">
            <a-form-item label="向量维度" required>
              <a-input-number
                v-model:value="embeddingDimension"
                :min="1"
                :precision="0"
                style="width: 100%"
                placeholder="例如 1024"
              />
            </a-form-item>
          </a-col>
          <a-col v-if="form.model_type === 'embedding'" :span="8">
            <a-form-item label="批大小">
              <a-input-number
                v-model:value="embeddingBatchSize"
                :min="1"
                :max="256"
                :precision="0"
                style="width: 100%"
              />
            </a-form-item>
          </a-col>
        </a-row>
        <a-form-item label="base_url" required>
          <a-input v-model:value="form.base_url" placeholder="https://api.deepseek.com" />
        </a-form-item>
        <a-form-item label="api_key">
          <a-input-password v-model:value="form.api_key" placeholder="可直接查看、修改或清空" />
        </a-form-item>
        <a-form-item label="能力标记">
          <a-space wrap>
            <a-checkbox v-model:checked="form.support_stream">流式输出</a-checkbox>
            <a-checkbox v-model:checked="form.support_tool_calling">工具调用</a-checkbox>
            <a-checkbox v-model:checked="form.support_structured_output">结构化输出</a-checkbox>
            <a-checkbox v-model:checked="form.is_multimodal">多模态</a-checkbox>
            <a-checkbox v-model:checked="form.enabled">启用</a-checkbox>
          </a-space>
        </a-form-item>
        <a-form-item label="description">
          <a-textarea v-model:value="form.description" :rows="3" />
        </a-form-item>
      </a-form>
    </a-modal>
  </div>
</template>

<script setup lang="ts">
/** 模型配置管理页逻辑。 */
import { computed, onMounted, reactive, ref } from 'vue'
import { message } from 'ant-design-vue'
import { deleteModelConfigs, searchModelConfigs, upsertModelConfig, type ModelConfigItem, type ModelConfigUpsertPayload, type ModelType } from '@/api/modelConfigs'

defineOptions({ name: 'ModelConfigView' })

const loading = ref(false)
const modalOpen = ref(false)
const editing = ref(false)
const originalModelCode = ref<string | null>(null)
const items = ref<ModelConfigItem[]>([])
const total = ref(0)

const filters = reactive<{ keyword?: string; model_type?: ModelType; enabled?: boolean; page: number; page_size: number }>({
  keyword: undefined,
  model_type: undefined,
  enabled: undefined,
  page: 1,
  page_size: 20,
})

const form = reactive<ModelConfigUpsertPayload>({
  model_code: '',
  model_name: '',
  model_type: 'chat',
  base_url: '',
  api_key: undefined,
  api_type: 'openai_compatible',
  support_stream: true,
  support_tool_calling: true,
  support_structured_output: true,
  is_multimodal: false,
  enabled: true,
  description: '',
  extra_config: {},
})

const embeddingDimension = computed<number | undefined>({
  /** 从模型扩展配置读取 Embedding 向量维度。 */
  get() {
    const value = form.extra_config?.dimension
    return typeof value === 'number' ? value : undefined
  },
  /** 将向量维度写回模型扩展配置，供知识库创建时读取。 */
  set(value) {
    form.extra_config = {
      ...(form.extra_config || {}),
      dimension: value,
    }
  },
})

const embeddingBatchSize = computed<number>({
  /** 读取 Embedding 单次请求的文本数量，旧配置默认显示 32。 */
  get() {
    const value = form.extra_config?.batch_size
    return typeof value === 'number' ? value : 32
  },
  /** 把批大小写回模型扩展配置。 */
  set(value) {
    form.extra_config = {
      ...(form.extra_config || {}),
      batch_size: value,
    }
  },
})

const columns = [
  { title: 'model_code', key: 'model_code', dataIndex: 'model_code' },
  { title: 'model_name', key: 'model_name', dataIndex: 'model_name' },
  { title: '类型', key: 'model_type', dataIndex: 'model_type', width: 110 },
  { title: '能力', key: 'capabilities' },
  { title: 'API Key', key: 'api_key', width: 110 },
  { title: '状态', key: 'enabled', width: 90 },
  { title: '操作', key: 'action', width: 150 },
]

const pagination = computed(() => ({
  current: filters.page,
  pageSize: filters.page_size,
  total: total.value,
  showSizeChanger: true,
}))

/** 重置弹窗表单。 */
function resetForm() {
  originalModelCode.value = null
  Object.assign(form, {
    model_code: '',
    model_name: '',
    model_type: 'chat',
    base_url: '',
    api_key: undefined,
    api_type: 'openai_compatible',
    support_stream: true,
    support_tool_calling: true,
    support_structured_output: true,
    is_multimodal: false,
    enabled: true,
    description: '',
    extra_config: {},
  })
}

/** 加载模型配置列表。 */
async function loadModels() {
  loading.value = true
  try {
    const page = await searchModelConfigs(filters)
    items.value = page.items || []
    total.value = page.total || 0
  } finally {
    loading.value = false
  }
}

/** 打开新增弹窗。 */
function openCreate() {
  editing.value = false
  resetForm()
  modalOpen.value = true
}

/** 打开编辑弹窗。 */
function openEdit(record: ModelConfigItem) {
  editing.value = true
  originalModelCode.value = record.model_code
  Object.assign(form, {
    ...record,
    api_key: record.api_key || undefined,
  })
  modalOpen.value = true
}

/** 保存模型配置。 */
async function submitForm() {
  if (!form.model_code || !form.model_name || !form.base_url) {
    message.warning('请填写 model_code、model_name 和 base_url')
    return
  }
  if (form.model_type === 'embedding' && !embeddingDimension.value) {
    message.warning('Embedding 模型必须配置向量维度')
    return
  }
  await upsertModelConfig({
    ...form,
    original_model_code: editing.value ? originalModelCode.value : null,
  })
  message.success('保存成功')
  modalOpen.value = false
  await loadModels()
}

/** 删除单个模型配置。 */
async function deleteOne(modelCode: string) {
  await deleteModelConfigs([modelCode])
  message.success('删除成功')
  await loadModels()
}

/** 响应表格分页变化。 */
function onTableChange(pager: { current?: number; pageSize?: number }) {
  filters.page = pager.current || 1
  filters.page_size = pager.pageSize || 20
  loadModels()
}

onMounted(loadModels)
</script>

<style scoped>
.page-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 16px;
}
.page-title {
  margin: 0;
  font-size: 20px;
  font-weight: 600;
}
.mb-4 {
  margin-bottom: 16px;
}
</style>
