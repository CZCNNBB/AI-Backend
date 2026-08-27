/**
 * 5. 会话历史列表页
 * - 当前后端仅支持 conversation_id 精确搜索
 */
<template>
  <div>
    <h2 class="page-title">💬 会话历史</h2>

    <a-alert
      v-if="!debugContextReady"
      message="请先在页面顶部配置平台 API Key 和外部用户 ID。"
      type="info"
      show-icon
      class="mb-4"
    />

    <a-alert
      message="提示：当前后端 /conversations/search 接口仅支持 conversation_id 精确匹配。"
      type="info"
      show-icon
      class="mb-4"
    />

    <a-card class="mb-4">
      <a-form layout="inline">
        <a-form-item label="conversation_id">
          <a-input
            v-model:value="conversationId"
            placeholder="输入完整 conversation_id"
            style="width: 320px"
            allow-clear
            @press-enter="onSearch"
          />
        </a-form-item>
        <a-form-item>
          <a-button type="primary" @click="onSearch">🔍 查询</a-button>
        </a-form-item>
      </a-form>
    </a-card>

    <a-card>
      <a-table
        :columns="columns"
        :data-source="data"
        :loading="loading"
        :pagination="false"
        row-key="conversation_id"
      >
        <template #bodyCell="{ column, record }">
          <template v-if="column.dataIndex === 'created_at' || column.dataIndex === 'updated_at'">
            {{ formatTime(record[column.dataIndex]) }}
          </template>
          <template v-else-if="column.dataIndex === 'action'">
            <a-button type="link" size="small" @click="router.push(`/conversations/${record.conversation_id}`)">
              查看详情
            </a-button>
          </template>
        </template>
      </a-table>
    </a-card>
  </div>
</template>

<script setup lang="ts">
/**
 * 会话历史列表页逻辑
 * - 精确搜索单条会话
 * - 表格单行展示
 */
import { onBeforeUnmount, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { searchConversations, type Conversation } from '@/api/conversation'
import dayjs from 'dayjs'
import {
  BUSINESS_DEBUG_CONTEXT_CHANGED,
  hasCompleteBusinessDebugContext,
} from '@/utils/businessDebugContext'

defineOptions({ name: 'ConversationListView' })

const router = useRouter()
const conversationId = ref('')
const loading = ref(false)
const debugContextReady = ref(hasCompleteBusinessDebugContext())
const data = ref<Conversation[]>([])

const columns = [
  { title: 'Conversation ID', dataIndex: 'conversation_id', width: 320, ellipsis: true },
  { title: '标题', dataIndex: 'title', ellipsis: true },
  { title: '用户', dataIndex: 'user_id', width: 140 },
  { title: '状态', dataIndex: 'status', width: 100 },
  { title: '创建时间', dataIndex: 'created_at', width: 180 },
  { title: '更新时间', dataIndex: 'updated_at', width: 180 },
  { title: '操作', dataIndex: 'action', width: 100 },
]

/** 查询 */
async function onSearch() {
  debugContextReady.value = hasCompleteBusinessDebugContext()
  if (!debugContextReady.value) {
    data.value = []
    return
  }
  if (!conversationId.value.trim()) {
    data.value = []
    return
  }
  loading.value = true
  try {
    // 后端 search 响应是 {items, total, page, page_size}
    const res = await searchConversations({ conversation_id: conversationId.value.trim() })
    data.value = res.items || []
  } catch {
    data.value = []
  } finally {
    loading.value = false
  }
}

/** 格式化 */
function formatTime(t?: string) {
  return t ? dayjs(t).format('YYYY-MM-DD HH:mm:ss') : '-'
}

/** 顶部调试身份变化时同步页面提示状态。 */
function onDebugContextChanged(): void {
  debugContextReady.value = hasCompleteBusinessDebugContext()
  if (!debugContextReady.value) data.value = []
}

onMounted(() => window.addEventListener(BUSINESS_DEBUG_CONTEXT_CHANGED, onDebugContextChanged))
onBeforeUnmount(() => window.removeEventListener(BUSINESS_DEBUG_CONTEXT_CHANGED, onDebugContextChanged))
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
</style>
