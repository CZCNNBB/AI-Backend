<template>
  <div class="detail-page">
    <header class="detail-header">
      <div class="title-side">
        <a-button type="text" @click="router.push('/knowledge')"><template #icon><ArrowLeftOutlined /></template></a-button>
        <span class="title-icon"><DatabaseOutlined /></span>
        <div>
          <div class="title-line">
            <h1>{{ knowledge?.name || '知识库详情' }}</h1>
            <a-tag v-if="knowledge" :color="knowledge.status === 'active' ? 'green' : 'default'">
              {{ baseStatusLabel(knowledge.status) }}
            </a-tag>
          </div>
          <p>{{ knowledge?.description || '暂无描述' }}</p>
        </div>
      </div>
      <div class="header-actions">
        <a-button :loading="loading" @click="loadAll"><template #icon><ReloadOutlined /></template>刷新</a-button>
        <a-button :disabled="knowledge?.status !== 'active'" @click="retrievalOpen = true">
          <template #icon><ExperimentOutlined /></template>检索测试
        </a-button>
        <a-button :disabled="knowledge?.status === 'deleted'" @click="goEdit"><template #icon><EditOutlined /></template>编辑</a-button>
        <a-button type="primary" :disabled="knowledge?.status !== 'active'" @click="openUpload">
          <template #icon><UploadOutlined /></template>添加文档
        </a-button>
      </div>
    </header>

    <a-skeleton v-if="loading && !knowledge" active :paragraph="{ rows: 8 }" />
    <template v-else-if="knowledge">
      <section class="metadata-strip">
        <div><span>知识库 ID</span><code>{{ knowledge.knowledge_id }}</code></div>
        <div><span>Embedding</span><strong>{{ knowledge.embedding_model_code }}</strong></div>
        <div><span>向量维度</span><strong>{{ knowledge.embedding_dimension }}</strong></div>
        <div><span>Collection</span><code>{{ knowledge.collection_name }}</code></div>
      </section>

      <a-tabs v-model:active-key="activeTab">
        <a-tab-pane key="documents">
          <template #tab><span><FileTextOutlined /> 文档 <a-badge :count="documents.length" :overflow-count="999" /></span></template>
          <div class="tab-toolbar">
            <a-input v-model:value="documentFilters.file_name" class="document-search" placeholder="搜索文件名" allow-clear @press-enter="loadDocuments">
              <template #prefix><SearchOutlined /></template>
            </a-input>
            <a-select v-model:value="documentFilters.status" class="filter-select" @change="loadDocuments">
              <a-select-option value="">全部状态</a-select-option>
              <a-select-option v-for="item in documentStatusOptions" :key="item.value" :value="item.value">{{ item.label }}</a-select-option>
            </a-select>
            <a-button @click="resetDocumentFilters">重置</a-button>
          </div>

          <a-table :columns="documentColumns" :data-source="documents" :loading="documentsLoading"
            :row-key="(record: KnowledgeDocumentRecord) => record.file_id"
            :pagination="{ pageSize: 10, hideOnSinglePage: true }" :scroll="{ x: 940 }">
            <template #emptyText>
              <a-empty description="这个知识库还没有文档">
                <a-button type="primary" :disabled="knowledge.status !== 'active'" @click="openUpload">添加第一份文档</a-button>
              </a-empty>
            </template>
            <template #bodyCell="{ column, record }">
              <template v-if="column.key === 'file'">
                <div class="file-cell">
                  <span class="file-icon">{{ extensionLabel(record.file_name) }}</span>
                  <div><strong>{{ record.file_name || record.file_id }}</strong><small>{{ formatBytes(record.size_bytes) }} · {{ record.mime_type || '未知类型' }}</small></div>
                </div>
              </template>
              <template v-else-if="column.key === 'status'">
                <a-tooltip :title="record.error_message || ''">
                  <a-tag :color="documentStatus(record.status).color">
                    <SyncOutlined v-if="isDocumentBusy(record.status)" spin /> {{ documentStatus(record.status).label }}
                  </a-tag>
                </a-tooltip>
              </template>
              <template v-else-if="column.key === 'chunks'"><strong>{{ record.chunk_count }}</strong><small class="secondary">v{{ record.index_version }}</small></template>
              <template v-else-if="column.key === 'indexed'"><span class="secondary">{{ formatDateTime(record.indexed_at) }}</span></template>
              <template v-else-if="column.key === 'actions'">
                <a-button type="text" :disabled="isDocumentBusy(record.status) || record.status === 'deleted'" @click="confirmReindex(record)">
                  <template #icon><RetweetOutlined /></template>
                </a-button>
                <a-button type="text" danger :disabled="isDocumentBusy(record.status) || record.status === 'deleted'" @click="confirmDeleteDocument(record)">
                  <template #icon><DeleteOutlined /></template>
                </a-button>
              </template>
            </template>
          </a-table>
        </a-tab-pane>

        <a-tab-pane key="tasks">
          <template #tab><span><UnorderedListOutlined /> 任务 <a-badge :count="activeTaskCount" /></span></template>
          <div class="tab-toolbar">
            <a-select v-model:value="taskFilters.operation" class="filter-select" @change="loadTasks(1)">
              <a-select-option value="">全部操作</a-select-option>
              <a-select-option value="ingest">首次入库</a-select-option>
              <a-select-option value="reindex">重建索引</a-select-option>
              <a-select-option value="delete">删除索引</a-select-option>
            </a-select>
            <a-select v-model:value="taskFilters.status" class="filter-select" @change="loadTasks(1)">
              <a-select-option value="">全部状态</a-select-option>
              <a-select-option v-for="item in taskStatusOptions" :key="item.value" :value="item.value">{{ item.label }}</a-select-option>
            </a-select>
            <a-button @click="resetTaskFilters">重置</a-button>
          </div>
          <a-table :columns="taskColumns" :data-source="tasks" :loading="tasksLoading"
            :row-key="(record: IngestionRunRecord) => record.run_id"
            :pagination="{ current: taskPage, pageSize: taskPageSize, total: taskTotal, showSizeChanger: false, hideOnSinglePage: true }"
            :scroll="{ x: 1000 }" @change="onTaskTableChange">
            <template #bodyCell="{ column, record }">
              <template v-if="column.key === 'operation'">{{ operationLabel(record.operation) }}</template>
              <template v-else-if="column.key === 'file'"><code class="id-code">{{ record.file_id }}</code></template>
              <template v-else-if="column.key === 'status'">
                <a-tag :color="taskStatus(record.status).color"><SyncOutlined v-if="['pending', 'running'].includes(record.status)" spin /> {{ taskStatus(record.status).label }}</a-tag>
              </template>
              <template v-else-if="column.key === 'retry'">{{ record.retry_count }} / {{ record.max_retries }}</template>
              <template v-else-if="column.key === 'created'"><span class="secondary">{{ formatDateTime(record.created_at) }}</span></template>
              <template v-else-if="column.key === 'actions'">
                <a-tooltip v-if="record.error_message" :title="record.error_message"><a-button type="text"><template #icon><InfoCircleOutlined /></template></a-button></a-tooltip>
                <a-button v-if="record.status === 'pending'" type="link" danger @click="cancelTask(record)">取消</a-button>
                <a-button v-if="record.status === 'failed'" type="link" @click="retryTask(record)">重试</a-button>
              </template>
            </template>
          </a-table>
        </a-tab-pane>

        <a-tab-pane key="settings" tab="配置">
          <section class="settings-grid">
            <div><h3>默认切片配置</h3><dl><template v-for="(value, key) in knowledge.split_config" :key="key"><dt>{{ key }}</dt><dd>{{ formatConfigValue(value) }}</dd></template></dl></div>
            <div><h3>生命周期</h3><dl><dt>创建时间</dt><dd>{{ formatDateTime(knowledge.created_at) }}</dd><dt>更新时间</dt><dd>{{ formatDateTime(knowledge.updated_at) }}</dd><dt>当前状态</dt><dd>{{ baseStatusLabel(knowledge.status) }}</dd></dl></div>
          </section>
        </a-tab-pane>
      </a-tabs>
    </template>
    <a-result v-else status="404" title="知识库不存在" sub-title="该知识库可能已被删除，或链接中的 ID 不正确。">
      <template #extra><a-button type="primary" @click="router.push('/knowledge')">返回列表</a-button></template>
    </a-result>

    <a-modal v-model:open="uploadOpen" title="添加文档" ok-text="上传并入库" cancel-text="取消"
      :confirm-loading="uploading" :ok-button-props="{ disabled: !selectedFiles.length }"
      @ok="uploadAndSubmit" @cancel="clearUpload">
      <button class="upload-zone" type="button" @click="fileInput?.click()">
        <UploadOutlined /><strong>选择需要入库的文件</strong><span>上传完成后自动提交至当前知识库</span>
      </button>
      <input ref="fileInput" class="native-file-input" type="file" multiple @change="onFilesSelected" />
      <ul v-if="selectedFiles.length" class="selected-files">
        <li v-for="(file, index) in selectedFiles" :key="file.name + file.size">
          <FileTextOutlined /><span>{{ file.name }}</span><small>{{ formatBytes(file.size) }}</small>
          <a-button type="text" danger @click="removeSelectedFile(index)"><template #icon><CloseOutlined /></template></a-button>
        </li>
      </ul>
    </a-modal>

    <KnowledgeRetrievalDrawer
      v-if="knowledge"
      v-model:open="retrievalOpen"
      :collection-name="knowledge.collection_name"
      :documents="documents"
    />
  </div>
</template>

<script setup lang="ts">
/** 知识库详情工作台：管理文档、索引任务和基础配置。 */
import { computed, onBeforeUnmount, onMounted, reactive, ref } from 'vue'
import { Modal, message } from 'ant-design-vue'
import { useRoute, useRouter } from 'vue-router'
import { ArrowLeftOutlined, CloseOutlined, DatabaseOutlined, DeleteOutlined, EditOutlined, ExperimentOutlined, FileTextOutlined, InfoCircleOutlined, ReloadOutlined, RetweetOutlined, SearchOutlined, SyncOutlined, UnorderedListOutlined, UploadOutlined } from '@ant-design/icons-vue'
import { uploadFiles } from '@/api/file'
import { cancelIngestionRun, deleteKnowledgeDocument, getKnowledgeBase, reindexKnowledgeDocument, retryIngestionRun, searchIngestionRuns, searchKnowledgeDocuments, submitKnowledgeDocument, type IngestionRunRecord, type KnowledgeBaseItem, type KnowledgeDocumentRecord } from '@/api/knowledge'
import KnowledgeRetrievalDrawer from './components/KnowledgeRetrievalDrawer.vue'

defineOptions({ name: 'KnowledgeDetail' })
const route = useRoute()
const router = useRouter()
const knowledgeId = computed(() => String(route.params.knowledge_id || ''))
const knowledge = ref<KnowledgeBaseItem | null>(null)
const loading = ref(false)
const activeTab = ref('documents')
const documents = ref<KnowledgeDocumentRecord[]>([])
const documentsLoading = ref(false)
const documentFilters = reactive({ file_name: '', status: '' })
const tasks = ref<IngestionRunRecord[]>([])
const tasksLoading = ref(false)
const taskFilters = reactive({ operation: '', status: '' })
const taskPage = ref(1)
const taskPageSize = 12
const taskTotal = ref(0)
let refreshTimer: number | undefined
const uploadOpen = ref(false)
const retrievalOpen = ref(false)
const uploading = ref(false)
const selectedFiles = ref<File[]>([])
const fileInput = ref<HTMLInputElement | null>(null)

const documentColumns = [
  { title: '文件', key: 'file', width: 360 }, { title: '状态', key: 'status', width: 120 },
  { title: '分块 / 版本', key: 'chunks', width: 130 }, { title: '最近索引', key: 'indexed', width: 180 },
  { title: '操作', key: 'actions', width: 110, fixed: 'right' as const },
]
const taskColumns = [
  { title: '操作', key: 'operation', width: 130 }, { title: '文件 ID', key: 'file', width: 280 },
  { title: '状态', key: 'status', width: 120 }, { title: '重试', key: 'retry', width: 90 },
  { title: '创建时间', key: 'created', width: 180 }, { title: '操作', key: 'actions', width: 130, fixed: 'right' as const },
]
const documentStatusOptions = [
  { value: 'indexed', label: '已索引' }, { value: 'pending', label: '排队中' },
  { value: 'indexing', label: '索引中' }, { value: 'deleting', label: '删除中' },
  { value: 'failed', label: '失败' }, { value: 'deleted', label: '已删除' },
]
const taskStatusOptions = [
  { value: 'pending', label: '排队中' }, { value: 'running', label: '运行中' },
  { value: 'completed', label: '已完成' }, { value: 'failed', label: '失败' },
  { value: 'cancelled', label: '已取消' },
]
const activeTaskCount = computed(() => tasks.value.filter((item) => ['pending', 'running'].includes(item.status)).length)

/** 并行加载当前知识库、文档和任务。 */
async function loadAll() {
  loading.value = true
  try {
    const [base] = await Promise.all([getKnowledgeBase(knowledgeId.value), loadDocuments(), loadTasks(taskPage.value)])
    knowledge.value = base
  } catch { knowledge.value = null } finally { loading.value = false }
}

/** 加载文档列表。 */
async function loadDocuments() {
  documentsLoading.value = true
  try {
    documents.value = await searchKnowledgeDocuments({
      knowledge_id: knowledgeId.value,
      file_name: documentFilters.file_name.trim() || undefined,
      status: documentFilters.status || undefined,
    })
  } finally { documentsLoading.value = false }
}

/** 加载任务分页列表。 */
async function loadTasks(page = taskPage.value) {
  tasksLoading.value = true
  try {
    const result = await searchIngestionRuns({
      knowledge_id: knowledgeId.value, operation: taskFilters.operation || undefined,
      status: taskFilters.status || undefined, page, page_size: taskPageSize,
    })
    tasks.value = result.items
    taskTotal.value = result.total
    taskPage.value = result.page
  } finally { tasksLoading.value = false }
}

/** 重置文档筛选。 */
function resetDocumentFilters() { documentFilters.file_name = ''; documentFilters.status = ''; loadDocuments() }
/** 重置任务筛选。 */
function resetTaskFilters() { taskFilters.operation = ''; taskFilters.status = ''; loadTasks(1) }
/** 响应任务表格分页。 */
function onTaskTableChange(pagination: { current?: number }) { loadTasks(pagination.current || 1) }
/** 打开上传弹窗。 */
function openUpload() { selectedFiles.value = []; uploadOpen.value = true }
/** 接收浏览器文件选择结果。 */
function onFilesSelected(event: Event) { selectedFiles.value = Array.from((event.target as HTMLInputElement).files || []) }
/** 删除一个待上传文件。 */
function removeSelectedFile(index: number) { selectedFiles.value.splice(index, 1) }
/** 清理上传临时状态。 */
function clearUpload() { selectedFiles.value = []; if (fileInput.value) fileInput.value.value = '' }

/** 上传原始文件并提交后台入库任务；MinerU、切片和向量化不阻塞当前弹窗。 */
async function uploadAndSubmit() {
  if (!selectedFiles.value.length) return
  uploading.value = true
  try {
    const uploadResult = await uploadFiles(selectedFiles.value)
    await Promise.all(
      uploadResult.file_ids.map((fileId) => submitKnowledgeDocument({
        knowledge_id: knowledgeId.value,
        file_id: fileId,
      })),
    )
    uploadOpen.value = false
    clearUpload()
    message.success(`已提交 ${uploadResult.file_ids.length} 份文档入库，请前往任务列表查看进度`)

    // 弹窗在任务提交成功后立即结束等待；列表刷新属于辅助展示，不阻塞用户操作。
    void Promise.all([loadDocuments(), loadTasks(1)]).catch(() => undefined)
  } finally { uploading.value = false }
}

/** 确认并提交重建索引任务。 */
function confirmReindex(record: KnowledgeDocumentRecord) {
  Modal.confirm({
    title: '重新构建索引', content: `将重新切片并向量化“${record.file_name || record.file_id}”。`, okText: '开始重建',
    async onOk() {
      await reindexKnowledgeDocument({ knowledge_id: knowledgeId.value, file_id: record.file_id })
      message.success('重建任务已提交')
      await Promise.all([loadDocuments(), loadTasks(1)])
    },
  })
}

/** 确认并提交文档异步删除任务。 */
function confirmDeleteDocument(record: KnowledgeDocumentRecord) {
  Modal.confirm({
    title: '删除文档索引', content: `将清理“${record.file_name || record.file_id}”的向量和分块证据，源文件不会被删除。`,
    okText: '确认删除', okType: 'danger',
    async onOk() {
      await deleteKnowledgeDocument(knowledgeId.value, record.file_id)
      message.success('删除任务已提交')
      await Promise.all([loadDocuments(), loadTasks(1)])
    },
  })
}

/** 取消排队任务。 */
async function cancelTask(record: IngestionRunRecord) {
  await cancelIngestionRun(record.run_id); message.success('任务已取消')
  await Promise.all([loadDocuments(), loadTasks(taskPage.value)])
}
/** 重试失败任务。 */
async function retryTask(record: IngestionRunRecord) {
  await retryIngestionRun(record.run_id); message.success('任务已重新提交')
  await Promise.all([loadDocuments(), loadTasks(1)])
}
/** 进入编辑页面。 */
function goEdit() { router.push(`/knowledge/${knowledgeId.value}/edit`) }
/** 判断文档是否处于任务处理阶段。 */
function isDocumentBusy(status: string) { return ['pending', 'indexing', 'deleting'].includes(status) }
/** 知识库状态中文名称。 */
function baseStatusLabel(status: string) { return ({ active: '运行中', disabled: '已停用', deleted: '已删除' } as Record<string, string>)[status] || status }
/** 文档状态展示映射。 */
function documentStatus(status: string) {
  return ({ pending: { label: '排队中', color: 'blue' }, indexing: { label: '索引中', color: 'processing' }, indexed: { label: '已索引', color: 'green' }, deleting: { label: '删除中', color: 'orange' }, failed: { label: '失败', color: 'red' }, deleted: { label: '已删除', color: 'default' } } as Record<string, { label: string; color: string }>)[status] || { label: status, color: 'default' }
}
/** 任务状态展示映射。 */
function taskStatus(status: string) {
  return ({ pending: { label: '排队中', color: 'blue' }, running: { label: '运行中', color: 'processing' }, completed: { label: '已完成', color: 'green' }, failed: { label: '失败', color: 'red' }, cancelled: { label: '已取消', color: 'default' } } as Record<string, { label: string; color: string }>)[status] || { label: status, color: 'default' }
}
/** 任务操作类型中文名称。 */
function operationLabel(value: string) { return ({ ingest: '首次入库', reindex: '重建索引', delete: '删除索引' } as Record<string, string>)[value] || value }
/** 提取文件扩展名作为稳定图标。 */
function extensionLabel(name?: string | null) { return name?.split('.').pop()?.slice(0, 4).toUpperCase() || 'FILE' }
/** 格式化文件大小。 */
function formatBytes(value?: number | null) {
  if (value === null || value === undefined) return '-'
  if (value < 1024) return `${value} B`
  if (value < 1048576) return `${(value / 1024).toFixed(1)} KB`
  return `${(value / 1048576).toFixed(1)} MB`
}
/** 格式化日期时间。 */
function formatDateTime(value?: string | null) {
  if (!value) return '-'
  return new Intl.DateTimeFormat('zh-CN', { year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' }).format(new Date(value))
}
/** 格式化配置值。 */
function formatConfigValue(value: unknown) { return Array.isArray(value) ? value.join(', ') : String(value ?? '-') }
/** 判断当前页面是否存在需要持续追踪的异步任务。 */
function hasActiveWork() {
  const taskRunning = tasks.value.some((item) => ['pending', 'running'].includes(item.status))
  const documentRunning = documents.value.some((item) => ['pending', 'indexing', 'deleting'].includes(item.status))
  return taskRunning || documentRunning
}

/**
 * 定时刷新异步任务及文档状态。
 * 页面仅在存在处理中任务且处于可见状态时请求后端；全部完成后保留定时器，
 * 但不再发起网络请求，新提交任务后会由提交动作主动刷新并恢复轮询。
 */
function startPolling() {
  refreshTimer = window.setInterval(() => {
    if (document.visibilityState !== 'visible' || !hasActiveWork()) return
    void Promise.all([loadDocuments(), loadTasks(taskPage.value)]).catch(() => undefined)
  }, 5000)
}
onMounted(() => { loadAll(); startPolling() })
onBeforeUnmount(() => { if (refreshTimer) window.clearInterval(refreshTimer) })
</script>

<style scoped>
.detail-header,.title-side,.title-line,.header-actions,.file-cell,.operation-cell{display:flex;align-items:center}.detail-header{align-items:flex-start;justify-content:space-between;gap:24px;margin-bottom:20px}.title-side{align-items:flex-start;gap:12px;min-width:0}.title-icon{display:inline-flex;align-items:center;justify-content:center;width:42px;height:42px;flex:0 0 42px;border-radius:7px;color:#3366cc;background:#edf3ff;font-size:20px}.title-line{gap:10px}.title-line h1{margin:0;font-size:23px;color:#172033}.title-side p{margin:5px 0 0;max-width:680px;color:#727d90;font-size:13px}.header-actions{gap:8px;flex-shrink:0}.metadata-strip{display:grid;grid-template-columns:1.15fr 1fr .7fr 1.5fr;border:1px solid #e7eaf0;border-radius:8px;margin-bottom:18px}.metadata-strip>div{display:flex;flex-direction:column;gap:5px;min-width:0;padding:14px 18px;border-right:1px solid #e7eaf0}.metadata-strip>div:last-child{border-right:0}.metadata-strip span{color:#7b8496;font-size:11px}.metadata-strip strong,.metadata-strip code{overflow:hidden;color:#273247;font-size:12px;text-overflow:ellipsis;white-space:nowrap}.tab-toolbar{display:flex;gap:10px;margin:4px 0 14px}.document-search{width:min(360px,46vw)}.filter-select{width:150px}.file-cell{gap:11px}.file-icon{display:inline-flex;align-items:center;justify-content:center;width:39px;height:39px;flex:0 0 39px;border-radius:6px;color:#3d609c;background:#eff3f9;font-size:9px;font-weight:700}.file-cell>div{display:flex;flex-direction:column;min-width:0}.file-cell strong{max-width:280px;overflow:hidden;color:#202b3d;font-size:13px;text-overflow:ellipsis;white-space:nowrap}.file-cell small{margin-top:3px;color:#8490a3}.secondary{margin-left:7px;color:#8490a3;font-size:12px}.id-code{color:#5d687b;font-size:11px}.settings-grid{display:grid;grid-template-columns:1fr 1fr;gap:48px;padding:12px 4px}.settings-grid h3{margin:0 0 16px;color:#263248;font-size:15px}.settings-grid dl{display:grid;grid-template-columns:150px 1fr;margin:0}.settings-grid dt,.settings-grid dd{padding:10px 0;border-bottom:1px solid #edf0f4}.settings-grid dt{color:#7a8598}.settings-grid dd{margin:0;color:#283448;word-break:break-word}.upload-zone{display:flex;flex-direction:column;align-items:center;width:100%;padding:28px 20px;border:1px dashed #aebbd0;border-radius:8px;color:#67758c;background:#fafbfd;cursor:pointer}.upload-zone>span:first-child{margin-bottom:10px;color:#3366cc;font-size:28px}.upload-zone strong{color:#273247}.upload-zone span:last-child{margin-top:5px;font-size:12px}.native-file-input{display:none}.selected-files{margin:14px 0 0;padding:0;list-style:none}.selected-files li{display:flex;align-items:center;gap:9px;padding:8px 0;border-bottom:1px solid #edf0f4}.selected-files li>span:nth-child(2){flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.selected-files small{color:#8490a3}:deep(.ant-table-thead>tr>th){color:#687386;font-size:12px;font-weight:600;background:#f8f9fb}@media(max-width:900px){.detail-header{flex-direction:column}.metadata-strip{grid-template-columns:1fr 1fr}.settings-grid{grid-template-columns:1fr}}@media(max-width:640px){.header-actions,.tab-toolbar{flex-wrap:wrap}.metadata-strip{grid-template-columns:1fr}.metadata-strip>div{border-right:0;border-bottom:1px solid #e7eaf0}.document-search{width:100%}.filter-select{flex:1}}
</style>
