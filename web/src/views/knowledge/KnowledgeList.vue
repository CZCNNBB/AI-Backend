<template>
  <div class="knowledge-page">
    <header class="page-header">
      <div>
        <h1>知识库</h1>
        <p>管理用于 Agent 检索的资料集合、索引文档和入库任务。</p>
      </div>
      <a-button type="primary" size="large" @click="goCreate">
        <template #icon><PlusOutlined /></template>
        新建知识库
      </a-button>
    </header>

    <section class="metric-strip" aria-label="知识库概览">
      <div class="metric-item">
        <DatabaseOutlined />
        <div><strong>{{ stats.total }}</strong><span>全部知识库</span></div>
      </div>
      <div class="metric-item metric-active">
        <CheckCircleOutlined />
        <div><strong>{{ stats.active }}</strong><span>运行中</span></div>
      </div>
      <div class="metric-item">
        <StopOutlined />
        <div><strong>{{ stats.disabled }}</strong><span>已停用</span></div>
      </div>
      <div class="metric-item">
        <FieldTimeOutlined />
        <div><strong>{{ formatDate(latestUpdatedAt) }}</strong><span>最近更新</span></div>
      </div>
    </section>

    <section class="toolbar">
      <a-input
        v-model:value="filters.keyword"
        class="search-input"
        placeholder="搜索知识库名称"
        allow-clear
        @press-enter="loadList"
      >
        <template #prefix><SearchOutlined /></template>
      </a-input>
      <a-select v-model:value="filters.status" class="status-filter" @change="loadList">
        <a-select-option value="">全部状态</a-select-option>
        <a-select-option value="active">运行中</a-select-option>
        <a-select-option value="disabled">已停用</a-select-option>
        <a-select-option value="deleted">已删除</a-select-option>
      </a-select>
      <a-button @click="resetFilters">重置</a-button>
      <a-button :loading="loading" @click="loadList">
        <template #icon><ReloadOutlined /></template>
      </a-button>
    </section>

    <a-alert
      v-if="error"
      class="state-alert"
      type="error"
      show-icon
      :message="error"
      action-text="重试"
      @close="error = ''"
    />

    <a-table
      class="knowledge-table"
      :columns="columns"
      :data-source="list"
      :loading="loading"
      :pagination="{ pageSize: 12, showSizeChanger: false, hideOnSinglePage: true }"
      :row-key="(record: KnowledgeBaseItem) => record.knowledge_id"
      :scroll="{ x: 980 }"
    >
      <template #emptyText>
        <a-empty description="暂无符合条件的知识库">
          <a-button type="primary" @click="goCreate">新建知识库</a-button>
        </a-empty>
      </template>

      <template #bodyCell="{ column, record }">
        <template v-if="column.key === 'name'">
          <button class="name-cell" type="button" @click="goDetail(record.knowledge_id)">
            <span class="database-icon"><DatabaseOutlined /></span>
            <span>
              <strong>{{ record.name }}</strong>
              <small>{{ record.description || '暂无描述' }}</small>
            </span>
          </button>
        </template>
        <template v-else-if="column.key === 'status'">
          <a-tag :color="statusView(record.status).color">
            {{ statusView(record.status).label }}
          </a-tag>
        </template>
        <template v-else-if="column.key === 'model'">
          <div class="model-cell">
            <code>{{ record.embedding_model_code }}</code>
            <span>{{ record.embedding_dimension }} 维</span>
          </div>
        </template>
        <template v-else-if="column.key === 'split'">
          <span class="split-cell">{{ splitLabel(record.split_config) }}</span>
        </template>
        <template v-else-if="column.key === 'updated'">
          <span class="time-cell">{{ formatDateTime(record.updated_at) }}</span>
        </template>
        <template v-else-if="column.key === 'actions'">
          <div class="row-actions">
            <a-tooltip title="管理文档和任务">
              <a-button type="text" @click="goDetail(record.knowledge_id)">
                <template #icon><FolderOpenOutlined /></template>
              </a-button>
            </a-tooltip>
            <a-tooltip title="编辑">
              <a-button type="text" :disabled="record.status === 'deleted'" @click="goEdit(record.knowledge_id)">
                <template #icon><EditOutlined /></template>
              </a-button>
            </a-tooltip>
            <a-dropdown :trigger="['click']">
              <a-button type="text"><MoreOutlined /></a-button>
              <template #overlay>
                <a-menu>
                  <a-menu-item
                    v-if="record.status !== 'deleted'"
                    @click="toggleStatus(record)"
                  >
                    {{ record.status === 'active' ? '停用知识库' : '启用知识库' }}
                  </a-menu-item>
                  <a-menu-divider />
                  <a-menu-item
                    danger
                    :disabled="record.status === 'deleted'"
                    @click="confirmDelete(record)"
                  >
                    删除知识库
                  </a-menu-item>
                </a-menu>
              </template>
            </a-dropdown>
          </div>
        </template>
      </template>
    </a-table>
  </div>
</template>

<script setup lang="ts">
/** 知识库列表工作台，负责检索、状态切换、导航和删除。 */
import { computed, onMounted, reactive, ref } from 'vue'
import { Modal, message } from 'ant-design-vue'
import { useRouter } from 'vue-router'
import {
  CheckCircleOutlined,
  DatabaseOutlined,
  EditOutlined,
  FieldTimeOutlined,
  FolderOpenOutlined,
  MoreOutlined,
  PlusOutlined,
  ReloadOutlined,
  SearchOutlined,
  StopOutlined,
} from '@ant-design/icons-vue'
import {
  deleteKnowledgeBase,
  searchKnowledgeBases,
  updateKnowledgeBase,
  type KnowledgeBaseItem,
} from '@/api/knowledge'

defineOptions({ name: 'KnowledgeList' })

const router = useRouter()
const list = ref<KnowledgeBaseItem[]>([])
const loading = ref(false)
const error = ref('')
const filters = reactive({ keyword: '', status: '' })

const columns = [
  { title: '知识库', key: 'name', width: 320 },
  { title: '状态', key: 'status', width: 100 },
  { title: 'Embedding 模型', key: 'model', width: 210 },
  { title: '默认切片', key: 'split', width: 160 },
  { title: '最近更新', key: 'updated', width: 170 },
  { title: '操作', key: 'actions', width: 136, fixed: 'right' as const },
]

const stats = computed(() => ({
  total: list.value.length,
  active: list.value.filter((item) => item.status === 'active').length,
  disabled: list.value.filter((item) => item.status === 'disabled').length,
}))

const latestUpdatedAt = computed(() => {
  return [...list.value].sort((a, b) => b.updated_at.localeCompare(a.updated_at))[0]?.updated_at
})

/** 从后端加载知识库列表。 */
async function loadList() {
  loading.value = true
  error.value = ''
  try {
    list.value = await searchKnowledgeBases({
      keyword: filters.keyword.trim() || undefined,
      status: filters.status || undefined,
    })
  } catch (reason) {
    error.value = reason instanceof Error ? reason.message : String(reason)
    list.value = []
  } finally {
    loading.value = false
  }
}

/** 清空筛选并重新加载。 */
function resetFilters() {
  filters.keyword = ''
  filters.status = ''
  loadList()
}

/** 切换知识库启用状态。 */
async function toggleStatus(record: KnowledgeBaseItem) {
  const nextStatus = record.status === 'active' ? 'disabled' : 'active'
  try {
    await updateKnowledgeBase({ knowledge_id: record.knowledge_id, status: nextStatus })
    message.success(nextStatus === 'active' ? '知识库已启用' : '知识库已停用')
    await loadList()
  } catch {
    // HTTP 层已展示具体错误，此处只负责停止后续状态更新。
  }
}

/** 二次确认后删除知识库及其 Collection。 */
function confirmDelete(record: KnowledgeBaseItem) {
  Modal.confirm({
    title: '删除知识库',
    content: `将删除“${record.name}”的全部索引数据和 Milvus Collection，此操作不可恢复。`,
    okText: '确认删除',
    okType: 'danger',
    cancelText: '取消',
    async onOk() {
      await deleteKnowledgeBase(record.knowledge_id)
      message.success('知识库已删除')
      await loadList()
    },
  })
}

/** 进入新建页面。 */
function goCreate() {
  router.push('/knowledge/create')
}

/** 进入知识库详情工作台。 */
function goDetail(knowledgeId: string) {
  router.push(`/knowledge/${knowledgeId}`)
}

/** 进入知识库编辑页面。 */
function goEdit(knowledgeId: string) {
  router.push(`/knowledge/${knowledgeId}/edit`)
}

/** 返回统一状态展示。 */
function statusView(status: string) {
  const mapping: Record<string, { label: string; color: string }> = {
    active: { label: '运行中', color: 'green' },
    disabled: { label: '已停用', color: 'default' },
    deleted: { label: '已删除', color: 'red' },
  }
  return mapping[status] || { label: status, color: 'default' }
}

/** 提炼切片配置用于列表扫描。 */
function splitLabel(config: Record<string, unknown>) {
  const type = String(config?.type || 'recursive_character')
  const size = config?.chunk_size ? ` · ${config.chunk_size}` : ''
  const labels: Record<string, string> = {
    recursive_character: '递归字符',
    markdown_document_header_then_recursive: 'Markdown 标题',
    markdown_header: 'Markdown',
    character: '字符',
    qa_separator: '问答分隔',
  }
  return (labels[type] || type) + size
}

/** 格式化日期。 */
function formatDate(value?: string | null) {
  return value ? value.slice(0, 10) : '-'
}

/** 格式化日期时间。 */
function formatDateTime(value?: string | null) {
  if (!value) return '-'
  return new Intl.DateTimeFormat('zh-CN', {
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  }).format(new Date(value))
}

onMounted(loadList)
</script>

<style scoped>
.knowledge-page { min-width: 0; }
.page-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 24px;
  margin-bottom: 24px;
}
.page-header h1 { margin: 0; font-size: 24px; line-height: 1.35; color: #172033; }
.page-header p { margin: 6px 0 0; color: #697386; font-size: 14px; }
.metric-strip {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  border: 1px solid #e7eaf0;
  border-radius: 8px;
  margin-bottom: 20px;
  background: #fff;
}
.metric-item {
  display: flex;
  align-items: center;
  gap: 12px;
  min-height: 86px;
  padding: 16px 20px;
  border-right: 1px solid #e7eaf0;
  color: #657085;
}
.metric-item:last-child { border-right: 0; }
.metric-item > span { font-size: 20px; color: #3366cc; }
.metric-item div { display: flex; flex-direction: column; min-width: 0; }
.metric-item strong { color: #172033; font-size: 21px; font-weight: 650; line-height: 1.2; }
.metric-item span { margin-top: 4px; font-size: 12px; color: #7b8496; }
.metric-active > span { color: #2f8f62; }
.toolbar {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 14px;
}
.search-input { width: min(360px, 45vw); }
.status-filter { width: 140px; }
.state-alert { margin-bottom: 14px; }
.knowledge-table { border-top: 1px solid #edf0f5; }
.name-cell {
  display: flex;
  align-items: center;
  gap: 12px;
  width: 100%;
  padding: 0;
  border: 0;
  background: transparent;
  text-align: left;
  cursor: pointer;
}
.database-icon {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 36px;
  height: 36px;
  flex: 0 0 36px;
  border-radius: 6px;
  color: #3366cc;
  background: #eef4ff;
}
.name-cell > span:last-child { display: flex; flex-direction: column; min-width: 0; }
.name-cell strong { color: #172033; font-size: 14px; font-weight: 600; }
.name-cell small {
  max-width: 250px;
  margin-top: 3px;
  overflow: hidden;
  color: #7b8496;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.model-cell { display: flex; flex-direction: column; gap: 3px; }
.model-cell code { color: #263248; font-size: 12px; }
.model-cell span, .split-cell, .time-cell { color: #7b8496; font-size: 12px; }
.row-actions { display: flex; align-items: center; }
:deep(.ant-table-thead > tr > th) {
  color: #687386;
  font-size: 12px;
  font-weight: 600;
  background: #f8f9fb;
}
:deep(.ant-table-tbody > tr > td) { padding-top: 13px; padding-bottom: 13px; }

@media (max-width: 900px) {
  .metric-strip { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .metric-item:nth-child(2) { border-right: 0; }
  .metric-item:nth-child(-n + 2) { border-bottom: 1px solid #e7eaf0; }
}
@media (max-width: 640px) {
  .page-header { align-items: stretch; flex-direction: column; }
  .metric-strip { grid-template-columns: 1fr; }
  .metric-item { border-right: 0; border-bottom: 1px solid #e7eaf0; }
  .metric-item:last-child { border-bottom: 0; }
  .toolbar { align-items: stretch; flex-wrap: wrap; }
  .search-input { width: 100%; }
  .status-filter { flex: 1; }
}
</style>
