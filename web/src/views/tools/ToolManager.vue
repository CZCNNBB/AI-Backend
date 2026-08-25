<!--
  工具管理页
  - 只展示 MCP 外接工具，内置能力工具不在工具管理页展示
  - 支持从 MCP 地址同步工具，也支持手动新增 MCP 工具
  - 工具测试统一使用 JSON 参数，Schema 只作为参考
  - 调试调用 POST /agent/tools/invoke，后端会分发到对应 MCP 工具
-->
<template>
  <div>
    <div class="page-header">
      <h2 class="page-title">工具管理</h2>
      <a-space>
        <a-button @click="openSyncModal">同步 MCP</a-button>
        <a-button type="primary" @click="openCreateModal">新增 MCP 工具</a-button>
      </a-space>
    </div>

    <a-row :gutter="16">
      <!-- 左侧：工具列表 -->
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
                      <a-tag :color="toolGroupColor(item.group)">{{ item.group }}</a-tag>
                      <a-tag v-if="!item.invokable" color="orange">动态</a-tag>
                    </a-space>
                  </template>
                  <template #description>
                    <div class="tool-desc">{{ shortDescription(item.description) }}</div>
                  </template>
                </a-list-item-meta>
              </a-list-item>
            </template>
          </a-list>
        </a-card>
      </a-col>

      <!-- 右侧：工具详情和调试区 -->
      <a-col :span="15">
        <a-card :title="selectedTool ? `工具详情 - ${selectedTool.name}` : '工具详情'">
          <a-empty v-if="!selectedTool" description="请先选择左侧工具" />
          <div v-else>
            <a-descriptions :column="1" size="small" bordered class="mb-4">
              <a-descriptions-item label="名称">{{ selectedTool.name }}</a-descriptions-item>
              <a-descriptions-item label="分组">
                <a-tag :color="toolGroupColor(selectedTool.group)">{{ selectedTool.group }}</a-tag>
              </a-descriptions-item>
              <a-descriptions-item label="可直接调试">
                <a-tag :color="selectedTool.invokable ? 'green' : 'orange'">
                  {{ selectedTool.invokable ? '是' : '否' }}
                </a-tag>
              </a-descriptions-item>
              <a-descriptions-item v-if="selectedTool.invoke_note" label="调用说明">
                {{ selectedTool.invoke_note }}
              </a-descriptions-item>
              <a-descriptions-item label="说明">
                <pre class="description-box">{{ selectedTool.description || '暂无说明' }}</pre>
              </a-descriptions-item>
            </a-descriptions>

            <a-tabs>
              <a-tab-pane key="json" tab="参数 JSON">
                <a-alert
                  v-if="!selectedTool.invokable"
                  type="warning"
                  show-icon
                  class="mb-4"
                  :message="selectedTool.invoke_note || '该工具不能脱离 Agent 运行上下文直接调用'"
                />
                <a-textarea
                  v-model:value="argsJsonText"
                  :rows="12"
                  placeholder='例如：{"keywords":["FastAPI","PostgreSQL"]}'
                  class="json-input"
                />
                <a-space class="mt-3">
                  <a-button type="primary" :loading="running" :disabled="!selectedTool.invokable" @click="onRun">
                    调用工具
                  </a-button>
                  <a-button @click="resetArgsJson">重置参数</a-button>
                  <a-button @click="formatArgsJson">格式化 JSON</a-button>
                </a-space>
              </a-tab-pane>

              <a-tab-pane key="schema" tab="参数 Schema">
                <pre class="result-box light">{{ prettyJson(selectedTool.args_schema || {}) }}</pre>
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
      v-model:open="syncModalOpen"
      title="同步 MCP 工具"
      :confirm-loading="syncing"
      @ok="onSyncMcpTools"
    >
      <a-form layout="vertical">
        <a-form-item label="MCP 服务地址" required>
          <a-input v-model:value="syncForm.base_url" placeholder="http://127.0.0.1:8091/mcp/" allow-clear />
        </a-form-item>
        <a-form-item label="传输协议">
          <a-select v-model:value="syncForm.transport" :options="transportOptions" />
        </a-form-item>
        <a-form-item label="工具编码前缀">
          <a-input v-model:value="syncForm.code_prefix" placeholder="例如 job，同步后得到 job.search_job_skills" allow-clear />
        </a-form-item>
        <a-form-item label="覆盖已有工具">
          <a-switch v-model:checked="syncForm.overwrite" />
        </a-form-item>
      </a-form>
    </a-modal>

    <a-modal
      v-model:open="createModalOpen"
      title="新增 MCP 工具"
      :confirm-loading="saving"
      width="720px"
      @ok="onCreateMcpTool"
    >
      <a-form layout="vertical">
        <a-row :gutter="12">
          <a-col :span="12">
            <a-form-item label="平台工具编码" required>
              <a-input v-model:value="createForm.mcp_code" placeholder="job.search_job_skills" allow-clear />
            </a-form-item>
          </a-col>
          <a-col :span="12">
            <a-form-item label="MCP 真实工具名" required>
              <a-input v-model:value="createForm.name" placeholder="search_job_skills" allow-clear />
            </a-form-item>
          </a-col>
        </a-row>
        <a-form-item label="MCP 服务地址" required>
          <a-input v-model:value="createForm.base_url" placeholder="http://127.0.0.1:8091/mcp/" allow-clear />
        </a-form-item>
        <a-form-item label="传输协议">
          <a-select v-model:value="createForm.transport" :options="transportOptions" />
        </a-form-item>
        <a-form-item label="工具描述">
          <a-textarea v-model:value="createForm.description" :rows="3" allow-clear />
        </a-form-item>
        <a-form-item label="输入参数 JSON Schema">
          <a-textarea v-model:value="createSchemaText" :rows="8" placeholder='例如：{"type":"object","properties":{"keywords":{"type":"array"}},"required":["keywords"]}' />
        </a-form-item>
      </a-form>
    </a-modal>
  </div>
</template>

<script setup lang="ts">
/**
 * 工具管理页逻辑。
 * - 从 /agent/capabilities 读取 MCP 外接工具详情。
 * - 支持同步 MCP 服务工具和手动新增 MCP 工具。
 * - 使用 JSON 参数测试工具，避免为复杂 MCP Schema 维护沉重的动态表单。
 * - 通过 /agent/tools/invoke 调试调用 MCP 工具。
 */
import { onMounted, reactive, ref } from 'vue'
import { message } from 'ant-design-vue'
import { getCapabilities, type AgentToolInfo } from '@/api/capabilities'
import { syncMcpTools, upsertMcpTool } from '@/api/mcp'
import { invokeAgentTool } from '@/api/tools'

defineOptions({ name: 'ToolManagerView' })

const loading = ref(false)
const tools = ref<AgentToolInfo[]>([])
const selectedTool = ref<AgentToolInfo | null>(null)
const running = ref(false)
const result = ref('')
const argsJsonText = ref('{}')
const syncModalOpen = ref(false)
const createModalOpen = ref(false)
const syncing = ref(false)
const saving = ref(false)
const createSchemaText = ref('')

const transportOptions = [
  { label: 'http', value: 'http' },
  { label: 'streamable-http', value: 'streamable-http' },
  { label: 'sse', value: 'sse' },
]

const syncForm = reactive({
  base_url: 'http://127.0.0.1:8091/mcp/',
  transport: 'http',
  code_prefix: 'job',
  overwrite: true,
})

const createForm = reactive({
  mcp_code: '',
  name: '',
  description: '',
  base_url: 'http://127.0.0.1:8091/mcp/',
  transport: 'http',
  status: 'enabled',
})

/** 加载工具详情列表。 */
async function load() {
  loading.value = true
  try {
    const cap = await getCapabilities()
    // 工具管理页只管理 MCP 外接工具。
    // A2A、规划等内置能力工具由系统参数自动挂载，不展示在这里，避免用户误配置到模板 tools。
    const capabilityTools = cap.tools || []
    tools.value = capabilityTools.length
      ? capabilityTools.filter((tool) => tool.group === 'mcp' && tool.template_selectable !== false)
      : (cap.registered_tools || []).map((name) => ({
          name,
          description: '',
          group: 'mcp',
          invokable: true,
          template_selectable: true,
          activation_mode: 'template',
          invoke_note: null,
          args_schema: {},
        }))

    if (selectedTool.value && !tools.value.some((tool) => tool.name === selectedTool.value?.name)) {
      selectedTool.value = null
    }
    if (!selectedTool.value && tools.value.length) selectTool(tools.value[0])
  } finally {
    loading.value = false
  }
}

/** 打开 MCP 同步弹窗。 */
function openSyncModal() {
  syncModalOpen.value = true
}

/** 打开手动新增 MCP 工具弹窗。 */
function openCreateModal() {
  resetCreateForm()
  createModalOpen.value = true
}

/** 重置手动新增 MCP 工具表单。 */
function resetCreateForm() {
  createForm.mcp_code = ''
  createForm.name = ''
  createForm.description = ''
  createForm.base_url = syncForm.base_url
  createForm.transport = syncForm.transport
  createForm.status = 'enabled'
  createSchemaText.value = ''
}

/** 从 MCP 服务地址同步工具列表。 */
async function onSyncMcpTools() {
  if (!syncForm.base_url.trim()) {
    message.error('请填写 MCP 服务地址')
    return
  }
  syncing.value = true
  try {
    const res = await syncMcpTools({
      base_url: syncForm.base_url.trim(),
      transport: syncForm.transport,
      code_prefix: syncForm.code_prefix?.trim() || null,
      auth_type: null,
      auth_config: null,
      overwrite: syncForm.overwrite,
    })
    message.success(`同步完成，共 ${res.synced} 个工具`)
    syncModalOpen.value = false
    await load()
  } finally {
    syncing.value = false
  }
}

/** 手动新增或更新 MCP 工具。 */
async function onCreateMcpTool() {
  if (!createForm.mcp_code.trim() || !createForm.name.trim() || !createForm.base_url.trim()) {
    message.error('请填写平台工具编码、MCP 真实工具名和服务地址')
    return
  }
  saving.value = true
  try {
    await upsertMcpTool({
      original_mcp_code: null,
      mcp_code: createForm.mcp_code.trim(),
      name: createForm.name.trim(),
      description: createForm.description?.trim() || null,
      base_url: createForm.base_url.trim(),
      transport: createForm.transport,
      auth_type: null,
      auth_config: null,
      input_schema: parseJsonObject(createSchemaText.value, '输入参数 JSON Schema'),
      output_schema: null,
      status: createForm.status,
    })
    message.success('MCP 工具已保存')
    createModalOpen.value = false
    await load()
  } finally {
    saving.value = false
  }
}

/** 选择工具并初始化 JSON 参数。 */
function selectTool(tool: AgentToolInfo) {
  selectedTool.value = tool
  result.value = ''
  resetArgsJson()
}

/** 根据工具 Schema 生成一份可编辑的 JSON 参数模板。 */
function resetArgsJson() {
  argsJsonText.value = prettyJson(buildExampleArgs(selectedTool.value?.args_schema || {}))
  result.value = ''
}

/** 格式化当前 JSON 参数文本。 */
function formatArgsJson() {
  try {
    argsJsonText.value = prettyJson(parseJsonObject(argsJsonText.value, '参数 JSON') || {})
  } catch {
    // parseJsonObject 已经展示错误提示，这里不再重复处理。
  }
}

/** 调试调用工具。 */
async function onRun() {
  if (!selectedTool.value) return
  running.value = true
  result.value = ''
  try {
    const args = parseJsonObject(argsJsonText.value, '参数 JSON') || {}
    const res = await invokeAgentTool({ tool_name: selectedTool.value.name, args })
    result.value = prettyJson(res)
  } catch (e: any) {
    result.value = `调用失败：${e?.message || e}`
  } finally {
    running.value = false
  }
}

/** 解析 JSON 对象文本，空值返回 null。 */
function parseJsonObject(value: string, label: string) {
  const text = value.trim()
  if (!text) return null
  try {
    const parsed = JSON.parse(text)
    if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) {
      throw new Error(`${label} 必须是 JSON 对象`)
    }
    return parsed
  } catch (error: any) {
    message.error(`${label} 格式错误：${error?.message || error}`)
    throw error
  }
}

/** 根据 JSON Schema 构建简单参数示例，方便用户快速编辑。 */
function buildExampleArgs(schema: Record<string, any>) {
  const properties = schema?.properties || {}
  const example: Record<string, unknown> = {}
  Object.entries(properties).forEach(([name, raw]) => {
    const item = raw as Record<string, any>
    if (item.default !== undefined) {
      example[name] = item.default
      return
    }
    if (item.type === 'array') example[name] = []
    else if (item.type === 'boolean') example[name] = false
    else if (item.type === 'integer' || item.type === 'number') example[name] = 0
    else if (item.type === 'object') example[name] = {}
    else example[name] = ''
  })
  return example
}

/** 根据工具分组返回标签颜色。 */
function toolGroupColor(group: string) {
  if (group === 'mcp') return 'purple'
  return 'blue'
}

/** 格式化 JSON。 */
function prettyJson(value: unknown) {
  return JSON.stringify(value, null, 2)
}

/** 截断列表描述。 */
function shortDescription(value: string) {
  const firstLine = (value || '暂无说明').trim().split('\n')[0]
  return firstLine.length > 80 ? `${firstLine.slice(0, 80)}...` : firstLine
}

onMounted(load)
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
.tool-item {
  cursor: pointer;
  transition: background 0.2s;
}
.tool-item:hover {
  background: #f5f5f5;
}
.tool-item.active {
  background: #e6f4ff;
}
.tool-desc {
  color: #6b7280;
  font-size: 12px;
  line-height: 1.5;
}
.description-box {
  max-height: 160px;
  margin: 0;
  white-space: pre-wrap;
  color: #374151;
  font-size: 12px;
}
.json-input textarea {
  font-family: Consolas, Monaco, 'Courier New', monospace;
}
.result-box {
  background: #1e1e1e;
  color: #d4d4d4;
  padding: 12px;
  border-radius: 4px;
  max-height: 420px;
  overflow: auto;
  font-size: 12px;
  margin: 0;
}
.result-box.light {
  background: #f8fafc;
  color: #111827;
  border: 1px solid #e5e7eb;
}
.mb-4 {
  margin-bottom: 16px;
}
.mt-3 {
  margin-top: 12px;
}
</style>
