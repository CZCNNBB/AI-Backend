/**
 * 6. 会话详情页
 * - Tab 切换：消息流 / 运行记录
 */
<template>
  <div>
    <h2 class="page-title">
      💬 会话详情 - <span class="text-gray-500 text-sm">{{ conversationId }}</span>
    </h2>

    <a-card class="mb-4">
      <a-space>
        <span><b>状态：</b>{{ conversation?.status || '-' }}</span>
        <span><b>标题：</b>{{ conversation?.title || '-' }}</span>
        <span><b>创建：</b>{{ formatTime(conversation?.created_at) }}</span>
        <a-button type="link" @click="router.push(`/agents`)" size="small">🤖 Agent 列表</a-button>
      </a-space>
    </a-card>

    <a-tabs v-model:active-key="activeTab">
      <!-- 消息流 -->
      <a-tab-pane key="messages" tab="📩 消息流">
        <a-card>
          <div class="message-area">
            <div v-for="(m, i) in messages" :key="m.message_id || i" :class="['msg', `msg-${m.role}`]">
              <div class="msg-meta">
                <a-tag :color="roleColor(m.role)">{{ m.role }}</a-tag>
                <a-tag v-if="m.message_type" color="default">{{ m.message_type }}</a-tag>
                <span v-if="m.tool_name" class="text-gray-500">🔧 {{ m.tool_name }}</span>
                <span class="msg-time">{{ formatTime(m.created_at) }}</span>
              </div>
              <div class="msg-content">{{ m.content }}</div>
              <a-collapse v-if="m.structured_content" ghost>
                <a-collapse-panel header="📦 结构化内容">
                  <pre>{{ JSON.stringify(m.structured_content, null, 2) }}</pre>
                </a-collapse-panel>
              </a-collapse>
            </div>
            <a-empty v-if="!messages.length && !loading" description="暂无消息" />
          </div>
        </a-card>
      </a-tab-pane>

      <!-- 运行记录 -->
      <a-tab-pane key="runs" tab="📊 运行记录">
        <a-card>
          <a-table
            :columns="runColumns"
            :data-source="runs"
            :loading="loadingRuns"
            :pagination="false"
            row-key="run_id"
          >
            <template #bodyCell="{ column, record }">
              <template v-if="column.dataIndex === 'status'">
                <a-tag :color="statusColor(record.status)">{{ record.status }}</a-tag>
              </template>
              <template v-else-if="column.dataIndex === 'started_at' || column.dataIndex === 'finished_at'">
                {{ formatTime(record[column.dataIndex]) }}
              </template>
              <template v-else-if="column.dataIndex === 'elapsed_ms'">
                {{ record.elapsed_ms ?? '-' }} ms
              </template>
              <template v-else-if="column.dataIndex === 'action'">
                <a-button type="link" size="small" @click="router.push('/runs')">在监控中查看</a-button>
              </template>
            </template>
          </a-table>
        </a-card>
      </a-tab-pane>
    </a-tabs>
  </div>
</template>

<script setup lang="ts">
/**
 * 会话详情页逻辑
 * - 加载会话元信息 + 消息列表 + 该会话的运行记录
 */
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import {
  searchConversations,
  getConversationMessages,
  type Conversation,
  type ConversationMessage,
} from '@/api/conversation'
import { searchAgentRuns, type AgentRun } from '@/api/agentRun'
import dayjs from 'dayjs'

defineOptions({ name: 'ConversationDetailView' })

const route = useRoute()
const router = useRouter()
const conversationId = computed(() => route.params.conversation_id as string)

const activeTab = ref('messages')

const conversation = ref<Conversation | null>(null)
const messages = ref<ConversationMessage[]>([])
const runs = ref<AgentRun[]>([])
const loading = ref(false)
const loadingRuns = ref(false)

const runColumns = [
  { title: 'Run ID', dataIndex: 'run_id', width: 220, ellipsis: true },
  { title: 'Agent', dataIndex: 'agent_id', width: 140 },
  { title: '类型', dataIndex: 'run_type', width: 80 },
  { title: '状态', dataIndex: 'status', width: 90 },
  { title: '耗时', dataIndex: 'elapsed_ms', width: 100 },
  { title: '开始时间', dataIndex: 'started_at', width: 180 },
  { title: '结束时间', dataIndex: 'finished_at', width: 180 },
  { title: '操作', dataIndex: 'action', width: 110 },
]

/** 加载元信息 + 消息 */
async function loadMessages() {
  loading.value = true
  try {
    try {
      // search 响应是 {items, total, ...}
      const res = await searchConversations({ conversation_id: conversationId.value })
      conversation.value = res.items?.[0] || null
    } catch {
      conversation.value = null
    }
    // 后端响应字段是 messages
    const res = await getConversationMessages(conversationId.value, 200)
    messages.value = res.messages || []
  } finally {
    loading.value = false
  }
}

/** 加载运行记录 */
async function loadRuns() {
  loadingRuns.value = true
  try {
    const res = await searchAgentRuns({
      conversation_id: conversationId.value,
      run_type: 'main',
      page: 1,
      page_size: 50,
    })
    runs.value = res.items
  } finally {
    loadingRuns.value = false
  }
}

/** 角色颜色 */
function roleColor(r: string) {
  return r === 'user' ? 'blue' : r === 'assistant' ? 'green' : r === 'tool' ? 'purple' : 'default'
}

/** 状态颜色 */
function statusColor(s: string) {
  return s === 'success' ? 'green' : s === 'failed' ? 'red' : 'blue'
}

/** 格式化时间 */
function formatTime(t?: string) {
  return t ? dayjs(t).format('YYYY-MM-DD HH:mm:ss') : '-'
}

onMounted(() => {
  loadMessages()
  loadRuns()
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
.message-area {
  min-height: 300px;
  max-height: 600px;
  overflow-y: auto;
}
.msg {
  margin-bottom: 10px;
  padding: 8px 10px;
  border-radius: 6px;
  background: #fafafa;
}
.msg-user {
  background: #e6f4ff;
}
.msg-assistant {
  background: #f6ffed;
}
.msg-tool {
  background: #f9f0ff;
}
.msg-meta {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 12px;
  color: #999;
  margin-bottom: 4px;
}
.msg-content {
  white-space: pre-wrap;
  word-break: break-word;
  line-height: 1.5;
}
.msg-time {
  margin-left: auto;
}
pre {
  background: #f5f5f5;
  padding: 8px;
  border-radius: 4px;
  font-size: 12px;
  max-height: 300px;
  overflow: auto;
}
</style>
