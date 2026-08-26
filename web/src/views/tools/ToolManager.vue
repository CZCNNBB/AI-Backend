<!-- HTTP API 转 MCP Tool 管理页面。 -->
<template>
  <div>
    <div class="page-header">
      <h2 class="page-title">MCP 工具管理</h2>
      <a-button type="primary" @click="openCreateModal">新增 API 工具</a-button>
    </div>

    <a-row :gutter="16">
      <a-col :span="9">
        <a-card title="工具列表" :loading="loading">
          <a-empty v-if="!tools.length" description="暂无工具" />
          <a-list v-else :data-source="tools" :pagination="{ pageSize: 10 }">
            <template #renderItem="{ item }">
              <a-list-item
                :class="['tool-item', { active: selectedTool?.name === item.name }]"
                @click="selectTool(item)"
              >
                <a-list-item-meta>
                  <template #title>
                    <a-space>
                      <span>{{ item.name }}</span>
                      <a-tag :color="statusColor(item.status)">{{ statusText(item.status) }}</a-tag>
                    </a-space>
                  </template>
                  <template #description>
                    <div class="tool-desc">{{ item.http_method }} {{ item.api_url }}</div>
                  </template>
                </a-list-item-meta>
              </a-list-item>
            </template>
          </a-list>
        </a-card>
      </a-col>

      <a-col :span="15">
        <a-card :title="selectedTool ? `工具详情 - ${selectedTool.name}` : '工具详情'">
          <a-empty v-if="!selectedTool" description="请先选择左侧工具" />
          <div v-else>
            <a-descriptions :column="1" size="small" bordered class="mb-4">
              <a-descriptions-item label="目标 API">
                {{ selectedTool.http_method }} {{ selectedTool.api_url }}
              </a-descriptions-item>
              <a-descriptions-item label="状态">
                <a-tag :color="statusColor(selectedTool.status)">{{ statusText(selectedTool.status) }}</a-tag>
              </a-descriptions-item>
              <a-descriptions-item label="说明">{{ selectedTool.description || '暂无说明' }}</a-descriptions-item>
              <a-descriptions-item label="超时">{{ selectedTool.timeout_seconds }} 秒</a-descriptions-item>
            </a-descriptions>

            <a-space class="mb-4">
              <a-button
                v-if="selectedTool.status !== 'enabled'"
                type="primary"
                @click="changePublishStatus(true)"
              >发布 Tool</a-button>
              <a-button v-else danger @click="changePublishStatus(false)">停用 Tool</a-button>
            </a-space>

            <a-tabs>
              <a-tab-pane key="invoke" tab="调试调用">
                <a-alert
                  v-if="selectedTool.status !== 'enabled'"
                  type="warning"
                  show-icon
                  class="mb-4"
                  message="当前 Tool 尚未发布，请先发布后再通过 MCP 调用。"
                />
                <a-textarea v-model:value="argsJsonText" :rows="9" class="json-input" />
                <a-space class="mt-3">
                  <a-button
                    type="primary"
                    :loading="running"
                    :disabled="selectedTool.status !== 'enabled'"
                    @click="onRun"
                  >调用工具</a-button>
                  <a-button @click="resetArgsJson">重置参数</a-button>
                  <a-button @click="formatArgsJson">格式化 JSON</a-button>
                </a-space>
              </a-tab-pane>
              <a-tab-pane key="schema" tab="自动生成 Schema">
                <pre class="result-box light">{{ prettyJson(selectedTool.input_schema || {}) }}</pre>
              </a-tab-pane>
              <a-tab-pane key="mapping" tab="参数映射">
                <pre class="result-box light">{{ prettyJson(selectedTool.parameters || []) }}</pre>
              </a-tab-pane>
            </a-tabs>

            <a-divider>调用结果</a-divider>
            <a-spin :spinning="running">
              <pre v-if="result" class="result-box">{{ result }}</pre>
              <a-empty v-else description="尚无结果" />
            </a-spin>
          </div>
        </a-card>
      </a-col>
    </a-row>

    <a-modal
      v-model:open="createModalOpen"
      title="配置 HTTP API 为 MCP Tool"
      :confirm-loading="saving"
      width="1000px"
      @ok="onCreateMcpTool"
    >
      <a-form layout="vertical">
        <a-row :gutter="12">
          <a-col :span="12">
            <a-form-item label="MCP Tool 名称" required>
              <a-input v-model:value="createForm.name" placeholder="例如 search_jobs" />
            </a-form-item>
          </a-col>
          <a-col :span="6">
            <a-form-item label="HTTP 方法">
              <a-select v-model:value="createForm.http_method" :options="httpMethodOptions" />
            </a-form-item>
          </a-col>
          <a-col :span="6">
            <a-form-item label="保存状态">
              <a-select v-model:value="createForm.status" :options="statusOptions" />
            </a-form-item>
          </a-col>
        </a-row>

        <a-form-item label="目标业务 API" required>
          <a-input v-model:value="createForm.api_url" placeholder="http://127.0.0.1:8080/api/jobs/{job_id}" />
        </a-form-item>
        <a-form-item label="工具描述">
          <a-textarea v-model:value="createForm.description" :rows="2" />
        </a-form-item>

        <a-divider orientation="left">参数映射</a-divider>
        <a-alert
          class="mb-4"
          type="info"
          show-icon
          message="Agent 参数由模型填写；Runtime inputs 从请求上下文注入；固定值会按所选类型自动解析。"
          description='固定字符串直接填 high（不加引号）；object 填 {"type":"enabled"}；array 填 ["a","b"]；boolean 填 true 或 false。'
        />
        <div v-for="(parameter, index) in createForm.parameters" :key="index" class="parameter-row">
          <a-row :gutter="8" align="middle">
            <a-col :span="6"><a-input v-model:value="parameter.name" placeholder="API 参数字段名" /></a-col>
            <a-col :span="3"><a-select v-model:value="parameter.source" :options="sourceOptions" /></a-col>
            <a-col :span="3"><a-select v-model:value="parameter.location" :options="locationOptions" /></a-col>
            <a-col :span="3"><a-select v-model:value="parameter.data_type" :options="parameterTypeOptions" /></a-col>
            <a-col :span="6">
              <a-input
                v-if="parameter.source === 'runtime'"
                v-model:value="parameter.runtime_path"
                placeholder="inputs 点分路径"
              />
              <a-input
                v-else-if="parameter.source === 'static'"
                v-model:value="parameter.value"
                :placeholder="staticValuePlaceholder(parameter.data_type)"
              />
              <a-switch
                v-else
                v-model:checked="parameter.required"
                checked-children="必填"
                un-checked-children="可选"
              />
            </a-col>
            <a-col :span="3"><a-button danger @click="removeParameter(index)">删除</a-button></a-col>
          </a-row>
          <a-input v-model:value="parameter.description" class="mt-2" placeholder="参数说明（给 Agent 阅读）" />
        </div>
        <a-button block type="dashed" @click="addParameter">新增参数</a-button>

        <a-divider orientation="left">请求头与认证</a-divider>
        <a-row :gutter="12">
          <a-col :span="12">
            <a-form-item label="固定请求头 JSON">
              <a-textarea v-model:value="staticHeadersText" :rows="4" placeholder='{"X-App-Id":"ai-platform"}' />
            </a-form-item>
          </a-col>
          <a-col :span="12">
            <a-form-item label="认证类型">
              <a-select v-model:value="createForm.auth_type" :options="authTypeOptions" />
            </a-form-item>
            <a-form-item label="认证配置 JSON">
              <a-textarea v-model:value="authConfigText" :rows="2" placeholder='Bearer：{"token":"..."}' />
            </a-form-item>
          </a-col>
        </a-row>

        <a-divider orientation="left">保存前测试</a-divider>
        <a-row :gutter="12">
          <a-col :span="12">
            <a-form-item label="Tool 参数 JSON">
              <a-textarea v-model:value="testArgsText" :rows="4" placeholder='{"keyword":"Python"}' />
            </a-form-item>
          </a-col>
          <a-col :span="12">
            <a-form-item label="模拟 runtime inputs JSON">
              <a-textarea v-model:value="testRuntimeInputsText" :rows="4" placeholder='{"tenant_id":"t-001"}' />
            </a-form-item>
          </a-col>
        </a-row>
        <a-button :loading="testingApi" @click="onTestApi">测试 API 连通性</a-button>
        <pre v-if="testApiResult" class="result-box mt-3">{{ testApiResult }}</pre>
      </a-form>
    </a-modal>
  </div>
</template>

<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { message } from 'ant-design-vue'
import {
  publishMcpTool,
  searchMcpTools,
  testMcpTool,
  upsertMcpTool,
  type McpToolParameter,
  type McpToolUpsertRequest,
  type McpToolView,
} from '@/api/mcp'
import { invokeAgentTool } from '@/api/tools'

defineOptions({ name: 'ToolManagerView' })

const loading = ref(false)
const tools = ref<McpToolView[]>([])
const selectedTool = ref<McpToolView | null>(null)
const running = ref(false)
const result = ref('')
const argsJsonText = ref('{}')
const createModalOpen = ref(false)
const saving = ref(false)
const testingApi = ref(false)
const testApiResult = ref('')
const staticHeadersText = ref('{}')
const authConfigText = ref('{}')
const testArgsText = ref('{}')
const testRuntimeInputsText = ref('{}')

const httpMethodOptions = ['GET', 'POST', 'PUT', 'PATCH', 'DELETE'].map((value) => ({ label: value, value }))
const statusOptions = [
  { label: '草稿（测试后再发布）', value: 'draft' },
  { label: '直接发布', value: 'enabled' },
]
const sourceOptions = [
  { label: 'Agent 参数', value: 'tool' },
  { label: 'Runtime inputs', value: 'runtime' },
  { label: '固定值', value: 'static' },
]
const locationOptions = ['path', 'query', 'header', 'body'].map((value) => ({ label: value, value }))
const parameterTypeOptions = ['string', 'integer', 'number', 'boolean', 'object', 'array'].map((value) => ({ label: value, value }))
const authTypeOptions = [
  { label: '无认证', value: 'none' },
  { label: 'Bearer Token', value: 'bearer' },
  { label: 'Basic Auth', value: 'basic' },
  { label: 'API Key', value: 'api_key' },
]

const createForm = reactive<McpToolUpsertRequest>(createEmptyForm())

/** 创建一份新的 API Tool 表单初始值。 */
function createEmptyForm(): McpToolUpsertRequest {
  return {
    name: '',
    description: '',
    api_url: '',
    http_method: 'POST',
    static_headers: {},
    parameters: [],
    auth_type: 'none',
    auth_config: {},
    output_schema: null,
    timeout_seconds: 30,
    status: 'draft',
  }
}

/** 加载包含草稿、已发布和已停用状态的工具列表。 */
async function load() {
  loading.value = true
  try {
    const response = await searchMcpTools()
    tools.value = response.items || []
    if (selectedTool.value) {
      selectedTool.value = tools.value.find((item) => item.name === selectedTool.value?.name) || null
    }
    if (!selectedTool.value && tools.value.length) selectTool(tools.value[0])
  } finally {
    loading.value = false
  }
}

/** 打开新增 API Tool 弹窗并清理上一次输入。 */
function openCreateModal() {
  Object.assign(createForm, createEmptyForm())
  staticHeadersText.value = '{}'
  authConfigText.value = '{}'
  testArgsText.value = '{}'
  testRuntimeInputsText.value = '{}'
  testApiResult.value = ''
  addParameter()
  createModalOpen.value = true
}

/** 新增一行默认的 Agent 参数映射。 */
function addParameter() {
  createForm.parameters.push({
    name: '',
    source: 'tool',
    location: 'body',
    data_type: 'string',
    required: false,
    description: '',
  })
}

/** 删除指定索引的参数映射。 */
function removeParameter(index: number) {
  createForm.parameters.splice(index, 1)
}

/** 构造保存和测试共用的规范化请求。 */
function buildToolPayload(): McpToolUpsertRequest {
  if (!createForm.name.trim() || !createForm.api_url.trim()) {
    throw new Error('请填写 MCP Tool 名称和目标业务 API')
  }
  const normalizedParameters = createForm.parameters
    .filter((parameter) => parameter.name.trim())
    .map((parameter) => ({
      ...parameter,
      name: parameter.name.trim(),
      description: parameter.description?.trim() || null,
      runtime_path: parameter.runtime_path?.trim() || null,
      value: parameter.source === 'static'
        ? parseStaticValue(parameter.value, parameter.data_type, parameter.name)
        : parameter.value,
    }))
  return {
    ...createForm,
    name: createForm.name.trim(),
    description: createForm.description?.trim() || null,
    api_url: createForm.api_url.trim(),
    static_headers: parseJsonObject(staticHeadersText.value, '固定请求头 JSON'),
    auth_config: parseJsonObject(authConfigText.value, '认证配置 JSON'),
    parameters: normalizedParameters,
  }
}

/** 根据固定值类型返回无需二次猜测的填写示例。 */
function staticValuePlaceholder(dataType: McpToolParameter['data_type']) {
  const placeholders: Record<McpToolParameter['data_type'], string> = {
    string: '例如 high（不加引号）',
    integer: '例如 1',
    number: '例如 0.7',
    boolean: 'true 或 false',
    object: '例如 {"type":"enabled"}',
    array: '例如 ["a","b"]',
  }
  return placeholders[dataType]
}

/** 按用户选择的数据类型解析固定值，避免对象或布尔值被错误发送为字符串。 */
function parseStaticValue(
  rawValue: any,
  dataType: McpToolParameter['data_type'],
  parameterName: string,
): any {
  if (dataType === 'string') {
    // 字符串采用直接输入规则：high 就表示 "high"，用户不需要额外添加 JSON 引号。
    return String(rawValue ?? '')
  }

  const normalizedText = String(rawValue ?? '').trim()
  if (!normalizedText) {
    throw new Error(`固定参数 ${parameterName} 不能为空`)
  }

  if (dataType === 'boolean') {
    if (normalizedText === 'true') return true
    if (normalizedText === 'false') return false
    throw new Error(`固定参数 ${parameterName} 必须填写 true 或 false`)
  }

  if (dataType === 'integer' || dataType === 'number') {
    const numberValue = Number(normalizedText)
    if (!Number.isFinite(numberValue)) {
      throw new Error(`固定参数 ${parameterName} 必须是有效数字`)
    }
    if (dataType === 'integer' && !Number.isInteger(numberValue)) {
      throw new Error(`固定参数 ${parameterName} 必须是整数`)
    }
    return numberValue
  }

  let jsonValue: any
  try {
    jsonValue = JSON.parse(normalizedText)
  } catch (error: any) {
    throw new Error(`固定参数 ${parameterName} 的 JSON 格式错误：${error?.message || error}`)
  }

  if (dataType === 'object' && (!jsonValue || typeof jsonValue !== 'object' || Array.isArray(jsonValue))) {
    throw new Error(`固定参数 ${parameterName} 必须是 JSON 对象`)
  }
  if (dataType === 'array' && !Array.isArray(jsonValue)) {
    throw new Error(`固定参数 ${parameterName} 必须是 JSON 数组`)
  }
  return jsonValue
}

/** 保存 API Tool 配置；enabled 状态会立即热发布到 /mcp。 */
async function onCreateMcpTool() {
  saving.value = true
  try {
    await upsertMcpTool(buildToolPayload())
    message.success('API Tool 已保存')
    createModalOpen.value = false
    await load()
  } catch (error: any) {
    message.error(error?.message || String(error))
  } finally {
    saving.value = false
  }
}

/** 使用未保存配置测试目标 API、请求头、认证和参数映射。 */
async function onTestApi() {
  testingApi.value = true
  testApiResult.value = ''
  try {
    const response = await testMcpTool({
      tool: buildToolPayload(),
      args: parseJsonObject(testArgsText.value, 'Tool 参数 JSON'),
      runtime_inputs: parseJsonObject(testRuntimeInputsText.value, 'Runtime inputs JSON'),
    })
    testApiResult.value = prettyJson(response)
    message.success(`API 测试成功，HTTP ${response.status_code}，耗时 ${response.elapsed_ms}ms`)
  } catch (error: any) {
    testApiResult.value = `测试失败：${error?.message || error}`
  } finally {
    testingApi.value = false
  }
}

/** 发布或停用当前 Tool，并刷新管理列表。 */
async function changePublishStatus(enabled: boolean) {
  if (!selectedTool.value) return
  await publishMcpTool(selectedTool.value.name, enabled)
  message.success(enabled ? 'Tool 已发布' : 'Tool 已停用')
  await load()
}

/** 选择一个工具并生成调试参数模板。 */
function selectTool(tool: McpToolView) {
  selectedTool.value = tool
  result.value = ''
  resetArgsJson()
}

/** 根据自动生成的输入 Schema 构造调试参数示例。 */
function resetArgsJson() {
  argsJsonText.value = prettyJson(buildExampleArgs(selectedTool.value?.input_schema || {}))
  result.value = ''
}

/** 格式化调试参数 JSON。 */
function formatArgsJson() {
  argsJsonText.value = prettyJson(parseJsonObject(argsJsonText.value, '参数 JSON'))
}

/** 通过 Agent 调试入口执行已发布 MCP Tool。 */
async function onRun() {
  if (!selectedTool.value) return
  running.value = true
  result.value = ''
  try {
    const args = parseJsonObject(argsJsonText.value, '参数 JSON')
    const response = await invokeAgentTool({ tool_name: selectedTool.value.name, args })
    result.value = prettyJson(response)
  } catch (error: any) {
    result.value = `调用失败：${error?.message || error}`
  } finally {
    running.value = false
  }
}

/** 解析并校验 JSON 对象文本。 */
function parseJsonObject(value: string, label: string): Record<string, any> {
  const text = value.trim() || '{}'
  const parsed = JSON.parse(text)
  if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) {
    throw new Error(`${label} 必须是 JSON 对象`)
  }
  return parsed
}

/** 根据 JSON Schema 的属性类型生成简单示例。 */
function buildExampleArgs(schema: Record<string, any>) {
  const example: Record<string, unknown> = {}
  Object.entries(schema?.properties || {}).forEach(([name, rawSchema]) => {
    const item = rawSchema as Record<string, any>
    if (item.default !== undefined) example[name] = item.default
    else if (item.type === 'array') example[name] = []
    else if (item.type === 'object') example[name] = {}
    else if (item.type === 'boolean') example[name] = false
    else if (item.type === 'integer' || item.type === 'number') example[name] = 0
    else example[name] = ''
  })
  return example
}

/** 返回工具状态的中文展示文本。 */
function statusText(status: string) {
  return { draft: '草稿', enabled: '已发布', disabled: '已停用' }[status] || status
}

/** 返回工具状态对应的标签颜色。 */
function statusColor(status: string) {
  return { draft: 'orange', enabled: 'green', disabled: 'red' }[status] || 'default'
}

/** 格式化任意 JSON 数据。 */
function prettyJson(value: unknown) {
  return JSON.stringify(value, null, 2)
}

onMounted(load)
</script>

<style scoped>
.page-header { display: flex; align-items: center; justify-content: space-between; margin-bottom: 16px; }
.page-title { margin: 0; font-size: 20px; font-weight: 600; }
.tool-item { cursor: pointer; transition: background 0.2s; }
.tool-item:hover { background: #f5f5f5; }
.tool-item.active { background: #e6f4ff; }
.tool-desc { color: #6b7280; font-size: 12px; line-height: 1.5; word-break: break-all; }
.parameter-row { padding: 12px; margin-bottom: 10px; border: 1px solid #e5e7eb; border-radius: 6px; }
.json-input textarea { font-family: Consolas, Monaco, 'Courier New', monospace; }
.result-box { margin: 0; padding: 12px; max-height: 420px; overflow: auto; border-radius: 4px; background: #1e1e1e; color: #d4d4d4; font-size: 12px; }
.result-box.light { background: #f8fafc; color: #111827; border: 1px solid #e5e7eb; }
.mb-4 { margin-bottom: 16px; }
.mt-2 { margin-top: 8px; }
.mt-3 { margin-top: 12px; }
</style>
