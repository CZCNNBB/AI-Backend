<!--
  Agent 调试台
  - 左侧:Agent 配置只读 + 运行参数控制(conversation_id、工具覆盖、特性开关)
  - 右侧:调试视图(双 tab)
    - 聊天视图:按事件类型分块展示 reasoning / tool_call / tool_result / model_delta
    - 事件流:所有 SSE 事件按时间顺序展示(支持清空、下载)
  - 严格遵循后端 SSE 事件协议(Agent流式输出前端接入说明.md)
-->
<template>
  <div class="playground">
    <h2 class="page-title">
      🧪 Agent 调试台 - {{ agentDetail?.agent_name || agentId }}
      <span v-if="running" class="running-badge">
        <a-spin size="small" /> 运行中
      </span>
    </h2>

    <a-row :gutter="16">
      <!-- 左侧:Agent 配置 + 运行参数 -->
      <a-col :span="8">
        <a-card title="📋 Agent 配置" :loading="loading" class="side-card">
          <a-descriptions v-if="agentDetail" :column="1" size="small" bordered>
            <a-descriptions-item label="Agent ID">{{ agentDetail.agent_id }}</a-descriptions-item>
            <a-descriptions-item label="名称">{{ agentDetail.agent_name }}</a-descriptions-item>
            <a-descriptions-item label="模型">
              {{ agentDetail.config?.runtime_options?.model_code || '-' }}
            </a-descriptions-item>
            <a-descriptions-item label="温度">
              {{ agentDetail.config?.runtime_options?.temperature ?? '-' }}
            </a-descriptions-item>
            <a-descriptions-item label="超时(秒)">
              {{ agentDetail.config?.runtime_options?.timeout_seconds ?? '-' }}
            </a-descriptions-item>
            <a-descriptions-item label="工具">
              <a-tag v-for="t in agentDetail.config?.tools || []" :key="t" color="purple" class="mb-1">
                {{ t }}
              </a-tag>
            </a-descriptions-item>
            <a-descriptions-item label="可被 A2A 调用">
              <a-tag :color="agentDetail.config?.is_sub_agent ? 'green' : 'default'">
                {{ agentDetail.config?.is_sub_agent ? '是' : '否' }}
              </a-tag>
            </a-descriptions-item>
            <a-descriptions-item v-if="agentDetail.config?.a2a?.sub_agent_list?.length" label="A2A 能力">
              <a-tag color="blue">已开启</a-tag>
            </a-descriptions-item>
          </a-descriptions>
          <a-empty v-else description="未加载到 Agent 配置" />

          <a-divider />

          <a-space direction="vertical" style="width: 100%">
            <div>
              <label>conversation_id</label>
              <a-input
                v-model:value="conversationId"
                placeholder="留空则自动生成"
                size="small"
                allow-clear
              />
            </div>
            <div>
              <label>工具覆盖(覆盖默认)</label>
              <a-select
                v-model:value="overrideTools"
                mode="multiple"
                size="small"
                placeholder="不选则使用模板默认"
                :options="toolOptions"
                style="width: 100%"
                allow-clear
              />
            </div>
            <div v-if="agentDetail?.config?.optional_features?.knowledge_enabled">
              <label>本次可访问知识库</label>
              <a-select
                v-model:value="selectedKnowledgeBaseIds"
                mode="multiple"
                size="small"
                placeholder="选择本次试跑允许检索的知识库"
                :options="knowledgeBaseOptions"
                style="width: 100%"
                show-search
                option-filter-prop="label"
                allow-clear
              />
            </div>
            <div>
              <a-checkbox v-model:checked="stream">流式输出</a-checkbox>
              <a-checkbox v-model:checked="memoryEnabled">长期记忆</a-checkbox>
              <a-checkbox v-model:checked="a2aEnabled">A2A 子 Agent</a-checkbox>
            </div>
            <a-button type="link" @click="router.push(`/agents/${agentId}/edit`)">
              ✏️ 编辑该 Agent
            </a-button>
          </a-space>
        </a-card>
      </a-col>

      <!-- 右侧:调试视图 -->
      <a-col :span="16">
        <a-card class="debug-card">
          <template #title>
            <a-space>
              <a-radio-group v-model:value="activeTab" size="small">
                <a-radio-button value="chat">💬 聊天视图</a-radio-button>
                <a-radio-button value="events">
                  🔍 事件流
                  <a-badge
                    v-if="rawEvents.length"
                    :count="rawEvents.length"
                    :number-style="{ backgroundColor: '#1677ff' }"
                    style="margin-left: 4px"
                  />
                </a-radio-button>
                <a-radio-button value="assembly">
                  ⚙️ 装配信息
                  <a-badge
                    v-if="assemblyInfo"
                    dot
                    :number-style="{ backgroundColor: '#52c41a' }"
                    style="margin-left: 4px"
                  />
                </a-radio-button>
              </a-radio-group>
            </a-space>
          </template>
          <template #extra>
            <a-space>
              <a-tooltip title="清空当前视图">
                <a-button size="small" @click="onClear">
                  <template #icon><DeleteOutlined /></template>
                  清空
                </a-button>
              </a-tooltip>
              <a-tooltip title="下载事件流(JSON)">
                <a-button size="small" :disabled="!rawEvents.length" @click="downloadEvents">
                  <template #icon><DownloadOutlined /></template>
                  导出
                </a-button>
              </a-tooltip>
            </a-space>
          </template>

          <!-- 聊天视图 -->
          <div v-show="activeTab === 'chat'" class="message-area">
            <a-empty v-if="!messages.length" description="开始一次对话吧" />
            <template v-else>
              <div
                v-for="(msg, i) in messages"
                :key="i"
                :class="['msg', `msg-${msg.role}`]"
              >
                <div class="msg-meta">
                  <a-tag :color="roleColor(msg.role)">{{ msg.role }}</a-tag>
                  <span v-if="msg.subtype" class="msg-subtype">{{ msg.subtype }}</span>
                  <span v-if="msg.tool_name" class="msg-tool-name">🔧 {{ msg.tool_name }}</span>
                  <span v-if="msg.event" class="msg-event-tag">{{ msg.event }}</span>
                  <span class="msg-time">{{ msg.time }}</span>
                </div>
                <div v-if="msg.subtype === 'reasoning'" class="msg-reasoning">
                  <span class="reasoning-icon">💭</span>
                  <span class="reasoning-label">思考过程</span>
                  <div class="msg-reasoning-content">{{ msg.content }}</div>
                </div>
                <div v-else-if="msg.subtype === 'tool_call'" class="msg-tool-block">
                  <div class="msg-tool-title">📤 模型请求调用工具</div>
                  <a-descriptions :column="1" size="small" :bordered="false">
                    <a-descriptions-item label="工具名">
                      <a-tag color="purple">{{ msg.tool_name }}</a-tag>
                    </a-descriptions-item>
                    <a-descriptions-item label="参数">
                      <pre class="json-block">{{ safeJson(msg.tool_args) }}</pre>
                    </a-descriptions-item>
                  </a-descriptions>
                </div>
                <div v-else-if="msg.subtype === 'tool_result'" class="msg-tool-block">
                  <div class="msg-tool-title">
                    📥 工具执行完成
                    <a-tag :color="msg.tool_status === 'failed' ? 'red' : 'green'" size="small">
                      {{ msg.tool_status === 'failed' ? '失败' : '成功' }}
                    </a-tag>
                  </div>
                  <a-descriptions :column="1" size="small" :bordered="false">
                    <a-descriptions-item label="工具名">
                      <a-tag color="purple">{{ msg.tool_name }}</a-tag>
                    </a-descriptions-item>
                    <a-descriptions-item label="输出">
                      <pre class="json-block">{{ safeJson(msg.tool_output) }}</pre>
                    </a-descriptions-item>
                  </a-descriptions>
                </div>
                <div v-else-if="msg.subtype === 'task_plan'" class="msg-plan-block">
                  <div class="msg-tool-title">🗓 任务计划</div>
                  <div class="msg-content">{{ msg.content }}</div>
                  <pre class="json-block">{{ safeJson(msg.contentJson) }}</pre>
                </div>
                <div v-else-if="msg.subtype === 'interrupt'" class="msg-interrupt-block">
                  <div class="msg-tool-title">
                    <a-tag color="orange">⏸ 中断</a-tag>
                    等待用户操作
                  </div>
                  <pre class="json-block">{{ safeJson(msg.contentJson) }}</pre>
                </div>
                <div v-else-if="msg.subtype === 'lifecycle'" class="msg-lifecycle">
                  <span class="lifecycle-icon">{{ msg.lifeIcon || '⚙️' }}</span>
                  <span>{{ msg.content }}</span>
                </div>
                <div v-else class="msg-content">{{ msg.content }}</div>

                <!-- 元信息:耗时、字数、run_id -->
                <div
                  v-if="(msg.elapsed_ms !== undefined || msg.answer_length !== undefined || msg.run_id) && !running"
                  class="msg-meta-extras"
                >
                  <span v-if="msg.elapsed_ms !== undefined" class="meta-chip">
                    <ClockCircleOutlined /> {{ formatDuration(msg.elapsed_ms) }}
                  </span>
                  <span v-if="msg.answer_length !== undefined" class="meta-chip">
                    📝 {{ msg.answer_length }} 字
                  </span>
                  <span v-if="msg.run_id" class="meta-chip meta-chip-id" :title="msg.run_id">
                    #{{ msg.run_id.slice(0, 8) }}
                  </span>
                </div>
              </div>

              <!-- 运行指示器 -->
              <div v-if="running" class="running-indicator">
                <a-spin size="small" />
                <span>正在等待事件... 已有 {{ rawEvents.length }} 条事件</span>
              </div>
            </template>
          </div>

          <!-- 事件流视图 -->
          <div v-show="activeTab === 'events'" class="events-area">
            <a-empty v-if="!rawEvents.length" description="尚无事件" />
            <div v-else class="events-list">
              <div
                v-for="(evt, i) in rawEvents"
                :key="i"
                :class="['event-item', `event-${evt.type}`]"
              >
                <div class="event-head">
                  <a-tag :color="eventColor(evt.type)" size="small">{{ evt.type }}</a-tag>
                  <span class="event-time">{{ evt.time }}</span>
                  <span v-if="evt.index !== undefined" class="event-index">#{{ evt.index }}</span>
                </div>
                <pre class="event-payload">{{ evt.payloadText }}</pre>
              </div>
            </div>
          </div>

          <!-- 装配信息视图 -->
          <div v-show="activeTab === 'assembly'" class="assembly-area">
            <a-empty v-if="!assemblyInfo && !runInfo" description="运行开始后将在此展示 Agent 装配信息" />
            <template v-else>
              <a-descriptions v-if="runInfo" title="🏃 运行信息" :column="2" size="small" bordered>
                <a-descriptions-item label="run_id">
                  <span class="mono">{{ runInfo.run_id }}</span>
                </a-descriptions-item>
                <a-descriptions-item label="thread_id">
                  <span class="mono">{{ runInfo.thread_id }}</span>
                </a-descriptions-item>
                <a-descriptions-item label="持久化会话">
                  <a-tag :color="runInfo.persistent_conversation ? 'green' : 'default'">
                    {{ runInfo.persistent_conversation ? '是' : '否' }}
                  </a-tag>
                </a-descriptions-item>
                <a-descriptions-item label="流式">
                  <a-tag :color="runInfo.stream ? 'blue' : 'default'">
                    {{ runInfo.stream ? '是' : '否' }}
                  </a-tag>
                </a-descriptions-item>
                <a-descriptions-item label="耗时">{{ formatDuration(runInfo.elapsed_ms) }}</a-descriptions-item>
                <a-descriptions-item label="回答长度">{{ runInfo.answer_length }} 字</a-descriptions-item>
              </a-descriptions>

              <a-descriptions
                v-if="assemblyInfo"
                title="🛠 Agent 装配"
                :column="2"
                size="small"
                bordered
                style="margin-top: 16px"
              >
                <a-descriptions-item label="模型">
                  <a-tag color="cyan">{{ assemblyInfo.model_code || '-' }}</a-tag>
                </a-descriptions-item>
                <a-descriptions-item label="checkpointer">
                  <a-tag :color="assemblyInfo.checkpointer_enabled ? 'green' : 'default'">
                    {{ assemblyInfo.checkpointer_enabled ? '启用' : '关闭' }}
                  </a-tag>
                </a-descriptions-item>
                <a-descriptions-item label="工具数">{{ assemblyInfo.tool_count ?? '-' }}</a-descriptions-item>
                <a-descriptions-item label="工具列表">
                  <a-tag v-for="t in assemblyInfo.tools || []" :key="t" color="purple" class="mb-1">
                    {{ t }}
                  </a-tag>
                </a-descriptions-item>
                <a-descriptions-item label="中间件" :span="2">
                  <a-tag v-for="m in assemblyInfo.middlewares || []" :key="m" color="blue" class="mb-1">
                    {{ m }}
                  </a-tag>
                </a-descriptions-item>
                <a-descriptions-item v-if="assemblyInfo.state_schemas?.length" label="State Schema" :span="2">
                  <a-tag v-for="s in assemblyInfo.state_schemas" :key="s" color="geekblue" class="mb-1">
                    {{ s }}
                  </a-tag>
                </a-descriptions-item>
                <a-descriptions-item label="其他配置" :span="2">
                  <pre class="json-block">{{ safeJson(assemblyInfo) }}</pre>
                </a-descriptions-item>
              </a-descriptions>
            </template>
          </div>

          <!-- 输入区 -->
          <a-divider />
          <a-textarea
            v-model:value="input"
            :rows="3"
            placeholder="输入你的 query..."
            :disabled="running"
          />
          <div class="mt-2">
            <a-space>
              <a-button type="primary" :loading="running" @click="onRun">
                <template #icon><SendOutlined /></template>
                {{ running ? '运行中' : '发送' }}
              </a-button>
              <a-button @click="onClear" :disabled="running">清空</a-button>
              <a-button @click="newConversation" :disabled="running">新建会话</a-button>
            </a-space>
          </div>
        </a-card>
      </a-col>
    </a-row>
  </div>
</template>

<script setup lang="ts">
/**
 * Agent 调试台
 * - 完整实现后端 SSE 事件协议(8+ 种事件)
 * - 双视图:聊天视图(分类型展示)+ 事件流(原始 JSON 列表)+ 装配信息
 * - 保留所有调试控制(工具覆盖、会话 ID、流式开关、特性开关)
 * - 严格区分:model_delta(正文)/ reasoning_delta(思考)/ tool_call(请求)/ tool_result(结果)
 */
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { message } from 'ant-design-vue'
import {
  ClockCircleOutlined,
  DeleteOutlined,
  DownloadOutlined,
  SendOutlined,
} from '@ant-design/icons-vue'
import {
  getAgentTemplateDetail,
  type AgentTemplate,
} from '@/api/agentTemplate'
import { getCapabilities } from '@/api/capabilities'
import { searchKnowledgeBases } from '@/api/knowledge'
import { runAgent, runAgentStream, type AgentRunRequestPayload } from '@/api/agentRun'

defineOptions({ name: 'AgentPlaygroundView' })

const route = useRoute()
const router = useRouter()
const agentId = computed(() => route.params.agent_id as string)

// 详情
const loading = ref(false)
const agentDetail = ref<AgentTemplate | null>(null)

// 工具选项
const toolOptions = ref<{ label: string; value: string }[]>([])
const knowledgeBaseOptions = ref<{ label: string; value: string }[]>([])
const selectedKnowledgeBaseIds = ref<string[]>([])

// 运行参数
const conversationId = ref<string>('')
const overrideTools = ref<string[]>([])
const stream = ref(true)
const memoryEnabled = ref(false)
const a2aEnabled = ref(false)
const running = ref(false)
const input = ref('')

// 视图切换
const activeTab = ref<'chat' | 'events' | 'assembly'>('chat')

/** 聊天视图用的消息 */
interface MessageItem {
  role: 'user' | 'assistant' | 'tool' | 'system'
  /** 子类型:reasoning/tool_call/tool_result/task_plan/interrupt/lifecycle/error */
  subtype?: string
  content: string
  /** 复杂内容(JSON 等), 用于 task_plan / interrupt 等非纯文本展示 */
  contentJson?: unknown
  tool_name?: string
  tool_args?: unknown
  tool_output?: unknown
  tool_status?: 'running' | 'done' | 'failed'
  event?: string
  lifeIcon?: string
  time: string
  /** 元信息 */
  run_id?: string
  elapsed_ms?: number
  answer_length?: number
}
const messages = ref<MessageItem[]>([])

/** 事件流视图用的原始事件 */
interface RawEvent {
  type: string
  payloadText: string  // 格式化后的 JSON 字符串
  time: string
  index?: number
}
const rawEvents = ref<RawEvent[]>([])

/** 装配信息(来自 agent_assembled) */
const assemblyInfo = ref<Record<string, any> | null>(null)

/** 运行信息(run_start + run_end 合并) */
const runInfo = ref<{
  run_id?: string
  thread_id?: string
  persistent_conversation?: boolean
  stream?: boolean
  elapsed_ms?: number
  answer_length?: number
  status?: string
} | null>(null)

/** 生成 uuid */
function uuid() {
  return 'conv_' + Date.now() + '_' + Math.random().toString(36).slice(2, 8)
}

/** 当前时间 */
function now() {
  return new Date().toLocaleTimeString()
}

/** 加载详情与工具 */
async function loadAll() {
  loading.value = true
  try {
    agentDetail.value = await getAgentTemplateDetail(agentId.value)
    if (agentDetail.value?.config?.a2a?.sub_agent_list?.length) {
      a2aEnabled.value = true
    }
    const cap = await getCapabilities()
    toolOptions.value = (cap.registered_tools || []).map((name) => ({ label: name, value: name }))
    await loadKnowledgeBaseOptions()
    if (!conversationId.value) conversationId.value = uuid()
  } finally {
    loading.value = false
  }
}

/** 加载本次试跑可选择的知识库，失败时不影响 Agent 基础试跑能力。 */
async function loadKnowledgeBaseOptions() {
  try {
    const knowledgeBases = await searchKnowledgeBases({ status: 'active' })
    knowledgeBaseOptions.value = (knowledgeBases || []).map((item) => ({
      label: item.name,
      value: item.knowledge_id,
    }))
  } catch {
    knowledgeBaseOptions.value = []
  }
}

/** 发送运行请求 */
async function onRun() {
  if (!input.value.trim()) {
    message.warning('请输入 query')
    return
  }
  const userText = input.value
  messages.value.push({ role: 'user', content: userText, time: now() })
  input.value = ''
  running.value = true

  // 通过 agent_id 让后端读取模板配置; 这里只传本次试跑需要覆盖的字段
  const payload: AgentRunRequestPayload = {
    agent_id: agentId.value,
    query: userText,
    conversation_id: conversationId.value,
    tools: overrideTools.value.length ? overrideTools.value : undefined,
    optional_features: {
      long_term_memory_enabled: memoryEnabled.value,
    },
    knowledge: selectedKnowledgeBaseIds.value.length
      ? { knowledge_base_ids: [...selectedKnowledgeBaseIds.value] }
      : null,
    a2a: a2aEnabled.value ? undefined : null,
  }

  try {
    if (stream.value) {
      await runStream(payload)
    } else {
      const res = await runAgent({ ...payload, stream: false })
      messages.value.push({ role: 'assistant', content: res.answer || '', time: now() })
      running.value = false
    }
  } catch (e) {
    running.value = false
    message.error('调用失败')
  }
}

/** 流式运行 - 严格按文档 8 种事件类型处理 */
async function runStream(payload: AgentRunRequestPayload) {
  // 准备流式消息载体
  messages.value.push({
    role: 'assistant',
    content: '',
    subtype: 'lifecycle',
    event: 'run_start',
    lifeIcon: '🚀',
    time: now(),
  })
  const lifecycleIdx = messages.value.length - 1

  await runAgentStream(
    payload,
    (event) => handleStreamEvent(event, lifecycleIdx),
    (err) => {
      message.error('流式调用失败:' + err.message)
      running.value = false
    },
    () => {
      running.value = false
    },
  )
}

/** 单事件处理 - 完整协议支持 */
function handleStreamEvent(event: Record<string, any>, lifecycleIdx: number) {
  const data = (event.data || {}) as Record<string, any>
  const eventType = String(event.type || '')

  // 1) 原始事件记录(无论类型都进事件流)
  pushRawEvent(eventType, event)

  // 2) 分流处理
  switch (eventType) {
    case 'run_start': {
      runInfo.value = {
        run_id: data.run_id,
        thread_id: data.thread_id,
        persistent_conversation: data.persistent_conversation,
        stream: data.stream,
      }
      // 更新生命周期占位
      messages.value[lifecycleIdx] = {
        ...messages.value[lifecycleIdx],
        content: `运行开始 - run_id: ${data.run_id?.slice(0, 12) || '-'}...`,
        lifeIcon: '🚀',
      }
      return
    }

    case 'agent_assembled': {
      assemblyInfo.value = data
      return
    }

    case 'reasoning_delta': {
      const delta = String(data.content || '')
      if (!delta) return
      appendToLastSubtype('reasoning', delta, 'assistant', 'reasoning')
      return
    }

    case 'model_delta': {
      const delta = String(data.content || '')
      if (!delta) return
      // 找/建一条 assistant 主消息(无 subtype 的那种)
      ensureMainAssistant().content += delta
      return
    }

    case 'tool_call': {
      messages.value.push({
        role: 'tool',
        subtype: 'tool_call',
        content: '',
        tool_name: String(data.tool_name || 'tool'),
        tool_args: data.args,
        tool_status: 'running',
        time: now(),
      })
      return
    }

    case 'tool_result': {
      // 找最近一条同名 tool_call, 标 done 并填充输出
      const toolName = String(data.tool_name || '')
      for (let i = messages.value.length - 1; i >= 0; i--) {
        const m = messages.value[i]
        if (m.subtype === 'tool_call' && m.tool_name === toolName && m.tool_status === 'running') {
          messages.value[i] = {
            ...m,
            subtype: 'tool_result',
            tool_status: 'done',
            tool_output: data.output,
            content: '',
          }
          break
        }
      }
      return
    }

    case 'task_plan': {
      messages.value.push({
        role: 'system',
        subtype: 'task_plan',
        content: '任务计划已更新',
        contentJson: data,
        time: now(),
      })
      return
    }

    case 'interrupt': {
      messages.value.push({
        role: 'system',
        subtype: 'interrupt',
        content: '运行被中断,等待用户操作',
        contentJson: data,
        lifeIcon: '⏸',
        time: now(),
      })
      return
    }

    case 'run_end': {
      runInfo.value = {
        ...(runInfo.value || {}),
        elapsed_ms: data.elapsed_ms,
        answer_length: data.answer_length,
        status: data.status || 'success',
      }
      // 给最后一条主 assistant 消息补上元信息
      const main = findMainAssistant()
      if (main) {
        messages.value[messages.value.indexOf(main)] = {
          ...main,
          run_id: runInfo.value?.run_id,
          elapsed_ms: data.elapsed_ms,
          answer_length: data.answer_length,
        }
      }
      return
    }

    case 'error': {
      messages.value.push({
        role: 'system',
        subtype: 'lifecycle',
        lifeIcon: '❌',
        content: `运行失败 - ${data.message || event.message || '未知错误'}`,
        time: now(),
      })
      runInfo.value = { ...(runInfo.value || {}), status: 'failed' }
      return
    }

    default:
      // 未知事件, 已在事件流中记录
      return
  }
}

/** 把推理/正文增量追加到当前对话 */
function appendToLastSubtype(targetSubtype: 'reasoning', delta: string, role: 'assistant', _sub: 'reasoning') {
  // reasoning 单独一条
  const last = messages.value[messages.value.length - 1]
  if (last && last.subtype === 'reasoning') {
    messages.value[messages.value.length - 1] = {
      ...last,
      content: last.content + delta,
    }
  } else {
    messages.value.push({
      role,
      subtype: targetSubtype,
      content: delta,
      time: now(),
    })
  }
}

/** 找/建一条主 assistant 消息(正文载体) */
function ensureMainAssistant() {
  // 如果最后一条是主 assistant(无 subtype), 直接用
  for (let i = messages.value.length - 1; i >= 0; i--) {
    const m = messages.value[i]
    if (m.role === 'assistant' && !m.subtype) return m
  }
  // 否则建一条新的
  const m: MessageItem = {
    role: 'assistant',
    content: '',
    time: now(),
  }
  messages.value.push(m)
  return m
}

/** 找最近的主 assistant 消息 */
function findMainAssistant() {
  for (let i = messages.value.length - 1; i >= 0; i--) {
    const m = messages.value[i]
    if (m.role === 'assistant' && !m.subtype) return m
  }
  return null
}

/** 原始事件入栈(用于事件流视图) */
function pushRawEvent(type: string, fullEvent: any) {
  let payloadText = ''
  try {
    payloadText = JSON.stringify(fullEvent, null, 2)
  } catch {
    payloadText = String(fullEvent)
  }
  if (payloadText.length > 4000) {
    payloadText = payloadText.slice(0, 4000) + '\n... (truncated)'
  }
  rawEvents.value.push({
    type,
    payloadText,
    time: now(),
    index: rawEvents.value.length + 1,
  })
}

/** 安全 JSON 序列化 */
function safeJson(value: unknown): string {
  if (value === undefined || value === null) return '-'
  if (typeof value === 'string') return value
  try {
    return JSON.stringify(value, null, 2)
  } catch {
    return String(value)
  }
}

/** 智能耗时格式 */
function formatDuration(ms?: number): string {
  if (ms === undefined) return '-'
  if (ms < 1000) return `${Math.round(ms)} ms`
  if (ms < 60_000) return `${(ms / 1000).toFixed(2)} s`
  const m = Math.floor(ms / 60_000)
  const s = ((ms % 60_000) / 1000).toFixed(1)
  return `${m}m ${s}s`
}

/** 事件类型对应的颜色 */
function eventColor(type: string): string {
  const colorMap: Record<string, string> = {
    run_start: 'blue',
    resume_start: 'cyan',
    agent_assembled: 'geekblue',
    reasoning_delta: 'purple',
    model_delta: 'green',
    tool_call: 'orange',
    tool_result: 'gold',
    task_plan: 'magenta',
    interrupt: 'red',
    run_end: 'green',
    error: 'red',
  }
  return colorMap[type] || 'default'
}

/** 角色颜色 */
function roleColor(r: string) {
  return r === 'user' ? 'blue' : r === 'assistant' ? 'green' : r === 'tool' ? 'purple' : 'default'
}

/** 清空当前调试 */
function onClear() {
  messages.value = []
  rawEvents.value = []
  assemblyInfo.value = null
  runInfo.value = null
}

/** 新建会话 */
function newConversation() {
  conversationId.value = uuid()
  onClear()
  message.success('已新建会话:' + conversationId.value)
}

/** 下载事件流 JSON */
function downloadEvents() {
  const blob = new Blob([JSON.stringify(rawEvents.value, null, 2)], { type: 'application/json' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = `agent-events-${agentId.value}-${Date.now()}.json`
  a.click()
  URL.revokeObjectURL(url)
}

onMounted(loadAll)
</script>

<style scoped>
.playground {
  padding: 0 4px;
}
.page-title {
  margin: 0 0 16px;
  font-size: 20px;
  font-weight: 600;
  display: flex;
  align-items: center;
  gap: 12px;
}
.running-badge {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-size: 12px;
  color: #1677ff;
  background: #e6f4ff;
  padding: 2px 10px;
  border-radius: 12px;
  font-weight: 500;
}
.side-card {
  min-height: 600px;
}
.debug-card {
  min-height: 600px;
}
.message-area {
  min-height: 400px;
  max-height: 540px;
  overflow-y: auto;
  padding: 8px 4px;
}
.msg {
  margin-bottom: 12px;
  padding: 10px 12px;
  border-radius: 6px;
  background: #fafafa;
  border-left: 3px solid #d9d9d9;
}
.msg-user {
  background: #e6f4ff;
  border-left-color: #1677ff;
}
.msg-assistant {
  background: #f6ffed;
  border-left-color: #52c41a;
}
.msg-tool {
  background: #fff7e6;
  border-left-color: #fa8c16;
}
.msg-system {
  background: #f5f5f5;
  border-left-color: #8c8c8c;
  font-size: 12px;
}
.msg-meta {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 12px;
  color: #666;
  margin-bottom: 6px;
  flex-wrap: wrap;
}
.msg-subtype {
  background: #f0f0f0;
  padding: 1px 6px;
  border-radius: 4px;
  font-size: 11px;
  color: #595959;
  font-family: 'Fira Code', Menlo, Consolas, monospace;
}
.msg-tool-name {
  font-size: 12px;
  color: #d46b08;
}
.msg-event-tag {
  font-size: 11px;
  color: #8c8c8c;
  font-family: 'Fira Code', Menlo, Consolas, monospace;
}
.msg-time {
  margin-left: auto;
  color: #bfbfbf;
  font-size: 11px;
}
.msg-content {
  white-space: pre-wrap;
  word-break: break-word;
  line-height: 1.6;
  font-size: 14px;
}
.msg-reasoning {
  background: #fafafa;
  padding: 8px 10px;
  border-radius: 4px;
  border-left: 3px solid #b37feb;
}
.reasoning-icon {
  font-size: 13px;
}
.reasoning-label {
  font-size: 11px;
  color: #b37feb;
  font-weight: 500;
  margin-left: 4px;
  text-transform: uppercase;
  letter-spacing: 0.5px;
}
.msg-reasoning-content {
  margin-top: 6px;
  font-size: 12px;
  color: #595959;
  white-space: pre-wrap;
  word-break: break-word;
  line-height: 1.7;
}
.msg-tool-block,
.msg-plan-block,
.msg-interrupt-block {
  background: #fff;
  padding: 8px 10px;
  border-radius: 4px;
  border: 1px solid #f0f0f0;
}
.msg-tool-title {
  font-size: 12px;
  font-weight: 600;
  color: #1f1f1f;
  margin-bottom: 8px;
  display: flex;
  align-items: center;
  gap: 6px;
}
.msg-lifecycle {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 12px;
  color: #595959;
}
.lifecycle-icon {
  font-size: 14px;
}
.json-block {
  background: #f5f5f5;
  padding: 8px 10px;
  border-radius: 4px;
  font-size: 12px;
  max-height: 240px;
  overflow: auto;
  margin: 0;
  white-space: pre-wrap;
  word-break: break-all;
  font-family: 'Fira Code', 'Cascadia Code', Menlo, Consolas, monospace;
}
.mb-1 { margin-bottom: 4px; }
.mb-2 { margin-bottom: 8px; }
.mt-2 { margin-top: 8px; }
.mono { font-family: 'Fira Code', Menlo, Consolas, monospace; font-size: 12px; }

/* 元信息 chip */
.msg-meta-extras {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-top: 8px;
  padding-top: 8px;
  border-top: 1px dashed #f0f0f0;
  flex-wrap: wrap;
}
.meta-chip {
  display: inline-flex;
  align-items: center;
  gap: 3px;
  padding: 2px 8px;
  font-size: 11px;
  color: #8c8c8c;
  background: #fafafa;
  border: 1px solid #f0f0f0;
  border-radius: 10px;
  white-space: nowrap;
}
.meta-chip-id {
  font-family: 'Fira Code', Menlo, Consolas, monospace;
  color: #1677ff;
  background: #e6f4ff;
  border-color: #91caff;
  cursor: help;
}

/* 运行指示器 */
.running-indicator {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 12px;
  background: #e6f4ff;
  border-radius: 4px;
  font-size: 12px;
  color: #1677ff;
  margin-top: 8px;
}

/* 事件流视图 */
.events-area {
  min-height: 400px;
  max-height: 540px;
  overflow-y: auto;
  padding: 4px;
}
.events-list {
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.event-item {
  border-left: 3px solid #d9d9d9;
  background: #fafafa;
  border-radius: 4px;
  padding: 6px 10px;
}
.event-run_start { border-left-color: #1677ff; }
.event-resume_start { border-left-color: #13c2c2; }
.event-agent_assembled { border-left-color: #2f54eb; }
.event-reasoning_delta { border-left-color: #b37feb; }
.event-model_delta { border-left-color: #52c41a; }
.event-tool_call { border-left-color: #fa8c16; }
.event-tool_result { border-left-color: #faad14; }
.event-task_plan { border-left-color: #c41d7f; }
.event-interrupt { border-left-color: #ff4d4f; background: #fff1f0; }
.event-run_end { border-left-color: #52c41a; }
.event-error { border-left-color: #ff4d4f; background: #fff1f0; }
.event-head {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 4px;
}
.event-time {
  font-size: 11px;
  color: #8c8c8c;
  margin-left: auto;
}
.event-index {
  font-size: 11px;
  color: #bfbfbf;
  font-family: 'Fira Code', Menlo, Consolas, monospace;
}
.event-payload {
  margin: 0;
  background: #fff;
  border: 1px solid #f0f0f0;
  padding: 6px 8px;
  border-radius: 3px;
  font-size: 11px;
  max-height: 200px;
  overflow: auto;
  white-space: pre-wrap;
  word-break: break-all;
  font-family: 'Fira Code', 'Cascadia Code', Menlo, Consolas, monospace;
  color: #595959;
}

/* 装配信息视图 */
.assembly-area {
  min-height: 400px;
  max-height: 540px;
  overflow-y: auto;
  padding: 4px;
}
</style>
