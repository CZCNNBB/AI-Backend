<!--
  Agent 调用页
  - 现代化聊天式调用界面
  - 顶部 Agent 选择器,中间聊天气泡,底部输入区
  - 渐变背景 + 卡片化设计 + 丰富空状态
-->
<template>
  <div class="invoke-page">
    <!-- 顶部:Agent 选择器与操作区 -->
    <div class="invoke-header">
      <div class="header-left">
        <div class="header-logo">🤖</div>
        <div class="header-title">
          <div class="title-main">Agent 调用台</div>
          <div class="title-sub">
            <span v-if="agentDetail" class="agent-info">
              <span class="status-dot" :class="`status-${agentDetail.status || 'active'}`"></span>
              当前 Agent: {{ agentName }}
            </span>
            <span v-else class="agent-info-placeholder">未选择 Agent</span>
          </div>
        </div>
      </div>
      <div class="header-right">
        <a-select
          v-model:value="selectedAgentId"
          show-search
          placeholder="切换 Agent 模板"
          class="agent-select"
          :options="agentOptions"
          :loading="agentListLoading"
          option-filter-prop="label"
          allow-clear
          @change="onAgentChange"
        >
          <template #suffixIcon><ApiOutlined /></template>
        </a-select>
        <a-tooltip title="新建会话">
          <a-button class="icon-btn" @click="newConversation">
            <template #icon><PlusOutlined /></template>
          </a-button>
        </a-tooltip>
        <a-tooltip title="管理 Agent 模板">
          <a-button class="icon-btn" @click="router.push('/agents')">
            <template #icon><SettingOutlined /></template>
          </a-button>
        </a-tooltip>
      </div>
    </div>

    <!-- 消息区 -->
    <div ref="messageArea" class="message-area" @scroll="onAreaScroll">
      <!-- 漂亮空状态 -->
      <div v-if="!messages.length" class="empty-state">
        <div class="empty-icon-wrap">
          <div class="empty-icon">💬</div>
          <div class="empty-ripple"></div>
        </div>
        <h2 class="empty-title">
          {{ selectedAgentId ? '开始与 Agent 对话' : '先选择一个 Agent 模板' }}
        </h2>
        <p class="empty-desc">
          {{ selectedAgentId
            ? '在下方输入框提问, Agent 会自动调用配置的工具并回复'
            : '从右上角下拉框选择要调用的 Agent,即可开始对话' }}
        </p>
        <div v-if="!selectedAgentId" class="empty-suggestions">
          <a-button v-for="(g, gi) in agentOptions.slice(0, 3)" :key="gi" type="default" size="small" @click="onAgentChange(g.value)">
            {{ g.label }}
          </a-button>
        </div>
      </div>

      <!-- 消息流 -->
      <div class="messages-wrap">
        <div
          v-for="(msg, i) in messages"
          :key="i"
          :class="['message', msg.role === 'user' ? 'message-user' : 'message-assistant']"
        >
          <div class="message-avatar">
            {{ msg.role === 'user' ? '👤' : '🤖' }}
          </div>
          <div class="message-body">
            <div class="message-meta">
              <span class="message-role">{{ msg.role === 'user' ? '我' : agentName }}</span>
              <span class="message-time">{{ msg.time }}</span>
            </div>
            <!-- Agent 流式时间线:按后端事件到达顺序渲染,保留 思考 -> 工具 -> 回复 的真实执行顺序 -->
            <template v-if="msg.role === 'assistant'">
              <div
                v-for="(block, bi) in msg.blocks"
                :key="`block-${i}-${bi}`"
              >
                <div v-if="block.type === 'reasoning'" class="message-reasoning">
                  <div class="reasoning-header">
                    <span class="reasoning-icon">💭</span>
                    <span class="reasoning-label">思考过程</span>
                  </div>
                  <div class="reasoning-content">{{ block.content }}</div>
                </div>

                <div v-else-if="block.type === 'tool'" class="tool-block-wrap">
                  <div class="message-tool-call">
                    <div class="tool-left">
                      <span class="tool-icon">🔧</span>
                      <span class="tool-name">{{ block.tool_name }}</span>
                      <span v-if="block.args && Object.keys(block.args).length" class="tool-args">
                        {{ formatToolArgs(block.args) }}
                      </span>
                      <a-tooltip
                        v-if="block.status === 'done' && block.output !== null && block.output !== undefined"
                        placement="topLeft"
                      >
                        <template #title>
                          <div class="tool-output-pre">
                            <MarkdownView :content="formatToolOutput(block.output)" />
                          </div>
                        </template>
                        <span class="tool-output-hint">查看结果</span>
                      </a-tooltip>
                    </div>
                    <span class="tool-status">
                      <a-spin v-if="block.status === 'running'" size="small" />
                      <span v-else-if="block.status === 'done'" class="status-done">✓</span>
                      <span v-else-if="block.status === 'failed'" class="status-failed">✕</span>
                    </span>
                  </div>

                  <div
                    v-for="subRun in block.sub_agent_runs || []"
                    :key="subRun.sub_run_id"
                    class="sub-agent-panel"
                  >
                    <button class="sub-agent-header" type="button" @click="subRun.collapsed = !subRun.collapsed">
                      <span class="sub-agent-dot" :class="`sub-agent-dot-${subRun.status}`"></span>
                      <span class="sub-agent-title">子 Agent：{{ subRun.agent_id }}</span>
                      <span class="sub-agent-meta">{{ summarizeSubAgentRun(subRun) }}</span>
                      <span class="sub-agent-status" :class="`sub-agent-status-${subRun.status}`">
                        {{ formatSubAgentStatus(subRun.status) }}
                      </span>
                      <span class="sub-agent-toggle">{{ subRun.collapsed ? '展开' : '收起' }}</span>
                    </button>
                    <div v-if="!subRun.collapsed" class="sub-agent-timeline">
                      <!-- 思考过程：折叠展示，避免抢戏 -->
                      <details v-if="getSubAgentReasoning(subRun)" class="sub-agent-reasoning">
                        <summary>💭 思考过程</summary>
                        <div class="sub-agent-reasoning-body">{{ getSubAgentReasoning(subRun) }}</div>
                      </details>

                      <!-- 工具调用 + 工具结果：紧凑 timeline -->
                      <div
                        v-for="(item, si) in getSubAgentToolPairs(subRun)"
                        :key="`subtool-${subRun.sub_run_id}-${si}`"
                        class="sub-agent-tool-row"
                      >
                        <span class="sub-agent-tool-icon">🔧</span>
                        <span class="sub-agent-tool-name">{{ item.toolName }}</span>
                        <span v-if="item.args" class="sub-agent-tool-args">{{ item.args }}</span>
                        <span class="sub-agent-tool-status" :class="`sub-agent-tool-status-${item.status}`">
                          {{ item.status === 'running' ? '执行中' : item.status === 'done' ? '完成' : '失败' }}
                        </span>
                      </div>

                      <!-- 子 Agent 最终输出：重点高亮 + Markdown 渲染 -->
                      <div v-if="getSubAgentOutput(subRun)" class="sub-agent-output">
                        <div class="sub-agent-output-label">📝 子 Agent 输出</div>
                        <MarkdownView :content="getSubAgentOutput(subRun)" />
                      </div>

                      <!-- 任务计划：复用主 Agent 的 plan 样式 -->
                      <div
                        v-for="plan in getSubAgentTaskPlans(subRun)"
                        :key="`subplan-${subRun.sub_run_id}-${plan.__idx}`"
                        class="message-task-plan sub-agent-plan"
                      >
                        <div class="plan-header">
                          <span class="plan-icon">🗓</span>
                          <span class="plan-title">{{ plan.title || '任务计划' }}</span>
                          <span class="plan-status">{{ plan.status || 'draft' }}</span>
                        </div>
                        <div v-if="getTaskPlanSteps(plan).length" class="plan-steps">
                          <div v-for="step in getTaskPlanSteps(plan)" :key="step.step_id || step.title" class="plan-step">
                            <span class="step-status" :class="getTaskStepStatusClass(step.status)">{{ step.status || 'waiting' }}</span>
                            <span class="step-title">{{ step.title || step.description || '-' }}</span>
                          </div>
                        </div>
                      </div>

                      <!-- 运行结束摘要 -->
                      <div
                        v-for="(subEvent, sei) in getSubAgentMetaEvents(subRun)"
                        :key="`submeta-${subRun.sub_run_id}-${sei}`"
                        class="sub-agent-event-meta"
                        :class="`sub-agent-event-meta-${subEvent.type}`"
                      >
                        <span v-if="subEvent.type === 'error'" class="meta-icon">⚠️</span>
                        <span v-else class="meta-icon">ℹ️</span>
                        <span>{{ formatSubAgentEvent(subEvent) }}</span>
                      </div>
                    </div>
                  </div>
                </div>

                <div v-else-if="block.type === 'task_plan'" class="message-task-plan">
                  <div class="plan-header">
                    <span class="plan-icon">🗓</span>
                    <span class="plan-title">{{ block.task_plan.title || '任务计划' }}</span>
                    <span class="plan-status">{{ block.task_plan.status || 'draft' }}</span>
                  </div>
                  <div v-if="getTaskPlanSteps(block.task_plan).length" class="plan-steps">
                    <div v-for="step in getTaskPlanSteps(block.task_plan)" :key="step.step_id || step.title" class="plan-step">
                      <span class="step-status" :class="getTaskStepStatusClass(step.status)">{{ step.status || 'waiting' }}</span>
                      <span class="step-title">{{ step.title || step.description || '-' }}</span>
                    </div>
                  </div>
                </div>

                <div v-else-if="block.type === 'context_summary'" class="message-context-summary">
                  <a-spin v-if="block.status === 'running'" size="small" />
                  <span>{{ block.status === 'running' ? '正在总结会话上下文' : block.status === 'completed' ? '会话上下文总结完成' : block.message || '会话上下文总结失败，已继续使用原始上下文' }}</span>
                </div>

                <div v-else-if="block.type === 'interrupt'" class="message-interrupt">
                  <div class="interrupt-header">
                    <span class="interrupt-icon">⏸</span>
                    <span class="interrupt-title">需要你确认任务计划</span>
                    <span v-if="block.status === 'answered'" class="interrupt-done">已处理</span>
                  </div>
                  <div v-if="getInterruptTaskPlan(block)" class="interrupt-plan">
                    <div class="plan-title">{{ getInterruptTaskPlan(block)?.title || '任务计划' }}</div>
                    <div v-for="step in getTaskPlanSteps(getInterruptTaskPlan(block))" :key="step.step_id || step.title" class="plan-step">
                      <span class="step-status" :class="getTaskStepStatusClass(step.status)">{{ step.status || 'waiting' }}</span>
                      <span class="step-title">{{ step.title || step.description || '-' }}</span>
                    </div>
                  </div>
                  <div v-if="block.status === 'waiting'" class="interrupt-actions">
                    <a-space wrap>
                      <a-button type="primary" size="small" @click="submitPlanConfirmation(i, bi, 'approve')">确认执行</a-button>
                      <a-button danger size="small" @click="submitPlanConfirmation(i, bi, 'cancel')">取消计划</a-button>
                    </a-space>
                    <div class="interrupt-feedback">
                      <a-textarea
                        v-model:value="block.feedback"
                        :rows="2"
                        placeholder="如果需要修改计划，在这里输入建议后点击提交修改"
                      />
                      <a-button size="small" @click="submitPlanConfirmation(i, bi, 'revise')">提交修改意见</a-button>
                    </div>
                  </div>
                </div>

                <div v-else-if="block.type === 'content'" class="message-content">
                  <MarkdownView :content="block.content" />
                </div>
              </div>
            </template>
            <!-- 用户消息正文 -->
            <div v-else-if="msg.content" class="message-content">{{ msg.content }}</div>
            <div v-if="msg.role === 'user' && msg.file_names?.length" class="message-file-list">
              <span v-for="fileName in msg.file_names" :key="fileName" class="message-file-chip">
                <PaperClipOutlined /> {{ fileName }}
              </span>
            </div>
            <!-- 元信息:耗时、回答长度、run_id 短码(完成时展示) -->
            <div
              v-if="(msg.elapsed_ms !== undefined || msg.answer_length !== undefined) && !running"
              class="message-meta-extras"
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
        </div>

        <!-- 等待首个 token:打字指示器 -->
        <div v-if="waitingFirstToken" class="message message-assistant">
          <div class="message-avatar">🤖</div>
          <div class="message-body">
            <div class="message-meta">
              <span class="message-role">{{ agentName }}</span>
            </div>
            <div class="typing-indicator">
              <span></span><span></span><span></span>
            </div>
          </div>
        </div>
      </div>

      <!-- 回到最新按钮 -->
      <transition name="jump-fade">
        <div v-if="showJumpToBottom" class="jump-to-bottom" @click="scrollToBottomAndStick">
          <span class="jump-icon">↓</span>
          <span>回到最新</span>
        </div>
      </transition>
    </div>

    <!-- 输入区 -->
    <div class="input-area">
      <div v-if="knowledgeEnabled" class="knowledge-scope">
        <span class="knowledge-scope-label">本次可访问知识库</span>
        <a-select
          v-model:value="selectedKnowledgeBaseIds"
          mode="multiple"
          placeholder="选择本次对话允许检索的知识库"
          :options="knowledgeBaseOptions"
          :disabled="running"
          :max-tag-count="3"
          show-search
          option-filter-prop="label"
          allow-clear
          class="knowledge-scope-select"
        />
      </div>
      <div v-if="uploadedFiles.length || uploadingFiles" class="attachment-tray">
        <a-spin v-if="uploadingFiles" size="small" />
        <span v-if="uploadingFiles" class="attachment-uploading">正在上传并解析附件...</span>
        <span v-for="file in uploadedFiles" :key="file.file_id" class="attachment-chip">
          <PaperClipOutlined />
          <span class="attachment-name" :title="file.original_name">{{ file.original_name }}</span>
          <button type="button" class="attachment-remove" :disabled="running" @click="removeUploadedFile(file.file_id)">
            <CloseOutlined />
          </button>
        </span>
      </div>
      <div class="input-wrap">
        <input ref="fileInput" class="file-input-hidden" type="file" multiple @change="onFilesSelected" />
        <a-tooltip title="上传附件">
          <a-button class="attach-btn" :disabled="inputDisabled || uploadingFiles" @click="openFilePicker">
            <template #icon><PaperClipOutlined /></template>
          </a-button>
        </a-tooltip>
        <a-textarea
          v-model:value="input"
          :rows="1"
          :auto-size="{ minRows: 1, maxRows: 6 }"
          :placeholder="inputPlaceholder"
          :disabled="inputDisabled"
          class="chat-input"
          @pressEnter="onPressEnter"
        />
        <a-button
          type="primary"
          class="send-btn"
          :loading="running"
          :disabled="inputDisabled || (!input.trim() && !uploadedFiles.length)"
          @click="onRun"
        >
          <template #icon v-if="!running"><SendOutlined /></template>
          {{ running ? '生成中' : '发送' }}
        </a-button>
      </div>
      <div class="input-hint">
        <span v-if="waitingPlanConfirmation" class="hint-active hint-waiting">
          <ThunderboltOutlined /> 当前 Agent 已暂停，请先处理上方任务计划确认卡片
        </span>
        <span v-else-if="selectedAgentId" class="hint-active">
          <ThunderboltOutlined /> 当前会话 ID: {{ conversationId.slice(0, 16) }}...
        </span>
        <span v-else>👈 请先选择 Agent</span>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
/**
 * Agent 调用页
 * - 提供现代化聊天式调用体验
 * - 顶部选择 Agent, 下方连续对话
 * - 微吸: 用户在底部则吸底, 翻看历史则不打扰
 */
import { computed, nextTick, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { message } from 'ant-design-vue'
import {
  ApiOutlined,
  ClockCircleOutlined,
  PlusOutlined,
  SettingOutlined,
  SendOutlined,
  ThunderboltOutlined,
  PaperClipOutlined,
  CloseOutlined,
} from '@ant-design/icons-vue'
import {
  getAgentTemplateDetail,
  searchAgentTemplates,
  type AgentTemplate,
} from '@/api/agentTemplate'
import { runAgentStream } from '@/api/agentRun'
import { searchKnowledgeBases } from '@/api/knowledge'
import { deleteAgentFiles, parseUploadedFile, uploadFiles, type UploadedFileView } from '@/api/file'
import MarkdownView from '@/components/MarkdownView.vue'

defineOptions({ name: 'AgentInvokeView' })

const router = useRouter()
const route = useRoute()

// Agent 列表
const agentListLoading = ref(false)
const agentOptions = ref<{ label: string; value: string }[]>([])

// 当前选中的 Agent
const selectedAgentId = ref<string>('')
const agentDetail = ref<AgentTemplate | null>(null)
const agentName = ref<string>('Agent')

// 会话与运行
const conversationId = ref<string>('')
const input = ref('')
const running = ref(false)
const fileInput = ref<HTMLInputElement | null>(null)
const uploadingFiles = ref(false)
const uploadedFiles = ref<UploadedFileView[]>([])
const knowledgeBaseOptions = ref<{ label: string; value: string }[]>([])
const selectedKnowledgeBaseIds = ref<string[]>([])

/** Agent 流式展示块,用于按事件到达顺序渲染思考、工具调用、任务计划、中断确认和正式回复。 */
type StreamBlock = ReasoningBlock | ContentBlock | ToolCallBlock | TaskPlanBlock | InterruptBlock | ContextSummaryBlock

/** 思考过程块。 */
interface ReasoningBlock {
  type: 'reasoning'
  content: string
}

/** 正式回复块。 */
interface ContentBlock {
  type: 'content'
  content: string
}

/** 子 Agent 单条运行事件。 */
interface SubAgentRunEvent {
  type: string
  data: Record<string, any>
  time: string
}

/** A2A 工具下挂载的子 Agent 运行过程。 */
interface SubAgentRunBlock {
  sub_run_id: string
  agent_id: string
  status: 'running' | 'done' | 'failed'
  collapsed: boolean
  events: SubAgentRunEvent[]
}

/** 单次工具调用块。 */
interface ToolCallBlock {
  type: 'tool'
  tool_name: string
  args: Record<string, unknown>
  /** 后端 tool_call 事件中的 id,用于和 tool_result.tool_call_id 匹配。 */
  call_id?: string | null
  /** 工具执行结果摘要(来自后端 tool_result.output), 仅作展示用。 */
  output: unknown
  status: 'running' | 'done' | 'failed'
  /** A2A 工具调用下的子 Agent 执行过程。 */
  sub_agent_runs?: SubAgentRunBlock[]
}

/** 任务计划展示块。 */
interface TaskPlanBlock {
  type: 'task_plan'
  task_plan: Record<string, any>
}


/** 会话上下文总结状态块，不展示内部摘要正文。 */
interface ContextSummaryBlock {
  type: 'context_summary'
  status: 'running' | 'completed' | 'failed'
  message?: string
}

/** 中断确认展示块。 */
interface InterruptBlock {
  type: 'interrupt'
  payload: Record<string, any>
  status: 'waiting' | 'answered'
  feedback: string
}

interface MessageItem {
  role: 'user' | 'assistant'
  content: string
  reasoning: string
  tool_calls: ToolCallBlock[]
  /** Agent 流式时间线块,用于真实还原 思考 -> 工具 -> 回复 的执行顺序。 */
  blocks: StreamBlock[]
  time: string
  /** 本次 run 的 run_id,来自 run_start 事件 */
  run_id?: string
  /** 本次 run 的耗时(毫秒),来自 run_end 事件 */
  elapsed_ms?: number
  /** 本次 run 的回答长度,来自 run_end 事件 */
  answer_length?: number
  /** 用户本轮随消息提交的附件名称，仅用于聊天记录展示。 */
  file_names?: string[]
}
const messages = ref<MessageItem[]>([])
const messageArea = ref<HTMLDivElement | null>(null)

/** 吸底开关 */
const stickToBottom = ref(true)

/** "回到最新"按钮展示条件 */
const showJumpToBottom = computed(() => {
  if (stickToBottom.value) return false
  if (!messageArea.value) return false
  return messageArea.value.scrollHeight > messageArea.value.clientHeight + 20
})

/** 距离底部多少像素以内算"在底部" */
const BOTTOM_THRESHOLD_PX = 40

/** 是否在等待首个 token */
const waitingFirstToken = computed(() => {
  if (!running.value) return false
  const last = messages.value[messages.value.length - 1]
  if (!last || last.role !== 'assistant') return true
  return !last.content && !last.reasoning
})

/** 是否存在等待用户处理的任务计划确认卡片。 */
const waitingPlanConfirmation = computed(() => findWaitingPlanInterrupt() !== null)

/** 当前模板是否声明了知识库检索能力。 */
const knowledgeEnabled = computed(
  () => !!agentDetail.value?.config?.optional_features?.knowledge_enabled,
)

/** 输入框是否禁用：运行中、未选 Agent 或存在待确认卡片时都不允许输入新对话。 */
const inputDisabled = computed(() => running.value || !selectedAgentId.value || waitingPlanConfirmation.value)

/** 输入框占位文案，根据当前交互状态提示用户下一步。 */
const inputPlaceholder = computed(() => {
  if (waitingPlanConfirmation.value) return '请先处理上方任务计划确认卡片'
  if (!selectedAgentId.value) return '请先选择 Agent 模板'
  return '输入你的问题, Enter 发送, Shift+Enter 换行'
})

/** 打开系统文件选择器。 */
function openFilePicker() {
  fileInput.value?.click()
}

/** 上传用户选择的文件，并缓存本次消息需要提交的 file_id。 */
async function onFilesSelected(event: Event) {
  const target = event.target as HTMLInputElement
  const files = Array.from(target.files || [])
  target.value = ''
  if (!files.length) return

  uploadingFiles.value = true
  let uploadedFileIds: string[] = []
  try {
    const uploadResult = await uploadFiles(files)
    uploadedFileIds = uploadResult.file_ids

    // 上传接口只负责保存原文件。Agent 需要立即读取附件，因此在当前业务场景中
    // 根据 file_id 显式调用解析接口，不能把解析职责重新塞回 /file/upload。
    const parseResults = await Promise.all(
      uploadedFileIds.map((fileId) => parseUploadedFile(fileId)),
    )
    const preparedFiles: UploadedFileView[] = parseResults.map((parseResult, index) => ({
      file_id: parseResult.file_id,
      original_name: parseResult.original_name || files[index]?.name || parseResult.file_id,
      extension: files[index]?.name.split('.').pop() || '',
      mime_type: files[index]?.type || null,
      size_bytes: files[index]?.size || 0,
      status: 'uploaded',
      content_type: parseResult.content_type,
      conversion_status: parseResult.conversion_status,
    }))
    uploadedFiles.value.push(...preparedFiles)
    message.success(`已上传并解析 ${preparedFiles.length} 个附件`)
  } catch {
    // 解析失败时清理本批已经上传的孤立文件，避免用户界面未挂载但服务端一直保留。
    if (uploadedFileIds.length) {
      await deleteAgentFiles(uploadedFileIds).catch(() => undefined)
    }
    message.error('附件上传或解析失败')
  } finally {
    uploadingFiles.value = false
  }
}

/** 删除尚未发送给 Agent 的附件，并同步清理服务端文件。 */
async function removeUploadedFile(fileId: string) {
  try {
    await deleteAgentFiles([fileId])
    uploadedFiles.value = uploadedFiles.value.filter((file) => file.file_id !== fileId)
  } catch {
    message.error('删除附件失败')
  }
}

/** 生成临时会话 ID */
function uuid() {
  return 'conv_' + Date.now() + '_' + Math.random().toString(36).slice(2, 8)
}

/** 确保当前页面有可用于 checkpointer 的会话 ID。 */
function ensureConversationId() {
  if (!conversationId.value) {
    conversationId.value = uuid()
  }
  return conversationId.value
}

/** 加载 Agent 模板列表 */
async function loadAgentList() {
  agentListLoading.value = true
  try {
    const res = await searchAgentTemplates({ page: 1, page_size: 100 })
    agentOptions.value = (res.items || []).map((item) => ({
      label: `${item.agent_name} (${item.agent_id})`,
      value: item.agent_id,
    }))
  } finally {
    agentListLoading.value = false
  }
}

/** 加载运行时可选择的知识库列表。 */
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

/** 加载选中的 Agent 详情 */
async function loadAgentDetail(agentId: string) {
  if (!agentId) {
    agentDetail.value = null
    agentName.value = 'Agent'
    return
  }
  try {
    agentDetail.value = await getAgentTemplateDetail(agentId)
    agentName.value = agentDetail.value?.agent_name || agentId
    if (!agentDetail.value?.config?.optional_features?.knowledge_enabled) {
      selectedKnowledgeBaseIds.value = []
    }
  } catch {
    agentName.value = agentId
  }
}

/** 选择器变化 */
function onAgentChange(agentId: string) {
  selectedAgentId.value = agentId
  messages.value = []
  input.value = ''
  uploadedFiles.value = []
  selectedKnowledgeBaseIds.value = []
  stickToBottom.value = true
  if (!conversationId.value) {
    conversationId.value = uuid()
  }
  loadAgentDetail(agentId)
}

/** 新建会话 */
function newConversation() {
  conversationId.value = uuid()
  messages.value = []
  input.value = ''
  uploadedFiles.value = []
  stickToBottom.value = true
  message.success('已新建会话')
}

/** 滚动到底部(只在 stickToBottom 时执行) */
async function scrollToBottom(force = false) {
  if (!force && !stickToBottom.value) return
  await nextTick()
  if (messageArea.value) {
    messageArea.value.scrollTop = messageArea.value.scrollHeight
  }
}

/** 用户主动点击"回到最新" */
function scrollToBottomAndStick() {
  stickToBottom.value = true
  scrollToBottom(true)
}

/** 监听消息区滚动 */
function onAreaScroll() {
  const el = messageArea.value
  if (!el) return
  const distanceFromBottom = el.scrollHeight - el.scrollTop - el.clientHeight
  stickToBottom.value = distanceFromBottom <= BOTTOM_THRESHOLD_PX
}

/** 键盘发送 */
function onPressEnter(e: KeyboardEvent) {
  if (e.shiftKey) return  // Shift+Enter 换行
  e.preventDefault()
  if (inputDisabled.value) return
  onRun()
}

/** 当前时间 */
function now() {
  return new Date().toLocaleTimeString()
}

/** 格式化工具入参 */
function formatToolArgs(args: Record<string, unknown> | undefined | null): string {
  if (!args) return ''
  const keys = Object.keys(args)
  if (keys.length === 0) return ''
  try {
    return JSON.stringify(args)
  } catch {
    return keys.map((k) => `${k}=${String(args[k])}`).join(', ')
  }
}

/** 格式化工具结果输出, 控制在合理长度内, 用于 tooltip 展示 */
function formatToolOutput(output: unknown): string {
  try {
    const text = JSON.stringify(output, null, 2)
    // 超过 2000 字截断, 避免 tooltip 爆炸
    if (text.length > 2000) {
      return text.slice(0, 2000) + '\n... (truncated)'
    }
    return text
  } catch {
    return String(output)
  }
}

/** 智能格式化耗时: < 1s 用毫秒, < 1m 用秒, 否则用分秒 */
function formatDuration(ms: number): string {
  if (ms < 1000) return `${Math.round(ms)} ms`
  if (ms < 60_000) return `${(ms / 1000).toFixed(2)} s`
  const minutes = Math.floor(ms / 60_000)
  const seconds = ((ms % 60_000) / 1000).toFixed(1)
  return `${minutes}m ${seconds}s`
}

/** 格式化子 Agent 运行状态。 */
function formatSubAgentStatus(status: SubAgentRunBlock['status']): string {
  if (status === 'running') return '运行中'
  if (status === 'done') return '完成'
  return '失败'
}

/** 汇总子 Agent 运行过程，用于折叠头部展示。 */
function summarizeSubAgentRun(subRun: SubAgentRunBlock): string {
  const toolCount = subRun.events.filter((event) => event.type === 'tool_call').length
  const outputCount = subRun.events.filter((event) => event.type === 'model_delta').length
  const parts = [`${subRun.events.length} 个事件`]
  if (toolCount) parts.push(`${toolCount} 次工具`)
  if (outputCount) parts.push(`${outputCount} 段输出`)
  return parts.join(' · ')
}

/** 把子 Agent 原始事件格式化成单行内容，避免小面板过度占用空间。 */
function formatSubAgentEvent(event: SubAgentRunEvent): string {
  const data = event.data || {}
  if (event.type === 'reasoning_delta' || event.type === 'model_delta') {
    return String(data.content || '').trim()
  }
  if (event.type === 'tool_call') {
    const toolName = String(data.tool_name || 'tool')
    return data.args && typeof data.args === 'object' ? `${toolName} ${formatToolArgs(data.args)}` : toolName
  }
  if (event.type === 'tool_result') {
    const toolName = String(data.tool_name || 'tool')
    return `${toolName} 完成`
  }
  if (event.type === 'run_end') {
    return typeof data.elapsed_ms === 'number' ? `耗时 ${formatDuration(data.elapsed_ms)}` : '子 Agent 运行完成'
  }
  if (event.type === 'error') {
    return String(data.message || '子 Agent 运行失败')
  }
  return formatToolOutput(data)
}

/**
 * 把子 Agent 的流式事件按类型归类：
 * - reasoning: 累加所有 reasoning_delta
 * - toolPairs: 配对 tool_call / tool_result（按 tool_call_id 或下标配对）
 * - output: 累加所有 model_delta
 * - plans: 抽离 task_plan 事件
 * - meta: 保留 run_end / error 等状态事件
 */
interface SubAgentGrouped {
  reasoning: string
  toolPairs: Array<{ toolName: string; args: string; status: 'running' | 'done' | 'failed' }>
  output: string
  plans: Array<Record<string, any> & { __idx: number }>
  meta: SubAgentRunEvent[]
}

/** 把子 Agent 事件数组归类为 timeline 所需的分组。 */
function groupSubAgentEvents(subRun: SubAgentRunBlock): SubAgentGrouped {
  const reasoningParts: string[] = []
  const outputParts: string[] = []
  const toolPairs: SubAgentGrouped['toolPairs'] = []
  const plans: SubAgentGrouped['plans'] = []
  const meta: SubAgentRunEvent[] = []
  // 用 id 配对 tool_call / tool_result；没有 id 时按下标相邻配对。
  const toolIndexById = new Map<string, number>()
  let fallbackIndex = 0

  for (const event of subRun.events) {
    const data = (event.data || {}) as Record<string, any>
    if (event.type === 'reasoning_delta') {
      const content = String(data.content || '')
      if (content) reasoningParts.push(content)
      continue
    }
    if (event.type === 'model_delta') {
      const content = String(data.content || '')
      if (content) outputParts.push(content)
      continue
    }
    if (event.type === 'tool_call') {
      const toolName = String(data.tool_name || 'tool')
      const args = data.args && typeof data.args === 'object' ? formatToolArgs(data.args) : ''
      const callId = typeof data.id === 'string' ? data.id : ''
      const pair = { toolName, args, status: 'running' as const }
      if (callId) toolIndexById.set(callId, toolPairs.length)
      else toolIndexById.set(`__fallback_${fallbackIndex++}`, toolPairs.length)
      toolPairs.push(pair)
      continue
    }
    if (event.type === 'tool_result') {
      const callId = typeof data.tool_call_id === 'string' ? data.tool_call_id : ''
      const pairIndex = callId ? toolIndexById.get(callId) : undefined
      if (typeof pairIndex === 'number' && toolPairs[pairIndex]) {
        toolPairs[pairIndex] = { ...toolPairs[pairIndex], status: data.status || 'done' }
      } else {
        // 没有配对的 tool_call，作为只读结果展示
        const toolName = String(data.tool_name || 'tool')
        toolPairs.push({ toolName, args: '', status: data.status || 'done' })
      }
      continue
    }
    if (event.type === 'task_plan') {
      const plan = data.task_plan
      if (plan && typeof plan === 'object') {
        plans.push({ ...(plan as Record<string, any>), __idx: plans.length })
      }
      continue
    }
    // run_end / error / run_start 等元信息
    if (event.type === 'run_end' || event.type === 'error' || event.type === 'run_start') {
      meta.push(event)
    }
  }
  return {
    reasoning: reasoningParts.join(''),
    output: outputParts.join(''),
    toolPairs,
    plans,
    meta,
  }
}

/** 汇总子 Agent 思考过程文本。 */
function getSubAgentReasoning(subRun: SubAgentRunBlock): string {
  return groupSubAgentEvents(subRun).reasoning
}

/** 汇总子 Agent 最终输出文本。 */
function getSubAgentOutput(subRun: SubAgentRunBlock): string {
  return groupSubAgentEvents(subRun).output
}

/** 汇总子 Agent 工具调用 timeline。 */
function getSubAgentToolPairs(subRun: SubAgentRunBlock): SubAgentGrouped['toolPairs'] {
  return groupSubAgentEvents(subRun).toolPairs
}

/** 汇总子 Agent 任务计划。 */
function getSubAgentTaskPlans(subRun: SubAgentRunBlock): SubAgentGrouped['plans'] {
  return groupSubAgentEvents(subRun).plans
}

/** 汇总子 Agent 元信息（运行结束 / 错误）。 */
function getSubAgentMetaEvents(subRun: SubAgentRunBlock): SubAgentRunEvent[] {
  return groupSubAgentEvents(subRun).meta
}

/** 判断工具块是否是 A2A 调用。 */
function isA2AToolBlock(block: ToolCallBlock): boolean {
  return block.tool_name === 'a2a_call'
}

/** 更新指定 assistant 消息。 */
function updateAssistantMessage(index: number, updater: (message: MessageItem) => MessageItem) {
  const current = messages.value[index]
  if (!current || current.role !== 'assistant') return
  messages.value[index] = updater(current)
}

/** 追加思考增量,连续思考会合并为同一个块。 */
function appendReasoningBlock(index: number, delta: string) {
  if (!delta) return
  updateAssistantMessage(index, (message) => {
    const blocks = [...message.blocks]
    const last = blocks[blocks.length - 1]
    if (last?.type === 'reasoning') {
      blocks[blocks.length - 1] = { ...last, content: last.content + delta }
    } else {
      blocks.push({ type: 'reasoning', content: delta })
    }
    return {
      ...message,
      reasoning: message.reasoning + delta,
      blocks,
    }
  })
}

/** 追加正式回复增量,连续回复会合并为同一个块。 */
function appendContentBlock(index: number, delta: string) {
  if (!delta) return
  updateAssistantMessage(index, (message) => {
    const blocks = [...message.blocks]
    const last = blocks[blocks.length - 1]
    if (last?.type === 'content') {
      blocks[blocks.length - 1] = { ...last, content: last.content + delta }
    } else {
      blocks.push({ type: 'content', content: delta })
    }
    return {
      ...message,
      content: message.content + delta,
      blocks,
    }
  })
}

/** 判断工具调用事件是否值得渲染,过滤模型工具调用分片里的空壳事件。 */
function isRenderableToolCallEvent(data: Record<string, any>): boolean {
  const toolName = String(data.tool_name || '')
  const args = data.args
  const hasRealToolName = toolName.length > 0 && toolName !== 'tool'
  const hasObjectArgs = !!args && typeof args === 'object' && !Array.isArray(args)

  // LangChain 的 tool_call_chunks 可能会把参数按字符串碎片流出, 例如 "{"、"\"name\": ..."。
  // 这类事件只代表模型正在拼工具参数,不是一次完整工具调用,前端不展示。
  return hasRealToolName && hasObjectArgs
}

/** 记录一次工具调用,并按到达顺序加入时间线。 */
function appendToolCallBlock(index: number, data: Record<string, any>) {
  if (!isRenderableToolCallEvent(data)) return

  const callId = typeof data.id === 'string' ? data.id : null
  const args = (data.args as Record<string, unknown>) || {}
  const toolBlock: ToolCallBlock = {
    type: 'tool',
    tool_name: String(data.tool_name || 'tool'),
    args,
    call_id: callId,
    output: null,
    status: 'running',
    sub_agent_runs: [],
  }

  updateAssistantMessage(index, (message) => {
    // 同一个 tool_call_id 可能被流式分片多次推送,这里更新同一个工具块,避免页面散成多张卡片。
    if (callId) {
      const blocks = [...message.blocks]
      const blockIndex = blocks.findIndex((block) => block.type === 'tool' && block.call_id === callId)
      const callIndex = message.tool_calls.findIndex((call) => call.call_id === callId)
      if (blockIndex >= 0) {
        const oldBlock = blocks[blockIndex] as ToolCallBlock
        const nextBlock: ToolCallBlock = {
          ...oldBlock,
          tool_name: toolBlock.tool_name || oldBlock.tool_name,
          args: Object.keys(args).length ? args : oldBlock.args,
          status: oldBlock.status === 'done' ? 'done' : 'running',
        }
        blocks[blockIndex] = nextBlock
        const tool_calls = message.tool_calls.map((call, currentIndex) =>
          currentIndex === callIndex ? nextBlock : call,
        )
        return { ...message, tool_calls, blocks }
      }
    }

    return {
      ...message,
      tool_calls: [...message.tool_calls, toolBlock],
      blocks: [...message.blocks, toolBlock],
    }
  })
}

/** 查找子 Agent 事件应该挂载到哪个 A2A 工具块。 */
function findA2AToolBlockIndex(blocks: StreamBlock[], parentToolCallId: string | null): number {
  if (parentToolCallId) {
    const matchedIndex = blocks.findIndex(
      (block) => block.type === 'tool' && block.call_id === parentToolCallId,
    )
    if (matchedIndex >= 0) return matchedIndex
  }

  // 兜底：如果后端没有传 parent_tool_call_id，就挂到最近一个 a2a_call 工具块下面。
  for (let index = blocks.length - 1; index >= 0; index -= 1) {
    const block = blocks[index]
    if (block.type === 'tool' && isA2AToolBlock(block)) return index
  }
  return -1
}

/** 根据子 Agent 事件类型推导子运行状态。 */
function getNextSubAgentStatus(eventType: string, currentStatus: SubAgentRunBlock['status']): SubAgentRunBlock['status'] {
  if (eventType === 'run_end') return 'done'
  if (eventType === 'error') return 'failed'
  return currentStatus
}

/** 把 sub_agent_event 挂到对应的 A2A 工具卡片下面。 */
function appendSubAgentEventBlock(index: number, data: Record<string, any>) {
  const rawEvent = data.event
  if (!rawEvent || typeof rawEvent !== 'object') return

  const subRunId = String(data.sub_run_id || '')
  if (!subRunId) return

  const agentId = String(data.agent_id || 'sub-agent')
  const parentToolCallId = typeof data.parent_tool_call_id === 'string' ? data.parent_tool_call_id : null
  const eventType = String(rawEvent.type || 'event')
  const eventData = ((rawEvent.data || {}) as Record<string, any>)
  const subEvent: SubAgentRunEvent = {
    type: eventType,
    data: eventData,
    time: now(),
  }

  updateAssistantMessage(index, (message) => {
    const blocks = message.blocks.map((block) => ({ ...block })) as StreamBlock[]
    const toolBlockIndex = findA2AToolBlockIndex(blocks, parentToolCallId)
    if (toolBlockIndex < 0) return message

    const toolBlock = blocks[toolBlockIndex]
    if (toolBlock.type !== 'tool') return message

    const currentRuns = [...(toolBlock.sub_agent_runs || [])]
    const runIndex = currentRuns.findIndex((run) => run.sub_run_id === subRunId)
    if (runIndex >= 0) {
      const currentRun = currentRuns[runIndex]
      const nextStatus = getNextSubAgentStatus(eventType, currentRun.status)
      currentRuns[runIndex] = {
        ...currentRun,
        status: nextStatus,
        collapsed: nextStatus === 'running' ? currentRun.collapsed : true,
        events: [...currentRun.events, subEvent],
      }
    } else {
      currentRuns.push({
        sub_run_id: subRunId,
        agent_id: agentId,
        status: getNextSubAgentStatus(eventType, 'running'),
        collapsed: false,
        events: [subEvent],
      })
    }

    const nextToolBlock: ToolCallBlock = {
      ...toolBlock,
      sub_agent_runs: currentRuns,
    }
    blocks[toolBlockIndex] = nextToolBlock

    const tool_calls = message.tool_calls.map((call) => {
      if (nextToolBlock.call_id && call.call_id === nextToolBlock.call_id) return nextToolBlock
      return call
    })

    return { ...message, blocks, tool_calls }
  })
}

/** 回填工具执行结果,优先按 tool_call_id 匹配,否则匹配最后一个运行中的工具块。 */
function finishToolCallBlock(index: number, data: Record<string, any>) {
  updateAssistantMessage(index, (message) => {
    const callId = typeof data.tool_call_id === 'string' ? data.tool_call_id : null
    const blocks = message.blocks.map((block) => ({ ...block })) as StreamBlock[]
    const toolIndexes = blocks
      .map((block, blockIndex) => ({ block, blockIndex }))
      .filter((item): item is { block: ToolCallBlock; blockIndex: number } => item.block.type === 'tool')

    const matched = callId
      ? toolIndexes.find((item) => item.block.call_id === callId)
      : [...toolIndexes].reverse().find((item) => item.block.status === 'running')
    const target = matched || toolIndexes[toolIndexes.length - 1]

    if (!target) return message

    const nextToolBlock: ToolCallBlock = {
      ...target.block,
      tool_name: String(data.tool_name || target.block.tool_name || 'tool'),
      status: 'done',
      output: data.output ?? null,
    }
    blocks[target.blockIndex] = nextToolBlock

    const toolCallIndex = (() => {
      if (nextToolBlock.call_id) {
        return message.tool_calls.findIndex((call) => call.call_id === nextToolBlock.call_id)
      }
      const runningIndex = message.tool_calls.findLastIndex((call) => call.status === 'running')
      return runningIndex >= 0 ? runningIndex : message.tool_calls.length - 1
    })()
    const tool_calls = message.tool_calls.map((call, callIndex) =>
      callIndex === toolCallIndex ? nextToolBlock : call,
    )

    return {
      ...message,
      tool_calls,
      blocks,
    }
  })
}

/** 把指定 assistant 消息中仍在运行的工具块标记为目标状态。 */
function markRunningTools(index: number, status: 'done' | 'failed') {
  updateAssistantMessage(index, (message) => {
    const blocks = message.blocks.map((block) => {
      if (block.type === 'tool' && block.status === 'running') {
        return { ...block, status }
      }
      return block
    }) as StreamBlock[]
    const tool_calls = message.tool_calls.map((call) =>
      call.status === 'running' ? { ...call, status } : call,
    )
    return { ...message, blocks, tool_calls }
  })
}

/** 从任务计划对象中读取步骤列表，避免模板里直接假设后端字段一定存在。 */
function getTaskPlanSteps(taskPlan: Record<string, any> | null | undefined): Array<Record<string, any>> {
  const steps = taskPlan?.steps
  return Array.isArray(steps) ? steps.filter((item) => item && typeof item === 'object') : []
}

/** 根据任务步骤状态返回对应的样式类名。 */
function getTaskStepStatusClass(status: unknown): string {
  const normalizedStatus = String(status || 'waiting').toLowerCase()
  return `step-status-${normalizedStatus}`
}

/** 从 interrupt block 中读取待确认的任务计划。 */
function getInterruptTaskPlan(block: InterruptBlock): Record<string, any> | null {
  const data = block.payload?.data
  if (!data || typeof data !== 'object') return null
  const taskPlan = (data as Record<string, any>).task_plan
  return taskPlan && typeof taskPlan === 'object' ? taskPlan as Record<string, any> : null
}

/** 把 task_plan 事件追加到 assistant 时间线中。 */
function appendTaskPlanBlock(index: number, data: Record<string, any>) {
  const taskPlan = data.task_plan
  if (!taskPlan || typeof taskPlan !== 'object') return
  updateAssistantMessage(index, (message) => ({
    ...message,
    blocks: [...message.blocks, { type: 'task_plan', task_plan: taskPlan as Record<string, any> }],
  }))
}

/** 对任意 JSON 值递归排序对象 key，保证任务计划签名稳定。 */
function normalizeJsonValue(value: unknown): unknown {
  if (Array.isArray(value)) return value.map((item) => normalizeJsonValue(item))
  if (value && typeof value === 'object') {
    return Object.keys(value as Record<string, unknown>)
      .sort()
      .reduce<Record<string, unknown>>((acc, key) => {
        acc[key] = normalizeJsonValue((value as Record<string, unknown>)[key])
        return acc
      }, {})
  }
  return value
}

/** 为任务计划构建稳定签名，用来判断 task_plan 与 interrupt 里的计划是否重复。 */
function buildTaskPlanSignature(taskPlan: Record<string, any> | null | undefined): string {
  try {
    return JSON.stringify(normalizeJsonValue(taskPlan || {}))
  } catch {
    return String(taskPlan || '')
  }
}

/** 判断中断 payload 中是否携带任务计划。 */
function getTaskPlanFromInterruptPayload(payload: Record<string, any>): Record<string, any> | null {
  const data = payload.data
  if (!data || typeof data !== 'object') return null
  const taskPlan = (data as Record<string, any>).task_plan
  return taskPlan && typeof taskPlan === 'object' ? taskPlan as Record<string, any> : null
}

/** 如果中断卡片已经包含同一份草稿计划，则移除刚刚追加的重复 task_plan 块。 */
function removeDuplicatedDraftPlanBeforeInterrupt(blocks: StreamBlock[], taskPlan: Record<string, any> | null): StreamBlock[] {
  if (!taskPlan || blocks.length === 0) return blocks
  const lastBlock = blocks[blocks.length - 1]
  if (lastBlock.type !== 'task_plan') return blocks

  const samePlan = buildTaskPlanSignature(lastBlock.task_plan) === buildTaskPlanSignature(taskPlan)
  const isDraft = String(lastBlock.task_plan.status || taskPlan.status || '').toLowerCase() === 'draft'
  return samePlan && isDraft ? blocks.slice(0, -1) : blocks
}

/** 把 interrupt 事件追加到 assistant 时间线中，用于渲染用户确认卡片。 */
function appendInterruptBlock(index: number, data: Record<string, any>) {
  const payload = data.payload
  if (!payload || typeof payload !== 'object') return
  const taskPlan = getTaskPlanFromInterruptPayload(payload as Record<string, any>)

  updateAssistantMessage(index, (message) => {
    // set_task_plan 后端会先推 task_plan，再推 interrupt；确认卡片本身也包含同一份 draft，
    // 因此这里合并展示，避免用户在同一轮里看到两张完全相同的任务计划卡片。
    const blocks = removeDuplicatedDraftPlanBeforeInterrupt([...message.blocks], taskPlan)
    return {
      ...message,
      blocks: [
        ...blocks,
        {
          type: 'interrupt',
          payload: payload as Record<string, any>,
          status: 'waiting',
          feedback: '',
        },
      ],
    }
  })
}

/** 标记某个中断确认块已经被用户处理，避免重复点击。 */
function markInterruptAnswered(messageIndex: number, blockIndex: number) {
  updateAssistantMessage(messageIndex, (message) => {
    const blocks = message.blocks.map((block, index) => {
      if (index === blockIndex && block.type === 'interrupt') {
        return { ...block, status: 'answered' }
      }
      return block
    }) as StreamBlock[]
    return { ...message, blocks }
  })
}

/** 在当前 Assistant 时间线追加会话总结状态块。 */
function appendContextSummaryBlock(index: number, status: ContextSummaryBlock['status'], summaryMessage = '') {
  updateAssistantMessage(index, (current) => ({
    ...current,
    blocks: [...current.blocks, { type: 'context_summary', status, message: summaryMessage }],
  }))
}

/** 更新当前 Assistant 时间线最后一个会话总结状态块。 */
function updateContextSummaryBlock(index: number, status: ContextSummaryBlock['status'], summaryMessage = '') {
  updateAssistantMessage(index, (current) => {
    const blocks = [...current.blocks]
    for (let blockIndex = blocks.length - 1; blockIndex >= 0; blockIndex -= 1) {
      const block = blocks[blockIndex]
      if (block.type === 'context_summary') {
        blocks[blockIndex] = { ...block, status, message: summaryMessage || block.message }
        return { ...current, blocks }
      }
    }
    return { ...current, blocks: [...blocks, { type: 'context_summary', status, message: summaryMessage }] }
  })
}

/** 创建一条新的 assistant 流式消息，并返回它在 messages 中的位置。 */
async function createAssistantStreamMessage(): Promise<number> {
  messages.value.push({ role: 'assistant', content: '', reasoning: '', tool_calls: [], blocks: [], time: now() })
  await scrollToBottom(true)
  return messages.value.length - 1
}

/** 处理单条 Agent SSE 事件。 */
function handleAgentStreamEvent(index: number, event: Record<string, any>) {
  const data = (event.data || {}) as Record<string, any>

  // 生命周期：运行开始，记录 run_id，方便后续做运行链路查看。
  if (event.type === 'run_start' || event.type === 'resume_start') {
    if (data.run_id) {
      const last = messages.value[index]
      if (last) messages.value[index] = { ...last, run_id: String(data.run_id) }
    }
    return
  }

  // 生命周期：Agent 装配完成，普通聊天页保持简洁，不直接展示。
  if (event.type === 'agent_assembled') return

  // 子 Agent 事件：挂到对应 a2a_call 工具卡片下方，避免和主 Agent 输出混在一起。
  if (event.type === 'sub_agent_event') {
    appendSubAgentEventBlock(index, data)
    scrollToBottom()
    return
  }

  // 会话总结：仅展示状态，不展示内部摘要内容。
  if (event.type === 'context_summary_started') {
    appendContextSummaryBlock(index, 'running')
    scrollToBottom()
    return
  }
  if (event.type === 'context_summary_completed') {
    updateContextSummaryBlock(index, 'completed')
    scrollToBottom()
    return
  }
  if (event.type === 'context_summary_failed') {
    updateContextSummaryBlock(index, 'failed', String(data.message || ''))
    scrollToBottom()
    return
  }

  // 工具调用：模型发起一次新工具调用，按事件顺序加入时间线。
  if (event.type === 'tool_call') {
    appendToolCallBlock(index, data)
    scrollToBottom()
    return
  }

  // 工具结果：回填对应工具块，不进入正式回复正文。
  if (event.type === 'tool_result') {
    finishToolCallBlock(index, data)
    scrollToBottom()
    return
  }

  // 任务计划：规划工具写入 task_plan state 后，后端会推送完整快照。
  if (event.type === 'task_plan') {
    appendTaskPlanBlock(index, data)
    scrollToBottom()
    return
  }

  // 中断：渲染确认卡片，等待用户提交结构化 payload 恢复运行。
  if (event.type === 'interrupt') {
    appendInterruptBlock(index, data)
    running.value = false
    scrollToBottom()
    return
  }

  // 思考过程：reasoning_delta 按顺序追加到时间线，连续思考自动合并。
  if (event.type === 'reasoning_delta') {
    const delta = String(data.content || event.delta || event.content || '')
    appendReasoningBlock(index, delta)
    scrollToBottom()
    return
  }

  // 正式回复：model_delta 按顺序追加到时间线，连续回复自动合并。
  if (event.type === 'model_delta') {
    const delta = String(data.content || event.delta || event.content || '')
    appendContentBlock(index, delta)
    scrollToBottom()
    return
  }

  // 生命周期：运行结束，记录耗时和最终状态。
  if (event.type === 'run_end') {
    markRunningTools(index, 'done')
    const last = messages.value[index]
    if (last) {
      messages.value[index] = {
        ...last,
        elapsed_ms: typeof data.elapsed_ms === 'number' ? data.elapsed_ms : undefined,
        answer_length: typeof data.answer_length === 'number' ? data.answer_length : undefined,
      }
    }
    running.value = false
    return
  }

  // 错误：展示错误信息，并关闭 loading。
  if (event.type === 'error') {
    messages.value[index] = {
      ...messages.value[index],
      content: messages.value[index].content
        ? messages.value[index].content + `\n\n[错误] ${data.message || event.message || '未知错误'}`
        : `[错误] ${data.message || event.message || '未知错误'}`,
    }
    markRunningTools(index, 'failed')
    running.value = false
  }
}

/** 以流式方式发送 Agent 消息。 */
async function executeAgentStream(payload: Parameters<typeof runAgentStream>[0]) {
  running.value = true
  stickToBottom.value = true
  const idx = await createAssistantStreamMessage()

  await runAgentStream(
    payload,
    (event) => handleAgentStreamEvent(idx, event),
    (err) => {
      message.error('流式调用失败:' + err.message)
      markRunningTools(idx, 'failed')
      running.value = false
    },
    () => {
      // 兜底：网络流结束时确保 loading 关闭；如果已经中断，按钮卡片仍会保留在消息中。
      markRunningTools(idx, 'done')
      running.value = false
      scrollToBottom()
    },
  )
}

/** 查找当前会话里等待用户确认的任务计划中断卡片。 */
function findWaitingPlanInterrupt(): { messageIndex: number; blockIndex: number; block: InterruptBlock } | null {
  for (let messageIndex = messages.value.length - 1; messageIndex >= 0; messageIndex--) {
    const messageItem = messages.value[messageIndex]
    for (let blockIndex = messageItem.blocks.length - 1; blockIndex >= 0; blockIndex--) {
      const block = messageItem.blocks[blockIndex]
      if (block.type === 'interrupt' && block.status === 'waiting' && block.payload?.type === 'plan_confirmation') {
        return { messageIndex, blockIndex, block }
      }
    }
  }
  return null
}

/** 发送运行请求。 */
async function onRun() {
  if (waitingPlanConfirmation.value) {
    message.warning('请先处理任务计划确认卡片')
    return
  }
  if (!selectedAgentId.value) {
    message.warning('请先选择一个 Agent')
    return
  }
  const text = input.value.trim() || '请查看我上传的附件内容。'
  const currentFiles = [...uploadedFiles.value]
  if (!input.value.trim() && !currentFiles.length) {
    message.warning('请输入问题或上传附件')
    return
  }

  messages.value.push({
    role: 'user',
    content: text,
    reasoning: '',
    tool_calls: [],
    blocks: [],
    time: now(),
    file_names: currentFiles.map((file) => file.original_name),
  })
  input.value = ''
  uploadedFiles.value = []

  try {
    await executeAgentStream({
      agent_id: selectedAgentId.value,
      query: text,
      conversation_id: ensureConversationId(),
      message_type: 'text',
      payload: {},
      file_ids: currentFiles.map((file) => file.file_id),
      knowledge: selectedKnowledgeBaseIds.value.length
        ? { knowledge_base_ids: [...selectedKnowledgeBaseIds.value] }
        : null,
    })
  } catch (e) {
    running.value = false
    message.error('调用失败')
  }
}

/** 提交任务计划确认动作，并通过统一消息入口恢复被中断的 Agent。 */
async function submitPlanConfirmation(messageIndex: number, blockIndex: number, action: 'approve' | 'revise' | 'cancel') {
  if (running.value) return
  const targetMessage = messages.value[messageIndex]
  const targetBlock = targetMessage?.blocks[blockIndex]
  if (!targetMessage || targetBlock?.type !== 'interrupt') return

  const feedback = targetBlock.feedback.trim()
  if (action === 'revise' && !feedback) {
    message.warning('请输入修改意见')
    return
  }

  const actionTextMap = {
    approve: '确认执行任务计划',
    revise: `修改任务计划：${feedback}`,
    cancel: '取消任务计划',
  }

  markInterruptAnswered(messageIndex, blockIndex)
  messages.value.push({ role: 'user', content: actionTextMap[action], reasoning: '', tool_calls: [], blocks: [], time: now() })

  try {
    await executeAgentStream({
      agent_id: selectedAgentId.value,
      query: actionTextMap[action],
      conversation_id: ensureConversationId(),
      message_type: action === 'revise' ? 'form_submit' : 'action_click',
      payload: {
        type: 'plan_confirmation',
        data: {
          action,
          feedback: action === 'revise' ? feedback : undefined,
        },
      },
    })
  } catch (e) {
    running.value = false
    message.error('恢复执行失败')
  }
}

onMounted(async () => {
  await Promise.all([loadAgentList(), loadKnowledgeBaseOptions()])
  const queryAgentId = route.query.agent_id as string
  if (queryAgentId) {
    selectedAgentId.value = queryAgentId
    await loadAgentDetail(queryAgentId)
  }
})
</script>

<style scoped>
/* ========== 整体页面 ========== */
.invoke-page {
  display: flex;
  flex-direction: column;
  height: calc(100vh - 112px);
  background: linear-gradient(135deg, #f5f7fa 0%, #e8ecf3 100%);
  border-radius: 12px;
  overflow: hidden;
  box-shadow: 0 4px 24px rgba(0, 0, 0, 0.06);
}

/* ========== 顶部 Header ========== */
.invoke-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 16px 24px;
  background: rgba(255, 255, 255, 0.85);
  backdrop-filter: blur(12px);
  border-bottom: 1px solid rgba(0, 0, 0, 0.06);
  z-index: 10;
}
.header-left {
  display: flex;
  align-items: center;
  gap: 12px;
}
.header-logo {
  width: 44px;
  height: 44px;
  border-radius: 12px;
  background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 22px;
  box-shadow: 0 4px 12px rgba(102, 126, 234, 0.3);
}
.header-title {
  display: flex;
  flex-direction: column;
  gap: 2px;
}
.title-main {
  font-size: 16px;
  font-weight: 600;
  color: #1f1f1f;
  letter-spacing: 0.3px;
}
.title-sub {
  font-size: 12px;
  color: #8c8c8c;
}
.agent-info {
  display: inline-flex;
  align-items: center;
  gap: 6px;
}
.agent-info-placeholder {
  color: #bfbfbf;
}
.status-dot {
  display: inline-block;
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: #52c41a;
  box-shadow: 0 0 0 2px rgba(82, 196, 26, 0.2);
  animation: pulse 2s infinite;
}
.status-dot.status-disabled {
  background: #bfbfbf;
  box-shadow: 0 0 0 2px rgba(191, 191, 191, 0.2);
}
@keyframes pulse {
  0%, 100% { box-shadow: 0 0 0 2px rgba(82, 196, 26, 0.2); }
  50% { box-shadow: 0 0 0 4px rgba(82, 196, 26, 0.1); }
}
.header-right {
  display: flex;
  align-items: center;
  gap: 8px;
}
.agent-select {
  width: 240px;
}
.icon-btn {
  width: 36px;
  height: 36px;
  padding: 0;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  border-radius: 8px;
}

/* ========== 消息区 ========== */
.message-area {
  flex: 1;
  overflow-y: auto;
  padding: 24px;
  position: relative;
}
.message-area::-webkit-scrollbar {
  width: 6px;
}
.message-area::-webkit-scrollbar-thumb {
  background: rgba(0, 0, 0, 0.1);
  border-radius: 3px;
}
.message-area::-webkit-scrollbar-thumb:hover {
  background: rgba(0, 0, 0, 0.2);
}
.messages-wrap {
  max-width: 860px;
  margin: 0 auto;
}

/* ========== 漂亮空状态 ========== */
.empty-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  height: 100%;
  min-height: 400px;
  text-align: center;
  padding: 0 24px;
}
.empty-icon-wrap {
  position: relative;
  margin-bottom: 24px;
}
.empty-icon {
  font-size: 56px;
  position: relative;
  z-index: 2;
  animation: float 3s ease-in-out infinite;
}
.empty-ripple {
  position: absolute;
  top: 50%;
  left: 50%;
  transform: translate(-50%, -50%);
  width: 100px;
  height: 100px;
  border-radius: 50%;
  background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
  opacity: 0.08;
  z-index: 1;
  animation: ripple 2.5s ease-in-out infinite;
}
@keyframes float {
  0%, 100% { transform: translateY(0); }
  50% { transform: translateY(-8px); }
}
@keyframes ripple {
  0%, 100% { transform: translate(-50%, -50%) scale(1); opacity: 0.08; }
  50% { transform: translate(-50%, -50%) scale(1.3); opacity: 0.04; }
}
.empty-title {
  font-size: 22px;
  font-weight: 600;
  color: #1f1f1f;
  margin: 0 0 8px;
}
.empty-desc {
  font-size: 14px;
  color: #8c8c8c;
  margin: 0 0 24px;
  max-width: 400px;
  line-height: 1.6;
}
.empty-suggestions {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  justify-content: center;
}

/* ========== 消息气泡 ========== */
.message {
  display: flex;
  gap: 12px;
  margin-bottom: 24px;
  animation: messageIn 0.3s ease-out;
}
@keyframes messageIn {
  from { opacity: 0; transform: translateY(8px); }
  to { opacity: 1; transform: translateY(0); }
}
.message-user {
  flex-direction: row-reverse;
}
.message-avatar {
  width: 36px;
  height: 36px;
  border-radius: 10px;
  display: flex;
  align-items: center;
  justify-content: center;
  background: linear-gradient(135deg, #f0f2f5 0%, #e6e9ed 100%);
  box-shadow: 0 2px 6px rgba(0, 0, 0, 0.06);
  font-size: 18px;
  flex-shrink: 0;
}
.message-user .message-avatar {
  background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
  color: #fff;
}
.message-body {
  background: #fff;
  padding: 12px 16px;
  border-radius: 12px;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.04);
  max-width: calc(100% - 60px);
  min-width: 60px;
}
.message-user .message-body {
  background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
  color: #fff;
}
.message-meta {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 4px;
  font-size: 12px;
  color: #8c8c8c;
}
.message-user .message-meta {
  color: rgba(255, 255, 255, 0.85);
}
.message-role {
  font-weight: 500;
}
.message-time {
  margin-left: auto;
}

/* ========== 思考过程 ========== */
.message-reasoning {
  margin-bottom: 10px;
  padding: 10px 12px;
  background: linear-gradient(135deg, #fafbfc 0%, #f5f6f8 100%);
  border-left: 3px solid #b37feb;
  border-radius: 6px;
  font-size: 12px;
  color: #595959;
  line-height: 1.7;
}
.reasoning-header {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-bottom: 6px;
}
.reasoning-icon {
  font-size: 13px;
}
.reasoning-label {
  font-size: 11px;
  color: #b37feb;
  font-weight: 500;
  letter-spacing: 0.5px;
  text-transform: uppercase;
}
.reasoning-content {
  white-space: pre-wrap;
  word-break: break-word;
}

/* ========== 工具调用 ========== */
.message-tool-call {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  margin-bottom: 8px;
  padding: 6px 10px;
  background: linear-gradient(135deg, #e6f4ff 0%, #f0f9ff 100%);
  border: 1px solid #91caff;
  border-radius: 8px;
  font-size: 12px;
  color: #003a8c;
}
.tool-left {
  display: flex;
  align-items: center;
  gap: 6px;
  flex: 1;
  min-width: 0;
  flex-wrap: wrap;
}
.tool-icon {
  font-size: 13px;
}
.tool-name {
  font-weight: 600;
  color: #0958d9;
}
.tool-args {
  color: #595959;
  font-family: 'Fira Code', 'Cascadia Code', Menlo, Consolas, monospace;
  font-size: 11px;
  word-break: break-all;
}
.tool-status {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 18px;
  height: 18px;
  font-weight: 600;
  font-size: 11px;
  flex-shrink: 0;
}
.status-done {
  color: #52c41a;
}
.status-failed {
  color: #ff4d4f;
}
.tool-output-hint {
  display: inline-block;
  margin-left: 4px;
  padding: 1px 6px;
  font-size: 10px;
  color: #1677ff;
  background: rgba(22, 119, 255, 0.08);
  border-radius: 4px;
  cursor: help;
}
.tool-output-pre {
  margin: 0;
  max-width: 480px;
  max-height: 360px;
  overflow: auto;
  font-size: 12px;
  line-height: 1.5;
  white-space: pre-wrap;
  word-break: break-all;
  font-family: 'Fira Code', 'Cascadia Code', Menlo, Consolas, monospace;
}


.tool-block-wrap {
  margin-bottom: 8px;
}
.sub-agent-panel {
  margin: 4px 0 10px 22px;
  border: 1px solid #d3adf7;
  border-radius: 8px;
  background: linear-gradient(135deg, #fcfaff 0%, #f9f0ff 100%);
  overflow: hidden;
}
.sub-agent-header {
  width: 100%;
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 7px 10px;
  border: 0;
  background: transparent;
  cursor: pointer;
  text-align: left;
  font-size: 12px;
  color: #391085;
}
.sub-agent-header:hover {
  background: rgba(114, 46, 209, 0.06);
}
.sub-agent-title {
  font-weight: 600;
  color: #531dab;
}
.sub-agent-meta {
  color: #8c8c8c;
  flex: 1;
  min-width: 0;
}
.sub-agent-status {
  padding: 1px 6px;
  border-radius: 10px;
  font-size: 11px;
  flex-shrink: 0;
}
.sub-agent-status-running {
  color: #0958d9;
  background: #e6f4ff;
}
.sub-agent-status-done {
  color: #389e0d;
  background: #f6ffed;
}
.sub-agent-status-failed {
  color: #cf1322;
  background: #fff1f0;
}
.sub-agent-toggle {
  color: #722ed1;
  font-size: 11px;
  flex-shrink: 0;
}
.sub-agent-events {
  padding: 4px 10px 10px;
  display: flex;
  flex-direction: column;
  gap: 5px;
}
.sub-agent-event {
  display: flex;
  align-items: flex-start;
  gap: 8px;
  padding: 5px 7px;
  border-radius: 6px;
  background: rgba(255, 255, 255, 0.72);
  font-size: 11px;
  line-height: 1.5;
}
.sub-event-type {
  flex-shrink: 0;
  min-width: 56px;
  color: #722ed1;
  font-weight: 600;
}
.sub-event-content {
  flex: 1;
  color: #434343;
  white-space: pre-wrap;
  word-break: break-word;
}
.sub-agent-event-reasoning_delta .sub-event-content {
  color: #595959;
}
.sub-agent-event-model_delta .sub-event-content {
  color: #1f1f1f;
}
.sub-agent-event-tool_call .sub-event-content {
  color: #0958d9;
}
.sub-agent-event-error .sub-event-content {
  color: #cf1322;
}

/* 子 Agent 嵌套时间线：把散落的小字事件重组成"思考 → 工具 → 输出"的连续流 */
.sub-agent-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  flex-shrink: 0;
  background: #d9d9d9;
}
.sub-agent-dot-running {
  background: #1677ff;
  box-shadow: 0 0 0 3px rgba(22, 119, 255, 0.18);
  animation: sub-agent-pulse 1.4s ease-in-out infinite;
}
.sub-agent-dot-done { background: #52c41a; }
.sub-agent-dot-failed { background: #ff4d4f; }
@keyframes sub-agent-pulse {
  0%, 100% { box-shadow: 0 0 0 3px rgba(22, 119, 255, 0.18); }
  50%      { box-shadow: 0 0 0 6px rgba(22, 119, 255, 0); }
}

.sub-agent-timeline {
  padding: 6px 12px 12px;
  display: flex;
  flex-direction: column;
  gap: 8px;
  border-top: 1px dashed #d3adf7;
  margin-top: 2px;
}

.sub-agent-reasoning {
  font-size: 12px;
  color: #595959;
  background: #fafafa;
  border: 1px solid #f0f0f0;
  border-radius: 6px;
  padding: 4px 10px;
}
.sub-agent-reasoning summary {
  cursor: pointer;
  color: #722ed1;
  font-weight: 500;
  user-select: none;
}
.sub-agent-reasoning-body {
  margin-top: 6px;
  line-height: 1.6;
  white-space: pre-wrap;
  word-break: break-word;
  color: #595959;
}

.sub-agent-tool-row {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 5px 10px;
  border-radius: 6px;
  background: #f0f5ff;
  border: 1px solid #d6e4ff;
  font-size: 12px;
  line-height: 1.5;
}
.sub-agent-tool-icon { flex-shrink: 0; }
.sub-agent-tool-name {
  font-weight: 600;
  color: #1d39c4;
}
.sub-agent-tool-args {
  flex: 1;
  color: #595959;
  font-family: 'SFMono-Regular', Consolas, monospace;
  font-size: 11px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  min-width: 0;
}
.sub-agent-tool-status {
  flex-shrink: 0;
  padding: 1px 8px;
  border-radius: 10px;
  font-size: 11px;
}
.sub-agent-tool-status-running {
  color: #0958d9;
  background: #e6f4ff;
}
.sub-agent-tool-status-done {
  color: #389e0d;
  background: #f6ffed;
}
.sub-agent-tool-status-failed {
  color: #cf1322;
  background: #fff1f0;
}

.sub-agent-output {
  margin-top: 2px;
  padding: 10px 12px;
  border-radius: 8px;
  background: #fff;
  border: 1px solid #d3adf7;
  border-left: 3px solid #722ed1;
}
.sub-agent-output-label {
  font-size: 11px;
  font-weight: 600;
  color: #722ed1;
  margin-bottom: 6px;
  letter-spacing: 0.4px;
}
/* 子 Agent 输出在嵌套卡片里需要比外部更小的字号 */
.sub-agent-output :deep(.markdown-view) {
  font-size: 13px;
  line-height: 1.6;
}

.sub-agent-plan {
  margin: 0;
}

.sub-agent-event-meta {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 4px 8px;
  font-size: 11px;
  color: #8c8c8c;
  background: rgba(0, 0, 0, 0.02);
  border-radius: 4px;
}
.sub-agent-event-meta .meta-icon {
  flex-shrink: 0;
}
.sub-agent-event-meta-error {
  color: #cf1322;
  background: #fff1f0;
}


/* ========== 任务计划与中断确认 ========== */
.message-task-plan,
.message-interrupt {
  margin-bottom: 10px;
  padding: 10px 12px;
  background: #fff7e6;
  border: 1px solid #ffd591;
  border-radius: 8px;
  font-size: 12px;
  color: #5c3b00;
}
.plan-header,
.interrupt-header {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 8px;
}
.plan-title,
.interrupt-title {
  font-weight: 600;
  color: #1f1f1f;
}
.plan-status,
.interrupt-done {
  margin-left: auto;
  padding: 1px 6px;
  border-radius: 4px;
  background: rgba(250, 140, 22, 0.12);
  color: #d46b08;
  font-size: 11px;
}
.plan-steps,
.interrupt-plan {
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.plan-step {
  display: flex;
  align-items: flex-start;
  gap: 8px;
  line-height: 1.5;
}
.step-status {
  flex-shrink: 0;
  min-width: 58px;
  padding: 1px 6px;
  border-radius: 4px;
  background: #f5f5f5;
  border: 1px solid #d9d9d9;
  color: #595959;
  text-align: center;
  font-size: 11px;
}
.step-status-waiting {
  background: #f5f5f5;
  border-color: #d9d9d9;
  color: #595959;
}
.step-status-running {
  background: #e6f4ff;
  border-color: #91caff;
  color: #0958d9;
}
.step-status-done {
  background: #f6ffed;
  border-color: #b7eb8f;
  color: #389e0d;
}
.step-status-failed {
  background: #fff1f0;
  border-color: #ffa39e;
  color: #cf1322;
}
.step-title {
  flex: 1;
  color: #434343;
  word-break: break-word;
}
.interrupt-actions {
  margin-top: 10px;
  padding-top: 10px;
  border-top: 1px dashed #ffd591;
}
.interrupt-feedback {
  display: flex;
  flex-direction: column;
  gap: 8px;
  margin-top: 8px;
}

/* ========== 消息元信息 chip ========== */
.message-meta-extras {
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

/* ========== 正式回复 ========== */
.message-content {
  white-space: pre-wrap;
  word-break: break-word;
  line-height: 1.7;
  font-size: 14px;
  color: #1f1f1f;
}
.message-user .message-content {
  color: #fff;
}

/* ========== 打字指示器 ========== */
.typing-indicator {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 4px 0;
}
.typing-indicator span {
  display: inline-block;
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
  animation: typingBounce 1.4s ease-in-out infinite;
}
.typing-indicator span:nth-child(2) {
  animation-delay: 0.2s;
}
.typing-indicator span:nth-child(3) {
  animation-delay: 0.4s;
}
@keyframes typingBounce {
  0%, 60%, 100% { transform: translateY(0); opacity: 0.4; }
  30% { transform: translateY(-6px); opacity: 1; }
}

/* ========== 回到最新按钮 ========== */
.jump-to-bottom {
  position: sticky;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  width: fit-content;
  margin: 8px auto 0;
  padding: 6px 16px;
  background: #fff;
  border: 1px solid #d9d9d9;
  border-radius: 18px;
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.1);
  font-size: 12px;
  color: #1677ff;
  cursor: pointer;
  user-select: none;
  z-index: 2;
  transition: all 0.2s;
}
.jump-to-bottom:hover {
  background: #e6f4ff;
  border-color: #91caff;
  transform: translateY(-1px);
  box-shadow: 0 6px 16px rgba(22, 119, 255, 0.15);
}
.jump-icon {
  font-size: 14px;
  font-weight: 600;
}
.jump-fade-enter-active,
.jump-fade-leave-active {
  transition: opacity 0.2s, transform 0.2s;
}
.jump-fade-enter-from,
.jump-fade-leave-to {
  opacity: 0;
  transform: translateY(8px);
}

/* ========== 输入区 ========== */
.input-area {
  padding: 16px 24px 20px;
  background: rgba(255, 255, 255, 0.85);
  backdrop-filter: blur(12px);
  border-top: 1px solid rgba(0, 0, 0, 0.06);
  z-index: 10;
}
.knowledge-scope {
  display: flex;
  align-items: center;
  gap: 10px;
  max-width: 860px;
  margin: 0 auto 8px;
}
.knowledge-scope-label {
  flex: 0 0 auto;
  color: #595959;
  font-size: 12px;
}
.knowledge-scope-select {
  flex: 1;
  min-width: 0;
}
.input-wrap {
  display: flex;
  align-items: flex-end;
  gap: 12px;
  max-width: 860px;
  margin: 0 auto;
  background: #fff;
  border: 1px solid #d9d9d9;
  border-radius: 16px;
  padding: 8px 8px 8px 16px;
  transition: all 0.2s;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.04);
}
.input-wrap:hover {
  border-color: #91caff;
}
.input-wrap:focus-within {
  border-color: #1677ff;
  box-shadow: 0 0 0 3px rgba(22, 119, 255, 0.1);
}
.chat-input {
  flex: 1;
  border: none !important;
  box-shadow: none !important;
  background: transparent !important;
  padding: 8px 0 !important;
  resize: none !important;
}
.chat-input :deep(.ant-input) {
  border: none !important;
  box-shadow: none !important;
  padding: 0 !important;
  background: transparent !important;
}
.attachment-tray {
  display: flex;
  align-items: center;
  gap: 8px;
  max-width: 860px;
  margin: 0 auto 8px;
  flex-wrap: wrap;
}
.attachment-uploading {
  font-size: 12px;
  color: #595959;
}
.attachment-chip,
.message-file-chip {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  max-width: 260px;
  padding: 4px 8px;
  border: 1px solid #91caff;
  border-radius: 6px;
  background: #e6f4ff;
  color: #0958d9;
  font-size: 12px;
}
.attachment-name {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.attachment-remove {
  display: inline-flex;
  align-items: center;
  border: 0;
  padding: 0;
  background: transparent;
  color: #0958d9;
  cursor: pointer;
}
.attachment-remove:disabled {
  cursor: not-allowed;
  color: #bfbfbf;
}
.file-input-hidden {
  display: none;
}
.attach-btn {
  flex: 0 0 auto;
  border: 0;
  box-shadow: none;
}
.message-file-list {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-top: 8px;
}
.message-user .message-file-chip {
  border-color: rgba(255, 255, 255, 0.5);
  background: rgba(255, 255, 255, 0.16);
  color: #fff;
}
.message-context-summary {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 10px;
  padding: 7px 10px;
  border-left: 3px solid #1677ff;
  border-radius: 4px;
  background: #e6f4ff;
  color: #0958d9;
  font-size: 12px;
}

.send-btn {
  height: 36px;
  min-width: 80px;
  border-radius: 12px;
  background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
  border: none;
  font-weight: 500;
}
.send-btn:hover:not(:disabled) {
  background: linear-gradient(135deg, #5568d3 0%, #6a3f9c 100%) !important;
}
.send-btn:disabled {
  background: #f5f5f5 !important;
  color: #bfbfbf !important;
  border: none;
}
.input-hint {
  max-width: 860px;
  margin: 8px auto 0;
  font-size: 12px;
  color: #8c8c8c;
  text-align: center;
}
.hint-active {
  display: inline-flex;
  align-items: center;
  gap: 4px;
}
.hint-waiting {
  color: #d46b08;
}
</style>
