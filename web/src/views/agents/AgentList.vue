/**
 * 2. Agent 模板管理列表页
 * - 分页 + 关键字搜索 + 状态筛选
 * - 操作：编辑 / 试跑 / 克隆 / 删除
 */
<template>
  <div>
    <h2 class="page-title">🤖 Agent 模板管理</h2>

    <!-- 顶部筛选 -->
    <a-card class="mb-4">
      <a-form layout="inline">
        <a-form-item label="关键字">
          <a-input
            v-model:value="filters.keyword"
            placeholder="搜索 agent_id / name / description"
            allow-clear
            style="width: 240px"
            @press-enter="onSearch"
          />
        </a-form-item>
        <a-form-item label="状态">
          <a-select v-model:value="filters.status" placeholder="全部" style="width: 140px" allow-clear>
            <a-select-option value="active">启用</a-select-option>
            <a-select-option value="disabled">禁用</a-select-option>
          </a-select>
        </a-form-item>
        <a-form-item>
          <a-button type="primary" @click="onSearch">🔍 查询</a-button>
          <a-button class="ml-2" @click="onReset">重置</a-button>
        </a-form-item>
        <a-form-item>
          <a-button type="primary" @click="router.push('/agents/create')">➕ 新建 Agent</a-button>
        </a-form-item>
      </a-form>
    </a-card>

    <!-- 列表 -->
    <a-card>
      <a-table
        :columns="columns"
        :data-source="list"
        :loading="loading"
        :pagination="pagination"
        row-key="agent_id"
        @change="onTableChange"
      >
        <template #bodyCell="{ column, record }">
          <template v-if="column.dataIndex === 'status'">
            <a-tag :color="record.status === 'active' ? 'green' : 'default'">
              {{ record.status === 'active' ? '启用' : '禁用' }}
            </a-tag>
          </template>
          <template v-else-if="column.dataIndex === 'is_sub_agent'">
            <a-tag :color="record.config?.is_sub_agent ? 'blue' : 'default'">
              {{ record.config?.is_sub_agent ? '可被 A2A' : '普通' }}
            </a-tag>
          </template>
          <template v-else-if="column.dataIndex === 'tools'">
            <a-tag v-for="t in (record.config?.tools || []).slice(0, 3)" :key="t" color="purple">{{ t }}</a-tag>
            <span v-if="(record.config?.tools || []).length > 3" class="text-gray-400">
              +{{ record.config.tools.length - 3 }}
            </span>
          </template>
          <template v-else-if="column.dataIndex === 'updated_at'">
            {{ formatTime(record.updated_at) }}
          </template>
          <template v-else-if="column.dataIndex === 'action'">
            <a-space>
              <a-button type="link" size="small" @click="router.push(`/agents/${record.agent_id}/edit`)">编辑</a-button>
              <a-button type="link" size="small" @click="router.push({ path: '/agent-invoke', query: { agent_id: record.agent_id } })">调用</a-button>
              <a-popconfirm title="确认删除该 Agent 模板？" @confirm="onDelete(record.agent_id)">
                <a-button type="link" size="small" danger>删除</a-button>
              </a-popconfirm>
            </a-space>
          </template>
        </template>
      </a-table>
    </a-card>
  </div>
</template>

<script setup lang="ts">
/**
 * Agent 列表页逻辑
 * - 搜索/筛选/分页
 * - 删除带二次确认
 */
import { onMounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { message } from 'ant-design-vue'
import { searchAgentTemplates, deleteAgentTemplate, type AgentTemplate } from '@/api/agentTemplate'
import dayjs from 'dayjs'

defineOptions({ name: 'AgentListView' })

const router = useRouter()
const loading = ref(false)
const list = ref<AgentTemplate[]>([])

const filters = reactive({ keyword: '', status: undefined as string | undefined })
const pagination = reactive({ current: 1, pageSize: 20, total: 0 })

const columns = [
  { title: 'Agent ID', dataIndex: 'agent_id', width: 180, ellipsis: true },
  { title: '名称', dataIndex: 'agent_name', width: 180 },
  { title: '描述', dataIndex: 'description', ellipsis: true },
  { title: '状态', dataIndex: 'status', width: 80 },
  { title: 'A2A', dataIndex: 'is_sub_agent', width: 90 },
  { title: '工具', dataIndex: 'tools', width: 220 },
  { title: '更新时间', dataIndex: 'updated_at', width: 170 },
  { title: '操作', dataIndex: 'action', width: 200, fixed: 'right' as const },
]

/** 加载列表 */
async function loadList() {
  loading.value = true
  try {
    const res = await searchAgentTemplates({
      keyword: filters.keyword || undefined,
      status: filters.status || undefined,
      page: pagination.current,
      page_size: pagination.pageSize,
    })
    list.value = res.items
    pagination.total = res.total
  } finally {
    loading.value = false
  }
}

/** 搜索 */
function onSearch() {
  pagination.current = 1
  loadList()
}

/** 重置 */
function onReset() {
  filters.keyword = ''
  filters.status = undefined
  onSearch()
}

/** 分页 / 排序变化 */
function onTableChange(pag: { current?: number; pageSize?: number }) {
  pagination.current = pag.current ?? 1
  pagination.pageSize = pag.pageSize ?? 20
  loadList()
}

/** 删除 */
async function onDelete(agent_id: string) {
  const deleted = await deleteAgentTemplate([agent_id])
  message.success(`删除成功，共删除 ${deleted} 条`)
  loadList()
}

/** 格式化时间 */
function formatTime(t?: string) {
  return t ? dayjs(t).format('YYYY-MM-DD HH:mm:ss') : '-'
}

onMounted(loadList)
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
