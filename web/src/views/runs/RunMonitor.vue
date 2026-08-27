/**
 * 7. Agent 运行监控页 ⭐
 * - 顶部统计卡片
 * - 左侧筛选（run_id / run_type / agent_id / status / 时间）
 * - 右侧列表 + 链路展开
 */
<template>
  <div>
    <h2 class="page-title">📈 Agent 运行监控</h2>

    <a-alert
      v-if="!debugContextReady"
      type="info"
      show-icon
      class="mb-4"
      message="请先配置调试业务身份"
      description="运行记录按平台 API Key 和外部用户 ID 隔离，请在页面顶部完成配置。"
    />

    <!-- 顶部统计 -->
    <a-row :gutter="16" class="mb-4">
      <a-col :span="6"><a-card><a-statistic title="今日运行" :value="stats.today" /></a-card></a-col>
      <a-col :span="6">
        <a-card>
          <a-statistic
            title="今日成功率"
            :value="stats.successRate"
            :precision="2"
            suffix="%"
            :value-style="{ color: stats.successRate >= 90 ? '#3f8600' : '#cf1322' }"
          />
        </a-card>
      </a-col>
      <a-col :span="6"><a-card><a-statistic title="今日失败" :value="stats.failed" /></a-card></a-col>
      <a-col :span="6"><a-card><a-statistic title="平均耗时" :value="formatElapsed(stats.avgElapsedRaw)" /></a-card></a-col>
    </a-row>

    <!-- 工具栏：筛选 + 刷新 + 已选筛选条件标签 -->
    <a-card class="mb-4">
      <a-space wrap>
        <a-button type="primary" @click="filterModalOpen = true">
          <template #icon><FilterOutlined /></template>
          筛选
        </a-button>
        <a-button @click="onSearch">
          <template #icon><ReloadOutlined /></template>
          刷新
        </a-button>
        <a-tag
          v-for="chip in activeFilterChips"
          :key="chip.key"
          color="blue"
          closable
          @close="removeFilterChip(chip.key)"
        >
          {{ chip.label }}
        </a-tag>
        <span v-if="!activeFilterChips.length" class="text-gray-400">无筛选条件</span>
      </a-space>
    </a-card>

    <!-- 筛选弹窗 -->
    <a-modal
      v-model:open="filterModalOpen"
      title="🔍 筛选运行记录"
      ok-text="应用筛选"
      cancel-text="取消"
      :width="560"
      @ok="onApplyFilter"
      @cancel="onCancelFilter"
    >
      <a-form layout="vertical">
        <a-form-item label="Run ID">
          <a-input v-model:value="filters.run_id" placeholder="精确搜索" allow-clear />
        </a-form-item>
        <a-form-item label="运行类型">
          <a-select v-model:value="filters.run_type" placeholder="全部" allow-clear>
            <a-select-option value="main">仅主 Agent</a-select-option>
            <a-select-option value="sub">仅子 Agent</a-select-option>
          </a-select>
        </a-form-item>
        <a-form-item label="Agent 模板">
          <a-select v-model:value="filters.agent_id" placeholder="全部" allow-clear show-search>
            <a-select-option v-for="a in agentOptions" :key="a" :value="a">{{ a }}</a-select-option>
          </a-select>
        </a-form-item>
        <a-form-item label="状态">
          <a-select v-model:value="filters.status" placeholder="全部" allow-clear>
            <a-select-option value="running">running</a-select-option>
            <a-select-option value="success">success</a-select-option>
            <a-select-option value="failed">failed</a-select-option>
          </a-select>
        </a-form-item>
        <a-form-item label="时间范围">
          <a-range-picker
            v-model:value="timeRange"
            show-time
            style="width: 100%"
          />
        </a-form-item>
        <a-form-item>
          <a-space>
            <a-button @click="onReset">重置全部</a-button>
          </a-space>
        </a-form-item>
      </a-form>
    </a-modal>

    <!-- 列表 -->
    <a-card>
      <a-table
        :columns="columns"
        :data-source="list"
        :loading="loading"
        :pagination="pagination"
        :scroll="{ x: 1400 }"
        row-key="run_id"
        @change="onTableChange"
        :expand-row-by-click="true"
        :expanded-row-keys="expandedKeys"
        @expand="onExpand"
      >
        <!-- 链路展开 -->
        <!-- @ts-ignore - record is provided by antd slot but unused here -->
        <template #expandedRowRender="{ record: _record }">
          <a-spin :spinning="chainLoading">
            <a-empty v-if="!chainData.length" description="无主子链路数据" />
            <a-tree
              v-else
              :tree-data="chainTree"
              :default-expand-all="true"
              show-line
            >
              <template #title="{ title, status, run_type, elapsed_ms, run_id }">
                <a-space>
                  <a-tag :color="statusColor(status)">{{ status }}</a-tag>
                  <a-tag v-if="run_type" color="blue">{{ run_type }}</a-tag>
                  <span>{{ title }}</span>
                  <span v-if="elapsed_ms != null" class="text-gray-500">({{ formatElapsed(elapsed_ms) }})</span>
                  <span class="text-gray-400 text-xs">{{ run_id }}</span>
                </a-space>
              </template>
            </a-tree>
          </a-spin>
        </template>

        <template #bodyCell="{ column, record }">
          <template v-if="column.dataIndex === 'status'">
            <a-tag :color="statusColor(record.status)">{{ record.status }}</a-tag>
          </template>
          <template v-else-if="column.dataIndex === 'run_type'">
            <a-tag :color="record.run_type === 'main' ? 'blue' : 'cyan'">{{ record.run_type }}</a-tag>
          </template>
          <template v-else-if="column.dataIndex === 'elapsed_ms'">
            {{ formatElapsed(record.elapsed_ms) }}
          </template>
          <template v-else-if="column.dataIndex === 'started_at'">
            {{ formatTime(record.started_at) }}
          </template>
          <template v-else-if="column.dataIndex === 'finished_at'">
            {{ formatTime(record.finished_at) }}
          </template>
          <template v-else-if="column.dataIndex === 'action'">
            <a-space size="small" wrap>
              <a-button
                v-if="record.run_type === 'main'"
                type="link"
                size="small"
                @click="loadChain(record.run_id)"
              >
                查看链路
              </a-button>
              <a-button
                type="link"
                size="small"
                :disabled="!record.agent_id"
                @click="router.push(`/agents/${record.agent_id}/playground`)"
              >
                带入 Playground
              </a-button>
            </a-space>
          </template>
        </template>
      </a-table>
    </a-card>
  </div>
</template>

<script setup lang="ts">
/**
 * 运行监控页逻辑
 * - 多条件筛选
 * - 表格内嵌主子链路展开（Tree）
 */
import { computed, onBeforeUnmount, onMounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { FilterOutlined, ReloadOutlined } from '@ant-design/icons-vue'
import { searchAgentRuns, getAgentRunChain, type AgentRun, type AgentRunChain } from '@/api/agentRun'
import { searchAgentTemplates } from '@/api/agentTemplate'
import dayjs, { type Dayjs } from 'dayjs'
import {
  BUSINESS_DEBUG_CONTEXT_CHANGED,
  hasCompleteBusinessDebugContext,
} from '@/utils/businessDebugContext'

defineOptions({ name: 'RunMonitorView' })

const router = useRouter()
const loading = ref(false)
const debugContextReady = ref(hasCompleteBusinessDebugContext())
const list = ref<AgentRun[]>([])

// 链路
const chainLoading = ref(false)
const chainMap = reactive<Record<string, AgentRunChain>>({})
const expandedKeys = ref<string[]>([])

const filters = reactive({
  run_id: '',
  run_type: undefined as string | undefined,
  agent_id: undefined as string | undefined,
  status: undefined as string | undefined,
})

const timeRange = ref<[Dayjs, Dayjs] | null>(null)
const agentOptions = ref<string[]>([])

const pagination = reactive({ current: 1, pageSize: 20, total: 0 })

const stats = reactive({ today: 0, failed: 0, successRate: 0, avgElapsedRaw: 0 })

// 筛选弹窗开关
const filterModalOpen = ref(false)

/** 当前已应用的筛选条件（用于顶部 chip 展示） */
const appliedFilters = reactive({
  run_id: '',
  run_type: undefined as string | undefined,
  agent_id: undefined as string | undefined,
  status: undefined as string | undefined,
})

/** 表格列定义：操作列 fixed 在右侧，确保不被挤出去 */
const columns = [
  { title: 'Run ID', dataIndex: 'run_id', width: 220, ellipsis: true },
  { title: '类型', dataIndex: 'run_type', width: 70 },
  { title: 'Agent', dataIndex: 'agent_id', width: 140, ellipsis: true },
  { title: '会话', dataIndex: 'conversation_id', width: 150, ellipsis: true },
  { title: '状态', dataIndex: 'status', width: 80 },
  { title: '耗时', dataIndex: 'elapsed_ms', width: 80 },
  { title: '开始时间', dataIndex: 'started_at', width: 150 },
  { title: '结束时间', dataIndex: 'finished_at', width: 150 },
  { title: '操作', dataIndex: 'action', width: 200, fixed: 'right' as const },
]

/** 顶部展示的筛选条件 chip 列表 */
const activeFilterChips = computed(() => {
  const chips: { key: string; label: string }[] = []
  if (appliedFilters.run_id) chips.push({ key: 'run_id', label: `Run ID: ${appliedFilters.run_id}` })
  if (appliedFilters.run_type) chips.push({ key: 'run_type', label: `类型: ${appliedFilters.run_type}` })
  if (appliedFilters.agent_id) chips.push({ key: 'agent_id', label: `Agent: ${appliedFilters.agent_id}` })
  if (appliedFilters.status) chips.push({ key: 'status', label: `状态: ${appliedFilters.status}` })
  if (timeRange.value) {
    const [from, to] = timeRange.value
    chips.push({ key: 'timeRange', label: `时间: ${from.format('MM-DD HH:mm')} ~ ${to.format('MM-DD HH:mm')}` })
  }
  return chips
})

/** 状态颜色 */
function statusColor(s: string) {
  return s === 'success' ? 'green' : s === 'failed' ? 'red' : 'blue'
}

/** 格式化时间 */
function formatTime(t?: string) {
  return t ? dayjs(t).format('YYYY-MM-DD HH:mm:ss') : '-'
}

/**
 * 智能格式化耗时
 * - < 1s: 毫秒（如 "650ms"）
 * - < 60s: 秒（如 "10.80s"）
 * - >= 60s: 分秒（如 "2m 15s"）
 */
function formatElapsed(ms?: number | null) {
  if (ms == null) return '-'
  if (ms < 1000) return `${ms}ms`
  if (ms < 60_000) return `${(ms / 1000).toFixed(2)}s`
  const m = Math.floor(ms / 60_000)
  const s = Math.round((ms % 60_000) / 1000)
  return `${m}m ${s}s`
}

/** 应用筛选（弹窗点确定时调用） */
function onApplyFilter() {
  appliedFilters.run_id = filters.run_id
  appliedFilters.run_type = filters.run_type
  appliedFilters.agent_id = filters.agent_id
  appliedFilters.status = filters.status
  filterModalOpen.value = false
  pagination.current = 1
  loadList()
}

/** 取消筛选 */
function onCancelFilter() {
  // 恢复弹窗中未应用前的状态为已应用状态
  filters.run_id = appliedFilters.run_id
  filters.run_type = appliedFilters.run_type
  filters.agent_id = appliedFilters.agent_id
  filters.status = appliedFilters.status
  filterModalOpen.value = false
}

/** 移除单个筛选条件 chip */
function removeFilterChip(key: string) {
  if (key === 'run_id') {
    filters.run_id = ''
    appliedFilters.run_id = ''
  } else if (key === 'run_type') {
    filters.run_type = undefined
    appliedFilters.run_type = undefined
  } else if (key === 'agent_id') {
    filters.agent_id = undefined
    appliedFilters.agent_id = undefined
  } else if (key === 'status') {
    filters.status = undefined
    appliedFilters.status = undefined
  } else if (key === 'timeRange') {
    timeRange.value = null
  }
  pagination.current = 1
  loadList()
}

/** 加载列表 */
async function loadList() {
  debugContextReady.value = hasCompleteBusinessDebugContext()
  if (!debugContextReady.value) {
    list.value = []
    pagination.total = 0
    stats.today = 0
    stats.failed = 0
    stats.successRate = 0
    stats.avgElapsedRaw = 0
    return
  }
  loading.value = true
  try {
    const res = await searchAgentRuns({
      page: pagination.current,
      page_size: pagination.pageSize,
      run_id: appliedFilters.run_id || undefined,
      run_type: appliedFilters.run_type as 'main' | 'sub' | undefined,
      agent_id: appliedFilters.agent_id,
      status: appliedFilters.status as 'running' | 'success' | 'failed' | undefined,
    })
    // 后端不支持时间范围筛选，若设置了 timeRange 则在前端过滤
    let items = res.items
    if (timeRange.value) {
      const [from, to] = timeRange.value
      items = items.filter((r) => {
        if (!r.started_at) return false
        const t = dayjs(r.started_at)
        return t.isAfter(from) && t.isBefore(to)
      })
    }
    list.value = items
    pagination.total = res.total
    // 统计今日
    const today = dayjs().startOf('day')
    const todayItems = res.items.filter((r) => r.started_at && dayjs(r.started_at).isAfter(today))
    stats.today = todayItems.length
    stats.failed = todayItems.filter((r) => r.status === 'failed').length
    const succ = todayItems.filter((r) => r.status === 'success').length
    stats.successRate = todayItems.length ? (succ / todayItems.length) * 100 : 0
    const totalElapsed = todayItems.reduce((s, r) => s + (r.elapsed_ms || 0), 0)
    stats.avgElapsedRaw = todayItems.length ? Math.round(totalElapsed / todayItems.length) : 0
  } finally {
    loading.value = false
  }
}

/** 查询（刷新按钮） */
function onSearch() {
  pagination.current = 1
  loadList()
}

/** 重置全部 */
function onReset() {
  filters.run_id = ''
  filters.run_type = undefined
  filters.agent_id = undefined
  filters.status = undefined
  timeRange.value = null
  appliedFilters.run_id = ''
  appliedFilters.run_type = undefined
  appliedFilters.agent_id = undefined
  appliedFilters.status = undefined
  filterModalOpen.value = false
  pagination.current = 1
  loadList()
}

/** 分页 */
function onTableChange(pag: { current?: number; pageSize?: number }) {
  pagination.current = pag.current ?? 1
  pagination.pageSize = pag.pageSize ?? 20
  loadList()
}

/** 展开行 */
function onExpand(expanded: boolean, record: AgentRun) {
  if (expanded && !chainMap[record.run_id]) {
    loadChain(record.run_id)
  }
}

/** 加载主子链路 */
async function loadChain(run_id: string) {
  chainLoading.value = true
  try {
    const data = await getAgentRunChain(run_id)
    chainMap[run_id] = data
    if (!expandedKeys.value.includes(run_id)) expandedKeys.value.push(run_id)
  } finally {
    chainLoading.value = false
  }
}

/** 当前展开行的链路数据 */
const chainData = computed(() => {
  if (!expandedKeys.value.length) return []
  const id = expandedKeys.value[expandedKeys.value.length - 1]
  return chainMap[id]?.items || []
})

/** 将链路数据转为 antd tree 格式 */
const chainTree = computed(() => {
  const items = chainData.value
  if (!items.length) return []
  const map = new Map<string, any>()
  items.forEach((it) => {
    map.set(it.run_id, {
      key: it.run_id,
      title: it.query?.slice(0, 60) || it.run_id,
      status: it.status,
      run_type: it.run_type,
      elapsed_ms: it.elapsed_ms,
      run_id: it.run_id,
      children: [] as any[],
    })
  })
  let root: any = null
  map.forEach((node) => {
    if (node.run_id === chainData.value[0]?.run_id || !node.parent_run_id || !map.has(node.parent_run_id)) {
      root = node
    } else {
      map.get(node.parent_run_id)!.children.push(node)
    }
  })
  return root ? [root] : []
})

/** 加载 Agent 选项 */
async function loadAgentOptions() {
  try {
    const res = await searchAgentTemplates({ page: 1, page_size: 100 })
    agentOptions.value = res.items.map((t) => t.agent_id)
  } catch {
    agentOptions.value = []
  }
}

onMounted(() => {
  window.addEventListener(BUSINESS_DEBUG_CONTEXT_CHANGED, loadList)
  void loadList()
  void loadAgentOptions()
})
onBeforeUnmount(() => window.removeEventListener(BUSINESS_DEBUG_CONTEXT_CHANGED, loadList))
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
.side-card {
  min-height: 500px;
}
</style>
