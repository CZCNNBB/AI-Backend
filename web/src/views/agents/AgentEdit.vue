<!--
  3. Agent 模板编辑页（创建/编辑共用）
  - 完整配置表单：基本信息、Prompt、工具、模型、可选能力
  - form.config 字段严格对齐后端 AgentTemplateConfig
-->
<template>
  <div>
    <h2 class="page-title">{{ isEdit ? '✏️ 编辑 Agent' : '➕ 新建 Agent' }}</h2>

    <a-form
      :model="form"
      :rules="rules"
      ref="formRef"
      layout="vertical"
      :label-col="{ style: { width: '140px' } }"
    >
      <!-- 基本信息 -->
      <a-card title="基本信息" class="mb-4">
        <a-row :gutter="16">
          <a-col :span="12">
            <a-form-item label="Agent ID" name="agent_id" required>
              <a-input v-model:value="form.agent_id" :disabled="isEdit" placeholder="唯一标识，创建后不可改" />
            </a-form-item>
          </a-col>
          <a-col :span="12">
            <a-form-item label="展示名称" name="agent_name" required>
              <a-input v-model:value="form.agent_name" placeholder="用户可见的 Agent 名称" />
            </a-form-item>
          </a-col>
        </a-row>
        <a-form-item label="描述" name="description">
          <a-textarea v-model:value="form.description" :rows="2" placeholder="Agent 用途简介" />
        </a-form-item>
        <a-form-item label="所属业务平台" name="platform_ids" required>
          <a-select
            v-model:value="form.platform_ids"
            mode="multiple"
            placeholder="先选择该 Agent 可以提供给哪些业务平台"
            :options="platformOptions"
            show-search
            option-filter-prop="label"
            @change="loadEligibleTools"
          />
          <div class="text-gray-500 mt-1">工具列表只展示同时覆盖这里全部业务平台的 MCP Tool。</div>
        </a-form-item>
        <a-form-item label="状态" name="status">
          <a-radio-group v-model:value="form.status">
            <a-radio value="active">启用</a-radio>
            <a-radio value="disabled">禁用</a-radio>
          </a-radio-group>
        </a-form-item>
      </a-card>

      <!-- Prompt 配置 -->
      <a-card title="Prompt 配置" class="mb-4">
        <a-form-item label="系统提示词" name="config.system_prompt">
          <a-textarea v-model:value="form.config.system_prompt" :rows="6" placeholder="System prompt" />
        </a-form-item>

      </a-card>

      <!-- 工具配置 -->
      <a-card title="工具配置" class="mb-4">
        <a-form-item label="绑定工具" name="config.tools">
          <a-select
            v-model:value="form.config.tools"
            mode="multiple"
            placeholder="选择该 Agent 可调用的常规工具"
            style="width: 100%"
            :options="toolOptions"
            show-search
            option-filter-prop="label"
          />
        </a-form-item>
      </a-card>

      <!-- A2A 调度配置 -->
      <a-card title="A2A 调度配置" class="mb-4">
        <a-form-item label="可调用子 Agent">
          <a-select
            v-model:value="a2aSubAgentList"
            mode="multiple"
            placeholder="选择后，该 Agent 运行时会动态获得 a2a_call 工具"
            style="width: 100%"
            :options="subAgentOptions"
            show-search
            option-filter-prop="label"
            allow-clear
          />
          <div class="text-gray-500 mt-1">
            留空表示不启用 A2A。只有声明为“可被 A2A 调用”的 Agent 会出现在这里。
          </div>
        </a-form-item>
      </a-card>

      <!-- 模型运行参数（config.runtime_options） -->
      <a-card title="模型运行参数 (runtime_options)" class="mb-4">
        <a-row :gutter="16">
          <a-col :span="8">
            <a-form-item label="模型别名">
              <a-select v-model:value="form.config.runtime_options!.model_code" placeholder="选择模型" :options="modelOptions" allow-clear />
            </a-form-item>
          </a-col>
          <a-col :span="8">
            <a-form-item label="温度 (0~2)">
              <a-input-number v-model:value="form.config.runtime_options!.temperature" :min="0" :max="2" :step="0.1" style="width: 100%" />
            </a-form-item>
          </a-col>
          <a-col :span="8">
            <a-form-item label="最大输出 tokens">
              <a-input-number v-model:value="form.config.runtime_options!.max_tokens" :min="1" style="width: 100%" />
            </a-form-item>
          </a-col>
        </a-row>
        <a-row :gutter="16">
          <a-col :span="8">
            <a-form-item label="超时时间(秒)">
              <a-input-number v-model:value="form.config.runtime_options!.timeout_seconds" :min="1" style="width: 100%" />
            </a-form-item>
          </a-col>
          <a-col :span="8">
            <a-form-item label="最大重试次数">
              <a-input-number v-model:value="form.config.runtime_options!.max_retries" :min="0" :max="10" />
            </a-form-item>
          </a-col>
        </a-row>
      </a-card>


      <!-- 会话上下文总结配置（config.context_summarization） -->
      <a-card title="会话上下文总结" class="mb-4">
        <a-form-item label="启用会话总结">
          <a-switch v-model:checked="contextSummarizationEnabled" />
          <span class="text-gray-500 ml-2">开启后，Agent 会使用独立模型压缩过长的会话工作上下文</span>
        </a-form-item>
        <template v-if="contextSummarizationEnabled && form.config.context_summarization">
          <a-row :gutter="16">
            <a-col :span="8">
              <a-form-item label="总结模型" required>
                <a-select
                  v-model:value="form.config.context_summarization.model_code"
                  placeholder="选择已启用的 Chat 模型"
                  :options="modelOptions"
                />
              </a-form-item>
            </a-col>
            <a-col :span="8">
              <a-form-item label="触发 Token 阈值">
                <a-input-number v-model:value="form.config.context_summarization.trigger_tokens" :min="1" style="width: 100%" />
              </a-form-item>
            </a-col>
            <a-col :span="8">
              <a-form-item label="保留近期消息数">
                <a-input-number v-model:value="form.config.context_summarization.keep_messages" :min="1" style="width: 100%" />
              </a-form-item>
            </a-col>
          </a-row>
          <a-row :gutter="16">
            <a-col :span="8">
              <a-form-item label="总结输入 Token 上限">
                <a-input-number v-model:value="form.config.context_summarization.trim_tokens_to_summarize" :min="1" style="width: 100%" />
              </a-form-item>
            </a-col>
          </a-row>
        </template>
      </a-card>

      <!-- 可选能力（config.optional_features） -->
      <a-card title="可选能力 (optional_features)" class="mb-4">
        <a-form-item label="长期记忆">
          <a-switch v-model:checked="form.config.optional_features!.long_term_memory_enabled" />
          <span class="text-gray-500 ml-2">开启后可跨会话记住用户偏好</span>
        </a-form-item>
        <a-form-item label="规划模式">
          <a-switch v-model:checked="form.config.optional_features!.planning_enabled" />
          <span class="text-gray-500 ml-2">开启后复杂任务会先生成任务计划，并等待用户确认</span>
        </a-form-item>
        <a-form-item label="挂载知识库">
          <a-switch v-model:checked="form.config.optional_features!.knowledge_enabled" />
          <span class="text-gray-500 ml-2">开启后系统自动挂载知识库检索工具</span>
        </a-form-item>
        <a-form-item label="可被 A2A 调用 (is_sub_agent)">
          <a-switch v-model:checked="form.config.is_sub_agent" />
          <span class="text-gray-500 ml-2">开启后其他 Agent 可通过 A2A 工具调用本 Agent</span>
        </a-form-item>
      </a-card>

      <!-- 底部操作 -->
      <a-card>
        <a-space>
          <a-button type="primary" :loading="saving" @click="onSubmit">💾 保存</a-button>
          <a-button @click="router.back()">返回</a-button>
          <a-button v-if="isEdit" @click="router.push(`/agents/${form.agent_id}/playground`)">
            🧪 进入 Playground
          </a-button>
        </a-space>
      </a-card>
    </a-form>
  </div>
</template>

<script setup lang="ts">
/**
 * Agent 编辑页逻辑
 * - 支持新建与编辑两种模式（isEdit 通过路由参数判断）
 * - 加载工具列表与可用模型
 * - form.config 字段对齐后端 AgentTemplateConfig / ModelRuntimeOptions / AgentOptionalFeatures
 */
import { computed, onMounted, reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { message } from 'ant-design-vue'
import {
  getAgentTemplateDetail,
  searchAgentTemplates,
  type AgentTemplate,
  upsertAgentTemplate,
} from '@/api/agentTemplate'
import { listEligibleMcpTools } from '@/api/mcp'
import { searchModelConfigs } from '@/api/modelConfigs'
import { searchBusinessPlatforms } from '@/api/platform'

defineOptions({ name: 'AgentEditView' })

const route = useRoute()
const router = useRouter()
const saving = ref(false)
const formRef = ref()

// 是否为编辑模式
const isEdit = computed(() => !!route.params.agent_id)

// 表单初始值（完全对齐后端 AgentTemplateConfig）
const form = reactive<AgentTemplate>({
  agent_id: '',
  agent_name: '',
  description: '',
  platform_ids: [],
  status: 'active',
  config: {
    system_prompt: '',
    tools: [],
    is_sub_agent: false,
    runtime_options: {
      model_code: undefined,
      temperature: 0.7,
      max_tokens: undefined,
      timeout_seconds: 60,
      max_retries: 2,
    },
    optional_features: {
      long_term_memory_enabled: false,
      planning_enabled: false,
      knowledge_enabled: false,
    },
    a2a: null,
    context_summarization: null,
  },
})

/** 会话总结开关映射到配置对象是否存在，不在后端保存 enabled 字段。 */
const contextSummarizationEnabled = computed({
  get: () => !!form.config.context_summarization,
  set: (enabled: boolean) => {
    form.config.context_summarization = enabled
      ? {
          model_code: '',
          trigger_tokens: 12000,
          keep_messages: 20,
          trim_tokens_to_summarize: 4000,
        }
      : null
  },
})


// 表单校验
const rules = {
  agent_id: [{ required: true, message: '请输入 Agent ID' }],
  agent_name: [{ required: true, message: '请输入展示名称' }],
  platform_ids: [{ required: true, type: 'array', min: 1, message: '请至少选择一个业务平台' }],
}

// 下拉数据
const toolOptions = ref<{ label: string; value: string }[]>([])
const platformOptions = ref<{ label: string; value: number }[]>([])
const modelOptions = ref<{ label: string; value: string }[]>([])
const subAgentOptions = ref<{ label: string; value: string }[]>([])
const a2aSubAgentList = ref<string[]>([])

/** 加载下拉数据 */
async function loadOptions() {
  try {
    const platformPage = await searchBusinessPlatforms({ page: 1, page_size: 100, status: 'enabled' })
    platformOptions.value = (platformPage.items || []).map((item) => ({
      label: `${item.platform_name} (${item.platform_code})`,
      value: item.id,
    }))
  } catch {
    platformOptions.value = []
  }
  await loadEligibleTools()
  try {
    const modelPage = await searchModelConfigs({ page: 1, page_size: 100, model_type: 'chat', enabled: true })
    modelOptions.value = (modelPage.items || []).map((item) => ({ label: item.model_code, value: item.model_code }))
  } catch {
    modelOptions.value = []
  }
  try {
    const templatePage = await searchAgentTemplates({ page: 1, page_size: 100, status: 'active' })
    subAgentOptions.value = (templatePage.items || [])
      .filter((item) => item.config?.is_sub_agent && item.agent_id !== form.agent_id)
      .map((item) => ({ label: `${item.agent_name} (${item.agent_id})`, value: item.agent_id }))
  } catch {
    subAgentOptions.value = []
  }
}

/** 根据 Agent 当前平台集合加载可安全挂载的 MCP Tool。 */
async function loadEligibleTools() {
  if (!form.platform_ids.length) {
    toolOptions.value = []
    return
  }
  try {
    const tools = await listEligibleMcpTools(form.platform_ids)
    toolOptions.value = tools.map((item) => ({ label: item.name, value: item.name }))
  } catch {
    toolOptions.value = []
  }
}

/** 加载编辑数据 */
async function loadDetail() {
  if (!isEdit.value) return
  const detail = await getAgentTemplateDetail(route.params.agent_id as string)
  // 逐字段覆盖 form，保留 reactive 引用
  form.agent_id = detail.agent_id
  form.agent_name = detail.agent_name
  form.description = detail.description || ''
  form.platform_ids = [...(detail.platform_ids || [])]
  form.status = detail.status
  form.config = {
    ...form.config,
    ...(detail.config || {}),
    runtime_options: {
      ...form.config.runtime_options,
      ...(detail.config?.runtime_options || {}),
    },
    optional_features: {
      ...form.config.optional_features,
      ...(detail.config?.optional_features || {}),
    },
    a2a: detail.config?.a2a || null,
    context_summarization: detail.config?.context_summarization || null,
  }
  a2aSubAgentList.value = detail.config?.a2a?.sub_agent_list || []
}

/** 提交 */
async function onSubmit() {
  await formRef.value?.validate()
  form.config.a2a = a2aSubAgentList.value.length
    ? { sub_agent_list: [...a2aSubAgentList.value] }
    : null
  if (form.config.context_summarization && !form.config.context_summarization.model_code.trim()) {
    message.warning('请为会话上下文总结选择模型')
    return
  }
  saving.value = true
  try {
    const res = await upsertAgentTemplate({
      agent_id: form.agent_id,
      agent_name: form.agent_name,
      description: form.description,
      platform_ids: form.platform_ids,
      status: form.status,
      config: form.config,
    })
    message.success('保存成功')
    if (!isEdit.value) {
      router.push(`/agents/${res.agent_id || form.agent_id}/edit`)
    }
  } finally {
    saving.value = false
  }
}

onMounted(async () => {
  await loadDetail()
  await loadOptions()
})
</script>

<style scoped>
.page-title {
  margin: 0 0 16px;
  font-size: 20px;
  font-weight: 600;
}
.mb-4 {
  margin-bottom: 16px;
}
.ml-2 {
  margin-left: 8px;
}
</style>
